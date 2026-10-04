import heapq
import itertools
import math
import os
import struct
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.geo import HAVERSINE, MBR, get_max_metric, get_metric, point_in_polygon, rect_in_polygon
from common.page import PAGE_SIZE
from common.types import RID
from engine.buffer_pool import BufferPool
from engine.segment import NIL, Segment
from index.base import Index
from index.rtree_page import MAX_INNER, MAX_LEAF, RTreePage

META_PAGE = 0
META_FORMAT = "<ii"               # raiz | free_list_head


def _rect(entry: tuple, is_leaf: bool) -> MBR:
    if is_leaf:
        return MBR.of_point(entry[0], entry[1])
    return MBR(*entry[:4])


def _preference(cover: MBR, rect: MBR) -> tuple:
    return cover.mindist(rect), cover.enlargement(rect), cover.area()


def _str_groups(entries: list, cap: int, is_leaf: bool) -> list:
    if is_leaf:
        cx, cy = (lambda e: e[0]), (lambda e: e[1])
    else:
        cx, cy = (lambda e: e[0] + e[2]), (lambda e: e[1] + e[3])
    slices = math.ceil(math.sqrt(math.ceil(len(entries) / cap)))
    per_slice = slices * cap
    entries = sorted(entries, key=cx)
    groups = []
    for i in range(0, len(entries), per_slice):
        tira = sorted(entries[i:i + per_slice], key=cy)
        groups.extend(tira[j:j + cap] for j in range(0, len(tira), cap))
    return groups


def _xy(point) -> tuple:
    lat, lon = point
    return float(lon), float(lat)


class RTree(Index):
    def __init__(self, pool: BufferPool, path: str):
        self._seg = Segment(pool, path)
        if self._seg.page_count() > 0:
            self._load()
        else:
            self._create()

    def file_paths(self) -> list[str]:
        return [self._seg.path]

    def close(self) -> None:
        self._seg.close()

    # Index

    def insert(self, key: Any, rid: RID) -> None:
        x, y = _xy(key)
        self._insert_entry((x, y, rid.page_id, rid.slot_id))

    def search(self, key: Any) -> list[RID]:
        x, y = _xy(key)
        return [rid for rid, _p in self._rect_search(MBR.of_point(x, y), None)]

    def range_search(self, low: Any, high: Any, stats: dict | None = None,
                     trace: list | None = None) -> list[RID]:
        rect = MBR.of_points([_xy(low), _xy(high)])
        return [rid for rid, _p in self._rect_search(rect, stats, trace)]

    def delete(self, key: Any, rid: RID) -> bool:
        x, y = _xy(key)
        target = (x, y, rid.page_id, rid.slot_id)
        path = self._find_leaf(self._root, target)
        if path is None:
            return False
        self._remove(path)
        return True

    def is_empty(self) -> bool:
        root = self._read(self._root)
        return root.is_leaf and not root.entries

    # consultas espaciales

    def radius_search(self, center: Any, radius_m: float, metrica: str = HAVERSINE,
                      stats: dict | None = None, trace: list | None = None) -> list:
        x, y = _xy(center)
        mindist = get_metric(metrica)
        maxdist = get_max_metric(metrica)
        encontrados = []
        nodos = hojas = 0
        pila = [(self._root, False)]
        while pila:
            page_id, completo = pila.pop()
            node = self._read(page_id)
            nodos += 1
            evento = {"type": "visit", "id": page_id, **({"full": True} if completo and trace is not None else {})} if trace is not None else None
            if node.is_leaf:
                hojas += 1
                matches = []
                for px, py, pid, slot in node.entries:
                    # en un subarbol completo no se calcula la distancia
                    d = None if completo else mindist(x, y, (px, py, px, py))
                    if completo or d <= radius_m:
                        encontrados.append((d, RID(pid, slot), (py, px)))
                        if trace is not None:
                            matches.append([py, px])
                if trace is not None:
                    evento["matches"] = matches
                    evento["hits"] = len(matches)
                    trace.append(evento)
            elif completo:
                if trace is not None:
                    trace.append(evento)
                pila.extend((e[4], True) for e in node.entries)
            else:
                full_hijos, podados = [], []
                for e in node.entries:
                    if mindist(x, y, e[:4]) <= radius_m:
                        es_full = maxdist(x, y, e[:4]) <= radius_m
                        pila.append((e[4], es_full))
                        if es_full and trace is not None:
                            full_hijos.append(e[4])
                    elif trace is not None:
                        podados.append(e[4])
                if trace is not None:
                    evento["full_children"] = full_hijos
                    trace.append(evento)
                    for hijo_id in podados:
                        trace.append({"type": "prune", "id": hijo_id, "parent": page_id})
        self._fill_stats(stats, nodos, hojas, len(encontrados))
        return encontrados

    def nearest_iter(self, center: Any, metrica: str = HAVERSINE, stats: dict | None = None,
                     trace: list | None = None):
        x, y = _xy(center)
        mindist = get_metric(metrica)
        contador = itertools.count()
        cola = [(0.0, next(contador), True, self._root)]
        if stats is not None:
            stats.update(nodos_visitados=0, hojas_visitadas=0, candidatos=0)
        try:
            while cola:
                d, _n, es_nodo, payload = heapq.heappop(cola)
                if not es_nodo:
                    if stats is not None:
                        stats["candidatos"] += 1
                    if trace is not None:
                        trace.append({"type": "hit", "point": [payload[1][0], payload[1][1]], "dist": d})
                    yield d, payload[0], payload[1]
                    continue
                node = self._read(payload)
                if stats is not None:
                    stats["nodos_visitados"] += 1
                    stats["hojas_visitadas"] += 1 if node.is_leaf else 0
                if trace is not None:
                    trace.append({"type": "visit", "id": payload, "dist": d})
                if node.is_leaf:
                    for px, py, page_id, slot_id in node.entries:
                        heapq.heappush(cola, (mindist(x, y, (px, py, px, py)), next(contador), False,
                                              (RID(page_id, slot_id), (py, px))))
                else:
                    for e in node.entries:
                        heapq.heappush(cola, (mindist(x, y, e[:4]), next(contador), True, e[4]))
        finally:
            if trace is not None:
                for _d, _n, es_nodo, payload in cola:
                    if es_nodo:
                        trace.append({"type": "prune", "id": payload})

    def knn(self, center: Any, k: int, metrica: str = HAVERSINE,
            stats: dict | None = None, trace: list | None = None) -> list:
        return list(itertools.islice(self.nearest_iter(center, metrica, stats, trace), k))

    def polygon_search(self, vertices: list, stats: dict | None = None, trace: list | None = None) -> list:
        vertices = [_xy(v) for v in vertices]
        caja = MBR.of_points(vertices)
        return self._collect(
            lambda px, py: caja.contains(px, py) and point_in_polygon(px, py, vertices),
            caja.intersects,
            lambda r: caja.contains_rect(r) and rect_in_polygon(r, vertices),
            stats, trace)

    @staticmethod
    def _fill_stats(stats: dict | None, nodos: int, hojas: int, candidatos: int) -> None:
        if stats is not None:
            stats.update(nodos_visitados=nodos, hojas_visitadas=hojas, candidatos=candidatos)

    def _rect_search(self, rect: MBR, stats: dict | None, trace: list | None = None) -> list:
        return self._collect(rect.contains, rect.intersects, rect.contains_rect, stats, trace)

    def _collect(self, keep, may_have, has_all, stats: dict | None, trace: list | None = None) -> list:
        encontrados = []
        nodos = hojas = 0
        pila = [(self._root, False)]
        while pila:
            page_id, completo = pila.pop()
            node = self._read(page_id)
            nodos += 1
            evento = {"type": "visit", "id": page_id, **({"full": True} if completo and trace is not None else {})} if trace is not None else None
            if node.is_leaf:
                hojas += 1
                matches = []
                for px, py, pid, slot in node.entries:
                    if completo or keep(px, py):
                        encontrados.append((RID(pid, slot), (py, px)))
                        if trace is not None:
                            matches.append([py, px])
                if trace is not None:
                    evento["matches"] = matches
                    evento["hits"] = len(matches)
                    trace.append(evento)
            elif completo:
                if trace is not None:
                    trace.append(evento)
                pila.extend((e[4], True) for e in node.entries)
            else:
                full_hijos, podados = [], []
                for e in node.entries:
                    if may_have(e[:4]):
                        es_full = has_all(e[:4])
                        pila.append((e[4], es_full))
                        if es_full and trace is not None:
                            full_hijos.append(e[4])
                    elif trace is not None:
                        podados.append(e[4])
                if trace is not None:
                    evento["full_children"] = full_hijos
                    trace.append(evento)
                    for hijo_id in podados:
                        trace.append({"type": "prune", "id": hijo_id, "parent": page_id})
        self._fill_stats(stats, nodos, hojas, len(encontrados))
        return encontrados

    def snapshot(self) -> dict:
        nodes = []

        def walk(page_id: int, level: int) -> int:
            node = self._read(page_id)
            mbr = node.mbr() if node.entries else None
            entry = {
                "id": page_id,
                "level": level,
                "leaf": node.is_leaf,
                "mbr": list(mbr) if mbr is not None else None,
                "count": len(node.entries),
            }
            if node.is_leaf:
                entry["points"] = [[py, px] for px, py, _pid, _slot in node.entries]
                nodes.append(entry)
                return level
            entry["children"] = [e[4] for e in node.entries]
            nodes.append(entry)
            return max((walk(e[4], level + 1) for e in node.entries), default=level)

        altura = walk(self._root, 0) + 1
        return {"root": self._root, "height": altura, "nodes": nodes}

    # insercion

    def _insert_entry(self, entry: tuple) -> None:
        rect = MBR.of_point(entry[0], entry[1])
        path = []
        page_id = self._root
        node = self._read(page_id)
        while not node.is_leaf:
            i = self._choose_subtree(node, rect)
            path.append((page_id, node, i))
            page_id = node.entries[i][4]
            node = self._read(page_id)

        node.entries.append(entry)
        split = self._write_or_split(page_id, node)
        child_id, child_mbr = page_id, node.mbr()

        while path:
            parent_id, parent, i = path.pop()
            changed = parent.entries[i][:4] != child_mbr
            if changed:
                parent.entries[i] = (*child_mbr, child_id)
            if split is not None:
                parent.entries.append(split)
                split = self._write_or_split(parent_id, parent)
            elif changed:
                self._write(parent_id, parent)
            else:
                return
            child_id, child_mbr = parent_id, parent.mbr()

        if split is not None:
            new_root_id = self._alloc_page()
            self._write(new_root_id, RTreePage(False, [(*child_mbr, child_id), split]))
            self._root = new_root_id
            self._flush_meta()

    @staticmethod
    def _choose_subtree(node: RTreePage, rect: MBR) -> int:
        mbrs = [MBR(*e[:4]) for e in node.entries]
        return min(range(len(mbrs)), key=lambda i: _preference(mbrs[i], rect))

    def _write_or_split(self, page_id: int, node: RTreePage):
        if len(node.entries) <= node.capacity():
            self._write(page_id, node)
            return None
        g1, g2 = self._split(node.entries, node.is_leaf)
        node.entries = g1
        sibling = RTreePage(node.is_leaf, g2)
        sibling_id = self._alloc_page()
        self._write(page_id, node)
        self._write(sibling_id, sibling)
        return (*sibling.mbr(), sibling_id)

    @staticmethod
    def _split(entries: list, is_leaf: bool):
        mbrs = [_rect(e, is_leaf) for e in entries]
        n = len(entries)
        s1, s2 = max(((i, j) for i in range(n - 1) for j in range(i + 1, n)),
                     key=lambda p: mbrs[p[0]].mindist(mbrs[p[1]]))

        tope = n // 2 + 1
        groups = ([entries[s1]], [entries[s2]])
        covers = [mbrs[s1], mbrs[s2]]
        resto = sorted((i for i in range(n) if i != s1 and i != s2),
                       key=lambda i: min(mbrs[s1].mindist(mbrs[i]), mbrs[s2].mindist(mbrs[i])))
        for i in resto:
            if len(groups[0]) == tope:
                g = 1
            elif len(groups[1]) == tope:
                g = 0
            else:
                g = min((0, 1), key=lambda k: _preference(covers[k], mbrs[i]))
            groups[g].append(entries[i])
            covers[g] = covers[g].union(mbrs[i])
        return groups

    # eliminacion

    def _find_leaf(self, page_id: int, target: tuple):
        node = self._read(page_id)
        if node.is_leaf:
            for i, e in enumerate(node.entries):
                if e == target:
                    return [(page_id, node, i)]
            return None
        x, y = target[0], target[1]
        for i, e in enumerate(node.entries):
            if MBR(*e[:4]).contains(x, y):
                sub = self._find_leaf(e[4], target)
                if sub is not None:
                    return [(page_id, node, i)] + sub
        return None

    def _remove(self, path: list) -> None:
        page_id, node, idx = path[-1]
        del node.entries[idx]
        for parent_id, parent, i in reversed(path[:-1]):
            if node.entries:
                self._write(page_id, node)
                parent.entries[i] = (*node.mbr(), page_id)
            else:
                self._free_page(page_id)
                del parent.entries[i]
            page_id, node = parent_id, parent

        if not node.entries:
            node = RTreePage(True)
        self._write(page_id, node)
        while not node.is_leaf and len(node.entries) == 1:
            child = node.entries[0][4]
            self._free_page(page_id)
            page_id, node = child, self._read(child)
        if page_id != self._root:
            self._root = page_id
            self._flush_meta()

    def bulk_load(self, pairs) -> None:
        pool, path = self._seg.pool, self._seg.path
        tmp_path = path + ".rebuild"
        pool.truncate(tmp_path, 0)
        fresh = RTree(pool, tmp_path)
        entries = [(*_xy(key), rid.page_id, rid.slot_id) for key, rid in pairs]
        if entries:
            fresh._str_build(entries)
        pool.replace(tmp_path, path)
        self._load()

    def _str_build(self, entries: list) -> None:
        is_leaf = True
        spare = self._root
        while True:
            level = []
            for group in _str_groups(entries, MAX_LEAF if is_leaf else MAX_INNER, is_leaf):
                node = RTreePage(is_leaf, group)
                if spare is not None:
                    page_id, spare = spare, None
                    self._write(page_id, node)
                else:
                    page_id = self._seg.append(node.to_bytes())
                level.append((*node.mbr(), page_id))
            if len(level) == 1:
                break
            entries, is_leaf = level, False
        self._root = level[0][4]
        self._flush_meta()

    # paginas y metapagina

    def _read(self, page_id: int) -> RTreePage:
        return RTreePage.from_bytes(self._seg.read(page_id))

    def _write(self, page_id: int, node: RTreePage) -> None:
        self._seg.write(page_id, node.to_bytes())

    def _alloc_page(self) -> int:
        reused = self._seg.free_head != NIL
        page_id = self._seg.alloc()
        if reused:
            self._flush_meta()
        return page_id

    def _free_page(self, page_id: int) -> None:
        self._seg.free(page_id)
        self._flush_meta()

    def _create(self) -> None:
        self._seg.append(bytes(PAGE_SIZE))
        self._root = self._seg.append(RTreePage(True).to_bytes())
        self._flush_meta()

    def _load(self) -> None:
        self._root, self._seg.free_head = struct.unpack_from(META_FORMAT, self._seg.read(META_PAGE), 0)

    def reload(self) -> None:
        self._load()

    def _flush_meta(self) -> None:
        buf = bytearray(PAGE_SIZE)
        struct.pack_into(META_FORMAT, buf, 0, self._root, self._seg.free_head)
        self._seg.write(META_PAGE, bytes(buf))

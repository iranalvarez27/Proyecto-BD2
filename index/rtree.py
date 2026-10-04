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

META_PAGE = 0
META_FORMAT = "<ii"               # raiz | free_list_head

HEADER = struct.Struct("<BxH")    # es_hoja | cantidad
LEAF = struct.Struct("<ddii")     # x (lon) | y (lat) | rid.page_id | rid.slot_id
INNER = struct.Struct("<ddddi")   # x_min | y_min | x_max | y_max | hijo

MAX_LEAF = (PAGE_SIZE - HEADER.size) // LEAF.size
MAX_INNER = (PAGE_SIZE - HEADER.size) // INNER.size


class _Node:
    __slots__ = ("is_leaf", "entries")

    def __init__(self, is_leaf: bool, entries: list | None = None):
        self.is_leaf = is_leaf
        self.entries = entries if entries is not None else []

    def capacity(self) -> int:
        return MAX_LEAF if self.is_leaf else MAX_INNER

    def mbr(self) -> MBR:
        if self.is_leaf:
            return MBR.of_points(self.entries)
        return MBR(min(e[0] for e in self.entries), min(e[1] for e in self.entries),
                   max(e[2] for e in self.entries), max(e[3] for e in self.entries))


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

    def range_search(self, low: Any, high: Any, stats: dict | None = None) -> list[RID]:
        rect = MBR.of_points([_xy(low), _xy(high)])
        return [rid for rid, _p in self._rect_search(rect, stats)]

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
                      stats: dict | None = None) -> list:
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
            if node.is_leaf:
                hojas += 1
                for px, py, pid, slot in node.entries:
                    # en un subarbol completo no se calcula la distancia
                    d = None if completo else mindist(x, y, (px, py, px, py))
                    if completo or d <= radius_m:
                        encontrados.append((d, RID(pid, slot), (py, px)))
            elif completo:
                pila.extend((e[4], True) for e in node.entries)
            else:
                for e in node.entries:
                    if mindist(x, y, e[:4]) <= radius_m:
                        pila.append((e[4], maxdist(x, y, e[:4]) <= radius_m))
        self._fill_stats(stats, nodos, hojas, len(encontrados))
        return encontrados

    def nearest_iter(self, center: Any, metrica: str = HAVERSINE, stats: dict | None = None):
        x, y = _xy(center)
        mindist = get_metric(metrica)
        contador = itertools.count()
        cola = [(0.0, next(contador), True, self._root)]
        if stats is not None:
            stats.update(nodos_visitados=0, hojas_visitadas=0, candidatos=0)
        while cola:
            d, _n, es_nodo, payload = heapq.heappop(cola)
            if not es_nodo:
                if stats is not None:
                    stats["candidatos"] += 1
                yield d, payload[0], payload[1]
                continue
            node = self._read(payload)
            if stats is not None:
                stats["nodos_visitados"] += 1
                stats["hojas_visitadas"] += 1 if node.is_leaf else 0
            if node.is_leaf:
                for px, py, page_id, slot_id in node.entries:
                    heapq.heappush(cola, (mindist(x, y, (px, py, px, py)), next(contador), False,
                                          (RID(page_id, slot_id), (py, px))))
            else:
                for e in node.entries:
                    heapq.heappush(cola, (mindist(x, y, e[:4]), next(contador), True, e[4]))

    def knn(self, center: Any, k: int, metrica: str = HAVERSINE,
            stats: dict | None = None) -> list:
        return list(itertools.islice(self.nearest_iter(center, metrica, stats), k))

    def polygon_search(self, vertices: list, stats: dict | None = None) -> list:
        vertices = [_xy(v) for v in vertices]
        caja = MBR.of_points(vertices)
        return self._collect(
            lambda px, py: caja.contains(px, py) and point_in_polygon(px, py, vertices),
            caja.intersects,
            lambda r: caja.contains_rect(r) and rect_in_polygon(r, vertices),
            stats)

    @staticmethod
    def _fill_stats(stats: dict | None, nodos: int, hojas: int, candidatos: int) -> None:
        if stats is not None:
            stats.update(nodos_visitados=nodos, hojas_visitadas=hojas, candidatos=candidatos)

    def _rect_search(self, rect: MBR, stats: dict | None) -> list:
        return self._collect(rect.contains, rect.intersects, rect.contains_rect, stats)

    def _collect(self, keep, may_have, has_all, stats: dict | None) -> list:
        encontrados = []
        nodos = hojas = 0
        pila = [(self._root, False)]
        while pila:
            page_id, completo = pila.pop()
            node = self._read(page_id)
            nodos += 1
            if node.is_leaf:
                hojas += 1
                for px, py, pid, slot in node.entries:
                    if completo or keep(px, py):
                        encontrados.append((RID(pid, slot), (py, px)))
            elif completo:
                pila.extend((e[4], True) for e in node.entries)
            else:
                for e in node.entries:
                    if may_have(e[:4]):
                        pila.append((e[4], has_all(e[:4])))
        self._fill_stats(stats, nodos, hojas, len(encontrados))
        return encontrados

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
            self._write(new_root_id, _Node(False, [(*child_mbr, child_id), split]))
            self._root = new_root_id
            self._flush_meta()

    @staticmethod
    def _choose_subtree(node: _Node, rect: MBR) -> int:
        mbrs = [MBR(*e[:4]) for e in node.entries]
        return min(range(len(mbrs)), key=lambda i: _preference(mbrs[i], rect))

    def _write_or_split(self, page_id: int, node: _Node):
        if len(node.entries) <= node.capacity():
            self._write(page_id, node)
            return None
        g1, g2 = self._split(node.entries, node.is_leaf)
        node.entries = g1
        sibling = _Node(node.is_leaf, g2)
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
            node = _Node(True)
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
                node = _Node(is_leaf, group)
                if spare is not None:
                    page_id, spare = spare, None
                    self._write(page_id, node)
                else:
                    page_id = self._seg.append(self._encode(node))
                level.append((*node.mbr(), page_id))
            if len(level) == 1:
                break
            entries, is_leaf = level, False
        self._root = level[0][4]
        self._flush_meta()

    # paginas y metapagina

    @staticmethod
    def _encode(node: _Node) -> bytes:
        codec = LEAF if node.is_leaf else INNER
        cuerpo = b"".join(codec.pack(*e) for e in node.entries)
        buf = HEADER.pack(1 if node.is_leaf else 0, len(node.entries)) + cuerpo
        return buf + bytes(PAGE_SIZE - len(buf))

    def _read(self, page_id: int) -> _Node:
        buf = self._seg.read(page_id)
        is_leaf, count = HEADER.unpack_from(buf, 0)
        codec = LEAF if is_leaf else INNER
        fin = HEADER.size + count * codec.size
        return _Node(bool(is_leaf), list(codec.iter_unpack(buf[HEADER.size:fin])))

    def _write(self, page_id: int, node: _Node) -> None:
        self._seg.write(page_id, self._encode(node))

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
        self._root = self._seg.append(self._encode(_Node(True)))
        self._flush_meta()

    def _load(self) -> None:
        self._root, self._seg.free_head = struct.unpack_from(META_FORMAT, self._seg.read(META_PAGE), 0)

    def reload(self) -> None:
        self._load()

    def _flush_meta(self) -> None:
        buf = bytearray(PAGE_SIZE)
        struct.pack_into(META_FORMAT, buf, 0, self._root, self._seg.free_head)
        self._seg.write(META_PAGE, bytes(buf))

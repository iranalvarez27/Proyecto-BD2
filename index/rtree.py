import heapq
import itertools
import math
import os
import struct
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.geo import (METRICA_HAVERSINE, como_punto, mbr_de_poligono,
                        punto_en_poligono, resolver_metrica)
from common.page import PAGE_SIZE
from common.types import RID
from engine.buffer_pool import BufferPool
from engine.segment import NIL, Segment
from index.base import Index

META_PAGE = 0
MAGIC = b"RTR1"
META_FORMAT = "<4siHi"            # magic | raiz | altura | free_list_head

HEADER = struct.Struct("<BxH")    # es_hoja | cantidad
LEAF = struct.Struct("<ddii")     # lat | lon | rid.page_id | rid.slot_id
INNER = struct.Struct("<ddddi")   # lat_min | lon_min | lat_max | lon_max | hijo

MAX_LEAF = (PAGE_SIZE - HEADER.size) // LEAF.size
MAX_INNER = (PAGE_SIZE - HEADER.size) // INNER.size
MIN_LEAF = int(MAX_LEAF * 0.4)
MIN_INNER = int(MAX_INNER * 0.4)
BULK_FILL = 0.85                  # ocupacion de los nodos tras una carga STR


class _Node:
    __slots__ = ("is_leaf", "entries")

    def __init__(self, is_leaf: bool, entries: list | None = None):
        self.is_leaf = is_leaf
        self.entries = entries if entries is not None else []

    def capacity(self) -> int:
        return MAX_LEAF if self.is_leaf else MAX_INNER

    def minimum(self) -> int:
        return MIN_LEAF if self.is_leaf else MIN_INNER

    def mbr(self) -> tuple:
        if self.is_leaf:
            lats = [e[0] for e in self.entries]
            lons = [e[1] for e in self.entries]
            return (min(lats), min(lons), max(lats), max(lons))
        return (min(e[0] for e in self.entries), min(e[1] for e in self.entries),
                max(e[2] for e in self.entries), max(e[3] for e in self.entries))


def _rect(entry: tuple, is_leaf: bool) -> tuple:
    if is_leaf:
        return (entry[0], entry[1], entry[0], entry[1])
    return entry[:4]


def _area(r: tuple) -> float:
    return (r[2] - r[0]) * (r[3] - r[1])


def _union(a: tuple, b: tuple) -> tuple:
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def _intersects(a: tuple, b: tuple) -> bool:
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


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

    @property
    def height(self) -> int:
        return self._height

    # ------------------------------------------------------------------
    # interfaz Index
    # ------------------------------------------------------------------

    def insert(self, key: Any, rid: RID) -> None:
        lat, lon = como_punto(key)
        self._insert_entry((lat, lon, rid.page_id, rid.slot_id))

    def search(self, key: Any) -> list[RID]:
        lat, lon = como_punto(key)
        return [rid for rid, _p in self._rect_search((lat, lon, lat, lon), None)]

    def range_search(self, low: Any, high: Any, stats: dict | None = None) -> list[RID]:
        lat1, lon1 = como_punto(low)
        lat2, lon2 = como_punto(high)
        rect = (min(lat1, lat2), min(lon1, lon2), max(lat1, lat2), max(lon1, lon2))
        return [rid for rid, _p in self._rect_search(rect, stats)]

    def delete(self, key: Any, rid: RID) -> bool:
        lat, lon = como_punto(key)
        target = (lat, lon, rid.page_id, rid.slot_id)
        path = self._find_leaf(self._root, target)
        if path is None:
            return False
        self._condense(path)
        return True

    def is_empty(self) -> bool:
        root = self._read(self._root)
        return root.is_leaf and not root.entries

    # ------------------------------------------------------------------
    # consultas espaciales
    # ------------------------------------------------------------------

    def radius_search(self, center: Any, radius_m: float, metrica: str = METRICA_HAVERSINE,
                      stats: dict | None = None) -> list:
        lat, lon = como_punto(center)
        dist, mindist = resolver_metrica(metrica)
        encontrados = []
        nodos = hojas = 0
        pila = [self._root]
        while pila:
            node = self._read(pila.pop())
            nodos += 1
            if node.is_leaf:
                hojas += 1
                for plat, plon, page_id, slot_id in node.entries:
                    d = dist(lat, lon, plat, plon)
                    if d <= radius_m:
                        encontrados.append((d, RID(page_id, slot_id), (plat, plon)))
            else:
                for e in node.entries:
                    if mindist(lat, lon, e[:4]) <= radius_m:
                        pila.append(e[4])
        self._fill_stats(stats, nodos, hojas, len(encontrados))
        return encontrados

    def nearest_iter(self, center: Any, metrica: str = METRICA_HAVERSINE, stats: dict | None = None):
        lat, lon = como_punto(center)
        dist, mindist = resolver_metrica(metrica)
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
                for plat, plon, page_id, slot_id in node.entries:
                    heapq.heappush(cola, (dist(lat, lon, plat, plon), next(contador), False,
                                          (RID(page_id, slot_id), (plat, plon))))
            else:
                for e in node.entries:
                    heapq.heappush(cola, (mindist(lat, lon, e[:4]), next(contador), True, e[4]))

    def knn(self, center: Any, k: int, metrica: str = METRICA_HAVERSINE,
            stats: dict | None = None) -> list:
        return list(itertools.islice(self.nearest_iter(center, metrica, stats), k))

    def polygon_search(self, vertices: list, stats: dict | None = None) -> list:
        vertices = [como_punto(v) for v in vertices]
        caja = mbr_de_poligono(vertices)
        encontrados = []
        nodos = hojas = 0
        pila = [self._root]
        while pila:
            node = self._read(pila.pop())
            nodos += 1
            if node.is_leaf:
                hojas += 1
                for plat, plon, page_id, slot_id in node.entries:
                    if (caja[0] <= plat <= caja[2] and caja[1] <= plon <= caja[3]
                            and punto_en_poligono(plat, plon, vertices)):
                        encontrados.append((RID(page_id, slot_id), (plat, plon)))
            else:
                for e in node.entries:
                    if _intersects(e[:4], caja):
                        pila.append(e[4])
        self._fill_stats(stats, nodos, hojas, len(encontrados))
        return encontrados

    def scan(self):
        pila = [self._root]
        while pila:
            node = self._read(pila.pop())
            if node.is_leaf:
                for plat, plon, page_id, slot_id in node.entries:
                    yield (plat, plon), RID(page_id, slot_id)
            else:
                pila.extend(e[4] for e in node.entries)

    def estadisticas(self) -> dict:
        nodos = hojas = entradas = 0
        pila = [self._root]
        while pila:
            node = self._read(pila.pop())
            nodos += 1
            if node.is_leaf:
                hojas += 1
                entradas += len(node.entries)
            else:
                pila.extend(e[4] for e in node.entries)
        paginas = self._seg.page_count()
        return {"altura": self._height, "nodos": nodos, "hojas": hojas, "entradas": entradas,
                "paginas": paginas, "bytes": paginas * PAGE_SIZE}

    @staticmethod
    def _fill_stats(stats: dict | None, nodos: int, hojas: int, candidatos: int) -> None:
        if stats is not None:
            stats.update(nodos_visitados=nodos, hojas_visitadas=hojas, candidatos=candidatos)

    def _rect_search(self, rect: tuple, stats: dict | None) -> list:
        encontrados = []
        nodos = hojas = 0
        pila = [self._root]
        while pila:
            node = self._read(pila.pop())
            nodos += 1
            if node.is_leaf:
                hojas += 1
                for plat, plon, page_id, slot_id in node.entries:
                    if rect[0] <= plat <= rect[2] and rect[1] <= plon <= rect[3]:
                        encontrados.append((RID(page_id, slot_id), (plat, plon)))
            else:
                for e in node.entries:
                    if _intersects(e[:4], rect):
                        pila.append(e[4])
        self._fill_stats(stats, nodos, hojas, len(encontrados))
        return encontrados

    # ------------------------------------------------------------------
    # insercion
    # ------------------------------------------------------------------

    def _insert_entry(self, entry: tuple) -> None:
        lat, lon = entry[0], entry[1]
        path = []
        page_id = self._root
        node = self._read(page_id)
        while not node.is_leaf:
            i = self._choose_subtree(node, lat, lon)
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
                return  # el MBR no crecio: los ancestros tampoco cambian
            child_id, child_mbr = parent_id, parent.mbr()

        if split is not None:
            new_root_id = self._alloc_page()
            self._write(new_root_id, _Node(False, [(*child_mbr, child_id), split]))
            self._root = new_root_id
            self._height += 1
            self._flush_meta()

    @staticmethod
    def _choose_subtree(node: _Node, lat: float, lon: float) -> int:
        best = 0
        best_key = None
        for i, (a, b, c, d, _child) in enumerate(node.entries):
            area = (c - a) * (d - b)
            grown = (max(c, lat) - min(a, lat)) * (max(d, lon) - min(b, lon))
            key = (grown - area, area)
            if best_key is None or key < best_key:
                best, best_key = i, key
        return best

    def _write_or_split(self, page_id: int, node: _Node):
        if len(node.entries) <= node.capacity():
            self._write(page_id, node)
            return None
        g1, g2 = self._quadratic_split(node.entries, node.is_leaf, node.minimum())
        node.entries = g1
        sibling = _Node(node.is_leaf, g2)
        sibling_id = self._alloc_page()
        self._write(page_id, node)
        self._write(sibling_id, sibling)
        return (*sibling.mbr(), sibling_id)

    @staticmethod
    def _quadratic_split(entries: list, is_leaf: bool, minimum: int):
        rects = [_rect(e, is_leaf) for e in entries]
        n = len(entries)

        # PickSeeds: el par que mas area desperdicia si quedara junto
        peor, s1, s2 = -1.0, 0, 1
        for i in range(n - 1):
            ri = rects[i]
            ai = _area(ri)
            for j in range(i + 1, n):
                rj = rects[j]
                waste = ((max(ri[2], rj[2]) - min(ri[0], rj[0]))
                         * (max(ri[3], rj[3]) - min(ri[1], rj[1])) - ai - _area(rj))
                if waste > peor:
                    peor, s1, s2 = waste, i, j

        g1, g2 = [entries[s1]], [entries[s2]]
        m1, m2 = rects[s1], rects[s2]
        restantes = [i for i in range(n) if i != s1 and i != s2]

        while restantes:
            # si un grupo necesita todo lo que queda para llegar al minimo, se lo lleva
            if len(g1) + len(restantes) <= minimum:
                g1.extend(entries[i] for i in restantes)
                break
            if len(g2) + len(restantes) <= minimum:
                g2.extend(entries[i] for i in restantes)
                break

            # PickNext: la entrada con mayor preferencia por uno de los grupos
            a1, a2 = _area(m1), _area(m2)
            mejor_pos, mejor_diff, mejor_d1, mejor_d2 = 0, -1.0, 0.0, 0.0
            for pos, i in enumerate(restantes):
                r = rects[i]
                d1 = ((max(m1[2], r[2]) - min(m1[0], r[0]))
                      * (max(m1[3], r[3]) - min(m1[1], r[1])) - a1)
                d2 = ((max(m2[2], r[2]) - min(m2[0], r[0]))
                      * (max(m2[3], r[3]) - min(m2[1], r[1])) - a2)
                diff = abs(d1 - d2)
                if diff > mejor_diff:
                    mejor_pos, mejor_diff, mejor_d1, mejor_d2 = pos, diff, d1, d2
            i = restantes.pop(mejor_pos)
            a_g1 = (mejor_d1, a1, len(g1)) <= (mejor_d2, a2, len(g2))
            if a_g1:
                g1.append(entries[i])
                m1 = _union(m1, rects[i])
            else:
                g2.append(entries[i])
                m2 = _union(m2, rects[i])
        return g1, g2

    # ------------------------------------------------------------------
    # eliminacion
    # ------------------------------------------------------------------

    def _find_leaf(self, page_id: int, target: tuple):
        node = self._read(page_id)
        if node.is_leaf:
            for i, e in enumerate(node.entries):
                if e == target:
                    return [(page_id, node, i)]
            return None
        lat, lon = target[0], target[1]
        for i, e in enumerate(node.entries):
            if e[0] <= lat <= e[2] and e[1] <= lon <= e[3]:
                sub = self._find_leaf(e[4], target)
                if sub is not None:
                    return [(page_id, node, i)] + sub
        return None

    def _condense(self, path: list) -> None:
        huerfanos = []
        page_id, node, idx = path[-1]
        del node.entries[idx]

        for level in range(len(path) - 1, 0, -1):
            parent_id, parent, parent_idx = path[level - 1]
            if len(node.entries) < node.minimum():
                huerfanos.extend(self._collect_and_free(node))
                self._free_page(page_id)
                del parent.entries[parent_idx]
            else:
                self._write(page_id, node)
                parent.entries[parent_idx] = (*node.mbr(), page_id)
            page_id, node = parent_id, parent

        # ``node`` es ahora la raiz
        if not node.is_leaf and not node.entries:
            node = _Node(True)
            self._height = 1
        self._write(page_id, node)
        while not node.is_leaf and len(node.entries) == 1:
            hijo = node.entries[0][4]
            self._free_page(page_id)
            page_id, node = hijo, self._read(hijo)
            self._height -= 1
        self._root = page_id
        self._flush_meta()

        for entry in huerfanos:
            self._insert_entry(entry)

    def _collect_and_free(self, node: _Node) -> list:
        if node.is_leaf:
            return list(node.entries)
        puntos = []
        for e in node.entries:
            puntos.extend(self._collect_and_free(self._read(e[4])))
            self._free_page(e[4])
        return puntos

    # ------------------------------------------------------------------
    # carga masiva (STR)
    # ------------------------------------------------------------------

    def bulk_load(self, pairs) -> None:
        entries = []
        for key, rid in pairs:
            lat, lon = como_punto(key)
            entries.append((lat, lon, rid.page_id, rid.slot_id))

        self._seg.truncate(1)
        if not entries:
            self._root = self._seg.append(self._encode(_Node(True)))
            self._height = 1
            self._flush_meta()
            return

        nivel = self._str_pack(entries, True)
        altura = 1
        while len(nivel) > 1:
            nivel = self._str_pack(nivel, False)
            altura += 1
        self._root = nivel[0][4]
        self._height = altura
        self._flush_meta()

    def _str_pack(self, entries: list, is_leaf: bool) -> list:
        cap = max(2, int((MAX_LEAF if is_leaf else MAX_INNER) * BULK_FILL))
        if is_leaf:
            por_lon = lambda e: e[1]
            por_lat = lambda e: e[0]
        else:
            por_lon = lambda e: (e[1] + e[3]) / 2
            por_lat = lambda e: (e[0] + e[2]) / 2

        n_nodos = math.ceil(len(entries) / cap)
        n_franjas = math.ceil(math.sqrt(n_nodos))
        tam_franja = n_franjas * cap

        entries.sort(key=por_lon)
        padres = []
        for inicio in range(0, len(entries), tam_franja):
            franja = sorted(entries[inicio:inicio + tam_franja], key=por_lat)
            for j in range(0, len(franja), cap):
                node = _Node(is_leaf, franja[j:j + cap])
                page_id = self._seg.append(self._encode(node))
                padres.append((*node.mbr(), page_id))
        return padres

    # ------------------------------------------------------------------
    # paginas y metapagina
    # ------------------------------------------------------------------

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
        self._height = 1
        self._flush_meta()

    def _load(self) -> None:
        magic, root, height, free_head = struct.unpack_from(META_FORMAT, self._seg.read(META_PAGE), 0)
        if magic != MAGIC:
            raise ValueError(f"{self._seg.path} no es un indice R-Tree")
        self._root = root
        self._height = height
        self._seg.free_head = free_head

    def reload(self) -> None:
        self._load()

    def _flush_meta(self) -> None:
        buf = bytearray(PAGE_SIZE)
        struct.pack_into(META_FORMAT, buf, 0, MAGIC, self._root, self._height, self._seg.free_head)
        self._seg.write(META_PAGE, bytes(buf))

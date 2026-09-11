import os
import struct
import sys
from bisect import bisect_left, bisect_right
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.types import RID, DataType
from index.base import Index
from index.key_codec import decode, encode, type_code, type_from_code
from index.node_page import (
    CHILD_CODEC,
    HEADER_SIZE,
    KEY_LEN_SIZE,
    QUARTER,
    USABLE,
    NIL,
    PAGE_ID_CODEC,
    PAGE_SIZE,
    RID_CODEC,
    NodePage,
)

MAGIC = b"BPIX"
VERSION = 1
META_PAGE = 0

# magic | version | flags | key_type | root | height | payload_size | free_list_head | n_entries
META_FORMAT = "<4sHBBiHHiq"
META_SIZE = struct.calcsize(META_FORMAT)  # 28

FLAG_UNIQUE = 1 << 0
FLAG_CLUSTERED = 1 << 1


class DuplicateKey(Exception):
    def __init__(self, key: Any):
        self.key = key
        super().__init__(f"{key!r} already exists in a unique index")


class BPlusTree(Index):
    """B+ tree over one file: page 0 is the metapage, and inner nodes, leaves
    and free pages are interleaved after it -- everything is addressed by page
    id, so a split never moves an existing node.

    Unlike the extendible hash the index is **not lossy**: the key is stored, so
    a match is a match and the caller does not have to recheck the base record.
    That is forced by the structure, not a preference -- an ordered tree cannot
    place a key it cannot compare.

    Keys are variable width (VARCHAR is indexable), so the tree has no order M:
    a node splits when its bytes overflow the page and is underfull below
    half."""

    def __init__(
        self,
        path: str,
        key_type: DataType | None = None,
        unique: bool = False,
        clustered: bool = False,
    ):
        self._path = path
        if os.path.exists(path) and os.path.getsize(path) >= PAGE_SIZE:
            self._load()
            if key_type is not None and key_type != self._key_type:
                raise ValueError(
                    f"{path} indexes {self._key_type.value}, not {key_type.value}"
                )
        else:
            if key_type is None:
                raise ValueError("a new index needs its key_type")
            self._create(key_type, unique, clustered)

    # ------------------------------------------------------------------ Index

    def insert(self, key: Any, rid: RID) -> None:
        self._insert_raw(encode(key, self._key_type), rid)

    def search(self, key: Any) -> list:
        return self.range_search(key, key)

    def range_search(self, low: Any, high: Any) -> list:
        """Inclusive [low, high]. One routine covers equality too: search(k) is
        the range [k, k]."""
        k_lo = encode(low, self._key_type)
        k_hi = encode(high, self._key_type)
        if k_lo > k_hi:
            return []
        return self._range_raw(k_lo, k_hi)

    def delete(self, key: Any, rid: RID) -> bool:
        return self._delete_raw(encode(key, self._key_type), rid)

    # -------------------------------------------------------------- insertion

    def _insert_raw(self, k: bytes, payload) -> None:
        path: list[tuple[int, int]] = []
        page_id = self._root
        node = self._read_node(page_id)
        while not node.is_leaf:
            i = bisect_left(node.keys, k)  # bisect_left, no `<`: hay repetidas
            path.append((page_id, i))
            page_id = node.child(i)
            node = self._read_node(page_id)

        i = bisect_left(node.keys, k)
        if self._unique and self._present(node, i, k):
            raise DuplicateKey(decode(k, self._key_type))

        # caso 1: entra, y entonces no se toca ningún nodo interno
        if node.will_fit(k):
            node.insert(i, k, payload)
            self._write_node(page_id, node)
            self._n_entries += 1
            self._flush_meta()
            return

        # caso 2: se parte la hoja y el aviso sube
        sep, right_id = self._split_leaf(page_id, node, i, k, payload)
        self._n_entries += 1

        while path:
            parent_id, idx = path.pop()
            parent = self._read_node(parent_id)
            # la mitad izquierda reusó la página vieja, así que el hijo en idx
            # ya es el correcto: solo hay que meter el separador y reapuntar el
            # que quedó a su derecha
            parent.insert(idx, sep, parent.child(idx))
            parent.set_child(idx + 1, right_id)

            if parent.byte_size() <= PAGE_SIZE:
                self._write_node(parent_id, parent)
                self._flush_meta()
                return
            sep, right_id = self._split_inner(parent_id, parent)

        # caso 3: se partió la raíz, el árbol crece hacia arriba
        new_root_id = self._alloc_page()
        new_root = NodePage(is_leaf=False)
        new_root.append(sep, self._root)
        new_root.last_child = right_id
        self._write_node(new_root_id, new_root)
        self._root = new_root_id
        self._height += 1
        self._flush_meta()

    def _split_leaf(self, page_id: int, leaf: NodePage, i: int, k: bytes, payload):
        """Returns (separator, right_page_id). The separator is *copied*: it is
        a datum and has to stay in the right half too."""
        keys = leaf.keys[:i] + [k] + leaf.keys[i:]
        payloads = leaf.payloads[:i] + [payload] + leaf.payloads[i:]
        m = leaf.split_index(keys)

        right_id = self._alloc_page()
        right = NodePage(is_leaf=True, leaf_codec=self._leaf_codec)
        right.keys, right.payloads = keys[m:], payloads[m:]
        right.prev_page = page_id
        right.next_page = leaf.next_page

        old_next = leaf.next_page
        leaf.keys, leaf.payloads = keys[:m], payloads[:m]
        leaf.next_page = right_id
        # leaf.prev_page no se toca: reusar la página vieja deja intacto el
        # `next` del vecino izquierdo y el puntero del padre

        self._write_node(page_id, leaf)
        self._write_node(right_id, right)
        if old_next != NIL:
            nxt = self._read_node(old_next)
            nxt.prev_page = right_id
            self._write_node(old_next, nxt)

        return keys[m], right_id

    def _split_inner(self, page_id: int, node: NodePage):
        """Returns (separator, right_page_id). Here the middle key is *lifted*:
        it is a signpost, it disappears from both children."""
        m = node.split_index(node.keys, min_right=2)
        mid_key = node.keys[m]
        mid_child = node.payloads[m]  # el subárbol de lo menor que la que sube

        right_id = self._alloc_page()
        right = NodePage(is_leaf=False)
        right.keys, right.payloads = node.keys[m + 1:], node.payloads[m + 1:]
        right.last_child = node.last_child

        node.keys, node.payloads = node.keys[:m], node.payloads[:m]
        node.last_child = mid_child

        self._write_node(page_id, node)
        self._write_node(right_id, right)
        return mid_key, right_id

    # --------------------------------------------------------------- borrado

    def _delete_raw(self, k: bytes, payload) -> bool:
        path: list[tuple[int, int]] = []
        page_id = self._root
        leaf = self._read_node(page_id)
        while not leaf.is_leaf:
            i = bisect_left(leaf.keys, k)
            path.append((page_id, i))
            page_id = leaf.child(i)
            leaf = self._read_node(page_id)

        i = bisect_left(leaf.keys, k)
        if i == leaf.count:
            # el descenso frena una hoja antes cuando la clave es un separador,
            # por el mismo motivo que _present
            page_id, leaf = self._advance(path)
            i = 0
            while leaf is not None and leaf.count == 0:
                page_id, leaf = self._advance(path)
            if leaf is None or leaf.keys[0] != k:
                return False
        elif leaf.keys[i] != k:
            return False

        # el RID pedido puede estar en cualquier copia de la clave, incluso en
        # una hoja posterior. Se lo pisa con el payload de la primera aparición
        # y se borra la primera, que es la única para la que tenemos el camino
        # de padres. Así el rebalanceo no necesita casos especiales.
        found = self._find_payload(page_id, leaf, i, k, payload)
        if found is None:
            return False
        other_id, other, j = found
        other.payloads[j] = leaf.payloads[i]
        if other is not leaf:
            self._write_node(other_id, other)

        old_min = leaf.keys[0]
        leaf.remove(i)
        self._write_node(page_id, leaf)
        self._n_entries -= 1

        new_min = leaf.keys[0] if leaf.count and leaf.keys[0] != old_min else None
        self._rebalance(path, new_min)
        self._flush_meta()
        return True

    def _find_payload(self, page_id: int, leaf: NodePage, i: int, k: bytes, payload):
        """Walks leaves forward from (leaf, i) while the key still matches,
        looking for the entry that carries this exact payload. Returns
        (page_id, node, slot) or None. The node comes back so the caller can
        overwrite the slot without re-reading the page."""
        node_id, node, j = page_id, leaf, i
        while True:
            if j == node.count:
                if node.next_page == NIL:
                    return None
                node_id = node.next_page
                node = self._read_node(node_id)
                j = 0
                continue
            if node.keys[j] != k:
                return None
            if node.payloads[j] == payload:
                return node_id, node, j
            j += 1

    def _advance(self, path: list[tuple[int, int]]):
        """Steps one leaf to the right *keeping the parent path valid* -- which
        is why this exists instead of just following next_page: the rebalance
        needs the path to the leaf it actually deletes from."""
        while path:
            parent_id, idx = path[-1]
            parent = self._read_node(parent_id)
            if idx < parent.count:
                path[-1] = (parent_id, idx + 1)
                node_id = parent.child(idx + 1)
                node = self._read_node(node_id)
                while not node.is_leaf:
                    path.append((node_id, 0))
                    node_id = node.child(0)
                    node = self._read_node(node_id)
                return node_id, node
            path.pop()
        return None, None

    def _rebalance(self, path: list[tuple[int, int]], new_min: bytes | None) -> None:
        while path:
            parent_id, idx = path.pop()
            parent = self._read_node(parent_id)
            dirty = False

            # el separador que apunta a este hijo es el de idx−1; si idx == 0
            # el que hay que arreglar está más arriba, así que se sigue subiendo
            if new_min is not None and idx > 0:
                # si el mínimo nuevo es más ancho puede no entrar en el padre.
                # Dejar el viejo es seguro: apunta por debajo del mínimo real,
                # y el descenso sigue cayendo en el hijo correcto
                if parent.can_replace(idx - 1, new_min):
                    parent.keys[idx - 1] = new_min
                    dirty = True
                new_min = None

            child_id = parent.child(idx)
            child = self._read_node(child_id)
            if child.is_underfull():
                if self._borrow(parent, idx, child_id, child):
                    dirty = True
                else:
                    freed = self._merge(parent, idx)
                    if freed is not None:
                        dirty = True
            if dirty:
                self._write_node(parent_id, parent)
            if new_min is None and not parent.is_underfull():
                break

        # la raíz se queda sin claves y con un solo hijo: sobra, y el árbol baja
        root = self._read_node(self._root)
        if not root.is_leaf and root.count == 0:
            old_root = self._root
            self._root = root.last_child
            self._height -= 1
            self._free_page(old_root)

    def _borrow(self, parent: NodePage, idx: int, node_id: int, node: NodePage) -> bool:
        """Takes one entry from a sibling that can spare it, trying the left
        one first. False if neither side works, and then the caller merges.

        Three things have to fit, not one: the entry in this node, the sibling
        staying half full, and the *parent*, because the separator that rises
        can be wider than the one it replaces. Nothing is mutated until all
        three are known to hold, so a side that fails just moves on.

        Careful: "cannot lend" does not imply "is underfull" -- can_lend(i) is
        false when content - entry_size(i) < HALF, which a wide boundary key
        triggers on siblings well above HALF. So the merge that follows is not
        guaranteed to fit either, and checks for itself."""
        for side in (-1, +1):
            sib_idx = idx + side
            if not 0 <= sib_idx <= parent.count:
                continue
            sib_id = parent.child(sib_idx)
            sib = self._read_node(sib_id)
            take = sib.count - 1 if side < 0 else 0
            if sib.count == 0 or not sib.can_lend(take):
                continue
            # el separador entre este nodo y el hermano: el de idx−1 si el
            # hermano está a la izquierda, el de idx si está a la derecha
            sep_idx = idx - 1 if side < 0 else idx

            if node.is_leaf:
                # la entrada cruza y el separador pasa a ser la clave que queda
                # al frente del nodo de la derecha. can_lend garantiza que al
                # hermano derecho le queda una segunda clave para ceder esa
                moving = sib.keys[take]
                new_sep = moving if side < 0 else sib.keys[1]
                if not node.will_fit(moving) or not parent.can_replace(sep_idx, new_sep):
                    continue
                key, pay = sib.remove(take)
                if side < 0:
                    node.insert(0, key, pay)
                else:
                    node.append(key, pay)
            else:
                # rotación de tres partes: una clave interna es un separador y
                # no puede saltar de nodo sin pasar por el padre
                lowered = parent.keys[sep_idx]
                new_sep = sib.keys[take]
                if not node.will_fit(lowered) or not parent.can_replace(sep_idx, new_sep):
                    continue
                _, moved_child = sib.remove(take)
                if side < 0:
                    node.insert(0, lowered, sib.last_child)
                    sib.last_child = moved_child
                else:
                    node.append(lowered, node.last_child)
                    node.last_child = moved_child

            parent.keys[sep_idx] = new_sep
            self._write_node(sib_id, sib)
            self._write_node(node_id, node)
            return True
        return False

    def _merge(self, parent: NodePage, idx: int) -> int | None:
        """Merges child idx with the one to its right, normalising so there is
        a single case to write; the last child has no right sibling, so there
        its left sibling absorbs it instead. Returns the freed page."""
        if idx == parent.count:
            idx -= 1  # somos el último hijo: nos absorbe el hermano izquierdo
        if idx < 0:
            return None

        left_id, right_id = parent.child(idx), parent.child(idx + 1)
        left, right = self._read_node(left_id), self._read_node(right_id)

        extra = 0 if left.is_leaf else left.entry_size(parent.keys[idx])
        if left.byte_size() + right.byte_size() - HEADER_SIZE + extra > PAGE_SIZE:
            return None  # no entran juntos; queda corto, que es legal

        if left.is_leaf:
            left.keys += right.keys
            left.payloads += right.payloads
            left.next_page = right.next_page
            if right.next_page != NIL:
                after = self._read_node(right.next_page)
                after.prev_page = left_id
                self._write_node(right.next_page, after)
        else:
            # el separador del padre baja y se vuelve una clave más, con el
            # último hijo de la izquierda colgando de ella
            left.append(parent.keys[idx], left.last_child)
            left.keys += right.keys
            left.payloads += right.payloads
            left.last_child = right.last_child

        # sacar el separador del padre sin perder el hijo que sobrevive
        if idx == parent.count - 1:
            parent.remove(idx)
            parent.last_child = left_id
        else:
            parent.keys[idx] = parent.keys[idx + 1]
            parent.remove(idx + 1)

        self._write_node(left_id, left)
        self._free_page(right_id)
        return right_id

    # ------------------------------------------------------------ bulk load

    @staticmethod
    def _pack(sizes: list[int], capacity: int, gap: int = 0) -> list[tuple[int, int]]:
        """Cuts consecutive items into runs that each fit in `capacity`.

        `gap` is how many items are *consumed* at each boundary instead of
        going into either run. It is 0 for leaves and 1 for inner levels: the
        separator between two parents belongs to neither, it rises to become
        the right parent's own minimum one level up. Getting that wrong makes a
        child appear under two parents.

        The last two runs are evened out when the last one comes up short --
        otherwise the tail of a bulk load is whatever happened to be left over,
        which can be one entry, or with a gap, none at all."""
        runs: list[tuple[int, int]] = []
        start = used = i = 0
        while i < len(sizes):
            if i > start and used + sizes[i] > capacity:
                runs.append((start, i))
                start = i = i + gap
                used = 0
                continue
            used += sizes[i]
            i += 1
        runs.append((start, len(sizes)))

        if len(runs) >= 2 and sum(sizes[runs[-1][0]:runs[-1][1]]) < QUARTER:
            a, end = runs[-2][0], runs[-1][1]
            best = best_gap = None
            for cut in range(a + 1, end - gap + 1):
                left = sum(sizes[a:cut])
                right = sum(sizes[cut + gap:end])
                if not right or left > capacity or right > capacity:
                    continue
                spread = abs(left - right)
                if best_gap is None or spread < best_gap:
                    best, best_gap = cut, spread
            if best is not None:
                runs[-2:] = [(a, best), (best + gap, end)]
        return runs

    def bulk_load(self, pairs) -> None:
        """Rebuilds the tree from scratch out of (key, payload) pairs already
        in ascending key order, bottom up and in one pass: no descent, no
        split, no page ever written twice.

        Leaves are filled to 100%, not the usual 70%. The user of this is the
        clustered index, whose tree is immutable between reorganizations, so
        leaving room for inserts that will never come would only buy extra
        height."""
        self._truncate_to_meta()
        codec = self._leaf_codec

        keys: list[bytes] = []
        payloads: list = []
        prev: bytes | None = None
        for value, payload in pairs:
            k = encode(value, self._key_type)
            if prev is not None:
                if k < prev:
                    raise ValueError("bulk_load needs the pairs in ascending key order")
                if k == prev and self._unique:
                    raise DuplicateKey(value)
            prev = k
            keys.append(k)
            payloads.append(payload)

        self._n_entries = len(keys)
        self._height = 1

        if not keys:  # índice vacío: una hoja raíz y nada más
            self._root = self._append_raw(
                NodePage(is_leaf=True, leaf_codec=codec).to_bytes()
            )
            self._flush_meta()
            return

        # ── nivel 0 · hojas, con ids consecutivos y la cadena ya enlazada ──
        runs = self._pack([KEY_LEN_SIZE + codec.size + len(k) for k in keys], USABLE)
        first = self._page_count()
        level: list[tuple[bytes, int]] = []
        for j, (a, b) in enumerate(runs):
            leaf = NodePage(is_leaf=True, leaf_codec=codec)
            leaf.keys, leaf.payloads = keys[a:b], payloads[a:b]
            leaf.prev_page = first + j - 1 if j > 0 else NIL
            leaf.next_page = first + j + 1 if j < len(runs) - 1 else NIL
            level.append((keys[a], self._append_raw(leaf.to_bytes())))

        # ── niveles superiores ──
        # Se agrupan los SEPARADORES, no los hijos: el separador j-ésimo es el
        # mínimo del hijo j+1 y lleva al hijo j como hijo izquierdo. Un grupo de
        # s separadores da un nodo de s+1 hijos, así que ningún nodo puede
        # quedar sin claves y no hace falta ningún caso especial.
        while len(level) > 1:
            # seps[t] = (mínimo del hijo t+1, id del hijo t). Un run [a,b) da un
            # nodo con hijos a..b: los separadores a..b−1 adentro, el hijo b de
            # last_child, y el separador b consumido como frontera (gap=1).
            seps = [(level[i][0], level[i - 1][1]) for i in range(1, len(level))]
            runs = self._pack([KEY_LEN_SIZE + CHILD_CODEC.size + len(k)
                               for k, _ in seps], USABLE, gap=1)
            parents: list[tuple[bytes, int]] = []
            for a, b in runs:
                node = NodePage(is_leaf=False)
                for k, left in seps[a:b]:
                    node.append(k, left)
                node.last_child = level[b][1]
                parents.append((level[a][0], self._append_raw(node.to_bytes())))
            level = parents
            self._height += 1

        self._root = level[0][1]
        self._flush_meta()

    def _truncate_to_meta(self) -> None:
        with open(self._path, "r+b") as f:
            f.truncate(PAGE_SIZE)
        self._free_list_head = NIL

    def floor(self, key: Any):
        """Payload of the greatest entry whose key is <= `key`, or None.

        This is the clustered index's lookup: its entries are page minimums, so
        "where does this key live" means "the last page whose minimum does not
        exceed it". Assumes unique keys, which a clustered index has."""
        k = encode(key, self._key_type)
        node = self._read_node(self._root)
        while not node.is_leaf:
            node = self._read_node(node.child(bisect_right(node.keys, k)))
        i = bisect_right(node.keys, k) - 1
        if i >= 0:
            return node.payloads[i]
        while node.prev_page != NIL:
            node = self._read_node(node.prev_page)
            if node.count:
                return node.payloads[-1]
        return None

    # ---------------------------------------------------------------- lectura

    def _present(self, leaf: NodePage, i: int, k: bytes) -> bool:
        """Whether `k` is already in the index, given the leaf the descent
        reached and `i = lower_bound(leaf, k)`.

        Looking at `leaf.keys[i]` is not enough. `bisect_left` lands on the
        *leftmost* subtree that could hold the key, so when `k` is itself a
        separator the key sits at the front of the **next** leaf: the descent
        stops one leaf short of it. Missing that check let a unique index take
        the same key twice."""
        if i < leaf.count:
            return leaf.keys[i] == k
        while leaf.next_page != NIL:
            leaf = self._read_node(leaf.next_page)
            if leaf.count:
                return leaf.keys[0] == k
        return False

    def _descend(self, k: bytes) -> tuple[int, NodePage]:
        page_id = self._root
        node = self._read_node(page_id)
        while not node.is_leaf:
            page_id = node.child(bisect_left(node.keys, k))
            node = self._read_node(page_id)
        return page_id, node

    def _range_raw(self, k_lo: bytes, k_hi: bytes) -> list:
        _, node = self._descend(k_lo)
        i = bisect_left(node.keys, k_lo)
        out = []
        while True:
            if i == node.count:
                if node.next_page == NIL:
                    break
                node = self._read_node(node.next_page)
                i = 0
                continue
            if node.keys[i] > k_hi:
                break
            out.append(node.payloads[i])
            i += 1
        return out

    def scan(self):
        """Every (key, payload) in key order, walking the leaf chain."""
        node = self._read_node(self._leftmost_leaf())
        while True:
            for k, p in zip(node.keys, node.payloads):
                yield decode(k, self._key_type), p
            if node.next_page == NIL:
                return
            node = self._read_node(node.next_page)

    def _leftmost_leaf(self) -> int:
        page_id = self._root
        node = self._read_node(page_id)
        while not node.is_leaf:
            page_id = node.child(0)
            node = self._read_node(page_id)
        return page_id

    # ------------------------------------------------------------ páginas

    def _page_count(self) -> int:
        return os.path.getsize(self._path) // PAGE_SIZE

    def _read_raw(self, page_id: int) -> bytes:
        with open(self._path, "rb") as f:
            f.seek(page_id * PAGE_SIZE)
            return f.read(PAGE_SIZE)

    def _write_raw(self, page_id: int, data: bytes) -> None:
        with open(self._path, "r+b") as f:
            f.seek(page_id * PAGE_SIZE)
            f.write(data)

    def _append_raw(self, data: bytes) -> int:
        page_id = self._page_count()
        with open(self._path, "ab") as f:
            f.write(data)
        return page_id

    def _alloc_page(self) -> int:
        """Reuses a freed page before growing the file. Merges free pages in
        the *middle* of the file, and truncating would shift every page after
        it and invalidate all the ids, so reuse is the only way back."""
        if self._free_list_head != NIL:
            page_id = self._free_list_head
            self._free_list_head = struct.unpack_from("<i", self._read_raw(page_id), 0)[0]
            self._flush_meta()
            return page_id
        return self._append_raw(bytes(PAGE_SIZE))

    def _free_page(self, page_id: int) -> None:
        buf = bytearray(PAGE_SIZE)
        struct.pack_into("<i", buf, 0, self._free_list_head)
        self._write_raw(page_id, bytes(buf))
        self._free_list_head = page_id
        self._flush_meta()

    def _read_node(self, page_id: int) -> NodePage:
        return NodePage.from_bytes(self._read_raw(page_id), leaf_codec=self._leaf_codec)

    def _write_node(self, page_id: int, node: NodePage) -> None:
        self._write_raw(page_id, node.to_bytes())

    # ------------------------------------------------------------ metapágina

    def _create(self, key_type: DataType, unique: bool, clustered: bool) -> None:
        self._key_type = key_type
        self._unique = unique or clustered  # una PK agrupada es única por definición
        self._clustered = clustered
        self._leaf_codec = PAGE_ID_CODEC if clustered else RID_CODEC
        self._root = 1
        self._height = 1
        self._free_list_head = NIL
        self._n_entries = 0

        with open(self._path, "wb") as f:
            f.write(bytes(PAGE_SIZE))  # metapágina, se completa abajo
            f.write(NodePage(is_leaf=True, leaf_codec=self._leaf_codec).to_bytes())
        self._flush_meta()

    def _load(self) -> None:
        (magic, version, flags, key_type, root, height,
         payload_size, free_list_head, n_entries) = struct.unpack_from(
            META_FORMAT, self._read_raw(META_PAGE), 0
        )
        if magic != MAGIC:
            raise ValueError(f"{self._path} is not a B+ tree index (magic {magic!r})")
        if version != VERSION:
            raise ValueError(f"{self._path} has format version {version}, expected {VERSION}")

        self._key_type = type_from_code(key_type)
        self._unique = bool(flags & FLAG_UNIQUE)
        self._clustered = bool(flags & FLAG_CLUSTERED)
        self._leaf_codec = PAGE_ID_CODEC if self._clustered else RID_CODEC
        if payload_size != self._leaf_codec.size:
            raise ValueError(
                f"metapage says payload_size={payload_size}, "
                f"but a {'clustered' if self._clustered else 'plain'} leaf uses "
                f"{self._leaf_codec.size}"
            )
        self._root = root
        self._height = height
        self._free_list_head = free_list_head
        self._n_entries = n_entries

    def _flush_meta(self) -> None:
        flags = (FLAG_UNIQUE if self._unique else 0) | (FLAG_CLUSTERED if self._clustered else 0)
        buf = bytearray(PAGE_SIZE)
        struct.pack_into(
            META_FORMAT, buf, 0,
            MAGIC, VERSION, flags, type_code(self._key_type),
            self._root, self._height, self._leaf_codec.size,
            self._free_list_head, self._n_entries,
        )
        self._write_raw(META_PAGE, bytes(buf))

    # ------------------------------------------------------------- diagnóstico

    def stats(self) -> dict:
        leaves = inner = 0
        used = 0
        stack = [self._root]
        while stack:
            node = self._read_node(stack.pop())
            used += node.byte_size() - HEADER_SIZE
            if node.is_leaf:
                leaves += 1
            else:
                inner += 1
                stack.extend(node.child(i) for i in range(node.count + 1))

        free = 0
        page_id = self._free_list_head
        while page_id != NIL:
            free += 1
            page_id = struct.unpack_from("<i", self._read_raw(page_id), 0)[0]

        nodes = leaves + inner
        return {
            "key_type": self._key_type.value,
            "unique": self._unique,
            "clustered": self._clustered,
            "height": self._height,
            "entries": self._n_entries,
            "leaves": leaves,
            "inner": inner,
            "free_pages": free,
            "file_pages": self._page_count(),
            "fill_ratio": round(used / (nodes * (PAGE_SIZE - HEADER_SIZE)), 3) if nodes else 0.0,
        }

    def check_invariants(self) -> None:
        """Walks the whole tree and raises ValueError listing every violation.
        This is what caught the two split-policy bugs in the extendible hash,
        so it goes in before delete, not after."""
        problems: list[str] = []
        depth_of: dict[int, int] = {}
        leaf_ids: list[int] = []

        def walk(page_id: int, depth: int, lo: bytes | None, hi: bytes | None) -> None:
            if page_id in depth_of:
                problems.append(f"la página {page_id} es hija de dos padres")
                return
            depth_of[page_id] = depth
            node = self._read_node(page_id)

            # ocupación mínima (la raíz está exenta)
            if page_id != self._root and not node.min_fill_ok():
                problems.append(
                    f"la página {page_id} ocupa {node.byte_size() - HEADER_SIZE} B, "
                    f"menos de un cuarto del espacio útil"
                )

            # orden interno
            for i in range(1, node.count):
                if node.keys[i - 1] > node.keys[i]:
                    problems.append(f"la página {page_id} tiene las claves desordenadas en {i}")
                elif node.keys[i - 1] == node.keys[i] and self._unique:
                    problems.append(f"la página {page_id} repite una clave en {i}")

            # las claves caen dentro del rango que fija el padre
            for i, k in enumerate(node.keys):
                if lo is not None and k < lo:
                    problems.append(f"la página {page_id} tiene una clave por debajo de su cota")
                    break
                if hi is not None and k > hi:
                    problems.append(f"la página {page_id} tiene una clave por encima de su cota")
                    break

            if node.is_leaf:
                leaf_ids.append(page_id)
                # una hoja no tiene último hijo
                if node.last_child != NIL:
                    problems.append(f"la hoja {page_id} tiene last_child")
                # todas las hojas al mismo nivel
                if depth + 1 != self._height:
                    problems.append(
                        f"la hoja {page_id} está a profundidad {depth + 1}, "
                        f"height dice {self._height}"
                    )
                return

            # un nodo interno no está en la cadena de hojas
            if node.next_page != NIL or node.prev_page != NIL:
                problems.append(f"el nodo interno {page_id} está enganchado a la cadena")
            if node.count == 0:
                problems.append(f"el nodo interno {page_id} no tiene claves")
                return
            if node.last_child == NIL:
                problems.append(f"el nodo interno {page_id} no tiene last_child")
                return

            for i in range(node.count + 1):
                sub_lo = node.keys[i - 1] if i > 0 else lo
                sub_hi = node.keys[i] if i < node.count else hi
                walk(node.child(i), depth + 1, sub_lo, sub_hi)

        walk(self._root, 0, None, None)

        # la raíz es hoja si y solo si el árbol tiene un nivel
        root_is_leaf = self._read_node(self._root).is_leaf
        if root_is_leaf != (self._height == 1):
            problems.append(
                f"root_is_leaf={root_is_leaf} pero height={self._height}"
            )

        # la cadena de hojas: enlazada en los dos sentidos, ordenada y completa
        chain: list[int] = []
        seen_in_chain = set()
        total = 0
        prev_key: bytes | None = None
        page_id = self._leftmost_leaf()
        expect_prev = NIL
        while page_id != NIL:
            if page_id in seen_in_chain:
                problems.append(f"la cadena de hojas cicla en {page_id}")
                break
            seen_in_chain.add(page_id)
            chain.append(page_id)
            node = self._read_node(page_id)
            if node.prev_page != expect_prev:
                problems.append(
                    f"la hoja {page_id} dice prev={node.prev_page}, "
                    f"se llegó desde {expect_prev}"
                )
            for k in node.keys:
                if prev_key is not None and k < prev_key:
                    problems.append(f"la cadena entrega claves desordenadas en {page_id}")
                    prev_key = None
                    break
                prev_key = k
            total += node.count
            expect_prev = page_id
            page_id = node.next_page

        if total != self._n_entries:
            problems.append(
                f"la cadena tiene {total} entradas, la metapágina dice {self._n_entries}"
            )
        if set(chain) != set(leaf_ids):
            problems.append(
                f"la cadena cubre {len(set(chain))} hojas, el árbol tiene {len(set(leaf_ids))}"
            )

        # árbol y free list disjuntos, y sin páginas huérfanas
        free: list[int] = []
        seen_free = set()
        page_id = self._free_list_head
        while page_id != NIL:
            if page_id in seen_free:
                problems.append(f"la free list cicla en {page_id}")
                break
            seen_free.add(page_id)
            free.append(page_id)
            page_id = struct.unpack_from("<i", self._read_raw(page_id), 0)[0]

        overlap = set(depth_of) & seen_free
        if overlap:
            problems.append(f"páginas en el árbol y en la free list a la vez: {sorted(overlap)}")
        orphans = set(range(1, self._page_count())) - set(depth_of) - seen_free
        if orphans:
            problems.append(f"páginas huérfanas: {sorted(orphans)}")

        if problems:
            raise ValueError(
                f"{len(problems)} invariante(s) rota(s) en {self._path}:\n  - "
                + "\n  - ".join(problems)
            )

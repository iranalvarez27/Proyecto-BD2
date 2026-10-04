"""Snapshots y animaciones de B+, Hash, R-Tree y Sequential File."""

from __future__ import annotations

from bisect import bisect_left
from collections import Counter
from typing import Any

from index.hash_utils import stable_hash
from query.catalog import (
    INDEX_BPLUS,
    INDEX_CLUSTERED,
    INDEX_HASH,
    INDEX_RTREE,
    STORAGE_SEQUENTIAL,
)


def json_val(value: Any):
    if isinstance(value, (int, float, str, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [json_val(v) for v in value]
    return str(value)


def _sanitize_tree(snapshot: dict | None) -> dict | None:
    if snapshot is None:
        return None
    out = dict(snapshot)
    nodes = []
    for node in snapshot.get("nodes", []):
        item = dict(node)
        item["keys"] = [json_val(k) for k in node.get("keys", [])]
        nodes.append(item)
    out["nodes"] = nodes
    return out


class DidacticBPlus:
    """Réplica de index/bplus_tree.py para la vista "Paso a paso".

    Sigue las mismas reglas que el índice real: bajada con bisect_left, punto
    de split equilibrado (split_index, min_right=2 en internos), underflow por
    debajo de la mitad de la página, préstamo probando primero el hermano
    izquierdo, merge con el hermano derecho salvo en el último hijo, y
    actualización del separador cuando cambia el mínimo de una hoja.
    La única diferencia es la unidad de capacidad: claves en lugar de bytes
    (máximo order - 1 claves por nodo), para que cada split y merge se vea.
    """

    def __init__(self, order: int = 4):
        self.order = order
        self.max_keys = order - 1
        self.nodes: dict[int, dict] = {}
        self.root = 0
        self.next_id = 1
        self.events: list[dict] = []
        self.frames: list[dict] = []
        # la precarga no graba pasos: solo la operación que se anima
        self.recording = False
        self.nodes[0] = {"id": 0, "leaf": True, "keys": [], "children": [], "next": None}

    def reset_frames(self) -> None:
        self.events = []
        self.frames = []
        self.recording = True

    def _node(self, nid: int) -> dict:
        return self.nodes[nid]

    def _alloc(self, leaf: bool) -> int:
        nid = self.next_id
        self.next_id += 1
        self.nodes[nid] = {"id": nid, "leaf": leaf, "keys": [], "children": [], "next": None}
        return nid

    # Equivalentes por número de claves de NodePage (index/node_page.py)
    def _underfull(self, node: dict) -> bool:
        # is_underfull: byte_size - HEADER < HALF
        return len(node["keys"]) * 2 < self.max_keys

    def _can_lend(self, node: dict) -> bool:
        # can_lend: lo que queda tras prestar sigue >= HALF
        return (len(node["keys"]) - 1) * 2 >= self.max_keys

    @staticmethod
    def _split_index(n: int, min_left: int = 1, min_right: int = 1) -> int:
        # split_index con todas las claves del mismo tamaño
        best, best_gap = None, None
        for m in range(1, n):
            if m < min_left or n - m < min_right:
                continue
            gap = abs(m - (n - m))
            if best_gap is None or gap < best_gap:
                best, best_gap = m, gap
        return best if best is not None else n // 2

    def snapshot(self) -> dict:
        nodes = []

        def walk(nid: int, level: int) -> None:
            node = self._node(nid)
            nodes.append({
                "id": nid,
                "level": level,
                "leaf": node["leaf"],
                "keys": [json_val(k) for k in node["keys"]],
                "count": len(node["keys"]),
                "children": list(node["children"]),
                "next": node["next"],
            })
            for child in node["children"]:
                walk(child, level + 1)

        walk(self.root, 0)
        height = (max((n["level"] for n in nodes), default=-1) + 1) if nodes else 0
        return {
            "kind": "bplus",
            "root": self.root,
            "height": height,
            "order": self.order,
            "nodes": nodes,
        }

    def _push_frame(self, event: dict | None) -> None:
        if not self.recording:
            return
        if event is not None:
            self.events.append(event)
        self.frames.append({"event": event, "tree": self.snapshot()})

    def _descend(self, key) -> tuple[list[tuple[int, int]], int, dict]:
        path: list[tuple[int, int]] = []
        nid = self.root
        node = self._node(nid)
        while not node["leaf"]:
            i = bisect_left(node["keys"], key)
            path.append((nid, i))
            nid = node["children"][i]
            node = self._node(nid)
        return path, nid, node

    # inserción (_insert_raw)

    def insert(self, key) -> None:
        path, nid, node = self._descend(key)
        i = bisect_left(node["keys"], key)
        node["keys"].insert(i, key)
        # El motor real reparte antes de escribir; este frame muestra la página
        # "desbordada" solo para explicar por qué hay que dividirla.
        self._push_frame({"type": "insert", "key": json_val(key), "page_id": nid, "kind": "leaf"})

        if len(node["keys"]) <= self.max_keys:
            return

        # El frame de cada split se emite cuando la página nueva ya cuelga de su
        # padre; si no, el recorrido desde la raíz no la encuentra.
        sep, right_id = self._split_leaf(nid)
        pending = {
            "type": "split", "kind": "leaf", "page_id": nid,
            "new_page_id": right_id, "sep": json_val(sep),
        }

        while path:
            parent_id, idx = path.pop()
            parent = self._node(parent_id)
            parent["keys"].insert(idx, sep)
            parent["children"].insert(idx + 1, right_id)
            pending["parent"] = parent_id
            overflow = len(parent["keys"]) > self.max_keys
            if overflow:
                pending["parent_overflow"] = True
            self._push_frame(pending)
            if not overflow:
                return
            sep, right_id = self._split_inner(parent_id)
            pending = {
                "type": "split", "kind": "inner", "page_id": parent_id,
                "new_page_id": right_id, "sep": json_val(sep),
            }

        new_root = self._alloc(False)
        new_root_node = self._node(new_root)
        new_root_node["keys"] = [sep]
        new_root_node["children"] = [self.root, right_id]
        old = self.root
        self.root = new_root
        pending["parent"] = new_root
        self._push_frame(pending)
        self._push_frame({
            "type": "new_root", "page_id": new_root, "old_root": old, "sep": json_val(sep),
        })

    def _split_leaf(self, nid: int) -> tuple:
        node = self._node(nid)
        m = self._split_index(len(node["keys"]))
        right_id = self._alloc(True)
        right = self._node(right_id)
        right["keys"] = node["keys"][m:]
        node["keys"] = node["keys"][:m]
        right["next"] = node["next"]
        node["next"] = right_id
        return right["keys"][0], right_id

    def _split_inner(self, nid: int) -> tuple:
        node = self._node(nid)
        m = self._split_index(len(node["keys"]), min_right=2)
        sep = node["keys"][m]
        right_id = self._alloc(False)
        right = self._node(right_id)
        right["keys"] = node["keys"][m + 1:]
        right["children"] = node["children"][m + 1:]
        node["keys"] = node["keys"][:m]
        node["children"] = node["children"][:m + 1]
        return sep, right_id

    # borrado (_delete_raw, _rebalance, _borrow, _merge)

    def _advance(self, path: list[tuple[int, int]]):
        while path:
            parent_id, idx = path[-1]
            parent = self._node(parent_id)
            if idx < len(parent["keys"]):
                path[-1] = (parent_id, idx + 1)
                nid = parent["children"][idx + 1]
                node = self._node(nid)
                while not node["leaf"]:
                    path.append((nid, 0))
                    nid = node["children"][0]
                    node = self._node(nid)
                return nid, node
            path.pop()
        return None, None

    def delete(self, key) -> bool:
        path, nid, node = self._descend(key)
        i = bisect_left(node["keys"], key)
        if i == len(node["keys"]):
            nid, node = self._advance(path)
            i = 0
            while node is not None and not node["keys"]:
                nid, node = self._advance(path)
            if node is None or node["keys"][0] != key:
                return False
        elif node["keys"][i] != key:
            return False

        old_min = node["keys"][0]
        node["keys"].pop(i)
        self._push_frame({"type": "delete", "key": json_val(key), "page_id": nid, "kind": "leaf"})
        new_min = node["keys"][0] if node["keys"] and node["keys"][0] != old_min else None
        self._rebalance(path, new_min)
        return True

    def _rebalance(self, path: list[tuple[int, int]], new_min) -> None:
        while path:
            parent_id, idx = path.pop()
            parent = self._node(parent_id)

            if new_min is not None and idx > 0:
                old_sep = parent["keys"][idx - 1]
                if old_sep != new_min:
                    parent["keys"][idx - 1] = new_min
                    self._push_frame({
                        "type": "separator", "page_id": parent_id,
                        "old": json_val(old_sep), "sep": json_val(new_min),
                    })
                new_min = None

            child_id = parent["children"][idx]
            child = self._node(child_id)
            if self._underfull(child):
                event = self._borrow(parent, idx, child_id, child)
                if event is not None:
                    self._push_frame(event)
                else:
                    merge_idx = idx - 1 if idx == len(parent["keys"]) else idx
                    kept = parent["children"][merge_idx] if merge_idx >= 0 else None
                    freed = self._merge(parent, idx)
                    if freed is not None:
                        self._push_frame({"type": "merge", "kept": kept, "absorbed": freed, "parent": parent_id})
            if new_min is None and not self._underfull(parent):
                break

        root = self._node(self.root)
        if not root["leaf"] and len(root["keys"]) == 0 and root["children"]:
            old = self.root
            self.root = root["children"][0]
            del self.nodes[old]
            self._push_frame({"type": "shrink_root", "old_root": old, "page_id": self.root})

    def _borrow(self, parent: dict, idx: int, node_id: int, node: dict) -> dict | None:
        for side in (-1, +1):
            sib_idx = idx + side
            if not 0 <= sib_idx <= len(parent["keys"]):
                continue
            sib_id = parent["children"][sib_idx]
            sib = self._node(sib_id)
            if not sib["keys"] or not self._can_lend(sib):
                continue
            take = len(sib["keys"]) - 1 if side < 0 else 0
            sep_idx = idx - 1 if side < 0 else idx
            if len(node["keys"]) >= self.max_keys:
                continue

            if node["leaf"]:
                moving = sib["keys"][take]
                new_sep = moving if side < 0 else sib["keys"][1]
                sib["keys"].pop(take)
                if side < 0:
                    node["keys"].insert(0, moving)
                else:
                    node["keys"].append(moving)
            else:
                lowered = parent["keys"][sep_idx]
                new_sep = sib["keys"][take]
                sib["keys"].pop(take)
                if side < 0:
                    moved_child = sib["children"].pop()
                    node["keys"].insert(0, lowered)
                    node["children"].insert(0, moved_child)
                else:
                    moved_child = sib["children"].pop(0)
                    node["keys"].append(lowered)
                    node["children"].append(moved_child)

            parent["keys"][sep_idx] = new_sep
            return {"type": "borrow", "from_id": sib_id, "to_id": node_id, "side": side,
                    "parent": None, "sep": json_val(new_sep)}
        return None

    def _merge(self, parent: dict, idx: int) -> int | None:
        if idx == len(parent["keys"]):
            idx -= 1
        if idx < 0:
            return None
        left_id, right_id = parent["children"][idx], parent["children"][idx + 1]
        left, right = self._node(left_id), self._node(right_id)
        extra = 0 if left["leaf"] else 1
        if len(left["keys"]) + len(right["keys"]) + extra > self.max_keys:
            return None
        if left["leaf"]:
            left["keys"].extend(right["keys"])
            left["next"] = right["next"]
        else:
            left["keys"].append(parent["keys"][idx])
            left["keys"].extend(right["keys"])
            left["children"].extend(right["children"])
        del parent["keys"][idx]
        del parent["children"][idx + 1]
        del self.nodes[right_id]
        return right_id


class DidacticHash:
    """Réplica de index/extendible_hash.py para la vista "División animada".

    Usa la misma stable_hash y los bits menos significativos, y las mismas
    reglas: insertar si la página primaria tiene sitio, overflow encadenado si
    la cubeta está "atascada" (_is_stuck), duplicar el directorio cuando
    profundidad local == global, split por el bit discriminante redistribuyendo
    toda la cadena (_write_chain) y, al borrar, compactar la página de overflow
    siguiente si cabe (_consolidate). Nunca fusiona cubetas ni encoge el
    directorio, igual que el motor. Solo cambia la capacidad (2 claves).
    """

    HASH_BITS = 64

    def __init__(self, capacity: int = 2):
        self.capacity = capacity
        self.global_depth = 0
        self.dir = [0]
        self.pages: dict[int, dict] = {0: self._page(0, 0, "primary")}
        self.next_id = 1
        self.events: list[dict] = []
        self.frames: list[dict] = []
        # la precarga no graba pasos: solo la operación que se anima
        self.recording = False

    @staticmethod
    def _page(pid: int, local_depth: int, kind: str, keys=None, overflow=None) -> dict:
        return {"id": pid, "local_depth": local_depth, "kind": kind,
                "keys": list(keys or []), "overflow": overflow}

    def _alloc(self) -> int:
        pid = self.next_id
        self.next_id += 1
        return pid

    def reset_frames(self) -> None:
        self.events = []
        self.frames = []
        self.recording = True

    def _chain(self, pid: int) -> list[dict]:
        chain = []
        current = pid
        while current is not None:
            page = self.pages[current]
            chain.append(page)
            current = page["overflow"]
        return chain

    def snapshot(self) -> dict:
        seen = []
        buckets = []
        for page_id in self.dir:
            if page_id in seen:
                continue
            seen.append(page_id)
            chain = self._chain(page_id)
            primary = chain[0]
            buckets.append({
                "id": page_id,
                "local_depth": primary["local_depth"],
                "count": sum(len(p["keys"]) for p in chain),
                "capacity": self.capacity,
                "keys": [json_val(k) for k in primary["keys"]],
                "dir_slots": [i for i, pid in enumerate(self.dir) if pid == page_id],
                "chain": [{
                    "id": page["id"],
                    "kind": page["kind"],
                    "local_depth": page["local_depth"],
                    "count": len(page["keys"]),
                    "keys": [json_val(k) for k in page["keys"]],
                    "hashes": [f"{stable_hash(k) & 0xFFFF:04x}" for k in page["keys"]],
                    "overflow": page["overflow"],
                } for page in chain],
            })
        return {
            "kind": "hash",
            "global_depth": self.global_depth,
            "capacity": self.capacity,
            "directory": list(self.dir),
            "directory_size": len(self.dir),
            "buckets": buckets,
        }

    def _push_frame(self, event: dict | None) -> None:
        if not self.recording:
            return
        if event is not None:
            self.events.append(event)
        self.frames.append({"event": event, "hash": self.snapshot()})

    def _mask(self) -> int:
        return (1 << self.global_depth) - 1

    def _bits(self, idx: int) -> str:
        return f"{idx:0{max(self.global_depth, 1)}b}"

    # inserción (_insert_hash)

    def insert(self, key) -> None:
        key_hash = stable_hash(key)
        while True:
            idx = key_hash & self._mask()
            page_id = self.dir[idx]
            bucket = self.pages[page_id]
            if len(bucket["keys"]) < self.capacity:
                bucket["keys"].append(key)
                self._push_frame({
                    "type": "insert", "key": json_val(key), "bucket": page_id,
                    "index": idx, "bits": self._bits(idx),
                })
                return
            if self._stuck(bucket, key_hash):
                target = self._add_to_overflow(page_id, bucket, key)
                self._push_frame({
                    "type": "overflow", "key": json_val(key), "bucket": page_id,
                    "page": target, "index": idx, "bits": self._bits(idx),
                    "local_depth": bucket["local_depth"],
                })
                return
            # Paso explícito "cubeta llena": decide si basta con dividir la
            # cubeta o si además hay que duplicar el directorio.
            self._push_frame({
                "type": "full", "key": json_val(key), "bucket": page_id,
                "index": idx, "bits": self._bits(idx),
                "local_depth": bucket["local_depth"], "global_depth": self.global_depth,
            })
            if bucket["local_depth"] == self.global_depth:
                old_size = len(self.dir)
                self.dir = self.dir + self.dir
                self.global_depth += 1
                self._push_frame({
                    "type": "double", "key": json_val(key),
                    "global_depth": self.global_depth,
                    "directory_size": len(self.dir), "old_size": old_size,
                })
            self._split(idx, page_id, bucket, key)

    def _stuck(self, bucket: dict, key_hash: int) -> bool:
        if bucket["local_depth"] >= self.HASH_BITS:
            return True
        bit = 1 << bucket["local_depth"]
        side = key_hash & bit
        same = sum(1 for k in bucket["keys"] if (stable_hash(k) & bit) == side)
        return same >= self.capacity

    def _add_to_overflow(self, primary_id: int, primary: dict, key) -> int:
        first_id = primary["overflow"]
        if first_id is not None:
            first = self.pages[first_id]
            if len(first["keys"]) < self.capacity:
                first["keys"].append(key)
                return first_id
        new_id = self._alloc()
        self.pages[new_id] = self._page(new_id, 0, "overflow", [key], first_id)
        primary["overflow"] = new_id
        return new_id

    def _split(self, idx: int, page_id: int, bucket: dict, incoming=None) -> None:
        old_depth = bucket["local_depth"]
        bit = 1 << old_depth
        entries: list = []
        spare: list[int] = []
        page = bucket
        while True:
            entries.extend(page["keys"])
            next_id = page["overflow"]
            if next_id is None:
                break
            spare.append(next_id)
            page = self.pages[next_id]

        keep, move = [], []
        for key in entries:
            (move if stable_hash(key) & bit else keep).append(key)

        image_id = spare.pop() if spare else self._alloc()
        self._write_chain(page_id, keep, old_depth + 1, spare)
        self._write_chain(image_id, move, old_depth + 1, spare)
        for leftover in spare:
            self.pages.pop(leftover, None)

        low = idx & (bit - 1)
        for i in range(low, len(self.dir), bit):
            if i & bit:
                self.dir[i] = image_id
        self._push_frame({
            "type": "split",
            "key": json_val(incoming),
            "bucket": page_id,
            "new_bucket": image_id,
            "local_depth": old_depth + 1,
            "bit": old_depth,
            "keep": [json_val(k) for k in keep],
            "move": [json_val(k) for k in move],
        })

    def _write_chain(self, head_id: int, keys: list, local_depth: int, spare: list[int]) -> None:
        cap = self.capacity
        chunks = [keys[i:i + cap] for i in range(0, len(keys), cap)] or [[]]
        page_ids = [head_id]
        while len(page_ids) < len(chunks):
            page_ids.append(spare.pop() if spare else self._alloc())
        for n, (pid, chunk) in enumerate(zip(page_ids, chunks)):
            self.pages[pid] = self._page(
                pid,
                local_depth if n == 0 else 0,
                "primary" if n == 0 else "overflow",
                chunk,
                page_ids[n + 1] if n + 1 < len(page_ids) else None,
            )

    # borrado (delete + _consolidate)

    def delete(self, key) -> bool:
        idx = stable_hash(key) & self._mask()
        bucket_id = self.dir[idx]
        current = bucket_id
        while current is not None:
            page = self.pages[current]
            if key in page["keys"]:
                page["keys"].remove(key)
                self._push_frame({
                    "type": "delete", "key": json_val(key), "bucket": bucket_id,
                    "page": current, "index": idx, "bits": self._bits(idx),
                })
                absorbed = self._consolidate(current, page)
                if absorbed is not None:
                    self._push_frame({
                        "type": "consolidate", "bucket": bucket_id,
                        "page": current, "absorbed": absorbed,
                    })
                return True
            current = page["overflow"]
        return False

    def _consolidate(self, page_id: int, page: dict) -> int | None:
        next_id = page["overflow"]
        if next_id is None:
            return None
        next_page = self.pages[next_id]
        if len(page["keys"]) + len(next_page["keys"]) > self.capacity:
            return None
        page["keys"].extend(next_page["keys"])
        page["overflow"] = next_page["overflow"]
        del self.pages[next_id]
        return next_id


def _column_values(info, column: str) -> list:
    idx = info.schema.column_index(column)
    storage = info.storage
    if hasattr(storage, "scan_con_rid"):
        return [record.values[idx] for _rid, record in storage.scan_con_rid(info.schema)]
    return [record.values[idx] for record in storage.scan()]


def _bplus_keys(tree) -> list:
    return [key for key, _payload in tree.scan()]


# La réplica didáctica (orden 4) se arma con una ventana de claves alrededor de
# la que cambia: con la tabla entera saldrían miles de nodos imposibles de leer.
DIDACTIC_BPLUS_KEYS = 40
DIDACTIC_HASH_KEYS = 24


def _sort_key(value):
    return (0, value) if isinstance(value, (int, float)) else (1, str(value))


def _bplus_window(keys: list, changed: list, limit: int = DIDACTIC_BPLUS_KEYS) -> list:
    if len(keys) <= limit:
        return list(keys)
    ordered = sorted(keys, key=_sort_key)
    if not changed:
        return ordered[:limit]
    ranks = [_sort_key(k) for k in ordered]
    half = max(1, limit // (2 * len(changed)))
    picked: set[int] = set()
    for key in changed:
        pos = bisect_left(ranks, _sort_key(key))
        picked.update(range(max(0, pos - half), min(len(ordered), pos + half)))
    return [ordered[i] for i in sorted(picked)]


def _hash_window(values: list, changed: list, limit: int = DIDACTIC_HASH_KEYS) -> list:
    if len(values) <= limit:
        return list(values)
    window = list(values[:limit])
    window.extend(changed)   # en un INSERT la clave nueva está al final de values
    return window


def replay_bplus(keys: list, changed=None, operation: str = "insert") -> dict:
    tree = DidacticBPlus(order=4)
    changed_list = [] if changed is None else list(changed)
    keys = _bplus_window(keys, changed_list)
    if operation == "insert" and changed_list:
        keep = list(keys)
        for key in changed_list:
            if key in keep:
                keep.remove(key)
        for key in keep:
            tree.insert(key)
        tree.reset_frames()
        before = tree.snapshot()
        for key in changed_list:
            tree.insert(key)
        return {
            "order": 4,
            "before": before,
            "after": tree.snapshot(),
            "frames": tree.frames,
            "events": tree.events,
        }
    if operation == "delete" and changed_list:
        for key in keys:
            tree.insert(key)
        for key in changed_list:
            tree.insert(key)
        tree.reset_frames()
        before = tree.snapshot()
        for key in changed_list:
            tree.delete(key)
        return {
            "order": 4,
            "before": before,
            "after": tree.snapshot(),
            "frames": tree.frames,
            "events": tree.events,
        }
    for key in keys:
        tree.insert(key)
    return {
        "order": 4,
        "before": None,
        "after": tree.snapshot(),
        "frames": [],
        "events": [],
    }


def replay_hash(values: list, changed=None, operation: str = "insert") -> dict:
    table = DidacticHash(capacity=2)
    changed_list = [] if changed is None else list(changed)
    values = _hash_window(values, changed_list)
    if operation == "insert" and changed_list:
        keep = list(values)
        for key in changed_list:
            if key in keep:
                keep.remove(key)
        for key in keep:
            table.insert(key)
        table.reset_frames()
        before = table.snapshot()
        for key in changed_list:
            table.insert(key)
        return {
            "capacity": 2,
            "before": before,
            "after": table.snapshot(),
            "frames": table.frames,
            "events": table.events,
        }
    if operation == "delete" and changed_list:
        for key in values:
            table.insert(key)
        for key in changed_list:
            table.insert(key)
        table.reset_frames()
        before = table.snapshot()
        # Se borra sobre la misma tabla para que las cubetas conserven su id
        # y la animación muestre solo la clave que se va.
        for key in changed_list:
            table.delete(key)
        return {
            "capacity": 2,
            "before": before,
            "after": table.snapshot(),
            "frames": table.frames,
            "events": table.events,
        }
    for key in values:
        table.insert(key)
    return {
        "capacity": 2,
        "before": None,
        "after": table.snapshot(),
        "frames": [],
        "events": [],
    }


def snapshot_table(catalog, table_name: str) -> dict:
    if not catalog.existe_tabla(table_name):
        raise ValueError(f"Tabla '{table_name}' no encontrada")
    info = catalog.get_table(table_name)
    indexes = []
    for column, (obj, tipo) in info.indices.items():
        entry = {"column": column, "type": tipo}
        if tipo in (INDEX_BPLUS, INDEX_CLUSTERED) and hasattr(obj, "snapshot"):
            entry["disk"] = _sanitize_tree(obj.snapshot())
            try:
                entry["keys"] = [json_val(k) for k in _bplus_keys(obj)]
            except Exception:
                entry["keys"] = [json_val(v) for v in _column_values(info, column)]
        elif tipo == INDEX_HASH and hasattr(obj, "snapshot"):
            entry["disk"] = obj.snapshot()
            entry["keys"] = [json_val(v) for v in _column_values(info, column)]
        elif tipo == INDEX_RTREE and hasattr(obj, "snapshot"):
            entry["disk"] = obj.snapshot()
        indexes.append(entry)

    sequential = None
    if info.tipo_storage == STORAGE_SEQUENTIAL and hasattr(info.storage, "snapshot"):
        sequential = info.storage.snapshot()

    return {
        "table": table_name,
        "storage": info.tipo_storage,
        "key_column": info.key_column,
        "indexes": indexes,
        "sequential": sequential,
    }


def begin_traces(catalog, table_name: str) -> None:
    info = catalog.get_table(table_name)
    for _column, (obj, _tipo) in info.indices.items():
        if hasattr(obj, "begin_trace"):
            obj.begin_trace()


def take_traces(catalog, table_name: str) -> dict:
    info = catalog.get_table(table_name)
    traces = {}
    for column, (obj, tipo) in info.indices.items():
        if hasattr(obj, "take_trace"):
            traces[f"{tipo}:{column}"] = obj.take_trace()
    return traces


def _diff_values(before: list, after: list) -> tuple[list, list]:
    left = Counter(before)
    right = Counter(after)
    inserted = []
    deleted = []
    for key in set(left) | set(right):
        delta = right[key] - left[key]
        if delta > 0:
            inserted.extend([key] * delta)
        elif delta < 0:
            deleted.extend([key] * (-delta))
    return inserted, deleted


def animate_mutation(catalog, table_name: str, before: dict, after: dict,
                     operation: str, traces: dict) -> dict:
    animations = []
    before_idx = {f"{i['type']}:{i['column']}": i for i in before.get("indexes", [])}
    after_idx = {f"{i['type']}:{i['column']}": i for i in after.get("indexes", [])}
    for key, current in after_idx.items():
        tipo, column = key.split(":", 1)
        prev = before_idx.get(key, {})
        disk_events = traces.get(key, [])
        if tipo in (INDEX_BPLUS, INDEX_CLUSTERED):
            inserted, deleted = _diff_values(prev.get("keys", []), current.get("keys", []))
            changed = inserted if operation == "INSERT" else deleted
            op = "insert" if inserted and not deleted else "delete" if deleted else "insert"
            didactic = replay_bplus(current.get("keys", []), changed, op)
            animations.append({
                "kind": "bplus",
                "column": column,
                "disk": current.get("disk"),
                "disk_before": prev.get("disk"),
                "disk_events": disk_events,
                "didactic": didactic,
                "changed": [json_val(v) for v in changed],
            })
        elif tipo == INDEX_HASH:
            inserted, deleted = _diff_values(prev.get("keys", []), current.get("keys", []))
            changed = inserted if operation == "INSERT" else deleted
            op = "insert" if inserted and not deleted else "delete" if deleted else "insert"
            raw_after = _column_values(catalog.get_table(table_name), column)
            didactic = replay_hash(raw_after, changed, op)
            animations.append({
                "kind": "hash",
                "column": column,
                "disk": current.get("disk"),
                "disk_before": prev.get("disk"),
                "disk_events": disk_events,
                "didactic": didactic,
                "changed": [json_val(v) for v in changed],
            })
        elif tipo == INDEX_RTREE:
            animations.append({
                "kind": "rtree",
                "column": column,
                "disk": current.get("disk"),
                "disk_before": prev.get("disk"),
                "disk_events": disk_events,
            })

    seq_anim = None
    if after.get("sequential") is not None:
        seq_anim = {
            "kind": "sequential",
            "before": before.get("sequential"),
            "after": after.get("sequential"),
        }

    return {
        "table": table_name,
        "operation": operation,
        "before": before,
        "after": after,
        "animations": animations,
        "sequential": seq_anim,
    }


def sequential_reorganize(before: dict | None, after: dict | None, table_name: str) -> dict:
    return {
        "table": table_name,
        "operation": "REORGANIZE",
        "animations": [],
        "sequential": {
            "kind": "sequential",
            "before": before,
            "after": after,
        },
        "after": {"table": table_name, "sequential": after, "indexes": []},
    }

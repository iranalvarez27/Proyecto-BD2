import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.types import RID

PAGE_SIZE = 4096

# is_leaf (u8) | reserved (u8) | count (u16) | last_child (i32) | next_page (i32) | prev_page (i32)
HEADER_FORMAT = "<BBHiii"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)  # 16

# entry: key_len (u16) | payload | key_bytes
KEY_LEN_FORMAT = "<H"
KEY_LEN_SIZE = struct.calcsize(KEY_LEN_FORMAT)  # 2

USABLE = PAGE_SIZE - HEADER_SIZE  # 4080
HALF = USABLE // 2  # merge threshold
QUARTER = USABLE // 4  # verifiable occupancy floor

NIL = -1


class ChildCodec:
    """Inner slot payload: the page id of its left child."""

    size = 4

    def pack(self, page_id: int) -> bytes:
        return struct.pack("<i", page_id)

    def unpack(self, raw: bytes) -> int:
        return struct.unpack("<i", raw)[0]


class RIDCodec:
    """Unclustered leaf payload: where the row lives."""

    size = 8

    def pack(self, rid: RID) -> bytes:
        return struct.pack("<ii", rid.page_id, rid.slot_id)

    def unpack(self, raw: bytes) -> RID:
        page_id, slot_id = struct.unpack("<ii", raw)
        return RID(page_id=page_id, slot_id=slot_id)


class PageIdCodec:
    """Clustered leaf payload: a MAIN page, one entry per page not per row."""

    size = 4

    def pack(self, page_id: int) -> bytes:
        return struct.pack("<i", page_id)

    def unpack(self, raw: bytes) -> int:
        return struct.unpack("<i", raw)[0]


CHILD_CODEC = ChildCodec()
RID_CODEC = RIDCodec()
PAGE_ID_CODEC = PageIdCodec()


class NodePage:
    """A B+ tree node: (key, payload) entries in key order, keys as opaque bytes."""

    def __init__(self, is_leaf: bool, leaf_codec=RID_CODEC):
        self.is_leaf = is_leaf
        self.leaf_codec = leaf_codec
        self.last_child = NIL
        self.next_page = NIL
        self.prev_page = NIL
        self.keys: list[bytes] = []
        self.payloads: list = []

    @property
    def codec(self):
        return self.leaf_codec if self.is_leaf else CHILD_CODEC

    @property
    def count(self) -> int:
        return len(self.keys)

    # -------------------------------------------------------------- occupancy

    def entry_size(self, key: bytes) -> int:
        return KEY_LEN_SIZE + self.codec.size + len(key)

    def byte_size(self) -> int:
        return HEADER_SIZE + sum(self.entry_size(k) for k in self.keys)

    def will_fit(self, key: bytes) -> bool:
        return self.byte_size() + self.entry_size(key) <= PAGE_SIZE

    def is_underfull(self) -> bool:
        """Below half the usable space: triggers borrow/merge."""
        return self.byte_size() - HEADER_SIZE < HALF

    def min_fill_ok(self) -> bool:
        """QUARTER, not HALF: a variable-width split cannot always cut near the middle."""
        return self.byte_size() - HEADER_SIZE >= QUARTER

    def can_lend(self, i: int) -> bool:
        """Whether giving entry `i` away leaves this node still half full."""
        if self.count == 0:
            return False
        return self.byte_size() - HEADER_SIZE - self.entry_size(self.keys[i]) >= HALF

    def can_replace(self, i: int, key: bytes) -> bool:
        """Whether swapping entry `i`'s key for `key` still fits."""
        return (self.byte_size() - self.entry_size(self.keys[i])
                + self.entry_size(key)) <= PAGE_SIZE

    # ---------------------------------------------------------------- entries

    def insert(self, i: int, key: bytes, payload) -> None:
        self.keys.insert(i, key)
        self.payloads.insert(i, payload)

    def append(self, key: bytes, payload) -> None:
        self.keys.append(key)
        self.payloads.append(payload)

    def remove(self, i: int):
        return self.keys.pop(i), self.payloads.pop(i)

    # --------------------------------------------------------------- children

    def child(self, i: int) -> int:
        """Child i of an inner node, where child(count) is the last child."""
        if self.is_leaf:
            raise ValueError("a leaf has no children")
        return self.last_child if i == self.count else self.payloads[i]

    def set_child(self, i: int, page_id: int) -> None:
        if self.is_leaf:
            raise ValueError("a leaf has no children")
        if i == self.count:
            self.last_child = page_id
        else:
            self.payloads[i] = page_id

    # -------------------------------------------------------------- split

    def split_index(self, keys: list[bytes], min_left: int = 1, min_right: int = 1) -> int:
        """Where to cut `keys` (already overflowing) so both halves fit."""
        sizes = [self.entry_size(k) for k in keys]
        total = sum(sizes)

        best = None
        best_gap = None
        prefix = 0
        for m in range(1, len(keys)):
            prefix += sizes[m - 1]
            if m < min_left or len(keys) - m < min_right:
                continue
            if prefix > USABLE or total - prefix > USABLE:
                continue
            gap = abs(prefix - (total - prefix))
            if best_gap is None or gap < best_gap:
                best, best_gap = m, gap

        if best is None:
            raise ValueError("no feasible split point: a key exceeds MAX_KEY_SIZE")
        return best

    # ----------------------------------------------------------- serialization

    def to_bytes(self) -> bytes:
        size = self.byte_size()
        if size > PAGE_SIZE:
            raise ValueError(f"node holds {size} > {PAGE_SIZE} bytes")

        buf = bytearray(PAGE_SIZE)
        struct.pack_into(
            HEADER_FORMAT, buf, 0,
            1 if self.is_leaf else 0,
            0,  # reserved
            self.count,
            self.last_child,
            self.next_page,
            self.prev_page,
        )
        offset = HEADER_SIZE
        for key, payload in zip(self.keys, self.payloads):
            struct.pack_into(KEY_LEN_FORMAT, buf, offset, len(key))
            offset += KEY_LEN_SIZE
            buf[offset:offset + self.codec.size] = self.codec.pack(payload)
            offset += self.codec.size
            buf[offset:offset + len(key)] = key
            offset += len(key)
        return bytes(buf)

    @classmethod
    def from_bytes(cls, data: bytes, leaf_codec=RID_CODEC) -> "NodePage":
        if len(data) != PAGE_SIZE:
            raise ValueError(f"page must have exactly {PAGE_SIZE} bytes")
        is_leaf, _reserved, count, last_child, next_page, prev_page = struct.unpack_from(
            HEADER_FORMAT, data, 0
        )
        page = cls(is_leaf=bool(is_leaf), leaf_codec=leaf_codec)
        page.last_child = last_child
        page.next_page = next_page
        page.prev_page = prev_page

        codec = page.codec
        offset = HEADER_SIZE
        for _ in range(count):
            key_len = struct.unpack_from(KEY_LEN_FORMAT, data, offset)[0]
            offset += KEY_LEN_SIZE
            payload = codec.unpack(data[offset:offset + codec.size])
            offset += codec.size
            page.keys.append(bytes(data[offset:offset + key_len]))
            page.payloads.append(payload)
            offset += key_len
        return page

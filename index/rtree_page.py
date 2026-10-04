import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.geo import MBR
from common.page import PAGE_SIZE

HEADER = struct.Struct("<BxH")    # es_hoja | cantidad
LEAF = struct.Struct("<ddii")     # x (lon) | y (lat) | rid.page_id | rid.slot_id
INNER = struct.Struct("<ddddi")   # x_min | y_min | x_max | y_max | hijo

MAX_LEAF = (PAGE_SIZE - HEADER.size) // LEAF.size     # 170
MAX_INNER = (PAGE_SIZE - HEADER.size) // INNER.size   # 113


class RTreePage:
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

    def to_bytes(self) -> bytes:
        codec = LEAF if self.is_leaf else INNER
        cuerpo = b"".join(codec.pack(*e) for e in self.entries)
        buf = HEADER.pack(1 if self.is_leaf else 0, len(self.entries)) + cuerpo
        return buf + bytes(PAGE_SIZE - len(buf))

    @classmethod
    def from_bytes(cls, buf: bytes) -> "RTreePage":
        is_leaf, count = HEADER.unpack_from(buf, 0)
        codec = LEAF if is_leaf else INNER
        fin = HEADER.size + count * codec.size
        return cls(bool(is_leaf), list(codec.iter_unpack(buf[HEADER.size:fin])))

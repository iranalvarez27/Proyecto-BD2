import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.types import RID

PAGE_SIZE = 4096

PAGE_KIND_PRIMARY = 0
PAGE_KIND_OVERFLOW = 1

# local_depth (u8) | page_kind (u8) | count (u16) | overflow_page_id (i32) | 8B reserved
HEADER_FORMAT = "<BBHi8x"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)  # 16

# hash (u64) | rid.page_id (i32) | rid.slot_id (i32)
ENTRY_FORMAT = "<Qii"
ENTRY_SIZE = struct.calcsize(ENTRY_FORMAT)  # 16

MAX_ENTRIES = (PAGE_SIZE - HEADER_SIZE) // ENTRY_SIZE  # 255


class BucketPage:
    """Fixed-size hash bucket: a dense array of (hash, RID) entries."""

    def __init__(self, local_depth: int = 0, page_kind: int = PAGE_KIND_PRIMARY):
        self.local_depth = local_depth
        self.page_kind = page_kind
        self.overflow_page_id = -1
        self.entries: list[tuple[int, RID]] = []

    @property
    def is_overflow(self) -> bool:
        return self.page_kind == PAGE_KIND_OVERFLOW

    def add(self, key_hash: int, rid: RID) -> None:
        self.entries.append((key_hash, rid))

    def remove(self, key_hash: int, rid: RID) -> bool:
        """Removes one occurrence, not all matches."""
        for i, (h, r) in enumerate(self.entries):
            if h == key_hash and r == rid:
                self.entries.pop(i)
                return True
        return False

    def to_bytes(self) -> bytes:
        if len(self.entries) > MAX_ENTRIES:
            raise ValueError(f"bucket holds {len(self.entries)} > {MAX_ENTRIES} entries")
        buf = bytearray(PAGE_SIZE)
        struct.pack_into(
            HEADER_FORMAT, buf, 0,
            self.local_depth,
            self.page_kind,
            len(self.entries),
            self.overflow_page_id,
        )
        offset = HEADER_SIZE
        for key_hash, rid in self.entries:
            struct.pack_into(ENTRY_FORMAT, buf, offset, key_hash, rid.page_id, rid.slot_id)
            offset += ENTRY_SIZE
        return bytes(buf)

    @classmethod
    def from_bytes(cls, data: bytes) -> "BucketPage":
        if len(data) != PAGE_SIZE:
            raise ValueError(f"page must have exactly {PAGE_SIZE} bytes")
        local_depth, page_kind, count, overflow_page_id = struct.unpack_from(HEADER_FORMAT, data, 0)
        page = cls(local_depth=local_depth, page_kind=page_kind)
        page.overflow_page_id = overflow_page_id
        offset = HEADER_SIZE
        for _ in range(count):
            key_hash, page_id, slot_id = struct.unpack_from(ENTRY_FORMAT, data, offset)
            page.entries.append((key_hash, RID(page_id=page_id, slot_id=slot_id)))
            offset += ENTRY_SIZE
        return page

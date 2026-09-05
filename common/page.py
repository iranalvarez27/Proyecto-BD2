import struct

PAGE_SIZE = 4096
HEADER_FORMAT = "<HH"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)

SLOT_FORMAT = "<HH"
SLOT_SIZE = struct.calcsize(SLOT_FORMAT)

class SlottedPage:
    def __init__(self): 
        self._buf = bytearray(PAGE_SIZE)
        self._nslots = 0
        self._free_end = PAGE_SIZE
        self._write_header()
    def _write_header(self):
        struct.pack_into(HEADER_FORMAT, self._buf, 0, self._nslots, self._free_end)
    def _slot_offset(self, slot_id: int) -> int:
        return HEADER_SIZE + slot_id * SLOT_SIZE
    def free_space(self) -> int:
        slot_directory_end = HEADER_SIZE + self._nslots * SLOT_SIZE
        return self._free_end - slot_directory_end
    def insert(self, data: bytes) -> int:
        record_size = len(data)
        if record_size == 0: 
            raise ValueError("Cannot insert empty record")
        reusable_slot = None
        for slot_id in range(self._nslots):
            slot_offset = self._slot_offset(slot_id)
            record_offset, record_length = struct.unpack_from(SLOT_FORMAT, self._buf, slot_offset)
            if record_length == 0:
                reusable_slot = slot_id
                break
        if reusable_slot is not None:
            required_space = record_size
        else: 
            required_space = record_size + SLOT_SIZE
        if self.free_space() < required_space:
            self.compact()
        if self.free_space() < required_space:
            raise ValueError("Not enough space in page")
        self._free_end -= record_size
        self._buf[self._free_end:self._free_end + record_size] = data
        if reusable_slot is not None:
            slot_id = reusable_slot
        else:
            slot_id = self._nslots
            self._nslots += 1
        struct.pack_into(SLOT_FORMAT, self._buf, self._slot_offset(slot_id), self._free_end, record_size)
        self._write_header()
        return slot_id
    def read(self, slot_id: int) -> bytes:
        if slot_id < 0 or slot_id >= self._nslots:
            raise ValueError(f"Invalid slot ID: {slot_id}")
        slot_offset = self._slot_offset(slot_id)
        record_offset, record_length = struct.unpack_from(SLOT_FORMAT, self._buf, slot_offset)
        if record_length == 0:
            return b""
        return bytes(self._buf[record_offset:record_offset + record_length])
    def delete(self, slot_id: int) -> None:
        if slot_id < 0 or slot_id >= self._nslots:
            raise ValueError(f"Invalid slot ID: {slot_id}")
        slot_offset = self._slot_offset(slot_id)
        record_offset, record_length = struct.unpack_from(SLOT_FORMAT, self._buf, slot_offset)
        if record_length == 0:
            return 
        struct.pack_into(SLOT_FORMAT, self._buf, slot_offset, 0, 0)
    def update(self, slot_id: int, data: bytes) -> None:
        if slot_id < 0 or slot_id >= self._nslots:
            raise ValueError(f"Invalid slot ID: {slot_id}")
        slot_offset = self._slot_offset(slot_id)
        record_offset, record_length = struct.unpack_from(SLOT_FORMAT, self._buf, slot_offset)
        if record_length == 0:
            raise ValueError(f"Slot {slot_id} is empty")
        if len(data) != record_length:
            raise ValueError(f"Updated record must have the same size")
        self._buf[record_offset:record_offset + record_length] = data
    def compact(self) -> None:
        live_records = []
        for slot_id in range(self._nslots):
            slot_offset = self._slot_offset(slot_id)
            record_offset, record_length = struct.unpack_from(SLOT_FORMAT, self._buf, slot_offset)
            if record_length > 0:
                data = bytes(self._buf[record_offset:record_offset + record_length])
                live_records.append((slot_id, data))
        new_buf = bytearray(PAGE_SIZE)
        new_free_end = PAGE_SIZE
        for slot_id, data in live_records:
            record_length = len(data)
            new_free_end -= record_length
            new_buf[new_free_end:new_free_end + record_length] = data
            struct.pack_into(SLOT_FORMAT, new_buf, self._slot_offset(slot_id), new_free_end, record_length)
        self._buf = new_buf
        self._free_end = new_free_end
        self._write_header()
    @property
    def slot_count(self) -> int:
        return self._nslots
    def to_bytes(self) -> bytes:
        return bytes(self._buf)
    @classmethod
    def from_bytes(cls, data: bytes) -> "SlottedPage":
        if len(data) != PAGE_SIZE:
            raise ValueError(f"Page must have exactly {PAGE_SIZE} bytes")
        page = cls()
        page._buf = bytearray(data)
        page._nslots, page._free_end = struct.unpack_from(HEADER_FORMAT, page._buf, 0)
        return page

import struct
from common.page import PAGE_SIZE
from engine.buffer_pool import BufferPool

NIL = -1

class Segment:
    def __init__(self, pool: BufferPool, path: str):
        self.pool = pool
        self.path = path
        self.free_head = NIL

    def page_count(self) -> int:
        return self.pool.page_count(self.path)

    def read(self, page_id: int) -> bytes:
        return self.pool.read_page(self.path, page_id)

    def write(self, page_id: int, data: bytes) -> None:
        self.pool.write_page(self.path, page_id, data)

    def append(self, data: bytes) -> int:
        return self.pool.append_page(self.path, data)

    def truncate(self, n_pages: int) -> None:
        self.pool.truncate(self.path, n_pages)
        self.free_head = NIL

    def alloc(self) -> int:
        if self.free_head == NIL:
            return self.append(bytes(PAGE_SIZE))
        page_id = self.free_head
        self.free_head = struct.unpack_from("<i", self.read(page_id), 0)[0]
        return page_id

    def free(self, page_id: int) -> None:
        buf = bytearray(PAGE_SIZE)
        struct.pack_into("<i", buf, 0, self.free_head)
        self.write(page_id, bytes(buf))
        self.free_head = page_id

    def close(self) -> None:
        self.pool.close(self.path)

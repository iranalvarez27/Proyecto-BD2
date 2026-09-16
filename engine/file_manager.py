import os

from common.page import PAGE_SIZE


class FileManager:
    """Page-sized reads and writes on OS files, with open handles and I/O counters."""

    def __init__(self):
        self._files = {}
        # the handles are buffered, so os.path.getsize can lag behind appends
        self._pages = {}
        self.reads = 0
        self.writes = 0

    def page_count(self, path: str) -> int:
        if path in self._pages:
            return self._pages[path]
        if not os.path.exists(path):
            return 0
        return os.path.getsize(path) // PAGE_SIZE

    def read_page(self, path: str, page_id: int) -> bytes:
        self._check_id(path, page_id)
        fp = self._handle(path)
        fp.seek(page_id * PAGE_SIZE)
        self.reads += 1
        return fp.read(PAGE_SIZE)

    def write_page(self, path: str, page_id: int, data: bytes) -> None:
        self._check_id(path, page_id)
        self._check_size(data)
        fp = self._handle(path)
        fp.seek(page_id * PAGE_SIZE)
        fp.write(data)
        self.writes += 1

    def append_page(self, path: str, data: bytes) -> int:
        self._check_size(data)
        fp = self._handle(path)
        page_id = self._pages[path]
        fp.seek(page_id * PAGE_SIZE)
        fp.write(data)
        self._pages[path] = page_id + 1
        self.writes += 1
        return page_id

    def truncate(self, path: str, n_pages: int) -> None:
        fp = self._handle(path)
        fp.flush()
        fp.truncate(n_pages * PAGE_SIZE)
        self._pages[path] = n_pages

    def replace(self, src: str, dst: str) -> None:
        self.close(src)
        self.close(dst)
        os.replace(src, dst)

    def close(self, path: str) -> None:
        fp = self._files.pop(path, None)
        self._pages.pop(path, None)
        if fp is not None:
            fp.close()

    def close_all(self) -> None:
        for path in list(self._files):
            self.close(path)

    def reset_counters(self) -> None:
        self.reads = 0
        self.writes = 0

    def _handle(self, path: str):
        fp = self._files.get(path)
        if fp is None:
            if not os.path.exists(path):
                open(path, "wb").close()
            fp = open(path, "r+b")
            self._files[path] = fp
            self._pages[path] = os.path.getsize(path) // PAGE_SIZE
        return fp

    def _check_id(self, path: str, page_id: int) -> None:
        if not 0 <= page_id < self.page_count(path):
            raise IndexError(f"{path}: page {page_id} out of range ({self.page_count(path)} pages)")

    @staticmethod
    def _check_size(data: bytes) -> None:
        if len(data) != PAGE_SIZE:
            raise ValueError(f"a page is {PAGE_SIZE} bytes, got {len(data)}")

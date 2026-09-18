import os

from common.page import PAGE_SIZE
from transaction import manager as tx_manager


class FileManager:
    def __init__(self):
        self._files = {}
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
        if tx_manager.TX_ACTIVE():
            # before-image for ROLLBACK
            fp.seek(page_id * PAGE_SIZE)
            tx_manager.TX_HOOK("WRITE", path, page_id, fp.read(PAGE_SIZE))
        fp.seek(page_id * PAGE_SIZE)
        fp.write(data)
        # out of the handle buffer: the page must survive the process dying
        fp.flush()
        self.writes += 1

    def append_page(self, path: str, data: bytes) -> int:
        self._check_size(data)
        fp = self._handle(path)
        page_id = self._pages[path]
        tx_manager.TX_HOOK("APPEND", path, page_id, None)
        fp.seek(page_id * PAGE_SIZE)
        fp.write(data)
        fp.flush()
        self._pages[path] = page_id + 1
        self.writes += 1
        return page_id

    def truncate(self, path: str, n_pages: int) -> None:
        fp = self._handle(path)
        fp.flush()
        if n_pages < self._pages[path]:
            self._snapshot(path)
        fp.truncate(n_pages * PAGE_SIZE)
        self._pages[path] = n_pages

    def replace(self, src: str, dst: str) -> None:
        self.close(src)
        self.close(dst)
        if os.path.exists(dst):
            self._snapshot(dst)
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

    @staticmethod
    def _snapshot(path: str) -> None:
        if tx_manager.TX_ACTIVE():
            with open(path, "rb") as fp:
                tx_manager.TX_HOOK("SNAPSHOT", path, None, fp.read())

    def _check_id(self, path: str, page_id: int) -> None:
        if not 0 <= page_id < self.page_count(path):
            raise IndexError(f"{path}: page {page_id} out of range ({self.page_count(path)} pages)")

    @staticmethod
    def _check_size(data: bytes) -> None:
        if len(data) != PAGE_SIZE:
            raise ValueError(f"a page is {PAGE_SIZE} bytes, got {len(data)}")

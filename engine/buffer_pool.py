from collections import OrderedDict
from engine.file_manager import FileManager

POOL_FRAMES = 256


class BufferPool:
    def __init__(self, fm: FileManager, frames: int = POOL_FRAMES):
        if frames < 1:
            raise ValueError("a buffer pool needs at least one frame")
        self.fm = fm
        self.frames = frames
        # (path, page_id) -> data, least recently used first
        self._frames = OrderedDict()
        self.hits = 0
        self.misses = 0

    def page_count(self, path: str) -> int:
        return self.fm.page_count(path)

    def read_page(self, path: str, page_id: int) -> bytes:
        data = self._frames.get((path, page_id))
        if data is not None:
            self._frames.move_to_end((path, page_id))
            self.hits += 1
            return data
        self.misses += 1
        data = self.fm.read_page(path, page_id)
        self._put(path, page_id, data)
        return data

    def write_page(self, path: str, page_id: int, data: bytes) -> None:
        self.fm.write_page(path, page_id, data)
        self._put(path, page_id, bytes(data))

    def append_page(self, path: str, data: bytes) -> int:
        page_id = self.fm.append_page(path, data)
        self._put(path, page_id, bytes(data))
        return page_id

    def truncate(self, path: str, n_pages: int) -> None:
        for key in [k for k in self._frames if k[0] == path and k[1] >= n_pages]:
            del self._frames[key]
        self.fm.truncate(path, n_pages)

    def replace(self, src: str, dst: str) -> None:
        self._drop(src)
        self._drop(dst)
        self.fm.replace(src, dst)

    def close(self, path: str) -> None:
        self._drop(path)
        self.fm.close(path)

    def close_all(self) -> None:
        self._frames.clear()
        self.fm.close_all()

    def reset_counters(self) -> None:
        self.hits = 0
        self.misses = 0
        self.fm.reset_counters()

    def _put(self, path: str, page_id: int, data: bytes) -> None:
        key = (path, page_id)
        if key in self._frames:
            self._frames[key] = data
            self._frames.move_to_end(key)
            return
        if len(self._frames) >= self.frames:
            self._frames.popitem(last=False)
        self._frames[key] = data

    def _drop(self, path: str) -> None:
        for key in [k for k in self._frames if k[0] == path]:
            del self._frames[key]

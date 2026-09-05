import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.page import SlottedPage, PAGE_SIZE
from common.record import Record
from common.types import Schema, RID, Column, DataType

class HeapFile:
    def __init__(self, file_path: str):
        self._file_path = file_path
        if not os.path.exists(file_path):
            open(file_path, "wb").close()
    def page_count(self) -> int:
        file_size = os.path.getsize(self._file_path)
        return file_size // PAGE_SIZE
    def read_page(self, page_id: int) -> SlottedPage:
        if page_id < 0 or page_id >= self.page_count():
            raise ValueError(f"Invalid page ID: {page_id}")
        with open(self._file_path, "rb") as file:
            file.seek(page_id * PAGE_SIZE)
            data = file.read(PAGE_SIZE)
        return SlottedPage.from_bytes(data)
    def write_page(self, page_id: int, page: SlottedPage) -> None:
        if page_id < 0 or page_id >= self.page_count():
            raise ValueError(f"Invalid page ID: {page_id}")
        with open(self._file_path, "r+b") as file:
            file.seek(page_id * PAGE_SIZE)
            file.write(page.to_bytes())
    def append_page(self, page: SlottedPage) -> int:
        page_id = self.page_count()
        with open(self._file_path, "ab") as file:
            file.write(page.to_bytes())
        return page_id
    def insert(self, record: Record, schema: Schema) -> RID:
        data = record.pack(schema)
        for page_id in range(self.page_count()):
            page = self.read_page(page_id)
            try:
                slot_id = page.insert(data)
                self.write_page(page_id, page)
                return RID(page_id=page_id, slot_id=slot_id)
            except ValueError:
                continue
        page = SlottedPage()
        slot_id = page.insert(data)
        page_id = self.append_page(page)
        return RID(page_id=page_id, slot_id=slot_id)
    def read(self, rid: RID, schema: Schema) -> Record | None:
        page = self.read_page(rid.page_id)
        data = page.read(rid.slot_id)
        if data == b"": 
            return None
        return Record.unpack(data, schema)
    def delete(self, rid: RID) -> None:
        page = self.read_page(rid.page_id)
        page.delete(rid.slot_id)
        self.write_page(rid.page_id, page)
    def scan(self, schema: Schema): 
        for page_id in range(self.page_count()):
            page = self.read_page(page_id)
            for slot_id in range(page.slot_count):
                data = page.read(slot_id)
                if data == b"":
                    continue
                yield Record.unpack(data, schema)

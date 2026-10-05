from common.types import RID


def _orden_fisico(page_id: int) -> tuple:
    # en el sequential AUX usa page_id negativos: primero MAIN, luego AUX
    return (page_id < 0, page_id if page_id >= 0 else -page_id - 1)


class RidBitmap:
    """Conjunto de RIDs agrupado por pagina: {page_id: bitset de slots}."""

    __slots__ = ("_pages",)

    def __init__(self, pages: dict[int, int] | None = None):
        self._pages = pages if pages is not None else {}

    @classmethod
    def from_rids(cls, rids) -> "RidBitmap":
        bitmap = cls()
        for rid in rids:
            bitmap.add(rid)
        return bitmap

    def add(self, rid: RID) -> None:
        self._pages[rid.page_id] = self._pages.get(rid.page_id, 0) | (1 << rid.slot_id)

    def __and__(self, other: "RidBitmap") -> "RidBitmap":
        if len(other._pages) < len(self._pages):
            self, other = other, self
        pages = {}
        for page_id, bits in self._pages.items():
            comunes = bits & other._pages.get(page_id, 0)
            if comunes:
                pages[page_id] = comunes
        return RidBitmap(pages)

    def __or__(self, other: "RidBitmap") -> "RidBitmap":
        pages = dict(self._pages)
        for page_id, bits in other._pages.items():
            pages[page_id] = pages.get(page_id, 0) | bits
        return RidBitmap(pages)

    def __len__(self) -> int:
        return sum(bits.bit_count() for bits in self._pages.values())

    def page_count(self) -> int:
        return len(self._pages)

    def pages(self):
        """(page_id, slots) en orden fisico, cada pagina una sola vez."""
        for page_id in sorted(self._pages, key=_orden_fisico):
            bits = self._pages[page_id]
            slots = []
            while bits:
                bajo = bits & -bits
                slots.append(bajo.bit_length() - 1)
                bits ^= bajo
            yield page_id, slots

    def __iter__(self):
        for page_id, slots in self.pages():
            for slot_id in slots:
                yield RID(page_id, slot_id)

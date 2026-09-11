import heapq
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.page import PAGE_SIZE
from common.record import Record
from common.types import DataType
from index.bplus_tree import BPlusTree, DuplicateKey
from storage.sequential_file import AUX_FILE, MAIN_FILE, SequentialEntry, SequentialFile


class ClusteredBPlusTree:
    """Clustered B+ tree over a SequentialFile's primary key.

    The leaf holds one entry per **page** of the MAIN area -- (page minimum ->
    page id) -- not one per row. That is what makes it clustered: the index
    order *is* the file's physical order, so finding the page already finds the
    row, and a range walks consecutive pages instead of paying a random I/O per
    match. It also makes the index about as large as the page count rather than
    the row count.

    The tree is **immutable between reorganizations** and is built only by bulk
    load, so there is no insert, no split, no borrow and no merge on this path.
    What buys that: while the file has live rows, nothing it does moves a row
    between MAIN pages -- insert appends to AUX, delete marks in place.

    The one exception is inserting into a file with *no* live rows, which
    appends to MAIN (see insert()); that one is detected and rebuilt, not
    assumed away.

    The invariant that makes it work is that every live row with key k is
    either in the MAIN page the descent reaches, **or in AUX**. AUX is not
    indexed: it is scanned linearly, which is only O(log n) because the wrapper
    caps it at log2(n) rows by triggering a reorganization.

    Known debt: reads three private members of SequentialFile
    (`_schema`, `_key_index`, `_iter_file_entries`). The ask to the file's owner
    is to make the AUX scan public; using it as-is for now."""

    def __init__(self, seq: SequentialFile, index_path: str):
        self._seq = seq
        self._schema = seq._schema
        self._key_index = seq._key_index
        key_type = self._schema.columns[self._key_index].type

        fresh = not (os.path.exists(index_path) and os.path.getsize(index_path) >= PAGE_SIZE)
        self._tree = BPlusTree(index_path, key_type, clustered=True)
        self._n_main = 0
        if fresh:
            self._rebuild()
        else:
            self._n_main = sum(1 for _ in self._main_rows())

    # --------------------------------------------------------------- lectura

    def search(self, key):
        """Two sources: the MAIN page the tree points at, then AUX."""
        page_id = self._tree.floor(key)
        if page_id is not None:
            for entry in self._live_in_page(page_id):
                if self._key_of(entry) == key:
                    return entry.record
        for entry in self._aux_rows():
            if self._key_of(entry) == key:
                return entry.record
        return None

    def range_search(self, low, high) -> list[Record]:
        """Inclusive [low, high]. The leaf chain is not used: after the descent
        the MAIN pages are walked by consecutive page id, because logical and
        physical order are the same thing here."""
        if low > high:
            return []
        start = self._tree.floor(low)
        from_main = []
        done = False
        for page_id in range(start or 0, self._seq.page_count(MAIN_FILE)):
            for entry in self._live_in_page(page_id):
                k = self._key_of(entry)
                if k > high:
                    done = True
                    break
                if k >= low:
                    from_main.append((k, entry.record))
            if done:
                break

        # AUX está acotado, así que entra en RAM: se ordena y se fusionan las
        # dos listas ordenadas, que es el merge del diseño de clase
        from_aux = sorted(
            (self._key_of(e), e.record)
            for e in self._aux_rows()
            if low <= self._key_of(e) <= high
        )
        return [r for _, r in heapq.merge(from_main, from_aux, key=lambda t: t[0])]

    # -------------------------------------------------------------- escritura

    def insert(self, record: Record) -> None:
        key = record.values[self._key_index]
        if self.search(key) is not None:
            # el SequentialFile no valida unicidad por su cuenta; el índice sí
            # puede, y le cuesta lo mismo que una búsqueda
            raise DuplicateKey(key)
        # No se da por sentado que la fila cae en AUX: `SequentialFile.insert`
        # appendea a **MAIN** cuando el archivo no tiene ninguna fila viva
        # (`_find_head()` devuelve None, y saltea las borradas, así que también
        # pasa tras borrar todo). Una fila nueva en MAIN sí puede dejar una
        # entrada vieja *hacia arriba*, que es el único caso que rompería el
        # descenso, así que se detecta y se reconstruye.
        before = self._main_extent()
        self._seq.insert(record)
        if self._main_extent() != before:
            self._rebuild()
        elif self.aux_count() > self.aux_limit():
            self.reorganize()

    def delete(self, key) -> bool:
        """El árbol no se toca. Sigue siendo O(n) porque lo es
        `SequentialFile.delete`, que recorre la lista enlazada desde la cabeza;
        acelerarlo es la fase 7 y toca el archivo de la teammate."""
        if not self._seq.delete(key):
            return False
        if self._seq.needs_reorganization():
            self.reorganize()
        return True

    def reorganize(self) -> None:
        self._seq.reorganize()
        self._rebuild()

    # ------------------------------------------------------------- política

    def aux_limit(self) -> int:
        """k < log2(n), la cota que se vio en clase. Es lo que hace que
        escanear AUX linealmente sea del mismo orden que el descenso."""
        return max(1, int(math.log2(max(self._n_main, 2))))

    def aux_count(self) -> int:
        return sum(1 for _ in self._aux_rows())

    # -------------------------------------------------------------- interno

    def _key_of(self, entry: SequentialEntry):
        return entry.record.values[self._key_index]

    def _main_extent(self) -> tuple[int, int]:
        """Cheap fingerprint of MAIN's physical size: page count plus the slot
        count of the last page. Detects a write to MAIN using only the
        sequential file's public API, instead of assuming when it does one."""
        pages = self._seq.page_count(MAIN_FILE)
        if pages == 0:
            return (0, 0)
        return (pages, self._seq.read_page(MAIN_FILE, pages - 1).slot_count)

    def _live_in_page(self, page_id: int):
        page = self._seq.read_page(MAIN_FILE, page_id)
        for slot_id in range(page.slot_count):
            data = page.read(slot_id)
            if data == b"":
                continue
            entry = SequentialEntry.unpack(data, self._schema)
            if not entry.deleted:
                yield entry

    def _main_rows(self):
        for page_id in range(self._seq.page_count(MAIN_FILE)):
            yield from self._live_in_page(page_id)

    def _aux_rows(self):
        for _pointer, entry in self._seq._iter_file_entries(AUX_FILE):
            if not entry.deleted:
                yield entry

    def _page_minimums(self):
        """(minimum, page_id) for every MAIN page that still has a live row."""
        for page_id in range(self._seq.page_count(MAIN_FILE)):
            keys = [self._key_of(e) for e in self._live_in_page(page_id)]
            if keys:
                yield min(keys), page_id

    def _rebuild(self) -> None:
        pairs = list(self._page_minimums())
        self._tree.bulk_load(pairs)
        self._n_main = sum(1 for _ in self._main_rows())

    # --------------------------------------------------------- diagnóstico

    def check_invariants(self) -> None:
        """Las del árbol, más las tres que solo valen para el agrupado."""
        self._tree.check_invariants()
        problems = []

        # una entrada por página de MAIN, en orden, y cada clave por DEBAJO o
        # igual al mínimo real de su página. Vieja *hacia abajo* es legal y
        # esperable: borrar la fila mínima de una página sube su mínimo real y
        # el descenso sigue cayendo donde corresponde. Vieja hacia arriba sí
        # sería un bug, y es lo que no puede pasar.
        entries = list(self._tree.scan())
        pages = [p for _, p in entries]
        if pages != sorted(set(pages)):
            problems.append("los page_id del árbol no son estrictamente crecientes")
        if pages and pages[-1] >= self._seq.page_count(MAIN_FILE):
            problems.append(f"el árbol apunta a la página {pages[-1]}, fuera de MAIN")
        else:
            for key, page_id in entries:
                live = [self._key_of(e) for e in self._live_in_page(page_id)]
                if live and key > min(live):
                    problems.append(
                        f"la entrada de la página {page_id} dice {key!r} pero el "
                        f"mínimo vivo es {min(live)!r} (vieja hacia arriba)"
                    )

        # todo registro vivo se encuentra por el índice
        missing = [r.values[self._key_index] for r in self._seq.scan()
                   if self.search(r.values[self._key_index]) is None]
        if missing:
            problems.append(
                f"{len(missing)} clave(s) están en el archivo pero no se "
                f"encuentran por el índice, p.ej. {missing[0]!r}"
            )

        # la cota de AUX
        n_aux, limit = self.aux_count(), self.aux_limit()
        if n_aux > limit:
            problems.append(f"AUX tiene {n_aux} filas, la cota es {limit}")

        if problems:
            raise ValueError(
                f"{len(problems)} invariante(s) rota(s):\n  - " + "\n  - ".join(problems)
            )

    def stats(self) -> dict:
        s = self._tree.stats()
        s.update({
            "main_rows": self._n_main,
            "main_pages": self._seq.page_count(MAIN_FILE),
            "aux_rows": self.aux_count(),
            "aux_limit": self.aux_limit(),
            "aux_pages": self._seq.page_count(AUX_FILE),
        })
        return s

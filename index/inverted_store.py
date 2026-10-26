import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.page import PAGE_SIZE
from common.types import RID
from engine.buffer_pool import BufferPool

EXT_DICCIONARIO = ".dic"
EXT_POSTINGS = ".pst"
EXT_DOCUMENTOS = ".doc"

POSTING = struct.Struct("<II")
POSTINGS_POR_PAGINA = PAGE_SIZE // POSTING.size

META_DICCIONARIO = struct.Struct("<IQI")
CABECERA_DICCIONARIO = struct.Struct("<H")
ENTRADA_DICCIONARIO = struct.Struct("<IQB")
MAX_BYTES_TERMINO = 255

META_DOCUMENTOS = struct.Struct("<IQ16s??")
DOCUMENTO = struct.Struct("<iiId")
DOCUMENTOS_POR_PAGINA = PAGE_SIZE // DOCUMENTO.size


def rutas(base: str) -> list[str]:
    return [base + EXT_DICCIONARIO, base + EXT_POSTINGS, base + EXT_DOCUMENTOS]


def eliminar(pool: BufferPool, base: str) -> None:
    for ruta in rutas(base):
        pool.close(ruta)
        if os.path.exists(ruta):
            os.remove(ruta)


def _pagina_diccionario(entradas: list) -> bytes:
    buf = bytearray(CABECERA_DICCIONARIO.pack(len(entradas)))
    for termino, df, inicio in entradas:
        crudo = termino.encode("utf-8")
        buf += ENTRADA_DICCIONARIO.pack(df, inicio, len(crudo)) + crudo
    return bytes(buf) + bytes(PAGE_SIZE - len(buf))


def _leer_pagina_diccionario(data: bytes) -> list:
    (cantidad,) = CABECERA_DICCIONARIO.unpack_from(data, 0)
    entradas = []
    offset = CABECERA_DICCIONARIO.size
    for _ in range(cantidad):
        df, inicio, largo = ENTRADA_DICCIONARIO.unpack_from(data, offset)
        offset += ENTRADA_DICCIONARIO.size
        entradas.append((data[offset:offset + largo].decode("utf-8"), df, inicio))
        offset += largo
    return entradas


class EscritorIndice:
    def __init__(self, pool: BufferPool, base: str):
        self.pool = pool
        self.ruta_diccionario = base + EXT_DICCIONARIO
        self.ruta_postings = base + EXT_POSTINGS
        for ruta in (self.ruta_diccionario, self.ruta_postings):
            pool.truncate(ruta, 0)
        self.pool.append_page(self.ruta_diccionario, bytes(PAGE_SIZE))
        self._pagina_dic = []
        self._bytes_dic = CABECERA_DICCIONARIO.size
        self._paginas_dic = 0
        self._buffer_postings = bytearray()
        self.num_terminos = 0
        self.num_postings = 0
        self._ultimo = None
        self._cerrado = False

    def __enter__(self) -> "EscritorIndice":
        return self

    def __exit__(self, tipo, valor, traza) -> None:
        if tipo is None:
            self.cerrar()

    def agregar(self, termino: str, postings: list) -> None:
        if self._cerrado:
            raise ValueError("el escritor ya fue cerrado")
        if self._ultimo is not None and termino <= self._ultimo:
            raise ValueError(f"los terminos deben llegar en orden estricto: '{termino}' despues de '{self._ultimo}'")
        if not postings:
            raise ValueError(f"el termino '{termino}' no tiene postings")
        crudo = termino.encode("utf-8")
        if not crudo or len(crudo) > MAX_BYTES_TERMINO:
            raise ValueError(f"el termino debe ocupar entre 1 y {MAX_BYTES_TERMINO} bytes: '{termino[:40]}'")

        anterior = -1
        for doc_id, tf in postings:
            if doc_id <= anterior:
                raise ValueError(f"los postings de '{termino}' deben estar ordenados por doc_id sin repetir")
            if tf < 1:
                raise ValueError(f"tf invalido ({tf}) para '{termino}' en el documento {doc_id}")
            anterior = doc_id
            self._buffer_postings += POSTING.pack(doc_id, tf)
        while len(self._buffer_postings) >= PAGE_SIZE:
            self.pool.append_page(self.ruta_postings, bytes(self._buffer_postings[:PAGE_SIZE]))
            del self._buffer_postings[:PAGE_SIZE]

        tamano = ENTRADA_DICCIONARIO.size + len(crudo)
        if self._bytes_dic + tamano > PAGE_SIZE:
            self._volcar_diccionario()
        self._pagina_dic.append((termino, len(postings), self.num_postings))
        self._bytes_dic += tamano
        self.num_terminos += 1
        self.num_postings += len(postings)
        self._ultimo = termino

    def cerrar(self) -> None:
        if self._cerrado:
            return
        if self._pagina_dic:
            self._volcar_diccionario()
        if self._buffer_postings:
            relleno = bytes(PAGE_SIZE - len(self._buffer_postings))
            self.pool.append_page(self.ruta_postings, bytes(self._buffer_postings) + relleno)
            self._buffer_postings = bytearray()
        meta = META_DICCIONARIO.pack(self.num_terminos, self.num_postings, self._paginas_dic)
        self.pool.write_page(self.ruta_diccionario, 0, meta + bytes(PAGE_SIZE - len(meta)))
        self._cerrado = True

    def _volcar_diccionario(self) -> None:
        self.pool.append_page(self.ruta_diccionario, _pagina_diccionario(self._pagina_dic))
        self._paginas_dic += 1
        self._pagina_dic = []
        self._bytes_dic = CABECERA_DICCIONARIO.size


class LectorIndice:
    def __init__(self, pool: BufferPool, base: str):
        self.pool = pool
        self.ruta_diccionario = base + EXT_DICCIONARIO
        self.ruta_postings = base + EXT_POSTINGS
        if pool.page_count(self.ruta_diccionario) == 0:
            raise FileNotFoundError(f"no existe el diccionario '{self.ruta_diccionario}'")
        self.num_terminos, self.num_postings, self._paginas_dic = META_DICCIONARIO.unpack_from(
            pool.read_page(self.ruta_diccionario, 0), 0)

    def __len__(self) -> int:
        return self.num_terminos

    def __contains__(self, termino: str) -> bool:
        return self.buscar(termino) is not None

    def _pagina(self, numero: int) -> list:
        return _leer_pagina_diccionario(self.pool.read_page(self.ruta_diccionario, numero + 1))

    def buscar(self, termino: str):
        bajo, alto = 0, self._paginas_dic - 1
        candidata = None
        while bajo <= alto:
            medio = (bajo + alto) // 2
            entradas = self._pagina(medio)
            if entradas[0][0] <= termino:
                candidata = entradas
                bajo = medio + 1
            else:
                alto = medio - 1
        if candidata is None:
            return None
        for t, df, inicio in candidata:
            if t == termino:
                return df, inicio
        return None

    def df(self, termino: str) -> int:
        encontrado = self.buscar(termino)
        return 0 if encontrado is None else encontrado[0]

    def postings(self, termino: str) -> list:
        encontrado = self.buscar(termino)
        if encontrado is None:
            return []
        df, inicio = encontrado
        return self._leer_postings(inicio, df)

    def iterar(self):
        for numero in range(self._paginas_dic):
            for termino, df, inicio in self._pagina(numero):
                yield termino, self._leer_postings(inicio, df)

    def terminos(self):
        for numero in range(self._paginas_dic):
            for termino, df, _inicio in self._pagina(numero):
                yield termino, df

    def _leer_postings(self, inicio: int, cantidad: int) -> list:
        resultado = []
        fin = inicio + cantidad
        actual = inicio
        while actual < fin:
            pagina, posicion = divmod(actual, POSTINGS_POR_PAGINA)
            tomar = min(fin - actual, POSTINGS_POR_PAGINA - posicion)
            data = self.pool.read_page(self.ruta_postings, pagina)
            desde = posicion * POSTING.size
            resultado.extend(POSTING.iter_unpack(data[desde:desde + tomar * POSTING.size]))
            actual += tomar
        return resultado


class ArchivoDocumentos:
    def __init__(self, pool: BufferPool, base: str, idioma: str | None = None, stemming: bool = True):
        self.pool = pool
        self.ruta = base + EXT_DOCUMENTOS
        self._pendiente = []
        if pool.page_count(self.ruta) > 0:
            self._cargar_meta()
        else:
            if idioma is None:
                raise ValueError(f"'{self.ruta}' no existe: hay que indicar el idioma para crearlo")
            if len(idioma.encode("utf-8")) > 16:
                raise ValueError(f"nombre de idioma demasiado largo: '{idioma}'")
            self.N = 0
            self.longitud_total = 0
            self.idioma = idioma
            self.stemming = stemming
            self.desactualizado = False
            self.pool.append_page(self.ruta, bytes(PAGE_SIZE))
            self._guardar_meta()

    def __len__(self) -> int:
        return self.N + len(self._pendiente)

    @property
    def longitud_promedio(self) -> float:
        total = len(self)
        if total == 0:
            return 0.0
        return (self.longitud_total + sum(e[2] for e in self._pendiente)) / total

    def agregar(self, rid: RID, longitud: int) -> int:
        if longitud < 0:
            raise ValueError(f"longitud invalida: {longitud}")
        doc_id = len(self)
        self._pendiente.append((rid.page_id, rid.slot_id, longitud, 0.0))
        if (self.N + len(self._pendiente)) % DOCUMENTOS_POR_PAGINA == 0:
            self.guardar()
        return doc_id

    def guardar(self) -> None:
        if self._pendiente:
            primero = self.N
            self.N += len(self._pendiente)
            self.longitud_total += sum(e[2] for e in self._pendiente)
            entradas = self._pendiente
            self._pendiente = []
            for doc_id in range(primero, self.N):
                pagina, posicion = divmod(doc_id, DOCUMENTOS_POR_PAGINA)
                if posicion == 0 or doc_id == primero:
                    buf = self._pagina_editable(pagina)
                DOCUMENTO.pack_into(buf, posicion * DOCUMENTO.size, *entradas[doc_id - primero])
                if posicion == DOCUMENTOS_POR_PAGINA - 1 or doc_id == self.N - 1:
                    self._escribir_pagina(pagina, buf)
        self._guardar_meta()

    def rid(self, doc_id: int) -> RID:
        page_id, slot_id, _longitud, _norma = self._entrada(doc_id)
        return RID(page_id, slot_id)

    def longitud(self, doc_id: int) -> int:
        return self._entrada(doc_id)[2]

    def norma(self, doc_id: int) -> float:
        return self._entrada(doc_id)[3]

    def iterar(self):
        self.guardar()
        for pagina in range((self.N + DOCUMENTOS_POR_PAGINA - 1) // DOCUMENTOS_POR_PAGINA):
            data = self.pool.read_page(self.ruta, pagina + 1)
            cantidad = min(DOCUMENTOS_POR_PAGINA, self.N - pagina * DOCUMENTOS_POR_PAGINA)
            for posicion in range(cantidad):
                page_id, slot_id, longitud, norma = DOCUMENTO.unpack_from(data, posicion * DOCUMENTO.size)
                yield pagina * DOCUMENTOS_POR_PAGINA + posicion, RID(page_id, slot_id), longitud, norma

    def guardar_normas(self, normas) -> None:
        self.guardar()
        normas = list(normas)
        if len(normas) != self.N:
            raise ValueError(f"se esperaban {self.N} normas, llegaron {len(normas)}")
        for pagina in range((self.N + DOCUMENTOS_POR_PAGINA - 1) // DOCUMENTOS_POR_PAGINA):
            buf = self._pagina_editable(pagina)
            desde = pagina * DOCUMENTOS_POR_PAGINA
            for posicion in range(min(DOCUMENTOS_POR_PAGINA, self.N - desde)):
                offset = posicion * DOCUMENTO.size
                page_id, slot_id, longitud, _norma = DOCUMENTO.unpack_from(buf, offset)
                DOCUMENTO.pack_into(buf, offset, page_id, slot_id, longitud, float(normas[desde + posicion]))
            self._escribir_pagina(pagina, buf)

    def marcar_desactualizado(self) -> None:
        if not self.desactualizado:
            self.desactualizado = True
            self._guardar_meta()

    def _entrada(self, doc_id: int) -> tuple:
        if not 0 <= doc_id < len(self):
            raise IndexError(f"doc_id {doc_id} fuera de rango ({len(self)} documentos)")
        if doc_id >= self.N:
            return self._pendiente[doc_id - self.N]
        pagina, posicion = divmod(doc_id, DOCUMENTOS_POR_PAGINA)
        return DOCUMENTO.unpack_from(self.pool.read_page(self.ruta, pagina + 1), posicion * DOCUMENTO.size)

    def _pagina_editable(self, pagina: int) -> bytearray:
        if pagina + 1 < self.pool.page_count(self.ruta):
            return bytearray(self.pool.read_page(self.ruta, pagina + 1))
        return bytearray(PAGE_SIZE)

    def _escribir_pagina(self, pagina: int, buf: bytearray) -> None:
        if pagina + 1 < self.pool.page_count(self.ruta):
            self.pool.write_page(self.ruta, pagina + 1, bytes(buf))
        else:
            self.pool.append_page(self.ruta, bytes(buf))

    def _cargar_meta(self) -> None:
        self.N, self.longitud_total, idioma, self.stemming, self.desactualizado = META_DOCUMENTOS.unpack_from(
            self.pool.read_page(self.ruta, 0), 0)
        self.idioma = idioma.rstrip(b"\x00").decode("utf-8")

    def _guardar_meta(self) -> None:
        meta = META_DOCUMENTOS.pack(self.N, self.longitud_total, self.idioma.encode("utf-8"),
                                    self.stemming, self.desactualizado)
        self.pool.write_page(self.ruta, 0, meta + bytes(PAGE_SIZE - len(meta)))

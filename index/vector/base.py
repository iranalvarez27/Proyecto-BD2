class IndiceVectorial:
    metodo: str = ""

    def __len__(self) -> int:
        raise NotImplementedError

    def extraer(self, ruta: str):
        raise NotImplementedError

    def buscar(self, vector, k: int, metrica: str) -> list:
        raise NotImplementedError

    def insert(self, key, rid) -> None:
        raise NotImplementedError

    def delete(self, key, rid) -> bool:
        raise NotImplementedError

    def bulk_load(self, pairs) -> None:
        raise NotImplementedError

    def configurar(self, extractor, resolver) -> None:
        raise NotImplementedError

    def guardar(self, ruta: str | None = None) -> None:
        raise NotImplementedError

    def sincronizar(self, pares) -> dict:
        raise NotImplementedError

    def file_paths(self) -> list[str]:
        return []

from index.vector.indices_faiss import IndiceHNSW, IndiceIVF
from index.vector.exacto import IndiceExacto

CONSTRUCTORES = {"EXACTO": IndiceExacto, "HNSW": IndiceHNSW, "IVF": IndiceIVF}

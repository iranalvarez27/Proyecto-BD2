import os
import sys
import uuid
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.engine_adapter import EngineAdapter

app = FastAPI(
    title="Minigestor Multimodal API",
    description="API REST para el Frontend del Minigestor de Base de Datos (BD2)",
    version="1.0.0",
)

# Enable CORS for Vite frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

engine = EngineAdapter()


class QueryRequest(BaseModel):
    query: str
    session_id: Optional[str] = None


class ReorganizeRequest(BaseModel):
    table_name: str


@app.get("/api/health")
def health_check():
    return {"status": "ok", "message": "Minigestor Engine API is active"}


@app.get("/api/session")
def new_session():
    """Genera un session_id nuevo para que el frontend identifique sus
    transacciones (BEGIN TRANSACTION / END TRANSACTION / ROLLBACK)."""
    return {"session_id": str(uuid.uuid4())}


@app.get("/api/tables")
def get_tables():
    """Returns all registered tables, columns, indexes and live storage metrics."""
    return engine.get_tables_metadata()


@app.post("/api/query")
def execute_query(req: QueryRequest):
    """Executes a SQL query for a session, returning result rows, execution plan
    and transactional state (active/xact_id)."""
    return engine.execute_query(req.query, req.session_id)


@app.post("/api/explain")
def explain_query(req: QueryRequest):
    """Generates and returns the visual execution plan for a SQL query."""
    return engine.explain_query(req.query)


@app.post("/api/tables/reorganize")
def reorganize_table(req: ReorganizeRequest):
    """Triggers reorganization on a SequentialFile when wasted_ratio exceeds threshold."""
    try:
        return engine.reorganize_table(req.table_name)
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex))


@app.post("/api/seed")
def seed_database():
    """Forces reseeding demo tables on disk."""
    engine.seed_data_if_empty()
    return {"success": True, "tables": engine.get_tables_metadata()}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)

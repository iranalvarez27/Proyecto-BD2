import os
import sys
import uuid
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    from backend.engine_adapter import EngineAdapter
except ModuleNotFoundError:
    from engine_adapter import EngineAdapter

app = FastAPI(title="Minigestor Multimodal API",description="API REST para el Frontend del Minigestor de Base de Datos (BD2)",version="1.0.0",)

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
    analyze: Optional[bool] = False

class ReorganizeRequest(BaseModel):
    table_name: str


@app.get("/api/health")
def health_check():
    return {"status": "ok", "message": "Minigestor Engine API is active"}


@app.get("/api/session")
def new_session():
    return {"session_id": str(uuid.uuid4())}


@app.get("/api/tables")
def get_tables():
    return engine.get_tables_metadata()


@app.post("/api/query")
def execute_query(req: QueryRequest):
    return engine.execute_query(req.query, req.session_id)


@app.post("/api/explain")
def explain_query(req: QueryRequest):
    return engine.explain_query(req.query, req.session_id, analyze=bool(req.analyze))


@app.post("/api/tables/reorganize")
def reorganize_table(req: ReorganizeRequest):
    try:
        return engine.reorganize_table(req.table_name)
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex))


@app.post("/api/seed")
def seed_database():
    engine.seed_data_if_empty()
    return {"success": True, "tables": engine.get_tables_metadata()}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)

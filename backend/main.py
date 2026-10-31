import base64
import os
import sys
import uuid
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
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

class ReorganizeRequest(BaseModel):
    table_name: str

class MediaUploadRequest(BaseModel):
    filename: str
    content_base64: str
    content_type: Optional[str] = None


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


@app.get("/api/tables/{table_name}/points")
def get_table_points(table_name: str, column: Optional[str] = None, limit: int = 5000):
    try:
        return engine.get_points(table_name, column, limit)
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex))


@app.get("/api/visualize/{table_name}")
def visualize_table(table_name: str):
    try:
        return engine.visualize_table(table_name)
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex))


@app.post("/api/tables/reorganize")
def reorganize_table(req: ReorganizeRequest):
    try:
        return engine.reorganize_table(req.table_name)
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex))


@app.post("/api/media/upload")
def upload_media(req: MediaUploadRequest):
    try:
        data_dir = os.path.join(PROJECT_ROOT, "data", "uploads")
        os.makedirs(data_dir, exist_ok=True)
        safe_name = os.path.basename(req.filename)
        raw_b64 = req.content_base64
        if "," in raw_b64:
            raw_b64 = raw_b64.split(",", 1)[1]
        decoded = base64.b64decode(raw_b64)
        file_path = os.path.join(data_dir, safe_name)
        with open(file_path, "wb") as f:
            f.write(decoded)
        return {
            "status": "success",
            "filename": safe_name,
            "path": f"uploads/{safe_name}",
            "url": f"/api/media/uploads/{safe_name}",
            "size": len(decoded),
        }
    except Exception as ex:
        raise HTTPException(status_code=400, detail=f"Error al guardar archivo: {ex}")


@app.get("/api/media/{subpath:path}")
def get_media(subpath: str):
    base_dir = os.path.join(PROJECT_ROOT, "data")
    full_path = os.path.abspath(os.path.join(base_dir, subpath))
    # Seguridad: evitar path traversal fuera de data/
    if not full_path.startswith(os.path.abspath(base_dir)):
        raise HTTPException(status_code=403, detail="Acceso denegado")
    if not os.path.exists(full_path) or not os.path.isfile(full_path):
        raise HTTPException(status_code=404, detail="Archivo multimedia no encontrado")
    return FileResponse(full_path)


@app.post("/api/seed")
def seed_database():
    engine.seed_data_if_empty()
    return {"success": True, "tables": engine.get_tables_metadata()}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)

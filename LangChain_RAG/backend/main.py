from __future__ import annotations

import shutil
import json
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from contracts.errors import ServiceError
from contracts.models import DocumentSummary, HealthResponse, QueryRequest, QueryResponse
from rag import create_backend_service

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

app = FastAPI(title="GraphRAG API", version="0.1.0")
service = create_backend_service()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    return HealthResponse(**service.health_check())


@app.get("/api/documents", response_model=list[DocumentSummary])
def list_documents(knowledge_base_id: str = "kb_demo") -> list[DocumentSummary]:
    try:
        return service.list_documents(knowledge_base_id)
    except ServiceError as error:
        raise HTTPException(status_code=500, detail=error.to_dict()) from error


@app.post("/api/documents/upload", response_model=DocumentSummary)
async def upload_document(
    file: UploadFile = File(...),
    knowledge_base_id: str = Form("kb_demo"),
) -> DocumentSummary:
    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名不能为空")

    safe_name = Path(file.filename).name
    target = UPLOAD_DIR / safe_name
    with target.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        return service.ingest_document(str(target), knowledge_base_id)
    except ServiceError as error:
        raise HTTPException(status_code=400, detail=error.to_dict()) from error


@app.delete("/api/documents/{document_id}")
def delete_document(document_id: str, knowledge_base_id: str = "kb_demo") -> dict:
    try:
        deleted = service.delete_document(knowledge_base_id, document_id)
    except ServiceError as error:
        raise HTTPException(status_code=500, detail=error.to_dict()) from error
    return {"deleted": deleted}


@app.post("/api/answer", response_model=QueryResponse)
def answer(request: QueryRequest) -> QueryResponse:
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="问题不能为空")
    try:
        return service.answer(request)
    except ServiceError as error:
        raise HTTPException(status_code=500, detail=error.to_dict()) from error


@app.post("/api/answer/stream")
def answer_stream(request: QueryRequest) -> StreamingResponse:
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="问题不能为空")

    def event_stream():
        try:
            for delta in service.answer_stream(request):
                payload = json.dumps({"type": "delta", "content": delta}, ensure_ascii=False)
                yield f"data: {payload}\n\n"
            yield "data: " + json.dumps({"type": "done"}, ensure_ascii=False) + "\n\n"
        except ServiceError as error:
            payload = json.dumps({"type": "error", "message": error.message}, ensure_ascii=False)
            yield f"data: {payload}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.delete("/api/sessions/{session_id}")
def clear_session(session_id: str) -> dict:
    cleared = service.clear_session(session_id)
    return {"cleared": cleared}

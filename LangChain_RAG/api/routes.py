"""FastAPI 路由 —— 暴露 BackendService 的所有方法为 REST 端点。"""

import logging
import os
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse

from api.dependencies import get_backend_service
from api.schemas import (
    DocumentSummaryResponse,
    ErrorResponse,
    GraphEdgeResponse,
    GraphNodeResponse,
    HealthResponse,
    QueryRequestModel,
    QueryResponseModel,
    SourceReferenceResponse,
)
from contracts.errors import ServiceError
from contracts.models import QueryRequest

logger = logging.getLogger("api.routes")

router = APIRouter(prefix="/api/v1", tags=["RAG API"])


# ── 辅助函数 ──────────────────────────────────────────────────


def _status_for_error(code: str) -> int:
    """将业务错误码映射为 HTTP 状态码。"""
    mapping = {
        "INVALID_REQUEST": 400,
        "INVALID_FILE_TYPE": 400,
        "DOCUMENT_PARSE_FAILED": 400,
        "DOCUMENT_TOO_LARGE": 413,
        "GRAPHDB_UNAVAILABLE": 503,
        "GRAPH_WRITE_FAILED": 502,
        "GRAPH_QUERY_FAILED": 502,
        "MODEL_CALL_FAILED": 502,
        "ENTITY_EXTRACTION_FAILED": 500,
        "EMPTY_RETRIEVAL_RESULT": 200,  # 空结果不算错误
    }
    return mapping.get(code, 500)


# ── 端点 ──────────────────────────────────────────────────────


@router.get("/health", response_model=HealthResponse)
def health_check(backend=Depends(get_backend_service)):
    """系统健康检查：LLM + GraphDB 连接状态。"""
    result = backend.health_check()
    return HealthResponse(**result)


@router.post(
    "/documents/ingest",
    response_model=DocumentSummaryResponse,
    responses={400: {"model": ErrorResponse}, 413: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
async def ingest_document(
    file: UploadFile = File(..., description="要上传的文档（PDF/DOCX/TXT）"),
    knowledge_base_id: str = Form(..., description="目标知识库 ID"),
    skip_entity_extraction: bool = Form(False, description="跳过实体关系抽取（大幅提速，但丧失图谱检索能力）"),
    backend=Depends(get_backend_service),
):
    """上传文档：解析 → 切块 → 实体抽取（可选） → 写入 GraphDB。

    支持 PDF、DOCX、TXT 格式。

    参数 ``skip_entity_extraction`` 设为 true 可跳过最耗时的
    LLM 实体抽取步骤（提速 10×+），适合只想测试检索效果的场景。
    """
    # 校验文件类型
    allowed_extensions = {".pdf", ".docx", ".txt", ".doc", ".md"}
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_FILE_TYPE", "message": f"不支持的文件类型: {suffix}，支持: {', '.join(allowed_extensions)}"},
        )

    # 保存上传文件到临时目录
    tmp_dir = tempfile.mkdtemp(prefix="rag_upload_")
    tmp_path = os.path.join(tmp_dir, file.filename or "uploaded_file")
    try:
        content = await file.read()
        with open(tmp_path, "wb") as f:
            f.write(content)
        logger.info("Uploaded file saved to: %s (%d bytes)", tmp_path, len(content))
    except Exception as e:
        raise HTTPException(status_code=500, detail={"code": "INTERNAL_ERROR", "message": f"文件保存失败: {e}"})

    try:
        result = backend.ingest_document(
            file_path=tmp_path,
            knowledge_base_id=knowledge_base_id,
            skip_entity_extraction=skip_entity_extraction,
        )
        return DocumentSummaryResponse(
            document_id=result.document_id,
            filename=result.filename,
            knowledge_base_id=result.knowledge_base_id,
            chunk_count=result.chunk_count,
            entity_count=result.entity_count,
            created_at=result.created_at,
        )
    except ServiceError as e:
        raise HTTPException(status_code=_status_for_error(e.code), detail=e.to_dict())
    finally:
        # 清理临时文件
        try:
            os.remove(tmp_path)
            os.rmdir(tmp_dir)
        except OSError:
            pass


@router.post(
    "/query",
    response_model=QueryResponseModel,
    responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
def answer_query(
    body: QueryRequestModel,
    backend=Depends(get_backend_service),
):
    """问答接口：意图识别 → 检索 → 重排 → LLM 生成答案。

    支持三种意图路由：
    - normal_chat: 普通对话
    - document_search: 基于文档的问答
    - graph_query: 知识图谱实体关系查询
    """
    request = QueryRequest(
        query=body.query,
        session_id=body.session_id,
        knowledge_base_id=body.knowledge_base_id,
        selected_document_ids=body.selected_document_ids,
        top_k=body.top_k,
        max_hops=body.max_hops,
        enable_query_rewrite=body.enable_query_rewrite,
        trace_id=body.trace_id,
    )

    try:
        response = backend.answer(request)
    except ServiceError as e:
        raise HTTPException(status_code=_status_for_error(e.code), detail=e.to_dict())

    return QueryResponseModel(
        answer=response.answer,
        intent=response.intent.value,
        original_query=response.original_query,
        rewritten_query=response.rewritten_query,
        sources=[
            SourceReferenceResponse(
                citation_index=s.citation_index,
                document_id=s.document_id,
                filename=s.filename,
                chunk_id=s.chunk_id,
                page_number=s.page_number,
                content=s.content,
                score=s.score,
            )
            for s in response.sources
        ],
        graph_nodes=[
            GraphNodeResponse(node_id=n.node_id, label=n.label, node_type=n.node_type)
            for n in response.graph_nodes
        ],
        graph_edges=[
            GraphEdgeResponse(edge_id=e.edge_id, source=e.source, target=e.target, relation=e.relation, source_chunk_id=e.source_chunk_id)
            for e in response.graph_edges
        ],
        graph_paths=response.graph_paths,
        session_id=response.session_id,
        trace_id=response.trace_id,
    )


@router.post(
    "/query/stream",
    responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
async def answer_query_stream(
    body: QueryRequestModel,
    backend=Depends(get_backend_service),
):
    """流式问答接口：检索完成后逐段返回 LLM 生成的内容（SSE 格式）。"""
    request = QueryRequest(
        query=body.query,
        session_id=body.session_id,
        knowledge_base_id=body.knowledge_base_id,
        selected_document_ids=body.selected_document_ids,
        top_k=body.top_k,
        max_hops=body.max_hops,
        enable_query_rewrite=body.enable_query_rewrite,
        trace_id=body.trace_id,
    )

    import json

    async def event_stream():
        try:
            for event in backend.answer_stream(request):
                if isinstance(event, dict):
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                else:
                    yield f"data: {json.dumps({'type': 'delta', 'content': event}, ensure_ascii=False)}\n\n"
        except ServiceError as e:
            yield f"data: {json.dumps({'type': 'error', 'message': e.message}, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get(
    "/documents",
    response_model=list[DocumentSummaryResponse],
)
def list_documents(
    knowledge_base_id: str = Query(..., description="知识库 ID"),
    backend=Depends(get_backend_service),
):
    """获取指定知识库中所有已上传的文档列表。"""
    try:
        docs = backend.list_documents(knowledge_base_id)
    except ServiceError as e:
        raise HTTPException(status_code=_status_for_error(e.code), detail=e.to_dict())

    return [
        DocumentSummaryResponse(
            document_id=d.document_id,
            filename=d.filename,
            knowledge_base_id=d.knowledge_base_id,
            chunk_count=d.chunk_count,
            entity_count=d.entity_count,
            created_at=d.created_at,
        )
        for d in docs
    ]


@router.delete(
    "/documents/{document_id}",
    responses={404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
def delete_document(
    document_id: str,
    knowledge_base_id: str = Query(..., description="知识库 ID"),
    backend=Depends(get_backend_service),
):
    """删除指定文档及其关联的知识图谱数据。"""
    try:
        deleted = backend.delete_document(knowledge_base_id, document_id)
    except ServiceError as e:
        raise HTTPException(status_code=_status_for_error(e.code), detail=e.to_dict())

    if not deleted:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": f"文档不存在: {document_id}"})

    return {"status": "deleted", "document_id": document_id}


@router.delete(
    "/sessions/{session_id}",
)
def clear_session(
    session_id: str,
    backend=Depends(get_backend_service),
):
    """清除指定会话的对话历史。"""
    cleared = backend.clear_session(session_id)
    return {"status": "cleared" if cleared else "not_found", "session_id": session_id}

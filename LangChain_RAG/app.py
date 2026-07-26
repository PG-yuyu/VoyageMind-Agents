"""智能文档检索助手 —— FastAPI 主入口。

启动方式:
    uvicorn app:app --reload --host 0.0.0.0 --port 8000

架构:
    FastAPI → BackendService → RAGPipeline → GraphRepository

依赖:
    需要配置环境变量（复制 .env.example 为 .env 并填入 API Key）。
    如果没有 GraphRepository 实现，自动使用 MockGraphRepository。
"""

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.routes import router as api_router
from contracts.errors import ServiceError

# ── 应用初始化 ────────────────────────────────────────────────

app = FastAPI(
    title="智能文档检索助手 API",
    description="GraphRAG + Agentic RAG 文档检索与问答系统",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── CORS 中间件 ───────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境应限制为具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 注册路由 ──────────────────────────────────────────────────

app.include_router(api_router)

# ── 全局异常处理 ──────────────────────────────────────────────


@app.exception_handler(ServiceError)
async def service_error_handler(request: Request, exc: ServiceError) -> JSONResponse:
    """将 ServiceError 转换为统一的 JSON 错误响应。"""
    status_code = {
        "INVALID_REQUEST": 400,
        "INVALID_FILE_TYPE": 400,
        "DOCUMENT_PARSE_FAILED": 400,
        "DOCUMENT_TOO_LARGE": 413,
        "GRAPHDB_UNAVAILABLE": 503,
        "GRAPH_WRITE_FAILED": 502,
        "GRAPH_QUERY_FAILED": 502,
        "MODEL_CALL_FAILED": 502,
        "ENTITY_EXTRACTION_FAILED": 500,
    }.get(exc.code, 500)

    return JSONResponse(
        status_code=status_code,
        content=exc.to_dict(),
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """兜底异常处理，避免内部错误直接暴露给客户端。"""
    logging.getLogger("app").exception("Unhandled exception on %s %s", request.method, request.url)
    return JSONResponse(
        status_code=500,
        content={
            "code": "INTERNAL_ERROR",
            "message": "服务器内部错误，请稍后重试",
            "retryable": True,
            "details": {},
        },
    )


# ── 根路径 ───────────────────────────────────────────────────


@app.get("/", tags=["Root"])
async def root():
    """API 根路径，返回服务信息。"""
    return {
        "service": "智能文档检索助手 API",
        "version": "0.1.0",
        "docs": "/docs",
        "health": "/api/v1/health",
    }

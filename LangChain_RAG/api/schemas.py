"""API 层的 Pydantic 模型 —— 用于 FastAPI 请求验证和响应序列化。

将 contracts/models.py 中的 stdlib dataclass 映射为 Pydantic BaseModel，
便于 FastAPI 生成 OpenAPI 文档和进行输入验证。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


# ── 请求模型 ──────────────────────────────────────────────────


class QueryRequestModel(BaseModel):
    """用户查询请求（API 入参）。"""
    query: str = Field(..., description="用户原始问题", min_length=1)
    session_id: str = Field(..., description="当前对话会话 ID")
    knowledge_base_id: str = Field(..., description="知识库 ID")
    selected_document_ids: list[str] = Field(default_factory=list, description="用户指定的文档范围")
    top_k: int = Field(default=10, ge=1, le=50, description="最多返回多少个证据块")
    max_hops: int = Field(default=2, ge=1, le=5, description="图检索最多查询几跳")
    enable_query_rewrite: bool = Field(default=True, description="是否启用问题改写")
    trace_id: str | None = Field(default=None, description="日志追踪编号")


# ── 响应模型 ──────────────────────────────────────────────────


class DocumentSummaryResponse(BaseModel):
    """文档摘要响应。"""
    document_id: str
    filename: str
    knowledge_base_id: str
    chunk_count: int
    entity_count: int
    created_at: str


class SourceReferenceResponse(BaseModel):
    """引用来源响应。"""
    citation_index: int | None = None
    document_id: str
    filename: str
    chunk_id: str
    page_number: int | None = None
    content: str
    score: float


class GraphNodeResponse(BaseModel):
    """知识图谱节点响应。"""
    node_id: str
    label: str
    node_type: str


class GraphEdgeResponse(BaseModel):
    """知识图谱边响应。"""
    edge_id: str
    source: str
    target: str
    relation: str
    source_chunk_id: str | None = None


class QueryResponseModel(BaseModel):
    """问答结果响应。"""
    answer: str
    intent: str
    original_query: str
    rewritten_query: str
    sources: list[SourceReferenceResponse] = []
    graph_nodes: list[GraphNodeResponse] = []
    graph_edges: list[GraphEdgeResponse] = []
    graph_paths: list[list[str]] = []
    session_id: str = ""
    trace_id: str = ""


class HealthResponse(BaseModel):
    """健康检查响应。"""
    status: str
    service: str
    version: str
    graphdb: str = "unknown"


class ErrorResponse(BaseModel):
    """统一错误响应。"""
    code: str
    message: str
    retryable: bool = False
    details: dict = {}

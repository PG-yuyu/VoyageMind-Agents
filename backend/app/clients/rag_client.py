"""LangChain_RAG 推荐依据客户端。"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from backend.app.schemas import Place


DEFAULT_EVIDENCE_TYPES = [
    "景点特色",
    "历史文化信息",
    "游览建议",
    "注意事项",
    "推荐理由依据",
    "来源文档信息",
]
DEFAULT_KNOWLEDGE_BASE_ID = "kb_demo"
MISSING_EVIDENCE_SUMMARY = "当前知识库中没有找到足够依据，不能作为推荐理由的知识来源。"


class RagBackendLike(Protocol):
    """已有 LangChain_RAG 后端服务需要提供的最小接口。"""

    def answer(self, request: Any) -> Any:
        """调用 LangChain_RAG 的问答入口。"""


@dataclass(frozen=True)
class RagSource:
    """RAG 返回的可追溯来源。"""

    title: str
    page: int | None = None
    url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """校验来源标题和页码格式。"""

        if not self.title.strip():
            raise ValueError("RAG 来源标题不能为空")
        if self.page is not None and self.page <= 0:
            raise ValueError("RAG 来源页码必须大于 0")


@dataclass(frozen=True)
class RagEvidenceResult:
    """单个地点的 RAG 依据结果。"""

    place_name: str
    summary: str
    sources: list[RagSource] = field(default_factory=list)
    sufficient: bool = False
    missing_reason: str | None = None
    evidence_types: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        """校验 RAG 结果必须说明是否有可靠来源。"""

        if not self.place_name.strip():
            raise ValueError("RAG 结果必须绑定地点名称")
        if not self.summary.strip():
            raise ValueError("RAG 依据摘要不能为空")
        if not self.sufficient and not self.missing_reason:
            raise ValueError("缺少 RAG 依据时必须说明原因")


class LangChainRagServiceAdapter:
    """直接封装并调用已有 LangChain_RAG 项目。"""

    def __init__(
        self,
        project_root: Path | str | None = None,
        backend_service: RagBackendLike | None = None,
        query_request_cls: type[Any] | None = None,
        knowledge_base_id: str = DEFAULT_KNOWLEDGE_BASE_ID,
        session_prefix: str = "member2-rag",
    ) -> None:
        """保存 RAG 项目路径和可注入的测试替身。"""

        self.project_root = Path(project_root) if project_root else self._default_project_root()
        self.backend_service = backend_service
        self.query_request_cls = query_request_cls
        self.knowledge_base_id = knowledge_base_id
        self.session_prefix = session_prefix

    def query_place_evidence(
        self,
        place: Place,
        evidence_types: list[str],
        top_k: int,
    ) -> dict[str, Any]:
        """调用 LangChain_RAG，为单个地点查询推荐依据。"""

        if not isinstance(place, Place):
            raise TypeError("LangChain_RAG 依据查询只能绑定 Place 数据模型")

        backend = self._get_backend_service()
        query_request_cls = self._get_query_request_cls()
        request = query_request_cls(
            query=self._build_question(place, evidence_types),
            session_id=f"{self.session_prefix}-{place.place_id}",
            knowledge_base_id=self.knowledge_base_id,
            selected_document_ids=[],
            top_k=top_k,
            enable_query_rewrite=True,
            trace_id=f"{self.session_prefix}-{place.place_id}",
        )
        response = backend.answer(request)
        return self._response_to_raw_result(response)

    def _get_backend_service(self) -> RagBackendLike:
        """懒加载 LangChain_RAG 后端服务。"""

        if self.backend_service is not None:
            return self.backend_service

        self._ensure_project_importable()
        from rag import create_backend_service

        self.backend_service = create_backend_service()
        return self.backend_service

    def _get_query_request_cls(self) -> type[Any]:
        """懒加载 LangChain_RAG 的 QueryRequest。"""

        if self.query_request_cls is not None:
            return self.query_request_cls

        self._ensure_project_importable()
        from contracts.models import QueryRequest

        self.query_request_cls = QueryRequest
        return self.query_request_cls

    def _ensure_project_importable(self) -> None:
        """把同级 LangChain_RAG 项目加入 Python 导入路径。"""

        if not self.project_root.exists():
            raise RuntimeError(f"未找到 LangChain_RAG 项目目录：{self.project_root}")
        project_root_text = str(self.project_root)
        if project_root_text not in sys.path:
            sys.path.insert(0, project_root_text)

    @staticmethod
    def _build_question(place: Place, evidence_types: list[str]) -> str:
        """构造面向 LangChain_RAG 的地点依据查询问题。"""

        evidence_text = "、".join(evidence_types)
        return (
            f"请基于知识库资料，检索并总结{place.city}{place.name}的{evidence_text}。"
            "回答必须只依据知识库内容，并保留可追溯来源。"
        )

    @staticmethod
    def _response_to_raw_result(response: Any) -> dict[str, Any]:
        """把 QueryResponse 转成成员二内部统一字典。"""

        sources = [
            {
                "title": getattr(source, "filename", ""),
                "page": getattr(source, "page_number", None),
                "document_id": getattr(source, "document_id", ""),
                "chunk_id": getattr(source, "chunk_id", ""),
                "content": getattr(source, "content", ""),
                "score": getattr(source, "score", None),
                "citation_index": getattr(source, "citation_index", None),
            }
            for source in list(getattr(response, "sources", []) or [])
        ]
        return {
            "answer": str(getattr(response, "answer", "") or ""),
            "sources": sources,
            "sufficient": bool(sources),
            "trace_id": getattr(response, "trace_id", None),
            "session_id": getattr(response, "session_id", None),
        }

    @staticmethod
    def _default_project_root() -> Path:
        """优先使用随主项目提交的 LangChain_RAG，兼容旧的同级目录。"""

        project_root = Path(__file__).resolve().parents[3]
        bundled_root = project_root / "LangChain_RAG"
        if bundled_root.exists():
            return bundled_root
        return project_root.parent / "LangChain_RAG"


class RagClient:
    """成员二 Step 8 使用的 RAG 依据客户端。"""

    def __init__(
        self,
        rag_service: Any | None = None,
        top_k: int = 3,
    ) -> None:
        """注入已有 RAG 服务适配器，默认直接调用 LangChain_RAG。"""

        if top_k <= 0:
            raise ValueError("RAG 检索数量必须大于 0")
        self.rag_service = rag_service or LangChainRagServiceAdapter()
        self.top_k = top_k

    def get_place_evidence(
        self,
        place: Place,
        evidence_types: list[str] | None = None,
    ) -> RagEvidenceResult:
        """为单个推荐地点查询 RAG 依据。"""

        if not isinstance(place, Place):
            raise TypeError("RAG 推荐依据只能绑定 Place 数据模型")
        requested_types = evidence_types or list(DEFAULT_EVIDENCE_TYPES)
        raw_result = self._call_rag_service(place, requested_types)
        return self._normalize_result(place, requested_types, raw_result)

    def _call_rag_service(
        self,
        place: Place,
        evidence_types: list[str],
    ) -> dict[str, Any]:
        """兼容直接适配器、成员一服务封装和测试替身。"""

        if hasattr(self.rag_service, "query_place_evidence"):
            return self.rag_service.query_place_evidence(
                place=place,
                evidence_types=evidence_types,
                top_k=self.top_k,
            )
        if hasattr(self.rag_service, "recommendation_evidence"):
            return self.rag_service.recommendation_evidence(
                place_name=place.name,
                evidence_types=evidence_types,
            )
        if hasattr(self.rag_service, "query"):
            return self.rag_service.query(
                question=LangChainRagServiceAdapter._build_question(place, evidence_types),
                category=place.place_type,
                place_name=place.name,
                top_k=self.top_k,
            )
        raise RuntimeError("RAG 服务缺少推荐依据查询接口")

    def _normalize_result(
        self,
        place: Place,
        evidence_types: list[str],
        raw_result: dict[str, Any],
    ) -> RagEvidenceResult:
        """把 RAG 原始响应转成稳定的 Step 8 结果。"""

        if not isinstance(raw_result, dict):
            raise TypeError("RAG 服务必须返回字典结果")

        sources = self._normalize_sources(raw_result.get("sources", []))
        sufficient = bool(raw_result.get("sufficient", bool(sources))) and bool(sources)
        summary = self._summary_from_raw(raw_result, sufficient)
        missing_reason = None
        if not sufficient:
            missing_reason = self._missing_reason_from_raw(raw_result)

        return RagEvidenceResult(
            place_name=place.name,
            summary=summary,
            sources=sources,
            sufficient=sufficient,
            missing_reason=missing_reason,
            evidence_types=evidence_types,
        )

    @staticmethod
    def _summary_from_raw(raw_result: dict[str, Any], sufficient: bool) -> str:
        """读取 RAG 摘要，证据不足时返回明确说明。"""

        summary = raw_result.get("summary") or raw_result.get("answer")
        if isinstance(summary, str) and summary.strip():
            return summary.strip()
        if sufficient:
            return "RAG 返回了来源，但未提供摘要。"
        return MISSING_EVIDENCE_SUMMARY

    @staticmethod
    def _missing_reason_from_raw(raw_result: dict[str, Any]) -> str:
        """读取证据不足原因。"""

        reason = raw_result.get("missing_reason") or raw_result.get("reason")
        if isinstance(reason, str) and reason.strip():
            return reason.strip()
        return "知识库没有返回可追溯来源"

    @classmethod
    def _normalize_sources(cls, raw_sources: Any) -> list[RagSource]:
        """兼容字符串、字典和 QueryResponse source 对象。"""

        if not isinstance(raw_sources, list):
            raise TypeError("RAG sources 必须是列表")

        sources: list[RagSource] = []
        for raw_source in raw_sources:
            source = cls._source_from_raw(raw_source)
            if source is not None:
                sources.append(source)
        return sources

    @classmethod
    def _source_from_raw(cls, raw_source: Any) -> RagSource | None:
        """把单条来源归一化，无法追溯的来源直接丢弃。"""

        if isinstance(raw_source, str):
            title = raw_source.strip()
            return RagSource(title=title) if title else None
        if not isinstance(raw_source, dict):
            raw_source = {
                "title": getattr(raw_source, "filename", ""),
                "page": getattr(raw_source, "page_number", None),
                "content": getattr(raw_source, "content", ""),
                "score": getattr(raw_source, "score", None),
            }

        title = cls._first_text(
            raw_source,
            ("title", "source", "document", "doc_name", "file_name", "filename", "name"),
        )
        if title is None:
            return None

        return RagSource(
            title=title,
            page=cls._positive_int(
                raw_source.get("page")
                or raw_source.get("page_no")
                or raw_source.get("page_number")
            ),
            url=cls._first_text(raw_source, ("url", "uri", "link")),
            metadata=dict(raw_source),
        )

    @staticmethod
    def _first_text(data: dict[str, Any], keys: tuple[str, ...]) -> str | None:
        """从多个候选字段中读取第一个非空字符串。"""

        for key in keys:
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    @staticmethod
    def _positive_int(value: Any) -> int | None:
        """把页码字段转成正整数。"""

        if value is None:
            return None
        try:
            page = int(value)
        except (TypeError, ValueError):
            return None
        return page if page > 0 else None


__all__ = [
    "DEFAULT_EVIDENCE_TYPES",
    "DEFAULT_KNOWLEDGE_BASE_ID",
    "LangChainRagServiceAdapter",
    "MISSING_EVIDENCE_SUMMARY",
    "RagClient",
    "RagEvidenceResult",
    "RagSource",
]


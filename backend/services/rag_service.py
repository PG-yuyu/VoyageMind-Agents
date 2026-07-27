from __future__ import annotations

import base64
import binascii
import tempfile
from functools import lru_cache
from pathlib import Path
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
LANGCHAIN_RAG_ROOT = PROJECT_ROOT / "LangChain_RAG"
DEFAULT_KNOWLEDGE_BASE_ID = "kb_demo"


def _ensure_langchain_rag_path() -> None:
    root = str(LANGCHAIN_RAG_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)


@lru_cache(maxsize=1)
def _backend_service():
    """Return the LangChain_RAG BackendService singleton."""

    _ensure_langchain_rag_path()
    from rag import create_backend_service

    return create_backend_service()


class RAGService:
    """Adapter from the main travel app to ``LangChain_RAG``.

    The real RAG database is the one configured by ``LangChain_RAG``:
    Neo4j for graph metadata plus Chroma for vectors.  This class only adapts
    request/response shapes for the main FastAPI and Vue app.
    """

    SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}

    def __init__(self, backend: Any | None = None) -> None:
        self.backend = backend

    @property
    def service(self):
        return self.backend or _backend_service()

    def health_check(self) -> dict[str, Any]:
        return self.service.health_check()

    def ingest_document(
        self,
        filename: str,
        content_base64: str,
        content_type: str | None = None,
        knowledge_base_id: str = DEFAULT_KNOWLEDGE_BASE_ID,
        skip_entity_extraction: bool = True,
    ) -> dict[str, Any]:
        clean_filename = self._safe_filename(filename)
        extension = Path(clean_filename).suffix.lower()
        if extension not in self.SUPPORTED_EXTENSIONS:
            supported = "、".join(sorted(self.SUPPORTED_EXTENSIONS))
            raise ValueError(f"不支持的文件类型：{extension or '未知'}，支持：{supported}")

        try:
            content = base64.b64decode(content_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("文件内容不是有效的 base64 编码") from exc
        if not content:
            raise ValueError("上传文件为空")

        with tempfile.TemporaryDirectory(prefix="voyagemind_rag_upload_") as tmp_dir:
            tmp_path = Path(tmp_dir) / clean_filename
            tmp_path.write_bytes(content)

            ingest = getattr(self.service, "ingest_document")
            try:
                summary = ingest(
                    file_path=str(tmp_path),
                    knowledge_base_id=knowledge_base_id,
                    skip_entity_extraction=skip_entity_extraction,
                )
            except TypeError:
                summary = ingest(str(tmp_path), knowledge_base_id)

        return self._document_payload(summary, size_bytes=len(content))

    def list_documents(
        self, knowledge_base_id: str = DEFAULT_KNOWLEDGE_BASE_ID
    ) -> list[dict[str, Any]]:
        documents = self.service.list_documents(knowledge_base_id)
        return [self._document_payload(document) for document in documents]

    def delete_document(
        self, document_id: str, knowledge_base_id: str = DEFAULT_KNOWLEDGE_BASE_ID
    ) -> bool:
        return bool(self.service.delete_document(knowledge_base_id, document_id))

    def query(
        self,
        question: str,
        category: str | None = None,
        place_name: str | None = None,
        top_k: int = 5,
        knowledge_base_id: str = DEFAULT_KNOWLEDGE_BASE_ID,
        selected_document_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        _ensure_langchain_rag_path()
        from contracts.models import QueryRequest

        query_text = " ".join(
            item for item in [question or "", category or "", place_name or ""] if item
        ).strip()
        request = QueryRequest(
            query=query_text or question or "",
            session_id="main_travel_app",
            knowledge_base_id=knowledge_base_id,
            selected_document_ids=selected_document_ids or [],
            top_k=top_k,
            max_hops=2,
            enable_query_rewrite=True,
        )
        response = self.service.answer(request)
        sources = [self._source_payload(source, index + 1) for index, source in enumerate(response.sources)]
        return {
            "answer": response.answer,
            "sources": sources,
            "sufficient": bool(sources),
            "request": {
                "question": question,
                "category": category,
                "place_name": place_name,
                "top_k": top_k,
                "knowledge_base_id": knowledge_base_id,
            },
            "intent": getattr(response.intent, "value", str(response.intent)),
            "rewritten_query": response.rewritten_query,
            "trace_id": response.trace_id,
        }

    def recommendation_evidence(
        self,
        place_name: str,
        evidence_types: list[str],
        knowledge_base_id: str = DEFAULT_KNOWLEDGE_BASE_ID,
    ) -> dict[str, Any]:
        result = self.query(
            question=" ".join([place_name, *[str(item) for item in evidence_types]]),
            place_name=place_name,
            top_k=3,
            knowledge_base_id=knowledge_base_id,
        )
        return {
            "place_name": place_name,
            "summary": result["answer"],
            "sources": result["sources"],
            "evidence_types": evidence_types,
            "sufficient": result["sufficient"],
        }

    def stats(self, knowledge_base_id: str = DEFAULT_KNOWLEDGE_BASE_ID) -> dict[str, Any]:
        health = self.health_check()
        documents = self.list_documents(knowledge_base_id)
        return {
            **health,
            "knowledge_base_id": knowledge_base_id,
            "document_count": len(documents),
            "chunk_count": sum(int(document.get("chunks") or 0) for document in documents),
            "langchain_rag_root": str(LANGCHAIN_RAG_ROOT),
        }

    def _document_payload(self, document: Any, size_bytes: int | None = None) -> dict[str, Any]:
        if hasattr(document, "model_dump"):
            data = document.model_dump()
        elif isinstance(document, dict):
            data = dict(document)
        else:
            data = {
                "document_id": getattr(document, "document_id", ""),
                "filename": getattr(document, "filename", ""),
                "knowledge_base_id": getattr(document, "knowledge_base_id", ""),
                "chunk_count": getattr(document, "chunk_count", 0),
                "entity_count": getattr(document, "entity_count", 0),
                "created_at": getattr(document, "created_at", ""),
            }

        filename = data.get("filename") or data.get("name") or ""
        extension = Path(filename).suffix.removeprefix(".").upper() or "FILE"
        return {
            "document_id": data.get("document_id"),
            "knowledge_base_id": data.get("knowledge_base_id") or DEFAULT_KNOWLEDGE_BASE_ID,
            "name": filename,
            "filename": filename,
            "type": extension,
            "size_bytes": size_bytes,
            "size": self._format_size(size_bytes) if size_bytes is not None else "已入库",
            "status": "可用于问答",
            "chunks": int(data.get("chunk_count") or 0),
            "chunk_count": int(data.get("chunk_count") or 0),
            "entity_count": int(data.get("entity_count") or 0),
            "created_at": data.get("created_at") or "",
        }

    def _source_payload(self, source: Any, fallback_index: int) -> dict[str, Any]:
        if hasattr(source, "model_dump"):
            data = source.model_dump()
        elif isinstance(source, dict):
            data = dict(source)
        else:
            data = {
                "citation_index": getattr(source, "citation_index", None),
                "document_id": getattr(source, "document_id", ""),
                "filename": getattr(source, "filename", ""),
                "chunk_id": getattr(source, "chunk_id", ""),
                "page_number": getattr(source, "page_number", None),
                "content": getattr(source, "content", ""),
                "score": getattr(source, "score", 0.0),
            }
        data["citation_index"] = data.get("citation_index") or fallback_index
        data["title"] = data.get("filename") or data.get("title") or "知识库来源"
        return data

    def _format_size(self, size: int) -> str:
        if size < 1024 * 1024:
            return f"{max(1, round(size / 1024))} KB"
        return f"{size / 1024 / 1024:.1f} MB"

    def _safe_filename(self, filename: str) -> str:
        name = Path(filename or "uploaded_document").name.strip()
        return name or "uploaded_document.txt"

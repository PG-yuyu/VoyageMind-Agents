from __future__ import annotations

from typing import Protocol

from contracts.models import DocumentSummary, QueryRequest, QueryResponse


class BackendService(Protocol):
    def ingest_document(self, file_path: str, knowledge_base_id: str) -> DocumentSummary:
        ...

    def answer(self, request: QueryRequest) -> QueryResponse:
        ...

    def list_documents(self, knowledge_base_id: str) -> list[DocumentSummary]:
        ...

    def delete_document(self, knowledge_base_id: str, document_id: str) -> bool:
        ...

    def clear_session(self, session_id: str) -> bool:
        ...

    def health_check(self) -> dict:
        ...


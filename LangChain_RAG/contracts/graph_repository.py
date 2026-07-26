from __future__ import annotations

from typing import Protocol

from contracts.models import DocumentGraphPayload, DocumentSummary, RetrievalResult


class GraphRepository(Protocol):
    def health_check(self) -> bool:
        ...

    def upsert_document_graph(self, payload: DocumentGraphPayload) -> DocumentSummary:
        ...

    def retrieve_context(
        self,
        query: str,
        entity_names: list[str],
        knowledge_base_id: str,
        document_ids: list[str],
        top_k: int = 5,
        max_hops: int = 2,
    ) -> RetrievalResult:
        ...

    def list_documents(self, knowledge_base_id: str) -> list[DocumentSummary]:
        ...

    def delete_document(self, knowledge_base_id: str, document_id: str) -> bool:
        ...

    def get_subgraph(
        self,
        knowledge_base_id: str,
        entity_ids: list[str],
        max_hops: int = 2,
    ) -> RetrievalResult:
        ...


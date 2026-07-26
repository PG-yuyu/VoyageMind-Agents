from __future__ import annotations

from contracts.models import (
    ChunkRecord,
    DocumentGraphPayload,
    DocumentSummary,
    EntityRecord,
    GraphEdge,
    GraphNode,
    RelationRecord,
    RetrievedChunk,
    RetrievalResult,
)


class MockGraphRepository:
    def __init__(self) -> None:
        self.documents: dict[str, list[DocumentSummary]] = {"kb_demo": []}
        self.chunks: dict[str, list[ChunkRecord]] = {"kb_demo": []}
        self.entities: dict[str, list[EntityRecord]] = {"kb_demo": []}
        self.relations: dict[str, list[RelationRecord]] = {"kb_demo": []}

    def health_check(self) -> bool:
        return True

    def upsert_document_graph(self, payload: DocumentGraphPayload) -> DocumentSummary:
        current = self.documents.setdefault(payload.knowledge_base_id, [])
        self.documents[payload.knowledge_base_id] = [
            item for item in current if item.document_id != payload.document.document_id
        ] + [payload.document]
        self.chunks[payload.knowledge_base_id] = [
            item
            for item in self.chunks.setdefault(payload.knowledge_base_id, [])
            if item.document_id != payload.document.document_id
        ] + payload.chunks
        self.entities[payload.knowledge_base_id] = [
            item
            for item in self.entities.setdefault(payload.knowledge_base_id, [])
            if item.entity_id not in {entity.entity_id for entity in payload.entities}
        ] + payload.entities
        self.relations[payload.knowledge_base_id] = [
            item
            for item in self.relations.setdefault(payload.knowledge_base_id, [])
            if item.relation_id not in {relation.relation_id for relation in payload.relations}
        ] + payload.relations
        return payload.document

    def retrieve_context(
        self,
        query: str,
        entity_names: list[str],
        knowledge_base_id: str,
        document_ids: list[str],
        top_k: int = 5,
        max_hops: int = 2,
    ) -> RetrievalResult:
        doc_map = {
            doc.document_id: doc.filename
            for doc in self.documents.get(knowledge_base_id, [])
        }
        allowed_docs = set(document_ids or [])
        chunks = [
            chunk
            for chunk in self.chunks.get(knowledge_base_id, [])
            if not allowed_docs or chunk.document_id in allowed_docs
        ]
        ranked_chunks = sorted(
            (
                RetrievedChunk(
                    chunk_id=chunk.chunk_id,
                    document_id=chunk.document_id,
                    filename=doc_map.get(chunk.document_id, "unknown"),
                    content=chunk.content,
                    page_number=chunk.page_number,
                    score=self._score_chunk(query, chunk.content),
                )
                for chunk in chunks
            ),
            key=lambda item: item.score,
            reverse=True,
        )[:top_k]

        entities = self.entities.get(knowledge_base_id, [])
        if entity_names:
            lowered_names = [name.lower() for name in entity_names]
            matched_entities = [
                entity
                for entity in entities
                if any(name in entity.name.lower() for name in lowered_names)
            ]
        else:
            matched_entities = entities[:10]

        nodes = [
            GraphNode(
                node_id=entity.entity_id,
                label=entity.name,
                node_type=entity.entity_type,
            )
            for entity in matched_entities
        ]
        node_ids = {node.node_id for node in nodes}
        edges = [
            GraphEdge(
                edge_id=relation.relation_id,
                source=relation.source_entity_id,
                target=relation.target_entity_id,
                relation=relation.relation_type,
                source_chunk_id=relation.source_chunk_id,
            )
            for relation in self.relations.get(knowledge_base_id, [])
            if relation.source_entity_id in node_ids or relation.target_entity_id in node_ids
        ]
        paths = [[edge.source, edge.relation, edge.target] for edge in edges]

        return RetrievalResult(
            rewritten_query=query,
            matched_entities=matched_entities,
            chunks=ranked_chunks,
            nodes=nodes,
            edges=edges,
            paths=paths,
        )

    def list_documents(self, knowledge_base_id: str) -> list[DocumentSummary]:
        return list(self.documents.get(knowledge_base_id, []))

    def delete_document(self, knowledge_base_id: str, document_id: str) -> bool:
        current = self.documents.get(knowledge_base_id, [])
        remaining = [item for item in current if item.document_id != document_id]
        self.documents[knowledge_base_id] = remaining
        self.chunks[knowledge_base_id] = [
            item for item in self.chunks.get(knowledge_base_id, []) if item.document_id != document_id
        ]
        return len(remaining) != len(current)

    def get_subgraph(
        self,
        knowledge_base_id: str,
        entity_ids: list[str],
        max_hops: int = 2,
    ) -> RetrievalResult:
        return RetrievalResult(
            rewritten_query="",
            matched_entities=[],
            chunks=[],
            nodes=[],
            edges=[],
            paths=[],
        )

    @staticmethod
    def _score_chunk(query: str, content: str) -> float:
        query_tokens = set(query.lower())
        content_lower = content.lower()
        if not query_tokens:
            return 0.0
        hits = sum(1 for token in query_tokens if token.strip() and token in content_lower)
        return hits / len(query_tokens)

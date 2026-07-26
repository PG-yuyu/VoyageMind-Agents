"""Neo4j repository for documents and parent-child chunks."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from typing import Any, Iterable, Mapping, Sequence

from neo4j_chroma import cypher_queries as queries
from neo4j_chroma.neo4j_client import Neo4jClient


@dataclass(slots=True)
class DocumentNode:
    document_id: str
    filename: str
    file_path: str = ""
    content: str = ""
    chunk_count: int = 0
    created_at: str | None = None
    is_active: bool = True


@dataclass(slots=True)
class ParentChunkNode:
    parent_id: str
    document_id: str
    content: str
    chunk_index: int
    vector_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ChildChunkNode:
    child_id: str
    document_id: str
    parent_id: str
    content: str
    chunk_index: int
    vector_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class DatabaseRepository:
    """Structured Neo4j storage for document metadata and chunk topology."""

    def __init__(self, neo4j_client: Neo4jClient):
        self.neo4j_client = neo4j_client

    @classmethod
    def from_env(cls) -> "DatabaseRepository":
        return cls(Neo4jClient.from_env())

    def health_check(self) -> bool:
        return self.neo4j_client.health_check()

    def initialize_schema(self) -> None:
        for query in queries.CREATE_CONSTRAINTS_AND_INDEXES:
            self.neo4j_client.execute(query)

    def upsert_document(
        self,
        document: DocumentNode | Mapping[str, Any],
        parent_chunks: Sequence[ParentChunkNode | Mapping[str, Any]],
        child_chunks: Sequence[ChildChunkNode | Mapping[str, Any]],
    ) -> DocumentNode:
        """Idempotently save one document and its parent-child chunks (batch writes)."""

        doc = self._coerce_document(document, chunk_count=len(parent_chunks))
        parents = [self._coerce_parent_chunk(chunk, doc.document_id) for chunk in parent_chunks]
        children = [self._coerce_child_chunk(chunk, doc.document_id) for chunk in child_chunks]

        self.delete_document(doc.document_id)
        self.neo4j_client.execute(queries.UPSERT_DOCUMENT, self._document_params(doc))

        # Batch write parent chunks
        if parents:
            self.neo4j_client.execute(queries.BATCH_UPSERT_PARENT_CHUNKS, {
                "parents": [self._parent_params(p) for p in parents],
            })
        # Batch write child chunks
        if children:
            self.neo4j_client.execute(queries.BATCH_UPSERT_CHILD_CHUNKS, {
                "children": [self._child_params(c) for c in children],
            })
        # Batch write NEXT_TO relations
        parent_pairs = self._adjacent_pairs(parents)
        if parent_pairs:
            self.neo4j_client.execute(queries.BATCH_CREATE_PARENT_NEXT_TO, {
                "pairs": [{"left_id": left.parent_id, "right_id": right.parent_id}
                          for left, right in parent_pairs],
            })
        child_pairs = self._adjacent_pairs(children)
        if child_pairs:
            self.neo4j_client.execute(queries.BATCH_CREATE_CHILD_NEXT_TO, {
                "pairs": [{"left_id": left.child_id, "right_id": right.child_id}
                          for left, right in child_pairs],
            })

        return doc

    def list_documents(self) -> list[DocumentNode]:
        return [self._row_to_document(row) for row in self.neo4j_client.execute(queries.LIST_DOCUMENTS)]

    def get_document(self, document_id: str) -> DocumentNode | None:
        rows = self.neo4j_client.execute(queries.GET_DOCUMENT, {"document_id": document_id})
        return self._row_to_document(rows[0]) if rows else None

    def get_parent_chunks(self, document_id: str) -> list[ParentChunkNode]:
        rows = self.neo4j_client.execute(
            queries.GET_PARENT_CHUNKS_BY_DOCUMENT,
            {"document_id": document_id},
        )
        return [self._row_to_parent_chunk(row) for row in rows]

    def get_child_chunks(self, document_id: str) -> list[ChildChunkNode]:
        rows = self.neo4j_client.execute(
            queries.GET_CHILD_CHUNKS_BY_DOCUMENT,
            {"document_id": document_id},
        )
        return [self._row_to_child_chunk(row) for row in rows]

    def get_parent_chunks_by_ids(self, parent_ids: Iterable[str]) -> list[ParentChunkNode]:
        ids = list(dict.fromkeys(parent_ids))
        if not ids:
            return []
        rows = self.neo4j_client.execute(
            queries.GET_PARENT_CHUNKS_BY_IDS,
            {"parent_ids": ids},
        )
        return [self._row_to_parent_chunk(row) for row in rows]

    def get_child_chunks_by_ids(self, child_ids: Iterable[str]) -> list[ChildChunkNode]:
        ids = list(dict.fromkeys(child_ids))
        if not ids:
            return []
        rows = self.neo4j_client.execute(
            queries.GET_CHILD_CHUNKS_BY_IDS,
            {"child_ids": ids},
        )
        return [self._row_to_child_chunk(row) for row in rows]

    def delete_document(self, document_id: str) -> bool:
        rows = self.neo4j_client.execute(queries.DELETE_DOCUMENT, {"document_id": document_id})
        return bool(rows)

    def clear_all_documents(self) -> int:
        rows = self.neo4j_client.execute(queries.CLEAR_ALL_DOCUMENTS)
        if not rows:
            return 0
        return int(rows[0].get("deleted_count") or 0)

    def close(self) -> None:
        self.neo4j_client.close()

    @staticmethod
    def _coerce_document(
        document: DocumentNode | Mapping[str, Any],
        chunk_count: int,
    ) -> DocumentNode:
        if isinstance(document, DocumentNode):
            doc = document
        else:
            doc = DocumentNode(
                document_id=str(document["document_id"]),
                filename=str(document.get("filename", "")),
                file_path=str(document.get("file_path", "")),
                content=str(document.get("content", "")),
                chunk_count=int(document.get("chunk_count", 0)),
                created_at=document.get("created_at"),
                is_active=bool(document.get("is_active", True)),
            )
        if not doc.created_at:
            doc.created_at = datetime.now(timezone.utc).isoformat()
        if doc.chunk_count == 0:
            doc.chunk_count = chunk_count
        return doc

    @staticmethod
    def _coerce_parent_chunk(
        chunk: ParentChunkNode | Mapping[str, Any],
        document_id: str,
    ) -> ParentChunkNode:
        if isinstance(chunk, ParentChunkNode):
            return chunk
        return ParentChunkNode(
            parent_id=str(chunk["parent_id"]),
            document_id=str(chunk.get("document_id", document_id)),
            content=str(chunk.get("content", "")),
            chunk_index=int(chunk.get("chunk_index", 0)),
            vector_id=str(chunk.get("vector_id", "")),
            metadata=dict(chunk.get("metadata", {})),
        )

    @staticmethod
    def _coerce_child_chunk(
        chunk: ChildChunkNode | Mapping[str, Any],
        document_id: str,
    ) -> ChildChunkNode:
        if isinstance(chunk, ChildChunkNode):
            return chunk
        return ChildChunkNode(
            child_id=str(chunk["child_id"]),
            document_id=str(chunk.get("document_id", document_id)),
            parent_id=str(chunk["parent_id"]),
            content=str(chunk.get("content", "")),
            chunk_index=int(chunk.get("chunk_index", 0)),
            vector_id=str(chunk.get("vector_id", "")),
            metadata=dict(chunk.get("metadata", {})),
        )

    @staticmethod
    def _document_params(document: DocumentNode) -> dict[str, Any]:
        return {
            "document_id": document.document_id,
            "filename": document.filename,
            "file_path": document.file_path,
            "content": document.content,
            "chunk_count": document.chunk_count,
            "created_at": document.created_at,
            "is_active": document.is_active,
        }

    @staticmethod
    def _parent_params(chunk: ParentChunkNode) -> dict[str, Any]:
        return {
            "parent_id": chunk.parent_id,
            "document_id": chunk.document_id,
            "content": chunk.content,
            "chunk_index": chunk.chunk_index,
            "vector_id": chunk.vector_id,
            "metadata": _dump_metadata(chunk.metadata),
        }

    @staticmethod
    def _child_params(chunk: ChildChunkNode) -> dict[str, Any]:
        return {
            "child_id": chunk.child_id,
            "document_id": chunk.document_id,
            "parent_id": chunk.parent_id,
            "content": chunk.content,
            "chunk_index": chunk.chunk_index,
            "vector_id": chunk.vector_id,
            "metadata": _dump_metadata(chunk.metadata),
        }

    @staticmethod
    def _row_to_document(row: Mapping[str, Any]) -> DocumentNode:
        return DocumentNode(
            document_id=str(row["document_id"]),
            filename=str(row.get("filename", "")),
            file_path=str(row.get("file_path", "")),
            content=str(row.get("content", "")),
            chunk_count=int(row.get("chunk_count") or 0),
            created_at=row.get("created_at"),
            is_active=bool(row.get("is_active", True)),
        )

    @staticmethod
    def _row_to_parent_chunk(row: Mapping[str, Any]) -> ParentChunkNode:
        return ParentChunkNode(
            parent_id=str(row["parent_id"]),
            document_id=str(row["document_id"]),
            content=str(row.get("content", "")),
            chunk_index=int(row.get("chunk_index") or 0),
            vector_id=str(row.get("vector_id", "")),
            metadata=_load_metadata(row.get("metadata")),
        )

    @staticmethod
    def _row_to_child_chunk(row: Mapping[str, Any]) -> ChildChunkNode:
        return ChildChunkNode(
            child_id=str(row["child_id"]),
            document_id=str(row["document_id"]),
            parent_id=str(row["parent_id"]),
            content=str(row.get("content", "")),
            chunk_index=int(row.get("chunk_index") or 0),
            vector_id=str(row.get("vector_id", "")),
            metadata=_load_metadata(row.get("metadata")),
        )

    @staticmethod
    def _adjacent_pairs(chunks: Sequence[Any]) -> list[tuple[Any, Any]]:
        ordered = sorted(chunks, key=lambda chunk: chunk.chunk_index)
        return list(zip(ordered, ordered[1:]))


def _dump_metadata(metadata: Mapping[str, Any]) -> str:
    return json.dumps(dict(metadata), ensure_ascii=False, sort_keys=True)


def _load_metadata(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    return json.loads(str(value))

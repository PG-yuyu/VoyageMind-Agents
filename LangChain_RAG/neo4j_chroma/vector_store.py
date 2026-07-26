"""Chroma vector storage for parent and child document chunks."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any, Iterable, Mapping, Sequence

from neo4j_chroma.chroma_client import ChromaClient
from neo4j_chroma.database_repository import ChildChunkNode, ParentChunkNode
from neo4j_chroma.embedding import HashEmbeddingFunction


@dataclass(slots=True)
class VectorDocument:
    vector_id: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class VectorSearchResult(VectorDocument):
    distance: float | None = None
    score: float = 0.0


@dataclass(slots=True)
class VectorWriteResult:
    parent_vector_ids: list[str]
    child_vector_ids: list[str]


class VectorStore:
    """Stores parent chunks and child chunks in two Chroma collections."""

    def __init__(
        self,
        chroma_client: ChromaClient,
        embedding_function: HashEmbeddingFunction | None = None,
    ):
        self.chroma_client = chroma_client
        self.embedding_function = (
            embedding_function
            or chroma_client.embedding_function
            or HashEmbeddingFunction()
        )

    @classmethod
    def from_env(cls) -> "VectorStore":
        chroma_client = ChromaClient.from_env()
        return cls(chroma_client=chroma_client)

    def health_check(self) -> bool:
        return self.chroma_client.health_check()

    def upsert_document(
        self,
        document_id: str,
        parent_chunks: Sequence[ParentChunkNode | Mapping[str, Any]],
        child_chunks: Sequence[ChildChunkNode | Mapping[str, Any]],
        filename: str = "",
    ) -> VectorWriteResult:
        """Idempotently write parent and child chunks for one document."""

        self.delete_document(document_id)
        parent_vector_ids = self.add_parent_chunks(parent_chunks, filename=filename)
        child_vector_ids = self.add_child_chunks(child_chunks, filename=filename)
        return VectorWriteResult(parent_vector_ids, child_vector_ids)

    def _should_skip_manual_embed(self) -> bool:
        """True when Chroma auto-computes embeddings (no manual embed needed)."""
        return getattr(self.chroma_client, "_skip_manual_embed", False)

    def add_parent_chunks(
        self,
        parent_chunks: Sequence[ParentChunkNode | Mapping[str, Any]],
        filename: str = "",
    ) -> list[str]:
        parents = [self._coerce_parent_chunk(chunk) for chunk in parent_chunks]
        ids = [chunk.vector_id or f"parent:{chunk.parent_id}" for chunk in parents]
        documents = [chunk.content for chunk in parents]
        metadatas = [
            self._parent_metadata(chunk, filename=filename, vector_id=vector_id)
            for chunk, vector_id in zip(parents, ids)
        ]
        kwargs = dict(ids=ids, documents=documents, metadatas=metadatas)
        if not self._should_skip_manual_embed():
            kwargs["embeddings"] = self.embedding_function.embed_documents(documents)
        if ids:
            self.chroma_client.parent_collection.upsert(**kwargs)
        return ids

    def add_child_chunks(
        self,
        child_chunks: Sequence[ChildChunkNode | Mapping[str, Any]],
        filename: str = "",
    ) -> list[str]:
        children = [self._coerce_child_chunk(chunk) for chunk in child_chunks]
        ids = [chunk.vector_id or f"child:{chunk.child_id}" for chunk in children]
        documents = [chunk.content for chunk in children]
        metadatas = [
            self._child_metadata(chunk, filename=filename, vector_id=vector_id)
            for chunk, vector_id in zip(children, ids)
        ]
        kwargs = dict(ids=ids, documents=documents, metadatas=metadatas)
        if not self._should_skip_manual_embed():
            kwargs["embeddings"] = self.embedding_function.embed_documents(documents)
        if ids:
            self.chroma_client.child_collection.upsert(**kwargs)
        return ids

    def query_child_chunks(
        self,
        query: str,
        top_k: int = 5,
        document_ids: Sequence[str] | None = None,
    ) -> list[VectorSearchResult]:
        where = self._document_filter(document_ids)
        kwargs: dict[str, Any] = dict(
            n_results=top_k,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        if self._should_skip_manual_embed():
            kwargs["query_texts"] = [query]
        else:
            kwargs["query_embeddings"] = [self.embedding_function.embed_query(query)]
        result = self.chroma_client.child_collection.query(**kwargs)
        return self._query_result_to_documents(result)

    def get_parent_documents_by_ids(self, parent_ids: Iterable[str]) -> list[VectorDocument]:
        ids = list(dict.fromkeys(str(parent_id) for parent_id in parent_ids if parent_id))
        if not ids:
            return []
        result = self.chroma_client.parent_collection.get(
            where=self._parent_filter(ids),
            include=["documents", "metadatas"],
        )
        documents = self._get_result_to_documents(result)
        by_parent_id = {doc.metadata.get("parent_id"): doc for doc in documents}
        return [by_parent_id[parent_id] for parent_id in ids if parent_id in by_parent_id]

    def delete_document(self, document_id: str) -> None:
        where = {"document_id": str(document_id)}
        self.chroma_client.parent_collection.delete(where=where)
        self.chroma_client.child_collection.delete(where=where)

    def close(self) -> None:
        self.chroma_client.close()

    @staticmethod
    def _coerce_parent_chunk(chunk: ParentChunkNode | Mapping[str, Any]) -> ParentChunkNode:
        if isinstance(chunk, ParentChunkNode):
            return chunk
        return ParentChunkNode(
            parent_id=str(chunk["parent_id"]),
            document_id=str(chunk["document_id"]),
            content=str(chunk.get("content", "")),
            chunk_index=int(chunk.get("chunk_index", 0)),
            vector_id=str(chunk.get("vector_id", "")),
            metadata=dict(chunk.get("metadata", {})),
        )

    @staticmethod
    def _coerce_child_chunk(chunk: ChildChunkNode | Mapping[str, Any]) -> ChildChunkNode:
        if isinstance(chunk, ChildChunkNode):
            return chunk
        return ChildChunkNode(
            child_id=str(chunk["child_id"]),
            document_id=str(chunk["document_id"]),
            parent_id=str(chunk["parent_id"]),
            content=str(chunk.get("content", "")),
            chunk_index=int(chunk.get("chunk_index", 0)),
            vector_id=str(chunk.get("vector_id", "")),
            metadata=dict(chunk.get("metadata", {})),
        )

    @staticmethod
    def _parent_metadata(
        chunk: ParentChunkNode,
        filename: str,
        vector_id: str,
    ) -> dict[str, Any]:
        metadata = {
            **chunk.metadata,
            "document_id": chunk.document_id,
            "parent_id": chunk.parent_id,
            "chunk_index": chunk.chunk_index,
            "filename": filename or chunk.metadata.get("filename", ""),
            "vector_id": vector_id,
        }
        return _sanitize_metadata(metadata)

    @staticmethod
    def _child_metadata(
        chunk: ChildChunkNode,
        filename: str,
        vector_id: str,
    ) -> dict[str, Any]:
        metadata = {
            **chunk.metadata,
            "document_id": chunk.document_id,
            "parent_id": chunk.parent_id,
            "child_id": chunk.child_id,
            "chunk_index": chunk.chunk_index,
            "filename": filename or chunk.metadata.get("filename", ""),
            "vector_id": vector_id,
        }
        return _sanitize_metadata(metadata)

    @staticmethod
    def _document_filter(document_ids: Sequence[str] | None) -> dict[str, Any] | None:
        if not document_ids:
            return None
        ids = [str(document_id) for document_id in document_ids]
        if len(ids) == 1:
            return {"document_id": ids[0]}
        return {"document_id": {"$in": ids}}

    @staticmethod
    def _parent_filter(parent_ids: Sequence[str]) -> dict[str, Any]:
        if len(parent_ids) == 1:
            return {"parent_id": parent_ids[0]}
        return {"parent_id": {"$in": list(parent_ids)}}

    @staticmethod
    def _query_result_to_documents(result: Mapping[str, Any]) -> list[VectorSearchResult]:
        ids = _first_query_result(result.get("ids", []))
        documents = _first_query_result(result.get("documents", []))
        metadatas = _first_query_result(result.get("metadatas", []))
        distances = _first_query_result(result.get("distances", []))
        rows = []
        for index, vector_id in enumerate(ids):
            distance = distances[index] if index < len(distances) else None
            rows.append(
                VectorSearchResult(
                    vector_id=str(vector_id),
                    content=documents[index] if index < len(documents) else "",
                    metadata=metadatas[index] if index < len(metadatas) else {},
                    distance=distance,
                    score=_distance_to_score(distance),
                ),
            )
        return rows

    @staticmethod
    def _get_result_to_documents(result: Mapping[str, Any]) -> list[VectorDocument]:
        ids = result.get("ids", [])
        documents = result.get("documents", [])
        metadatas = result.get("metadatas", [])
        rows = []
        for index, vector_id in enumerate(ids):
            rows.append(
                VectorDocument(
                    vector_id=str(vector_id),
                    content=documents[index] if index < len(documents) else "",
                    metadata=metadatas[index] if index < len(metadatas) else {},
                ),
            )
        return rows


def _first_query_result(value: Any) -> list[Any]:
    if not value:
        return []
    first = value[0]
    return first if isinstance(first, list) else value


def _distance_to_score(distance: float | None) -> float:
    if distance is None:
        return 0.0
    return 1.0 / (1.0 + max(distance, 0.0))


def _sanitize_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    sanitized = {}
    for key, value in metadata.items():
        if value is None:
            continue
        if isinstance(value, bool | int | float | str):
            sanitized[key] = value
        else:
            sanitized[key] = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return sanitized

"""Retrieval loop that combines Chroma recall and Neo4j source metadata.

Ensures document diversity by querying a larger candidate pool and then
distributing the top_k slots across different documents.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
import logging
from typing import Any, Sequence

from neo4j_chroma.database_repository import ChildChunkNode, DatabaseRepository, ParentChunkNode
from neo4j_chroma.vector_store import VectorDocument, VectorSearchResult, VectorStore

logger = logging.getLogger("neo4j_chroma.hybrid_retriever")

# ── Constants ────────────────────────────────────────────────────

# Minimum child chunks to retrieve per document in multi-doc mode.
# A value of 3 ensures each document contributes enough candidate text
# for meaningful cross-document answers, even when many documents share
# the top_k budget.
_MIN_CHUNKS_PER_DOC = 3

# Maximum documents to auto-discover and query in multi-doc mode when
# the caller did not specify document_ids.  Beyond this limit we fall
# back to a single enlarged query to avoid excessive Chroma queries.
_MAX_AUTO_DISCOVER_DOCS = 20


@dataclass(slots=True)
class SourceInfo:
    document_id: str
    filename: str
    parent_id: str
    child_id: str
    chunk_index: int | None
    page_number: int | None
    content: str
    child_content: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RetrievalOutput:
    query: str
    context: str
    retrieved_docs: list[SourceInfo] = field(default_factory=list)
    sources: list[SourceInfo] = field(default_factory=list)
    graph_results: list[dict[str, Any]] = field(default_factory=list)


class HybridRetriever:
    """Implements child recall, parent backtracking, and source assembly."""

    def __init__(
        self,
        vector_store: VectorStore,
        database_repository: DatabaseRepository | None = None,
    ):
        self.vector_store = vector_store
        self.database_repository = database_repository

    @classmethod
    def from_env(cls) -> "HybridRetriever":
        return cls(
            vector_store=VectorStore.from_env(),
            database_repository=DatabaseRepository.from_env(),
        )

    def health_check(self) -> bool:
        vector_ok = self.vector_store.health_check()
        neo4j_ok = True
        if self.database_repository is not None:
            neo4j_ok = self.database_repository.health_check()
        return vector_ok and neo4j_ok

    def close(self) -> None:
        self.vector_store.close()
        if self.database_repository is not None:
            self.database_repository.close()

    @staticmethod
    def _pool_size(top_k: int) -> int:
        """Return a larger candidate pool so per-document diversity has room to work."""
        return max(top_k * 5, 30)

    def _auto_discover_document_ids(self) -> list[str]:
        """Query Neo4j for all active documents, returning their IDs.

        Returns an empty list on error or when no documents exist.
        """
        if self.database_repository is None:
            return []
        try:
            docs = self.database_repository.list_documents()
            ids = [d.document_id for d in docs if d.is_active]
            if ids:
                logger.info("Auto-discovered %d documents for multi-doc retrieval", len(ids))
            return ids
        except Exception as exc:
            logger.warning("Failed to auto-discover documents: %s", exc)
            return []

    def _retrieve_multi_document(
        self,
        query: str,
        document_ids: Sequence[str],
        top_k: int,
    ) -> list[VectorSearchResult]:
        """Query each selected document separately so every document gets a fair chance.

        When ``document_ids`` contains multiple documents, a single vector query
        often returns chunks from only the document whose content is semantically
        closest to the *whole* query — other documents get squeezed out even if
        they answer a different *part* of the query.  By querying per document
        and then interleaving, we guarantee coverage.

        Each document is queried for at least ``_MIN_CHUNKS_PER_DOC`` child chunks
        so that even with many documents the per-doc context is meaningful.
        """
        ids = list(document_ids)
        if not ids:
            return []

        per_doc_k = max(_MIN_CHUNKS_PER_DOC, top_k // len(ids))
        all_results: list[VectorSearchResult] = []

        for doc_id in ids:
            doc_results = self.vector_store.query_child_chunks(
                query,
                top_k=per_doc_k,
                document_ids=[doc_id],
            )
            logger.info(
                "Per-doc query: doc=%s, requested=%d, got=%d",
                doc_id, per_doc_k, len(doc_results),
            )
            all_results.extend(doc_results)

        logger.info(
            "Multi-doc merge: total=%d, unique_docs=%d, top_k=%d",
            len(all_results),
            len({r.metadata.get("document_id", "?") for r in all_results}),
            top_k,
        )

        # Sort by score descending and take top_k
        all_results.sort(key=lambda r: r.score, reverse=True)
        return self._ensure_document_diversity(all_results, top_k)

    @staticmethod
    def _ensure_document_diversity(
        results: list[VectorSearchResult],
        target_k: int,
    ) -> list[VectorSearchResult]:
        """Redistribute results across documents so no single document monopolises.

        Groups results by ``document_id``, gives each document a fair share of
        the ``target_k`` slots (at least 1), and fills remaining slots with the
        highest-scoring leftovers.
        """
        if not results:
            return results

        # Group by document_id
        doc_groups: OrderedDict[str, list[VectorSearchResult]] = OrderedDict()
        for r in results:
            doc_id = str(r.metadata.get("document_id", "unknown"))
            doc_groups.setdefault(doc_id, []).append(r)

        # Single document — just return top target_k
        if len(doc_groups) <= 1:
            return sorted(results, key=lambda r: r.score, reverse=True)[:target_k]

        # Sort within each group once
        for results_list in doc_groups.values():
            results_list.sort(key=lambda r: r.score, reverse=True)

        # Distribute slots: at least 1 per document, fill rest by score
        num_docs = len(doc_groups)
        guaranteed = max(1, target_k // num_docs)

        selected: list[VectorSearchResult] = []
        selected_set: set[str] = set()  # track by vector_id to avoid duplicates

        # First pass: take top `guaranteed` from each document
        for doc_results in doc_groups.values():
            for r in doc_results[:guaranteed]:
                if r.vector_id not in selected_set:
                    selected_set.add(r.vector_id)
                    selected.append(r)

        # Second pass: if still room, add next-best from any document
        if len(selected) < target_k:
            all_remaining = sorted(
                [r for r in results if r.vector_id not in selected_set],
                key=lambda r: r.score,
                reverse=True,
            )
            for r in all_remaining[: target_k - len(selected)]:
                selected_set.add(r.vector_id)
                selected.append(r)

        selected.sort(key=lambda r: r.score, reverse=True)
        return selected[:target_k]

    def retrieve(
        self,
        query: str,
        document_ids: Sequence[str] | None = None,
        top_k: int = 5,
        entity_names: Sequence[str] | None = None,
        max_hops: int = 2,
    ) -> RetrievalOutput:
        # ── Resolve document IDs ──────────────────────────────────────
        # When the caller didn't specify which documents to search, we
        # auto-discover all active documents from Neo4j so that every
        # document gets a fair chance via per-doc querying, avoiding the
        # scenario where a single vector query returns results dominated
        # by only one document.
        ids = list(document_ids) if document_ids else []
        if not ids and self.database_repository is not None:
            ids = self._auto_discover_document_ids()
            if len(ids) > _MAX_AUTO_DISCOVER_DOCS:
                logger.info(
                    "Too many auto-discovered docs (%d > %d), falling back to single query",
                    len(ids), _MAX_AUTO_DISCOVER_DOCS,
                )
                ids = []  # fall through to the single-query path below

        # ── Per-document querying when multiple documents are known ───
        # Each selected document is queried separately so that every doc
        # contributes to the result, even if the query embedding is skewed
        # toward one document's topic.
        if len(ids) > 1:
            logger.info(
                "Multi-doc mode: %d docs, top_k=%d",
                len(ids), top_k,
            )
            child_results = self._retrieve_multi_document(query, ids, top_k)
        else:
            # Single document, or auto-discovery found nothing / too many:
            # query a larger pool, then ensure diversity.
            pool_k = self._pool_size(top_k)
            logger.info(
                "Single/doc mode: ids=%s, pool_k=%d, top_k=%d",
                ids, pool_k, top_k,
            )
            child_results = self.vector_store.query_child_chunks(
                query,
                top_k=pool_k,
                document_ids=ids or None,
            )
            child_results = self._ensure_document_diversity(child_results, top_k)

        parent_ids = _unique(
            result.metadata.get("parent_id")
            for result in child_results
            if result.metadata.get("parent_id")
        )
        child_ids = _unique(
            result.metadata.get("child_id")
            for result in child_results
            if result.metadata.get("child_id")
        )

        parent_documents = self.vector_store.get_parent_documents_by_ids(parent_ids)
        parent_vectors = {
            str(doc.metadata.get("parent_id")): doc
            for doc in parent_documents
            if doc.metadata.get("parent_id")
        }
        neo4j_parents, neo4j_children = self._load_neo4j_sources(parent_ids, child_ids)

        sources = [
            self._build_source(
                child_result,
                parent_vectors,
                neo4j_parents,
                neo4j_children,
            )
            for child_result in child_results
        ]
        context = self._build_context(sources)
        graph_results = self._retrieve_graph_results(entity_names or [], document_ids, max_hops)
        return RetrievalOutput(
            query=query,
            context=context,
            retrieved_docs=sources,
            sources=sources,
            graph_results=graph_results,
        )

    def _load_neo4j_sources(
        self,
        parent_ids: Sequence[str],
        child_ids: Sequence[str],
    ) -> tuple[dict[str, ParentChunkNode], dict[str, ChildChunkNode]]:
        if self.database_repository is None:
            return {}, {}
        parents = self.database_repository.get_parent_chunks_by_ids(parent_ids)
        children = self.database_repository.get_child_chunks_by_ids(child_ids)
        return (
            {parent.parent_id: parent for parent in parents},
            {child.child_id: child for child in children},
        )

    def _retrieve_graph_results(
        self,
        entity_names: Sequence[str],
        document_ids: Sequence[str] | None,
        max_hops: int,
    ) -> list[dict[str, Any]]:
        if not entity_names or self.database_repository is None:
            return []
        method = getattr(self.database_repository, "retrieve_entity_context", None)
        if method is None:
            return []
        return method(entity_names=list(entity_names), document_ids=list(document_ids or []), max_hops=max_hops)

    @staticmethod
    def _build_source(
        child_result: VectorSearchResult,
        parent_vectors: dict[str, VectorDocument],
        neo4j_parents: dict[str, ParentChunkNode],
        neo4j_children: dict[str, ChildChunkNode],
    ) -> SourceInfo:
        child_meta = dict(child_result.metadata)
        child_id = str(child_meta.get("child_id", ""))
        parent_id = str(child_meta.get("parent_id", ""))
        neo4j_child = neo4j_children.get(child_id)
        neo4j_parent = neo4j_parents.get(parent_id)
        parent_vector = parent_vectors.get(parent_id)

        merged_metadata = {}
        if parent_vector:
            merged_metadata.update(parent_vector.metadata)
        if neo4j_parent:
            merged_metadata.update(neo4j_parent.metadata)
        if neo4j_child:
            merged_metadata.update(neo4j_child.metadata)
        merged_metadata.update(child_meta)

        content = (
            parent_vector.content
            if parent_vector and parent_vector.content
            else neo4j_parent.content
            if neo4j_parent
            else child_result.content
        )
        child_content = neo4j_child.content if neo4j_child else child_result.content
        return SourceInfo(
            document_id=str(merged_metadata.get("document_id", "")),
            filename=str(merged_metadata.get("filename", "")),
            parent_id=parent_id,
            child_id=child_id,
            chunk_index=_optional_int(merged_metadata.get("chunk_index")),
            page_number=_optional_int(merged_metadata.get("page_number")),
            content=content,
            child_content=child_content,
            score=child_result.score,
            metadata=merged_metadata,
        )

    @staticmethod
    def _build_context(sources: Sequence[SourceInfo]) -> str:
        seen = set()
        context_parts = []
        for source in sources:
            key = source.parent_id or source.child_id or source.content
            if key in seen:
                continue
            seen.add(key)
            context_parts.append(source.content)
        return "\n\n".join(context_parts)


def _unique(values: Sequence[Any]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if value))


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)

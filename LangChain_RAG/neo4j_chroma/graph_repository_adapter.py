"""Adapter that implements contracts.GraphRepository using the neo4j_chroma module.

Bridges the RAG layer (DocumentGraphPayload, RetrievalResult) to Neo4j+Chroma
(DatabaseRepository, VectorStore, HybridRetriever).  Also stores entities and
relations as Neo4j nodes/relationships so graph queries work end-to-end.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Sequence

from contracts.graph_repository import GraphRepository
from contracts.models import (
    DocumentGraphPayload,
    DocumentSummary,
    EntityRecord,
    GraphEdge,
    GraphNode,
    RelationRecord,
    RetrievedChunk,
    RetrievalResult,
    now_text,
)
from neo4j_chroma.database_repository import (
    ChildChunkNode,
    DatabaseRepository,
    DocumentNode,
    ParentChunkNode,
)
from neo4j_chroma.hybrid_retriever import HybridRetriever, SourceInfo
from neo4j_chroma import cypher_queries as queries
from neo4j_chroma.neo4j_client import Neo4jClient
from neo4j_chroma.vector_store import VectorStore

logger = logging.getLogger("neo4j_chroma.graph_repository_adapter")

# ── Cypher constants for entity / relation storage ──────────────

_MERGE_ENTITY = """
MERGE (e:Entity {entity_id: $entity_id})
SET e.name = $name,
    e.entity_type = $entity_type,
    e.aliases = $aliases,
    e.knowledge_base_id = $knowledge_base_id
RETURN e.entity_id AS entity_id
"""

_MERGE_RELATION = """
MATCH (src:Entity {entity_id: $source_entity_id})
MATCH (tgt:Entity {entity_id: $target_entity_id})
MERGE (src)-[r:RELATED {relation_id: $relation_id}]->(tgt)
SET r.relation_type = $relation_type,
    r.source_chunk_id = $source_chunk_id,
    r.confidence = $confidence,
    r.knowledge_base_id = $knowledge_base_id
RETURN r.relation_id AS relation_id
"""

_DELETE_ENTITY_RELATIONS = """
MATCH (e:Entity {knowledge_base_id: $knowledge_base_id, document_id: $document_id})
OPTIONAL MATCH (e)-[r:RELATED]-()
DETACH DELETE e, r
"""

_RETRIEVE_ENTITIES_BY_DOCUMENT = """
MATCH (e:Entity {knowledge_base_id: $knowledge_base_id, document_id: $document_id})
RETURN e.entity_id AS entity_id,
       e.name AS name,
       e.entity_type AS entity_type,
       e.aliases AS aliases
"""

_RETRIEVE_ENTITIES_BY_NAME = """
MATCH (e:Entity {knowledge_base_id: $knowledge_base_id})
WHERE toLower(e.name) CONTAINS toLower($keyword)
   OR toLower(e.aliases) CONTAINS toLower($keyword)
RETURN e.entity_id AS entity_id,
       e.name AS name,
       e.entity_type AS entity_type,
       e.aliases AS aliases
"""

_RETRIEVE_RELATIONS_BY_ENTITY = """
MATCH (src:Entity {entity_id: $entity_id})-[r:RELATED]->(tgt:Entity)
RETURN r.relation_id AS relation_id,
       r.relation_type AS relation_type,
       r.source_chunk_id AS source_chunk_id,
       r.confidence AS confidence,
       src.entity_id AS source_entity_id,
       src.name AS source_name,
       tgt.entity_id AS target_entity_id,
       tgt.name AS target_name
UNION
MATCH (src:Entity)-[r:RELATED]->(tgt:Entity {entity_id: $entity_id})
RETURN r.relation_id AS relation_id,
       r.relation_type AS relation_type,
       r.source_chunk_id AS source_chunk_id,
       r.confidence AS confidence,
       src.entity_id AS source_entity_id,
       src.name AS source_name,
       tgt.entity_id AS target_entity_id,
       tgt.name AS target_name
"""


class Neo4jChromaGraphRepository(GraphRepository):
    """GraphRepository backed by Neo4j + Chroma.

    Delegates document chunk storage to DatabaseRepository and VectorStore,
    retrieves via HybridRetriever, and stores entities/relations directly
    as Neo4j nodes so the graph-query path works end-to-end.
    """

    def __init__(
        self,
        database_repository: DatabaseRepository,
        vector_store: VectorStore,
        hybrid_retriever: HybridRetriever | None = None,
        initialised: bool = False,
    ) -> None:
        self.database_repository = database_repository
        self.vector_store = vector_store
        self.hybrid_retriever = hybrid_retriever or HybridRetriever(
            vector_store=vector_store,
            database_repository=database_repository,
        )
        self._neo4j_client: Neo4jClient | None = None
        self._initialised = initialised

    # ── Factories ──────────────────────────────────────────────────

    @classmethod
    def from_env(cls, *, initialise_schema: bool = False) -> "Neo4jChromaGraphRepository":
        """Build from environment variables (NEO4J_URI, CHROMA_*, …)."""
        db_repo = DatabaseRepository.from_env()
        vs = VectorStore.from_env()
        hybrid = HybridRetriever(
            vector_store=vs,
            database_repository=db_repo,
        )
        inst = cls(
            database_repository=db_repo,
            vector_store=vs,
            hybrid_retriever=hybrid,
        )
        inst._neo4j_client = db_repo.neo4j_client
        if initialise_schema:
            db_repo.initialize_schema()
            inst._initialised = True
        return inst

    # ── Health ─────────────────────────────────────────────────────

    def health_check(self) -> bool:
        try:
            neo4j_ok = self.database_repository.health_check()
            chroma_ok = self.vector_store.health_check()
            return neo4j_ok and chroma_ok
        except Exception as exc:
            logger.warning("Health check failed: %s", exc)
            return False

    # ── Write ──────────────────────────────────────────────────────

    def upsert_document_graph(
        self,
        payload: DocumentGraphPayload,
    ) -> DocumentSummary:
        """Write a document + chunks + entities + relations to Neo4j + Chroma."""
        doc = payload.document
        chunks = payload.chunks
        kb_id = payload.knowledge_base_id
        logger.info("Upserting document %s (%s) in kb=%s", doc.document_id, doc.filename, kb_id)

        # 1. Convert ChunkRecord → ParentChunkNode + ChildChunkNode
        parent_chunks: list[ParentChunkNode] = []
        child_chunks: list[ChildChunkNode] = []
        for i, chunk in enumerate(chunks):
            parent_id = chunk.chunk_id
            page_number = chunk.page_number
            title = chunk.title
            meta: dict[str, Any] = {
                "page_number": page_number,
                "title": title or "",
                "knowledge_base_id": kb_id,
            }
            if chunk.metadata:
                meta.update(chunk.metadata)

            parent_chunks.append(ParentChunkNode(
                parent_id=parent_id,
                document_id=doc.document_id,
                content=chunk.content,
                chunk_index=i,
                vector_id=f"parent:{parent_id}",
                metadata=meta,
            ))

            # Create child chunks from smaller splits of the parent content
            # for more granular retrieval
            child_splits = _split_chunk_for_children(chunk.content, parent_id, i, doc.document_id, kb_id, page_number, title)
            child_chunks.extend(child_splits)

        # 2. Convert DocumentSummary → DocumentNode
        document_node = DocumentNode(
            document_id=doc.document_id,
            filename=doc.filename,
            file_path="",
            content="",
            chunk_count=len(parent_chunks),
            created_at=doc.created_at or now_text(),
            is_active=True,
        )

        # 3. Write to Neo4j (document + chunk structure)
        self.database_repository.upsert_document(
            document=document_node,
            parent_chunks=parent_chunks,
            child_chunks=child_chunks,
        )

        # 4. Write to Chroma (parent vectors + child vectors)
        self.vector_store.upsert_document(
            document_id=doc.document_id,
            parent_chunks=parent_chunks,
            child_chunks=child_chunks,
            filename=doc.filename,
        )

        # 5. Write entities + relations to Neo4j (as Entity nodes)
        if payload.entities or payload.relations:
            self._upsert_entity_graph(payload.entities, payload.relations, kb_id, doc.document_id)

        # 6. Return the DocumentSummary
        doc.chunk_count = len(parent_chunks)
        doc.entity_count = len(payload.entities)
        return doc

    def _upsert_entity_graph(
        self,
        entities: list[EntityRecord],
        relations: list[RelationRecord],
        knowledge_base_id: str,
        document_id: str,
    ) -> None:
        """Write Entity nodes and RELATED relationships into Neo4j (batch writes)."""
        client = self._get_neo4j_client()
        if client is None:
            logger.warning("No Neo4j client available (using mock mode), skipping entity storage")
            return

        # Delete existing entity nodes for this document (idempotent)
        try:
            client.execute(_DELETE_ENTITY_RELATIONS, {
                "knowledge_base_id": knowledge_base_id,
                "document_id": document_id,
            })
        except Exception as exc:
            logger.warning("Failed to clear old entity graph: %s", exc)

        # Batch create Entity nodes
        if entities:
            entity_params = [
                {
                    "entity_id": ent.entity_id,
                    "name": ent.name,
                    "entity_type": ent.entity_type,
                    "aliases": json.dumps(ent.aliases, ensure_ascii=False),
                    "knowledge_base_id": knowledge_base_id,
                    "document_id": document_id,
                }
                for ent in entities
            ]
            try:
                client.execute(queries.BATCH_MERGE_ENTITIES, {"entities": entity_params})
                logger.info("Batch created %d entities", len(entities))
            except Exception as exc:
                logger.warning("Failed to batch create entities: %s", exc)

        # Batch create relationships
        if relations:
            relation_params = [
                {
                    "source_entity_id": rel.source_entity_id,
                    "target_entity_id": rel.target_entity_id,
                    "relation_id": rel.relation_id,
                    "relation_type": rel.relation_type,
                    "source_chunk_id": rel.source_chunk_id,
                    "confidence": rel.confidence,
                    "knowledge_base_id": knowledge_base_id,
                }
                for rel in relations
            ]
            try:
                client.execute(queries.BATCH_MERGE_RELATIONS, {"relations": relation_params})
                logger.info("Batch created %d relations", len(relations))
            except Exception as exc:
                logger.warning("Failed to batch create relations: %s", exc)

        logger.info("Entity graph written: %d entities, %d relations", len(entities), len(relations))

    # ── Retrieve ─────────────────────────────────────────────────

    def retrieve_context(
        self,
        query: str,
        entity_names: list[str],
        knowledge_base_id: str,
        document_ids: list[str],
        top_k: int = 5,
        max_hops: int = 2,
    ) -> RetrievalResult:
        """Search child chunks via Chroma, backtrack parent context, merge with entity graph."""
        logger.info("Retrieving context for query='%.60s...' kb=%s", query, knowledge_base_id)

        # 1. Vector-based retrieval via HybridRetriever
        retrieval_output = self.hybrid_retriever.retrieve(
            query=query,
            document_ids=document_ids or None,
            top_k=top_k,
            entity_names=entity_names,
            max_hops=max_hops,
        )

        # 2. Convert SourceInfo list → RetrievedChunk list
        chunks = [
            RetrievedChunk(
                chunk_id=source.child_id or source.parent_id,
                document_id=source.document_id,
                filename=source.filename,
                content=source.content,
                page_number=source.page_number,
                score=source.score,
            )
            for source in retrieval_output.sources
        ]

        # 3. Entity / relation graph retrieval from Neo4j
        matched_entities: list[EntityRecord] = []
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []
        paths: list[list[str]] = []

        client = self._get_neo4j_client()
        # Always try Neo4j entity search when there's a query or known entities/docs
        has_content = bool(entity_names) or bool(document_ids) or bool(query.strip())
        if client is not None and has_content:
            # Find matching entities by name (or fall back to query keywords)
            search_names = entity_names or []
            if not search_names and query.strip():
                # Use the query itself as the keyword for entity search
                # (extracts entities like "戊戌维新运动" from the query text)
                search_names = [query.strip()]

            for name in search_names:
                rows = client.execute(_RETRIEVE_ENTITIES_BY_NAME, {
                    "knowledge_base_id": knowledge_base_id,
                    "keyword": name,
                })
                for row in rows:
                    matched_entities.append(EntityRecord(
                        entity_id=str(row["entity_id"]),
                        name=str(row.get("name", "")),
                        entity_type=str(row.get("entity_type", "Concept")),
                        aliases=_load_json_list(row.get("aliases", [])),
                    ))

            # If no entity names specified, get all entities for the matching documents
            if not search_names and document_ids:
                for doc_id in document_ids:
                    rows = client.execute(_RETRIEVE_ENTITIES_BY_DOCUMENT, {
                        "knowledge_base_id": knowledge_base_id,
                        "document_id": doc_id,
                    })
                    for row in rows:
                        matched_entities.append(EntityRecord(
                            entity_id=str(row["entity_id"]),
                            name=str(row.get("name", "")),
                            entity_type=str(row.get("entity_type", "Concept")),
                            aliases=_load_json_list(row.get("aliases", [])),
                        ))

            # Build GraphNode list and collect edges
            entity_id_set: set[str] = set()
            for ent in matched_entities:
                nodes.append(GraphNode(
                    node_id=ent.entity_id,
                    label=ent.name,
                    node_type=ent.entity_type,
                ))
                entity_id_set.add(ent.entity_id)

            # Fetch relationships for matched entities
            seen_edge_keys: set[str] = set()
            for eid in entity_id_set:
                rel_rows = client.execute(_RETRIEVE_RELATIONS_BY_ENTITY, {"entity_id": eid})
                for row in rel_rows:
                    edge = GraphEdge(
                        edge_id=str(row.get("relation_id", "")),
                        source=str(row.get("source_name", row.get("source_entity_id", ""))),
                        target=str(row.get("target_name", row.get("target_entity_id", ""))),
                        relation=str(row.get("relation_type", "related_to")),
                        source_chunk_id=str(row.get("source_chunk_id")) or None,
                    )
                    dedup_key = f"{edge.source}|{edge.relation}|{edge.target}"
                    if dedup_key not in seen_edge_keys:
                        seen_edge_keys.add(dedup_key)
                        edges.append(edge)
                        paths.append([edge.source, edge.relation, edge.target])

                    # Add neighbour nodes that aren't already in our list
                    src_id = str(row.get("source_entity_id", ""))
                    tgt_id = str(row.get("target_entity_id", ""))
                    if src_id not in entity_id_set and row.get("source_name"):
                        nodes.append(GraphNode(
                            node_id=src_id,
                            label=str(row["source_name"]),
                            node_type="Concept",
                        ))
                        entity_id_set.add(src_id)
                    if tgt_id not in entity_id_set and row.get("target_name"):
                        nodes.append(GraphNode(
                            node_id=tgt_id,
                            label=str(row["target_name"]),
                            node_type="Concept",
                        ))
                        entity_id_set.add(tgt_id)

            # Deduplicate nodes
            seen_node_ids: set[str] = set()
            deduped_nodes: list[GraphNode] = []
            for n in nodes:
                if n.node_id not in seen_node_ids:
                    seen_node_ids.add(n.node_id)
                    deduped_nodes.append(n)
            nodes = deduped_nodes

        logger.info(
            "Retrieval: %d chunks, %d entities, %d nodes, %d edges",
            len(chunks), len(matched_entities), len(nodes), len(edges),
        )

        return RetrievalResult(
            rewritten_query=query,
            matched_entities=matched_entities,
            chunks=chunks,
            nodes=nodes,
            edges=edges,
            paths=paths,
        )

    # ── List documents ─────────────────────────────────────────

    def list_documents(self, knowledge_base_id: str) -> list[DocumentSummary]:
        """List all documents.  The neo4j_chroma module does not segment by
        knowledge_base_id, so we return every active document."""
        try:
            nodes = self.database_repository.list_documents()
        except Exception as exc:
            logger.warning("Failed to list documents: %s", exc)
            return []

        results: list[DocumentSummary] = []
        for node in nodes:
            results.append(DocumentSummary(
                document_id=node.document_id,
                filename=node.filename,
                knowledge_base_id=knowledge_base_id,
                chunk_count=node.chunk_count,
                entity_count=0,  # updated on upsert
                created_at=node.created_at or "",
            ))
        return results

    # ── Delete document ────────────────────────────────────────

    def delete_document(self, knowledge_base_id: str, document_id: str) -> bool:
        """Delete a document from Neo4j + Chroma + entity graph."""
        logger.info("Deleting document %s from kb=%s", document_id, knowledge_base_id)

        # Delete from Chroma
        try:
            self.vector_store.delete_document(document_id)
        except Exception as exc:
            logger.warning("Chroma delete failed for %s: %s", document_id, exc)

        # Delete entity nodes from Neo4j
        client = self._get_neo4j_client()
        if client is not None:
            try:
                client.execute(_DELETE_ENTITY_RELATIONS, {
                    "knowledge_base_id": knowledge_base_id,
                    "document_id": document_id,
                })
            except Exception as exc:
                logger.warning("Entity delete failed for %s: %s", document_id, exc)

        # Delete document + chunks from Neo4j
        try:
            return self.database_repository.delete_document(document_id)
        except Exception as exc:
            logger.warning("Neo4j delete failed for %s: %s", document_id, exc)
            # If the document doesn't exist in Neo4j but was in Chroma, still return True
            return False

    # ── Subgraph ───────────────────────────────────────────────

    def get_subgraph(
        self,
        knowledge_base_id: str,
        entity_ids: list[str],
        max_hops: int = 2,
    ) -> RetrievalResult:
        """Return the subgraph around specified entity IDs.

        Fetches Entity nodes and their RELATIONSHIP edges up to max_hops depth.
        """
        client = self._get_neo4j_client()
        if client is None:
            return RetrievalResult(rewritten_query="")

        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []
        paths: list[list[str]] = []
        seen_nodes: set[str] = set()
        seen_edges: set[str] = set()
        boundary: set[str] = set(entity_ids)

        for _hop in range(max_hops):
            if not boundary:
                break
            next_boundary: set[str] = set()
            for eid in boundary:
                if eid in seen_nodes:
                    continue
                seen_nodes.add(eid)

                rel_rows = client.execute(_RETRIEVE_RELATIONS_BY_ENTITY, {"entity_id": eid})
                for row in rel_rows:
                    src_id = str(row.get("source_entity_id", ""))
                    tgt_id = str(row.get("target_entity_id", ""))
                    rel_id = str(row.get("relation_id", ""))
                    rel_type = str(row.get("relation_type", "related_to"))

                    edge_key = f"{src_id}|{rel_id}|{tgt_id}"
                    if edge_key not in seen_edges:
                        seen_edges.add(edge_key)
                        src_name = str(row.get("source_name", src_id))
                        tgt_name = str(row.get("target_name", tgt_id))
                        edges.append(GraphEdge(
                            edge_id=rel_id,
                            source=src_name,
                            target=tgt_name,
                            relation=rel_type,
                            source_chunk_id=str(row.get("source_chunk_id")) or None,
                        ))
                        paths.append([src_name, rel_type, tgt_name])

                    if src_id not in seen_nodes:
                        next_boundary.add(src_id)
                    if tgt_id not in seen_nodes:
                        next_boundary.add(tgt_id)

            boundary = next_boundary

        # Build node list from all entity IDs we've seen
        for eid in seen_nodes:
            row = None
            # Fetch entity name
            try:
                rows = client.execute(
                    "MATCH (e:Entity {entity_id: $entity_id}) RETURN e.name AS name, e.entity_type AS type",
                    {"entity_id": eid},
                )
                if rows:
                    row = rows[0]
            except Exception:
                pass
            nodes.append(GraphNode(
                node_id=eid,
                label=str(row.get("name", eid)) if row else eid,
                node_type=str(row.get("type", "Concept")) if row else "Concept",
            ))

        logger.info("Subgraph: %d nodes, %d edges (max_hops=%d)", len(nodes), len(edges), max_hops)
        return RetrievalResult(
            rewritten_query="",
            matched_entities=[],
            chunks=[],
            nodes=nodes,
            edges=edges,
            paths=paths,
        )

    # ── Internal helpers ───────────────────────────────────────

    def _get_neo4j_client(self) -> Neo4jClient | None:
        if self._neo4j_client is not None:
            return self._neo4j_client
        # Try to extract from the database repository
        try:
            self._neo4j_client = self.database_repository.neo4j_client
            return self._neo4j_client
        except AttributeError:
            return None

    def close(self) -> None:
        """Release underlying connections."""
        try:
            self.vector_store.close()
        except Exception:
            pass
        try:
            self.database_repository.close()
        except Exception:
            pass


# ── Helper: split a parent chunk into smaller child chunks ──────

def _split_chunk_for_children(
    content: str,
    parent_id: str,
    parent_index: int,
    document_id: str,
    knowledge_base_id: str,
    page_number: int | None,
    title: str | None,
    child_size: int = 150,
    child_overlap: int = 30,
) -> list[ChildChunkNode]:
    """Split a single parent chunk into smaller overlapping child chunks.

    Each child chunk is stored with its parent_id so the retrieval loop can
    backtrack from child → parent for full context.
    """
    if not content:
        return []

    children: list[ChildChunkNode] = []
    start = 0
    child_idx = 0

    while start < len(content):
        end = min(start + child_size, len(content))
        # Try to break at a sentence boundary if we're not at the end
        if end < len(content):
            # Look for Chinese period, newline, or English period+space
            for boundary_char in ("\n", "。", ". ", "！", "？"):
                pos = content.rfind(boundary_char, start, end)
                if pos > start:
                    end = pos + len(boundary_char)
                    break

        child_text = content[start:end].strip()
        if child_text:
            child_id = f"{parent_id}_c{child_idx}"
            children.append(ChildChunkNode(
                child_id=child_id,
                document_id=document_id,
                parent_id=parent_id,
                content=child_text,
                chunk_index=child_idx,
                vector_id=f"child:{child_id}",
                metadata={
                    "knowledge_base_id": knowledge_base_id,
                    "page_number": page_number,
                    "title": title or "",
                },
            ))
            child_idx += 1

        step = max(1, child_size - child_overlap)
        start += step

    # If no child chunks were produced (very short content), create one from the parent
    if not children:
        children.append(ChildChunkNode(
            child_id=f"{parent_id}_c0",
            document_id=document_id,
            parent_id=parent_id,
            content=content,
            chunk_index=0,
            vector_id=f"child:{parent_id}_c0",
            metadata={
                "knowledge_base_id": knowledge_base_id,
                "page_number": page_number,
                "title": title or "",
            },
        ))

    return children


def _load_json_list(value: Any) -> list[str]:
    """Parse a JSON-encoded list or return the value as-is if it's already a list."""
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(v) for v in parsed]
        except (json.JSONDecodeError, TypeError):
            pass
    return []

"""Cypher statements for Neo4j document and chunk storage."""

CREATE_CONSTRAINTS_AND_INDEXES = [
    """
    CREATE CONSTRAINT document_id_unique IF NOT EXISTS
    FOR (d:Document) REQUIRE d.document_id IS UNIQUE
    """,
    """
    CREATE CONSTRAINT parent_id_unique IF NOT EXISTS
    FOR (p:ParentChunk) REQUIRE p.parent_id IS UNIQUE
    """,
    """
    CREATE CONSTRAINT child_id_unique IF NOT EXISTS
    FOR (c:ChildChunk) REQUIRE c.child_id IS UNIQUE
    """,
    """
    CREATE INDEX document_filename_index IF NOT EXISTS
    FOR (d:Document) ON (d.filename)
    """,
    """
    CREATE INDEX parent_document_id_index IF NOT EXISTS
    FOR (p:ParentChunk) ON (p.document_id)
    """,
    """
    CREATE INDEX child_document_id_index IF NOT EXISTS
    FOR (c:ChildChunk) ON (c.document_id)
    """,
    """
    CREATE INDEX child_parent_id_index IF NOT EXISTS
    FOR (c:ChildChunk) ON (c.parent_id)
    """,
]

UPSERT_DOCUMENT = """
MERGE (d:Document {document_id: $document_id})
SET d.filename = $filename,
    d.file_path = $file_path,
    d.content = $content,
    d.chunk_count = $chunk_count,
    d.created_at = $created_at,
    d.is_active = $is_active
RETURN d.document_id AS document_id
"""

UPSERT_PARENT_CHUNK = """
MATCH (d:Document {document_id: $document_id})
MERGE (p:ParentChunk {parent_id: $parent_id})
SET p.document_id = $document_id,
    p.content = $content,
    p.chunk_index = $chunk_index,
    p.vector_id = $vector_id,
    p.metadata = $metadata
MERGE (d)-[:HAS_PARENT_CHUNK]->(p)
RETURN p.parent_id AS parent_id
"""

UPSERT_CHILD_CHUNK = """
MATCH (p:ParentChunk {parent_id: $parent_id})
MERGE (c:ChildChunk {child_id: $child_id})
SET c.document_id = $document_id,
    c.parent_id = $parent_id,
    c.content = $content,
    c.chunk_index = $chunk_index,
    c.vector_id = $vector_id,
    c.metadata = $metadata
MERGE (p)-[:HAS_CHILD_CHUNK]->(c)
RETURN c.child_id AS child_id
"""

CREATE_PARENT_NEXT_TO = """
MATCH (left:ParentChunk {parent_id: $left_parent_id})
MATCH (right:ParentChunk {parent_id: $right_parent_id})
MERGE (left)-[:NEXT_TO]->(right)
RETURN left.parent_id AS left_parent_id, right.parent_id AS right_parent_id
"""

CREATE_CHILD_NEXT_TO = """
MATCH (left:ChildChunk {child_id: $left_child_id})
MATCH (right:ChildChunk {child_id: $right_child_id})
MERGE (left)-[:NEXT_TO]->(right)
RETURN left.child_id AS left_child_id, right.child_id AS right_child_id
"""

LIST_DOCUMENTS = """
MATCH (d:Document)
WHERE d.is_active = true
RETURN d.document_id AS document_id,
       d.filename AS filename,
       d.file_path AS file_path,
       d.content AS content,
       d.chunk_count AS chunk_count,
       d.created_at AS created_at,
       d.is_active AS is_active
ORDER BY d.created_at DESC
"""

GET_DOCUMENT = """
MATCH (d:Document {document_id: $document_id})
RETURN d.document_id AS document_id,
       d.filename AS filename,
       d.file_path AS file_path,
       d.content AS content,
       d.chunk_count AS chunk_count,
       d.created_at AS created_at,
       d.is_active AS is_active
"""

GET_PARENT_CHUNKS_BY_DOCUMENT = """
MATCH (:Document {document_id: $document_id})-[:HAS_PARENT_CHUNK]->(p:ParentChunk)
RETURN p.parent_id AS parent_id,
       p.document_id AS document_id,
       p.content AS content,
       p.chunk_index AS chunk_index,
       p.vector_id AS vector_id,
       p.metadata AS metadata
ORDER BY p.chunk_index ASC
"""

GET_CHILD_CHUNKS_BY_DOCUMENT = """
MATCH (:Document {document_id: $document_id})-[:HAS_PARENT_CHUNK]->(:ParentChunk)
      -[:HAS_CHILD_CHUNK]->(c:ChildChunk)
RETURN c.child_id AS child_id,
       c.document_id AS document_id,
       c.parent_id AS parent_id,
       c.content AS content,
       c.chunk_index AS chunk_index,
       c.vector_id AS vector_id,
       c.metadata AS metadata
ORDER BY c.chunk_index ASC
"""

GET_PARENT_CHUNKS_BY_IDS = """
MATCH (p:ParentChunk)
WHERE p.parent_id IN $parent_ids
RETURN p.parent_id AS parent_id,
       p.document_id AS document_id,
       p.content AS content,
       p.chunk_index AS chunk_index,
       p.vector_id AS vector_id,
       p.metadata AS metadata
ORDER BY p.chunk_index ASC
"""

GET_CHILD_CHUNKS_BY_IDS = """
MATCH (c:ChildChunk)
WHERE c.child_id IN $child_ids
RETURN c.child_id AS child_id,
       c.document_id AS document_id,
       c.parent_id AS parent_id,
       c.content AS content,
       c.chunk_index AS chunk_index,
       c.vector_id AS vector_id,
       c.metadata AS metadata
ORDER BY c.chunk_index ASC
"""

DELETE_DOCUMENT = """
MATCH (d:Document {document_id: $document_id})
OPTIONAL MATCH (d)-[:HAS_PARENT_CHUNK]->(p:ParentChunk)
OPTIONAL MATCH (p)-[:HAS_CHILD_CHUNK]->(c:ChildChunk)
WITH d, collect(DISTINCT p) AS parents, collect(DISTINCT c) AS children
FOREACH (child IN children | DETACH DELETE child)
FOREACH (parent IN parents | DETACH DELETE parent)
DETACH DELETE d
RETURN 1 AS deleted_count
"""

CLEAR_ALL_DOCUMENTS = """
MATCH (n)
WHERE n:Document OR n:ParentChunk OR n:ChildChunk
WITH collect(n) AS nodes, count(n) AS deleted_count
FOREACH (node IN nodes | DETACH DELETE node)
RETURN deleted_count
"""

# ══════════════════════════════════════════════════════════════
# 批量写入（UNWIND）—— 大幅减少独立查询次数
# ══════════════════════════════════════════════════════════════

BATCH_UPSERT_PARENT_CHUNKS = """
UNWIND $parents AS p
MATCH (d:Document {document_id: p.document_id})
MERGE (chunk:ParentChunk {parent_id: p.parent_id})
SET chunk.document_id = p.document_id,
    chunk.content = p.content,
    chunk.chunk_index = p.chunk_index,
    chunk.vector_id = p.vector_id,
    chunk.metadata = p.metadata
MERGE (d)-[:HAS_PARENT_CHUNK]->(chunk)
RETURN chunk.parent_id AS parent_id
"""

BATCH_UPSERT_CHILD_CHUNKS = """
UNWIND $children AS c
MATCH (p:ParentChunk {parent_id: c.parent_id})
MERGE (chunk:ChildChunk {child_id: c.child_id})
SET chunk.document_id = c.document_id,
    chunk.parent_id = c.parent_id,
    chunk.content = c.content,
    chunk.chunk_index = c.chunk_index,
    chunk.vector_id = c.vector_id,
    chunk.metadata = c.metadata
MERGE (p)-[:HAS_CHILD_CHUNK]->(chunk)
RETURN chunk.child_id AS child_id
"""

BATCH_CREATE_PARENT_NEXT_TO = """
UNWIND $pairs AS pair
MATCH (left:ParentChunk {parent_id: pair.left_id})
MATCH (right:ParentChunk {parent_id: pair.right_id})
MERGE (left)-[:NEXT_TO]->(right)
"""

BATCH_CREATE_CHILD_NEXT_TO = """
UNWIND $pairs AS pair
MATCH (left:ChildChunk {child_id: pair.left_id})
MATCH (right:ChildChunk {child_id: pair.right_id})
MERGE (left)-[:NEXT_TO]->(right)
"""

BATCH_MERGE_ENTITIES = """
UNWIND $entities AS e
MERGE (entity:Entity {entity_id: e.entity_id})
SET entity.name = e.name,
    entity.entity_type = e.entity_type,
    entity.aliases = e.aliases,
    entity.knowledge_base_id = e.knowledge_base_id,
    entity.document_id = e.document_id
RETURN entity.entity_id AS entity_id
"""

BATCH_MERGE_RELATIONS = """
UNWIND $relations AS r
MATCH (src:Entity {entity_id: r.source_entity_id})
MATCH (tgt:Entity {entity_id: r.target_entity_id})
MERGE (src)-[rel:RELATED {relation_id: r.relation_id}]->(tgt)
SET rel.relation_type = r.relation_type,
    rel.source_chunk_id = r.source_chunk_id,
    rel.confidence = r.confidence,
    rel.knowledge_base_id = r.knowledge_base_id
RETURN rel.relation_id AS relation_id
"""

"""Mock GraphRepository —— 成员 3 独立测试用。

模拟成员 2 的 GraphDB 实现，允许在无 GraphDB 环境下开发测试。
"""

import logging
from copy import deepcopy

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
)

logger = logging.getLogger("tests.mock_graph_repository")


class MockGraphRepository(GraphRepository):
    """内存模拟的 GraphRepository，完整实现协议接口。"""

    def __init__(self):
        self._documents: dict[str, DocumentSummary] = {}
        self._chunks: dict[str, list] = {}  # document_id → list of anything
        self._entities: dict[str, list[EntityRecord]] = {}
        self._relations: dict[str, list[RelationRecord]] = {}

    # ── 健康检查 ────────────────────────────────────────────

    def health_check(self) -> bool:
        return True

    # ── 文档写入 ────────────────────────────────────────────

    def upsert_document_graph(
        self,
        payload: DocumentGraphPayload,
    ) -> DocumentSummary:
        doc = payload.document
        doc_id = doc.document_id

        logger.info("Mock: upserting document %s (%s)", doc_id, doc.filename)

        self._documents[doc_id] = deepcopy(doc)
        self._chunks[doc_id] = deepcopy(payload.chunks)
        self._entities[doc_id] = deepcopy(payload.entities)
        self._relations[doc_id] = deepcopy(payload.relations)

        return doc

    # ── 检索 ────────────────────────────────────────────────

    def retrieve_context(
        self,
        query: str,
        entity_names: list[str],
        knowledge_base_id: str,
        document_ids: list[str],
        top_k: int = 5,
        max_hops: int = 2,
    ) -> RetrievalResult:
        logger.info(
            "Mock: retrieving context for query='%.50s...', entities=%s, docs=%s",
            query, entity_names, document_ids,
        )

        matched_entities: list[EntityRecord] = []
        all_chunks = []
        all_nodes: list[GraphNode] = []
        all_edges: list[GraphEdge] = []

        # 确定要查询的文档范围
        if document_ids:
            target_docs = [d for d in document_ids if d in self._documents]
        else:
            target_docs = list(self._documents.keys())

        # 收集匹配的实体、chunks、节点和边
        for doc_id in target_docs:
            chunks = self._chunks.get(doc_id, [])
            entities = self._entities.get(doc_id, [])
            relations = self._relations.get(doc_id, [])

            # 查找匹配的实体
            if entity_names:
                for ent in entities:
                    normalized_ent = ent.name.lower().strip()
                    for search_name in entity_names:
                        if search_name.lower().strip() in normalized_ent or \
                           any(search_name.lower().strip() in a.lower() for a in ent.aliases):
                            matched_entities.append(ent)
                            break

            # 如果没有指定实体，返回所有实体
            if not entity_names:
                matched_entities.extend(entities)

            # 添加 chunk（带基本评分）
            for i, chunk in enumerate(chunks):
                score = 0.5  # 默认分数
                # 简单的关键词匹配加分
                query_lower = query.lower()
                chunk_content_lower = chunk.content.lower()
                if any(word in chunk_content_lower for word in query_lower.split()):
                    score = 0.8

                all_chunks.append(RetrievedChunk(
                    chunk_id=chunk.chunk_id,
                    document_id=chunk.document_id,
                    filename=self._documents[doc_id].filename,
                    content=chunk.content,
                    page_number=chunk.page_number,
                    score=score,
                ))

            # 添加图节点
            for ent in entities:
                all_nodes.append(GraphNode(
                    node_id=ent.entity_id,
                    label=ent.name,
                    node_type=ent.entity_type,
                ))

            # 添加图边
            for rel in relations:
                # 查找 source 和 target 的实体名
                src_name = rel.source_entity_id
                tgt_name = rel.target_entity_id
                for ent in entities:
                    if ent.entity_id == rel.source_entity_id:
                        src_name = ent.name
                    if ent.entity_id == rel.target_entity_id:
                        tgt_name = ent.name

                all_edges.append(GraphEdge(
                    edge_id=rel.relation_id,
                    source=src_name,
                    target=tgt_name,
                    relation=rel.relation_type,
                    source_chunk_id=rel.source_chunk_id,
                ))

        # 限制 top_k
        sorted_chunks = sorted(all_chunks, key=lambda c: c.score, reverse=True)
        top_chunks = sorted_chunks[:top_k]

        return RetrievalResult(
            rewritten_query=query,
            matched_entities=list({e.entity_id: e for e in matched_entities}.values()),
            chunks=top_chunks,
            nodes=list({n.node_id: n for n in all_nodes}.values()),
            edges=all_edges,
            paths=[],
        )

    # ── 文档列表 ────────────────────────────────────────────

    def list_documents(self, knowledge_base_id: str) -> list[DocumentSummary]:
        return list(self._documents.values())

    # ── 文档删除 ────────────────────────────────────────────

    def delete_document(self, knowledge_base_id: str, document_id: str) -> bool:
        if document_id in self._documents:
            del self._documents[document_id]
            self._chunks.pop(document_id, None)
            self._entities.pop(document_id, None)
            self._relations.pop(document_id, None)
            logger.info("Mock: deleted document %s", document_id)
            return True
        return False

    # ── 子图查询 ────────────────────────────────────────────

    def get_subgraph(
        self,
        knowledge_base_id: str,
        entity_ids: list[str],
        max_hops: int = 2,
    ) -> RetrievalResult:
        """返回特定实体的子图。"""
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []

        entity_id_set = set(entity_ids)

        for doc_id in self._documents:
            entities = self._entities.get(doc_id, [])
            relations = self._relations.get(doc_id, [])

            # 包含目标实体
            for ent in entities:
                if ent.entity_id in entity_id_set:
                    nodes.append(GraphNode(
                        node_id=ent.entity_id,
                        label=ent.name,
                        node_type=ent.entity_type,
                    ))

            # 包含与目标实体相关的边
            for rel in relations:
                if rel.source_entity_id in entity_id_set or rel.target_entity_id in entity_id_set:
                    src_name = rel.source_entity_id
                    tgt_name = rel.target_entity_id
                    for ent in entities:
                        if ent.entity_id == rel.source_entity_id:
                            src_name = ent.name
                        if ent.entity_id == rel.target_entity_id:
                            tgt_name = ent.name

                    edges.append(GraphEdge(
                        edge_id=rel.relation_id,
                        source=src_name,
                        target=tgt_name,
                        relation=rel.relation_type,
                        source_chunk_id=rel.source_chunk_id,
                    ))

                    # 一跳邻居也加入节点
                    for ent in entities:
                        if ent.entity_id == rel.source_entity_id or ent.entity_id == rel.target_entity_id:
                            if ent.entity_id not in {n.node_id for n in nodes}:
                                nodes.append(GraphNode(
                                    node_id=ent.entity_id,
                                    label=ent.name,
                                    node_type=ent.entity_type,
                                ))

        return RetrievalResult(
            rewritten_query="",
            chunks=[],
            nodes=nodes,
            edges=edges,
            paths=[],
        )

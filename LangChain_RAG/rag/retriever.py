"""检索编排 —— 封装对 GraphRepository 的调用。

处理：
- 参数校验
- 空实体回退
- GraphDB 错误封装
"""

import logging

from contracts.errors import (
    GRAPHDB_UNAVAILABLE,
    GRAPH_QUERY_FAILED,
    ServiceError,
)
from contracts.graph_repository import GraphRepository
from contracts.models import RetrievalResult

logger = logging.getLogger("rag.retriever")


class Retriever:
    """GraphDB 检索编排器。"""

    def __init__(self, graph_repository: GraphRepository):
        self.graph = graph_repository

    def retrieve(
        self,
        query: str,
        entity_names: list[str],
        knowledge_base_id: str,
        document_ids: list[str] | None = None,
        top_k: int = 5,
        max_hops: int = 2,
    ) -> RetrievalResult:
        """从 GraphDB 检索文档块、实体和关系。

        Args:
            query: 改写后的查询文本。
            entity_names: 从查询中提取的实体名称列表。
            knowledge_base_id: 知识库标识。
            document_ids: 限定的文档范围，空列表表示全部。
            top_k: 最多返回的块数。
            max_hops: 图遍历最大跳数。

        Returns:
            RetrievalResult: 包含匹配实体、文档块、图节点和边。
        """
        doc_ids = document_ids or []

        # 净化实体名称
        clean_entities = [e.strip() for e in entity_names if e.strip()]

        logger.info(
            "Retrieving: query='%.50s...', entities=%s, docs=%s, top_k=%d, max_hops=%d",
            query, clean_entities, doc_ids, top_k, max_hops,
        )

        try:
            result = self.graph.retrieve_context(
                query=query,
                entity_names=clean_entities,
                knowledge_base_id=knowledge_base_id,
                document_ids=doc_ids,
                top_k=top_k,
                max_hops=max_hops,
            )
            logger.info(
                "Retrieval result: %d entities, %d chunks, %d nodes, %d edges",
                len(result.matched_entities),
                len(result.chunks),
                len(result.nodes),
                len(result.edges),
            )
            return result

        except ServiceError:
            raise
        except ConnectionError as e:
            raise ServiceError(
                code=GRAPHDB_UNAVAILABLE,
                message="知识图谱数据库连接失败，请检查 GraphDB 服务是否启动",
                retryable=True,
                details={"error": str(e)},
            ) from e
        except Exception as e:
            raise ServiceError(
                code=GRAPH_QUERY_FAILED,
                message="知识图谱查询失败",
                retryable=True,
                details={"error": str(e)},
            ) from e

    def get_subgraph(
        self,
        knowledge_base_id: str,
        entity_ids: list[str],
        max_hops: int = 2,
    ) -> RetrievalResult:
        """获取指定实体的子图。"""
        try:
            return self.graph.get_subgraph(
                knowledge_base_id=knowledge_base_id,
                entity_ids=entity_ids,
                max_hops=max_hops,
            )
        except ServiceError:
            raise
        except Exception as e:
            raise ServiceError(
                code=GRAPH_QUERY_FAILED,
                message="子图查询失败",
                retryable=True,
                details={"error": str(e)},
            ) from e

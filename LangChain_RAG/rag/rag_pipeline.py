"""RAG 主流程编排器 —— 整合所有模块。

完整的文档上传和问答流水线：
- upload: 文档处理 → 实体抽取 → 写入 GraphDB
- ask: 意图识别 → 查询改写 → 实体抽取 → 检索 → 重排 → 答案生成
"""

import logging
import re
import uuid
from datetime import date

from contracts.errors import (
    DOCUMENT_PARSE_FAILED,
    ENTITY_EXTRACTION_FAILED,
    GRAPH_WRITE_FAILED,
    ServiceError,
)
from contracts.graph_repository import GraphRepository
from contracts.models import (
    ChunkRecord,
    DocumentGraphPayload,
    DocumentSummary,
    EntityRecord,
    GraphEdge,
    GraphNode,
    IntentType,
    QueryRequest,
    QueryResponse,
    RelationRecord,
    RetrievedChunk,
    SourceReference,
)
from rag.document_processor import DocumentProcessor
from rag.entity_extractor import EntityExtractor
from rag.intent_router import IntentRouter
from rag.llm_client import LLMClient
from rag.prompt_builder import (
    build_answer_prompt,
    build_normal_chat_prompt,
)
from rag.query_rewriter import QueryRewriter
from rag.reranker import Reranker
from rag.retriever import Retriever
from rag.session_store import SessionStore

logger = logging.getLogger("rag.pipeline")


class RAGPipeline:
    """RAG 主流程编排器 —— 整合文档处理和问答的所有步骤。"""

    def __init__(
        self,
        document_processor: DocumentProcessor,
        entity_extractor: EntityExtractor,
        intent_router: IntentRouter,
        query_rewriter: QueryRewriter,
        retriever: Retriever,
        reranker: Reranker,
        llm_client: LLMClient,
        session_store: SessionStore,
        graph_repository: GraphRepository,
    ):
        self.document_processor = document_processor
        self.entity_extractor = entity_extractor
        self.intent_router = intent_router
        self.query_rewriter = query_rewriter
        self.retriever = retriever
        self.reranker = reranker
        self.llm = llm_client
        self.session_store = session_store
        self.graph = graph_repository

    # ══════════════════════════════════════════════════════════
    # 文档上传流水线
    # ══════════════════════════════════════════════════════════

    def process_document(
        self,
        file_path: str,
        knowledge_base_id: str,
        skip_entity_extraction: bool = False,
    ) -> DocumentSummary:
        """完整的文档上传流水线。

        Steps:
        1. 文档处理 → DocumentSummary + ChunkRecords
        2. [可选] 实体关系抽取（可跳过以加速）
        3. 组装 DocumentGraphPayload
        4. 调用 GraphDB 写入
        5. 返回 DocumentSummary
        """
        trace_id = str(uuid.uuid4())[:8]
        logger.info("[%s] Processing document: %s", trace_id, file_path)

        # Step 1: 文档处理
        try:
            doc_summary, chunks = self.document_processor.process(
                file_path=file_path,
                knowledge_base_id=knowledge_base_id,
            )
        except ServiceError:
            raise
        except Exception as e:
            raise ServiceError(
                code=DOCUMENT_PARSE_FAILED,
                message=f"文档处理失败: {e}",
                details={"file_path": file_path},
            ) from e

        logger.info("[%s] Document parsed: %s, %d chunks", trace_id, doc_summary.filename, len(chunks))

        # Step 2: 实体关系抽取（可跳过，提速 10×+）
        entities: list[EntityRecord] = []
        relations: list[RelationRecord] = []
        if not skip_entity_extraction:
            try:
                entities, relations = self.entity_extractor.extract(chunks)
            except ServiceError:
                logger.warning("[%s] Entity extraction failed, continuing with empty entities", trace_id)
            except Exception as e:
                logger.warning("[%s] Entity extraction error: %s", trace_id, e)
        else:
            logger.info("[%s] Entity extraction skipped (skip_entity_extraction=true)", trace_id)

        logger.info("[%s] Extracted: %d entities, %d relations", trace_id, len(entities), len(relations))

        # Step 3: 组装 payload
        doc_summary.entity_count = len(entities)
        payload = DocumentGraphPayload(
            schema_version="1.0",
            knowledge_base_id=knowledge_base_id,
            document=doc_summary,
            chunks=chunks,
            entities=entities,
            relations=relations,
        )

        # Step 4: 写入 GraphDB
        try:
            result = self.graph.upsert_document_graph(payload)
            logger.info("[%s] Document saved to GraphDB: %s", trace_id, result.document_id)
            return result
        except ServiceError:
            raise
        except Exception as e:
            raise ServiceError(
                code=GRAPH_WRITE_FAILED,
                message=f"写入知识图谱失败: {e}",
                retryable=True,
                details={"document_id": doc_summary.document_id},
            ) from e

    # ══════════════════════════════════════════════════════════
    # 问答流水线
    # ══════════════════════════════════════════════════════════

    def answer_query(self, request: QueryRequest) -> QueryResponse:
        """完整的问答流水线。

        Steps:
        1. 保存用户消息
        2. 意图识别
        3. 普通聊天 → 直接 LLM 回复
        4. 查询改写
        5. 查询实体抽取
        6. GraphDB 检索
        7. 重排
        8. 组装 Prompt → LLM 生成答案
        9. 保存助手回复
        10. 构建 QueryResponse
        """
        trace_id = request.trace_id or str(uuid.uuid4())[:8]
        logger.info("[%s] Answering query: %.80s...", trace_id, request.query)

        # Step 1: 保存用户消息
        self.session_store.add_message(request.session_id, "user", request.query)

        # Step 2: 意图识别
        intent = self._detect_intent(request.query, trace_id)

        # Step 3: 普通聊天（快速路径，无需检索）
        if intent == IntentType.NORMAL_CHAT:
            return self._handle_normal_chat(request, trace_id)

        # Step 4: 查询改写
        rewritten_query = request.query
        if request.enable_query_rewrite:
            rewritten_query = self._rewrite_query(request.query, request.session_id, trace_id)

        # Step 5: 查询实体抽取
        entity_names = self._extract_query_entities(rewritten_query, intent, trace_id)

        # Step 6: 检索
        retrieval_result = self._retrieve(
            rewritten_query=rewritten_query,
            entity_names=entity_names,
            request=request,
            trace_id=trace_id,
        )

        # Step 7: 重排
        reranked_chunks = self._rerank_chunks(rewritten_query, retrieval_result.chunks, trace_id)
        sources = self._build_sources(reranked_chunks)

        # Step 8: 答案生成
        answer = self._generate_answer(
            query=request.query,
            rewritten_query=rewritten_query,
            chunks=reranked_chunks,
            graph_nodes=retrieval_result.nodes,
            graph_edges=retrieval_result.edges,
            intent=intent,
            sources=sources,
            trace_id=trace_id,
        )

        # Step 9: 保存助手回复
        self.session_store.add_message(request.session_id, "assistant", answer)
        cited_sources = self._filter_cited_sources(answer, sources)

        # Step 10: 构建响应
        logger.info(
            "[%s] Response ready: intent=%s, sources=%d, graph_nodes=%d, answer_length=%d",
            trace_id, intent.value, len(cited_sources), len(retrieval_result.nodes), len(answer),
        )

        return QueryResponse(
            answer=answer,
            intent=intent,
            original_query=request.query,
            rewritten_query=rewritten_query,
            sources=sources,
            graph_nodes=retrieval_result.nodes,
            graph_edges=retrieval_result.edges,
            graph_paths=retrieval_result.paths,
            session_id=request.session_id,
            trace_id=trace_id,
        )

    def answer_query_stream(self, request: QueryRequest):
        """流式问答：检索流程完成后，将 LLM 生成结果逐段返回。"""
        trace_id = request.trace_id or str(uuid.uuid4())[:8]
        logger.info("[%s] Streaming query: %.80s...", trace_id, request.query)

        self.session_store.add_message(request.session_id, "user", request.query)
        intent = self._detect_intent(request.query, trace_id)

        if intent == IntentType.NORMAL_CHAT:
            history = self.session_store.get_history(request.session_id, max_messages=6)
            messages = build_normal_chat_prompt(request.query, history)
            collected: list[str] = []
            try:
                for delta in self.llm.chat_stream(messages):
                    collected.append(delta)
                    yield delta
            except Exception as e:
                logger.error("[%s] Normal chat stream failed: %s", trace_id, e)
                fallback = "抱歉，我暂时无法回复，请稍后再试。"
                collected.append(fallback)
                yield fallback
            self.session_store.add_message(request.session_id, "assistant", "".join(collected))
            yield {"type": "sources", "sources": []}
            return

        rewritten_query = request.query
        if request.enable_query_rewrite:
            rewritten_query = self._rewrite_query(request.query, request.session_id, trace_id)

        entity_names = self._extract_query_entities(rewritten_query, intent, trace_id)
        retrieval_result = self._retrieve(
            rewritten_query=rewritten_query,
            entity_names=entity_names,
            request=request,
            trace_id=trace_id,
        )
        reranked_chunks = self._rerank_chunks(rewritten_query, retrieval_result.chunks, trace_id)
        sources = self._build_sources(reranked_chunks)
        messages = build_answer_prompt(
            query=request.query,
            rewritten_query=rewritten_query,
            chunks=reranked_chunks,
            graph_nodes=retrieval_result.nodes,
            graph_edges=retrieval_result.edges,
            intent=intent,
            sources=sources,
        )

        collected: list[str] = []
        try:
            for delta in self.llm.chat_stream(messages, temperature=0.3):
                collected.append(delta)
                yield delta
        except Exception as e:
            logger.error("[%s] Answer stream failed: %s", trace_id, e)
            fallback = "抱歉，我在生成回答时遇到了问题，请稍后再试。"
            collected.append(fallback)
            yield fallback

        answer = "".join(collected)
        self.session_store.add_message(request.session_id, "assistant", answer)
        cited_sources = self._filter_cited_sources(answer, sources)
        yield {
            "type": "sources",
            "sources": [
                source.model_dump() if hasattr(source, "model_dump") else source.dict()
                for source in cited_sources
            ],
        }

    # ── 子步骤（每步有独立错误处理）─────────────────────────

    def _detect_intent(self, query: str, trace_id: str) -> IntentType:
        try:
            return self.intent_router.detect(query)
        except Exception as e:
            logger.warning("[%s] Intent detection failed: %s, fallback to DOCUMENT_SEARCH", trace_id, e)
            return IntentType.DOCUMENT_SEARCH

    def _handle_normal_chat(
        self,
        request: QueryRequest,
        trace_id: str,
    ) -> QueryResponse:
        """处理普通对话意图。"""
        history = self.session_store.get_history(request.session_id, max_messages=6)
        messages = build_normal_chat_prompt(request.query, history)

        try:
            answer = self.llm.chat(messages)
        except Exception as e:
            logger.error("[%s] Normal chat LLM failed: %s", trace_id, e)
            answer = "抱歉，我暂时无法回复，请稍后再试。"

        self.session_store.add_message(request.session_id, "assistant", answer)

        return QueryResponse(
            answer=answer,
            intent=IntentType.NORMAL_CHAT,
            original_query=request.query,
            rewritten_query=request.query,
            sources=[],
            graph_nodes=[],
            graph_edges=[],
            graph_paths=[],
            session_id=request.session_id,
            trace_id=trace_id,
        )

    def _rewrite_query(self, query: str, session_id: str, trace_id: str) -> str:
        try:
            return self.query_rewriter.rewrite(query, session_id)
        except Exception as e:
            logger.warning("[%s] Query rewrite failed: %s, using original", trace_id, e)
            return query

    def _extract_query_entities(
        self,
        query: str,
        intent: IntentType,
        trace_id: str,
    ) -> list[str]:
        """从查询中抽取实体名称。

        对所有搜索类意图（DOCUMENT_SEARCH / GRAPH_QUERY）都抽取实体，
        用于 Neo4j 实体节点匹配和图谱检索，作为向量检索的补充。

        NORMAL_CHAT 跳过抽取。
        """
        if intent == IntentType.NORMAL_CHAT:
            return []

        try:
            entities = self.entity_extractor.extract_from_query(query)
            if entities:
                logger.info(
                    "[%s] Extracted %d entities from query: %s",
                    trace_id, len(entities), entities,
                )
            return entities
        except Exception as e:
            logger.warning("[%s] Query entity extraction failed: %s", trace_id, e)
            return []

    def _retrieve(
        self,
        rewritten_query: str,
        entity_names: list[str],
        request: QueryRequest,
        trace_id: str,
    ):
        """调用 Retriever 从 GraphDB 获取证据。失败时返回空结果。"""
        from contracts.models import RetrievalResult
        try:
            return self.retriever.retrieve(
                query=rewritten_query,
                entity_names=entity_names,
                knowledge_base_id=request.knowledge_base_id,
                document_ids=request.selected_document_ids,
                top_k=request.top_k,
                max_hops=request.max_hops,
            )
        except ServiceError as e:
            logger.warning("[%s] Graph retrieval failed: %s", trace_id, e)
            return RetrievalResult(rewritten_query=rewritten_query)

    def _rerank_chunks(
        self,
        query: str,
        chunks: list[RetrievedChunk],
        trace_id: str,
    ) -> list[RetrievedChunk]:
        try:
            return self.reranker.rerank(query, chunks)
        except Exception as e:
            logger.warning("[%s] Reranking failed: %s, using original order", trace_id, e)
            return chunks

    def _generate_answer(
        self,
        query: str,
        rewritten_query: str,
        chunks: list[RetrievedChunk],
        graph_nodes: list[GraphNode],
        graph_edges: list[GraphEdge],
        intent: IntentType,
        sources: list[SourceReference],
        trace_id: str,
    ) -> str:
        """调用 LLM 生成最终答案。"""
        messages = build_answer_prompt(
            query=query,
            rewritten_query=rewritten_query,
            chunks=chunks,
            graph_nodes=graph_nodes,
            graph_edges=graph_edges,
            intent=intent,
            sources=sources,
        )

        try:
            return self.llm.chat(messages, temperature=0.3)
        except Exception as e:
            logger.error("[%s] Answer generation failed: %s", trace_id, e)
            return "抱歉，我在生成回答时遇到了问题，请稍后再试。"

    @staticmethod
    def _build_sources(chunks: list[RetrievedChunk]) -> list[SourceReference]:
        """将检索到的 chunk 转换为 SourceReference 列表。"""
        sources: list[SourceReference] = []
        seen: set[tuple[str, int | None, str]] = set()
        for chunk in chunks:
            content_preview = "".join(chunk.content.split())[:160]
            key = (chunk.document_id, chunk.page_number, content_preview)
            if key in seen:
                continue
            seen.add(key)
            sources.append(SourceReference(
                document_id=chunk.document_id,
                filename=chunk.filename,
                chunk_id=chunk.chunk_id,
                page_number=chunk.page_number,
                content=RAGPipeline._clean_source_content(chunk.content)[:1200],
                score=chunk.score,
            ))
        sorted_sources = sorted(
            sources,
            key=lambda source: (
                source.filename,
                source.page_number if source.page_number is not None else 10**9,
                source.chunk_id,
            ),
        )
        for index, source in enumerate(sorted_sources, start=1):
            source.citation_index = index
        return sorted_sources

    @staticmethod
    def _filter_cited_sources(answer: str, sources: list[SourceReference]) -> list[SourceReference]:
        cited_indexes = {
            int(match)
            for match in re.findall(r"\{\{source:(\d+)\}\}", answer)
        }
        if not cited_indexes:
            return []
        return [
            source
            for source in sources
            if source.citation_index in cited_indexes
        ]

    @staticmethod
    def _clean_source_content(content: str) -> str:
        return re.sub(r"^[\s。．.，,、；;：:!！?？·•●○\-—–]+", "", content).strip()

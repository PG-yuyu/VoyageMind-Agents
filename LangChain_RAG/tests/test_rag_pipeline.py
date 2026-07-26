"""RAG Pipeline 集成测试 —— 使用 Mock 组件测试完整流程。"""

import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from contracts.models import (
    DocumentSummary,
    IntentType,
    QueryRequest,
    QueryResponse,
)
from rag.config import Settings
from rag.document_processor import DocumentProcessor
from rag.entity_extractor import EntityExtractor
from rag.intent_router import IntentRouter
from rag.llm_client import LLMClient
from rag.query_rewriter import QueryRewriter
from rag.rag_pipeline import RAGPipeline
from rag.reranker import Reranker
from rag.retriever import Retriever
from rag.backend_service_impl import RAGBackendService, _create_graph_repository
from rag.session_store import SessionStore
from tests.mocks.mock_graph_repository import MockGraphRepository


class TestRAGPipeline(unittest.TestCase):
    """RAG Pipeline 集成测试。"""

    def setUp(self):
        self.settings = Settings(
            chunk_size=300,
            chunk_overlap=50,
            rerank_top_k=10,
            llm_api_key="test-key",
            llm_base_url="https://api.test.com",
            llm_model="test-model",
        )
        self.mock_llm = MagicMock(spec=LLMClient)
        self.mock_llm.model = "test-model"

        self.graph = MockGraphRepository()
        self.session_store = SessionStore()
        self.doc_processor = DocumentProcessor(self.settings)
        self.entity_extractor = EntityExtractor(self.mock_llm)
        self.query_rewriter = QueryRewriter(self.mock_llm, self.session_store, enabled=True)
        self.intent_router = IntentRouter(self.mock_llm)
        self.retriever = Retriever(self.graph)
        self.reranker = Reranker(self.settings)

        self.pipeline = RAGPipeline(
            document_processor=self.doc_processor,
            entity_extractor=self.entity_extractor,
            intent_router=self.intent_router,
            query_rewriter=self.query_rewriter,
            retriever=self.retriever,
            reranker=self.reranker,
            llm_client=self.mock_llm,
            session_store=self.session_store,
            graph_repository=self.graph,
        )

        self.backend = RAGBackendService(
            pipeline=self.pipeline,
            graph_repository=self.graph,
        )

    def _create_tmp_txt(self, content: str) -> str:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8",
        ) as f:
            f.write(content)
            return f.name

    # ── 文档上传流程 ────────────────────────────────────────

    def test_process_document_full_flow(self):
        """测试完整的文档处理流程（Mock LLM）。"""
        self.mock_llm.chat_json.return_value = {
            "entities": [
                {"id": "entity_1", "name": "Python", "type": "Technology", "aliases": []},
            ],
            "relations": [],
        }

        content = "Python 是一种流行的编程语言，广泛应用于数据科学和人工智能领域。"
        tmp_path = self._create_tmp_txt(content)

        try:
            summary = self.pipeline.process_document(tmp_path, "kb_test")
            self.assertIsInstance(summary, DocumentSummary)
            self.assertTrue(summary.document_id.startswith("doc_"))
            self.assertEqual(summary.knowledge_base_id, "kb_test")

            # 验证文档已写入 Mock GraphDB
            docs = self.graph.list_documents("kb_test")
            self.assertEqual(len(docs), 1)
            self.assertEqual(docs[0].document_id, summary.document_id)
        finally:
            os.unlink(tmp_path)

    def test_process_document_no_entities(self):
        """测试 LLM 实体抽取失败时的优雅降级。"""
        from contracts.errors import ServiceError
        self.mock_llm.chat_json.side_effect = ServiceError(
            code="MODEL_CALL_FAILED", message="Error",
        )

        content = "简单文本内容，没有明显实体。"
        tmp_path = self._create_tmp_txt(content)

        try:
            # 应该不抛异常，继续处理
            summary = self.pipeline.process_document(tmp_path, "kb_test")
            self.assertIsInstance(summary, DocumentSummary)
            self.assertEqual(summary.entity_count, 0)
        finally:
            os.unlink(tmp_path)

    # ── 问答流程 ────────────────────────────────────────────

    def test_answer_normal_chat(self):
        """测试普通聊天意图。"""
        self.mock_llm.chat.return_value = "你好！我是智能文档检索助手。"

        request = QueryRequest(
            query="你好",
            session_id="sess_001",
            knowledge_base_id="kb_test",
        )

        response = self.pipeline.answer_query(request)
        self.assertEqual(response.intent, IntentType.NORMAL_CHAT)
        self.assertIn("你好", response.answer)
        self.assertEqual(len(response.sources), 0)

    def test_answer_document_search(self):
        """测试文档搜索意图。"""
        # 先上传一个文档
        self.mock_llm.chat_json.return_value = {
            "entities": [
                {"id": "entity_1", "name": "Python", "type": "Technology", "aliases": []},
            ],
            "relations": [],
        }

        content = "Python 是一种编程语言。它由 Guido van Rossum 于 1991 年创建。"
        tmp_path = self._create_tmp_txt(content)

        try:
            self.pipeline.process_document(tmp_path, "kb_test")
        finally:
            os.unlink(tmp_path)

        # Mock LLM 用于答案生成
        self.mock_llm.chat.return_value = "根据文档，Python 是由 Guido van Rossum 于 1991 年创建的。[1]"

        request = QueryRequest(
            query="Python 是谁创建的？",
            session_id="sess_002",
            knowledge_base_id="kb_test",
        )

        response = self.pipeline.answer_query(request)
        self.assertIsInstance(response, QueryResponse)
        self.assertIn("Guido", response.answer)
        self.assertGreater(len(response.sources), 0)

    def test_answer_with_session_history(self):
        """测试多轮对话的 session 管理。"""
        self.mock_llm.chat.return_value = "测试回答"
        self.mock_llm.chat_json.return_value = {"intent": "document_search"}

        request1 = QueryRequest(
            query="第一个问题",
            session_id="sess_003",
            knowledge_base_id="kb_test",
        )
        self.pipeline.answer_query(request1)

        # 验证历史已保存
        history = self.session_store.get_history("sess_003")
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["role"], "user")
        self.assertEqual(history[0]["content"], "第一个问题")
        self.assertEqual(history[1]["role"], "assistant")

    def test_answer_empty_retrieval(self):
        """测试没有检索到任何内容时的回答。"""
        self.mock_llm.chat.return_value = "根据现有资料，未能找到相关信息。"

        request = QueryRequest(
            query="一个不存在于文档中的问题",
            session_id="sess_004",
            knowledge_base_id="kb_test",
        )

        response = self.pipeline.answer_query(request)
        self.assertIsInstance(response, QueryResponse)
        self.assertIn("未能找到", response.answer)

    # ── BackendService 接口 ─────────────────────────────────

    def test_backend_ingest_document(self):
        """测试 BackendService.ingest_document。"""
        self.mock_llm.chat_json.return_value = {"entities": [], "relations": []}

        content = "测试文档内容。"
        tmp_path = self._create_tmp_txt(content)

        try:
            summary = self.backend.ingest_document(tmp_path, "kb_test")
            self.assertIsInstance(summary, DocumentSummary)
            self.assertEqual(summary.knowledge_base_id, "kb_test")
        finally:
            os.unlink(tmp_path)

    def test_backend_list_documents(self):
        """测试 BackendService.list_documents。"""
        self.mock_llm.chat_json.return_value = {"entities": [], "relations": []}

        content = "测试文档。"
        tmp_path = self._create_tmp_txt(content)

        try:
            self.backend.ingest_document(tmp_path, "kb_test")
            docs = self.backend.list_documents("kb_test")
            self.assertEqual(len(docs), 1)
        finally:
            os.unlink(tmp_path)

    def test_backend_delete_document(self):
        """测试 BackendService.delete_document。"""
        self.mock_llm.chat_json.return_value = {"entities": [], "relations": []}

        content = "测试文档。"
        tmp_path = self._create_tmp_txt(content)

        try:
            summary = self.backend.ingest_document(tmp_path, "kb_test")
            result = self.backend.delete_document("kb_test", summary.document_id)
            self.assertTrue(result)
            docs = self.backend.list_documents("kb_test")
            self.assertEqual(len(docs), 0)
        finally:
            os.unlink(tmp_path)

    def test_backend_clear_session(self):
        """测试 BackendService.clear_session。"""
        self.session_store.add_message("sess_test", "user", "hello")
        result = self.backend.clear_session("sess_test")
        self.assertTrue(result)
        history = self.session_store.get_history("sess_test")
        self.assertEqual(len(history), 0)

    def test_backend_health_check(self):
        """测试 BackendService.health_check。"""
        result = self.backend.health_check()
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["graphdb"], "ready")

    def test_backend_empty_query(self):
        """测试空查询被优雅处理为普通聊天。"""
        self.mock_llm.chat.return_value = "你好！我是智能文档检索助手。"
        response = self.backend.answer(QueryRequest(
            query="",
            session_id="sess",
            knowledge_base_id="kb",
        ))
        # 空查询被归类为 NORMAL_CHAT 并返回消息
        self.assertIsNotNone(response.answer)


class TestIntentRouterHeuristics(unittest.TestCase):
    """意图识别规则预检测试（不需要 Mock LLM）。"""

    def setUp(self):
        self.router = IntentRouter(MagicMock(spec=LLMClient))

    def test_greeting_heuristic(self):
        """测试问候语规则。"""
        self.assertEqual(
            self.router._heuristic_check("你好"),
            IntentType.NORMAL_CHAT,
        )
        self.assertEqual(
            self.router._heuristic_check("谢谢"),
            IntentType.NORMAL_CHAT,
        )

    def test_short_input_heuristic(self):
        """测试短输入规则。"""
        self.assertEqual(
            self.router._heuristic_check("嗯"),
            IntentType.NORMAL_CHAT,
        )

    def test_relation_keyword_heuristic(self):
        """测试关系关键词规则。"""
        self.assertEqual(
            self.router._heuristic_check("人工智能和机器学习有什么关系"),
            IntentType.GRAPH_QUERY,
        )

    def test_entity_relation_pattern_heuristic(self):
        """测试实体关系模式规则。"""
        self.assertEqual(
            self.router._heuristic_check("深度学习属于机器学习的哪种类型"),
            IntentType.GRAPH_QUERY,
        )

    def test_no_heuristic_match(self):
        """测试无规则匹配时返回 None。"""
        self.assertIsNone(
            self.router._heuristic_check("请解释一下深度学习的基本原理"),
        )


class TestReranker(unittest.TestCase):
    """重排器测试。"""

    def setUp(self):
        self.reranker = Reranker(Settings(rerank_top_k=2))

    def test_rerank_basic(self):
        """测试基本重排。"""
        from contracts.models import RetrievedChunk

        chunks = [
            RetrievedChunk(chunk_id="c1", document_id="d1", filename="f1.pdf", content="深度学习是机器学习的分支", page_number=1, score=0.5),
            RetrievedChunk(chunk_id="c2", document_id="d1", filename="f1.pdf", content="今天天气不错", page_number=1, score=0.5),
            RetrievedChunk(chunk_id="c3", document_id="d1", filename="f1.pdf", content="机器学习是AI的核心", page_number=1, score=0.5),
        ]

        result = self.reranker.rerank("深度学习", chunks)
        self.assertLessEqual(len(result), 2)
        # 第一个分块（包含关键词）应该排在前面
        self.assertEqual(result[0].chunk_id, "c1")

    def test_rerank_empty(self):
        """测试空列表重排。"""
        result = self.reranker.rerank("query", [])
        self.assertEqual(len(result), 0)

    def test_rerank_fewer_than_top_k(self):
        """测试候选少于 top_k 时全部返回。"""
        from contracts.models import RetrievedChunk
        chunks = [RetrievedChunk(chunk_id="c1", document_id="d1", filename="f1.pdf", content="test", page_number=1, score=0.5)]
        result = self.reranker.rerank("test query", chunks)
        self.assertEqual(len(result), 1)


if __name__ == "__main__":
    unittest.main()

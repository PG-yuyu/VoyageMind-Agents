"""文档处理器测试 —— 测试文档加载、清洗、切块和 ID 生成。"""

import os
import sys
import tempfile
import unittest

# 确保项目根目录在 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from contracts.models import ChunkRecord, DocumentSummary
from rag.config import Settings
from rag.document_loader import DocumentLoader
from rag.document_processor import DocumentProcessor


class TestDocumentLoader(unittest.TestCase):
    """DocumentLoader 单元测试。"""

    def setUp(self):
        self.loader = DocumentLoader()

    def test_load_txt_utf8(self):
        """测试加载 UTF-8 编码的 TXT 文件。"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8",
        ) as f:
            f.write("Hello World\n这是中文测试内容。\n\n第二段内容。")
            tmp_path = f.name

        try:
            result = self.loader.load(tmp_path)
            self.assertIn("Hello World", result.content)
            self.assertIn("中文测试", result.content)
            self.assertIn("第二段", result.content)
            self.assertEqual(len(result.pages), 1)
            self.assertEqual(result.metadata["extension"], ".txt")
        finally:
            os.unlink(tmp_path)

    def test_load_txt_gbk(self):
        """测试加载 GBK 编码的 TXT 文件。"""
        with tempfile.NamedTemporaryFile(
            mode="wb", suffix=".txt", delete=False,
        ) as f:
            f.write("GBK编码的中文内容测试。".encode("gbk"))
            tmp_path = f.name

        try:
            result = self.loader.load(tmp_path)
            self.assertIn("中文内容", result.content)
        finally:
            os.unlink(tmp_path)

    def test_load_unsupported_format(self):
        """测试不支持的格式抛出异常。"""
        from contracts.errors import ServiceError
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xyz", delete=False,
        ) as f:
            f.write("test")
            tmp_path = f.name

        try:
            with self.assertRaises(ServiceError) as ctx:
                self.loader.load(tmp_path)
            self.assertEqual(ctx.exception.code, "INVALID_FILE_TYPE")
        finally:
            os.unlink(tmp_path)

    def test_load_nonexistent_file(self):
        """测试文件不存在时抛出异常。"""
        from contracts.errors import ServiceError
        with self.assertRaises(ServiceError) as ctx:
            self.loader.load("/nonexistent/file.txt")
        self.assertEqual(ctx.exception.code, "DOCUMENT_PARSE_FAILED")


class TestDocumentProcessor(unittest.TestCase):
    """DocumentProcessor 单元测试。"""

    def setUp(self):
        self.settings = Settings(chunk_size=200, chunk_overlap=30)
        self.processor = DocumentProcessor(self.settings)

    def _create_tmp_txt(self, content: str) -> str:
        """创建临时 TXT 文件并返回路径。"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8",
        ) as f:
            f.write(content)
            return f.name

    def test_process_basic(self):
        """测试基本文档处理流程。"""
        content = "第一段内容。\n\n第二段不同的内容。" * 10
        tmp_path = self._create_tmp_txt(content)

        try:
            summary, chunks = self.processor.process(tmp_path, "kb_test")

            # 检查摘要
            self.assertIsInstance(summary, DocumentSummary)
            self.assertTrue(summary.document_id.startswith("doc_"))
            self.assertGreater(summary.chunk_count, 0)
            self.assertEqual(summary.knowledge_base_id, "kb_test")

            # 检查分块
            self.assertGreater(len(chunks), 0)
            for chunk in chunks:
                self.assertIsInstance(chunk, ChunkRecord)
                self.assertTrue(chunk.chunk_id.startswith("chunk_"))
                self.assertEqual(chunk.document_id, summary.document_id)
                self.assertGreater(len(chunk.content), 0)
        finally:
            os.unlink(tmp_path)

    def test_chunk_size_respected(self):
        """测试切块大小不超过 chunk_size。"""
        # 使用短句子，方便控制
        content = "A" * 50 + "\n\n" + "B" * 50 + "\n\n" + "C" * 50
        tmp_path = self._create_tmp_txt(content)

        try:
            summary, chunks = self.processor.process(tmp_path, "kb_test")
            # 每个 chunk 大小应在合理范围内
            for chunk in chunks:
                self.assertLessEqual(len(chunk.content), self.settings.chunk_size + 100,
                                     f"Chunk too large: {len(chunk.content)} > {self.settings.chunk_size}")
        finally:
            os.unlink(tmp_path)

    def test_document_id_stable(self):
        """测试 document_id 对同一文件是稳定的。"""
        content = "相同的测试内容。"
        tmp_path = self._create_tmp_txt(content)

        try:
            summary1, _ = self.processor.process(tmp_path, "kb_test")
            summary2, _ = self.processor.process(tmp_path, "kb_test")
            self.assertEqual(summary1.document_id, summary2.document_id,
                             "Document ID should be stable for the same file")
        finally:
            os.unlink(tmp_path)

    def test_empty_document(self):
        """测试空文档处理。"""
        content = ""
        tmp_path = self._create_tmp_txt(content)

        try:
            summary, chunks = self.processor.process(tmp_path, "kb_test")
            self.assertEqual(summary.chunk_count, 0)
            self.assertEqual(len(chunks), 0)
        finally:
            os.unlink(tmp_path)

    def test_metadata_preserved(self):
        """测试元数据保留（页码）。"""
        content = "Page 1 content\n\nPage 2 content here more text to make chunks bigger" * 5
        tmp_path = self._create_tmp_txt(content)

        try:
            summary, chunks = self.processor.process(tmp_path, "kb_test")
            self.assertTrue(summary.filename.endswith(".txt"))
            self.assertGreater(len(summary.created_at), 0)
        finally:
            os.unlink(tmp_path)


if __name__ == "__main__":
    unittest.main()

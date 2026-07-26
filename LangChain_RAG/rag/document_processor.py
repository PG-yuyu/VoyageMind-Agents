"""文档处理器 —— 文本清洗、固定大小切块、ID 生成。

切块策略：固定大小 + 重叠，段落边界感知。
ID 生成：SHA256 哈希取前 12 位，前缀标识类型。
"""

import hashlib
import logging
import re
import unicodedata
from datetime import date

from contracts.models import ChunkRecord, DocumentSummary
from rag.config import Settings, get_settings
from rag.document_loader import DocumentLoader, compute_file_hash

logger = logging.getLogger("rag.document_processor")


class DocumentProcessor:
    """文档处理：加载 → 清洗 → 切块 → 生成 ID。"""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.chunk_size = self.settings.chunk_size
        self.chunk_overlap = self.settings.chunk_overlap
        self.loader = DocumentLoader()

        # 用于 ID 生成时缓存
        self._document_id: str = ""

    # ── 主入口 ──────────────────────────────────────────────

    def process(
        self,
        file_path: str,
        knowledge_base_id: str,
    ) -> tuple[DocumentSummary, list[ChunkRecord]]:
        """处理文档：读取 → 清洗 → 切块 → 生成摘要和分块列表。

        Args:
            file_path: 文档文件路径。
            knowledge_base_id: 知识库标识。

        Returns:
            (DocumentSummary, list[ChunkRecord])
        """
        # 1. 加载文档
        load_result = self.loader.load(file_path)
        filename = load_result.metadata.get("filename", "")

        # 2. 清洗文本
        cleaned_content, cleaned_pages = self._clean(load_result)

        # 3. 生成 document_id
        file_hash = compute_file_hash(file_path)[:12]
        self._document_id = f"doc_{file_hash}"

        # 4. 切块
        chunks = self._chunk_text(cleaned_content, cleaned_pages, self._document_id)

        # 5. 构建摘要
        summary = DocumentSummary(
            document_id=self._document_id,
            filename=filename,
            knowledge_base_id=knowledge_base_id,
            chunk_count=len(chunks),
            entity_count=0,  # 实体数量在抽取后更新
            created_at=date.today().isoformat(),
        )

        logger.info(
            "Document processed: %s → %d chunks (chunk_size=%d, overlap=%d)",
            filename, len(chunks), self.chunk_size, self.chunk_overlap,
        )
        return summary, chunks

    # ── 文本清洗 ────────────────────────────────────────────

    def _clean(self, load_result) -> tuple[str, list]:
        """清洗文本：去空行、规范化 Unicode、清理无效字符。"""
        from rag.document_loader import PageInfo

        cleaned_pages: list[PageInfo] = []
        full_text_parts: list[str] = []

        for page in load_result.pages:
            text = page.text

            # 去除 null 字节
            text = text.replace("\x00", "")

            # Unicode 规范化 (NFKC)
            text = unicodedata.normalize("NFKC", text)

            # 合并多个空白字符
            text = re.sub(r"[ \t]+", " ", text)

            # 合并 3 个以上连续换行为 2 个
            text = re.sub(r"\n{3,}", "\n\n", text)

            # 去除行首行尾空白
            text = text.strip()

            if len(text) >= 20:  # 过滤接近空白的页
                cleaned_pages.append(PageInfo(page_number=page.page_number, text=text))
                full_text_parts.append(text)

        content = "\n\n".join(full_text_parts)
        return content, cleaned_pages

    # ── 文本切块 ────────────────────────────────────────────

    def _chunk_text(
        self,
        text: str,
        pages: list,
        document_id: str,
    ) -> list[ChunkRecord]:
        """固定大小切块，先按段落边界分割，再合并到目标大小。

        每个 chunk 保留：
        - 来源页码
        - 原标题（如有 markdown heading）
        """
        if not text.strip():
            return []

        page_chunks = self._chunk_pages(pages, document_id)
        if page_chunks:
            return page_chunks

        # 1. 先按段落分割
        paragraphs = text.split("\n\n")
        chunks: list[ChunkRecord] = []
        current_chunk: list[str] = []
        current_len = 0
        chunk_index = 0

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            para_len = len(para)

            # 如果当前 chunk 加上这个段落会超出大小，先保存当前 chunk
            if current_len + para_len > self.chunk_size and current_chunk:
                chunk_text = "\n\n".join(current_chunk)
                chunk_index += 1
                chunks.append(self._make_chunk_record(
                    text=chunk_text,
                    document_id=document_id,
                    chunk_index=chunk_index,
                    pages=pages,
                ))

                # 重叠：保留最后一个段落作为下一个 chunk 的开头
                if self.chunk_overlap > 0 and len(current_chunk) >= 1:
                    overlap_para = current_chunk[-1]
                    current_chunk = [overlap_para]
                    current_len = len(overlap_para)
                else:
                    current_chunk = []
                    current_len = 0

            current_chunk.append(para)
            current_len += para_len

        # 2. 处理剩余内容
        if current_chunk:
            chunk_text = "\n\n".join(current_chunk)
            chunk_index += 1
            chunks.append(self._make_chunk_record(
                text=chunk_text,
                document_id=document_id,
                chunk_index=chunk_index,
                pages=pages,
            ))

        # 3. 如果文本很短没有被段落分割命中，直接固定大小切
        if not chunks and len(text) > 0:
            for i in range(0, len(text), self.chunk_size - self.chunk_overlap):
                chunk_text = text[i:i + self.chunk_size].strip()
                if not chunk_text:
                    break
                chunk_index += 1
                chunks.append(self._make_chunk_record(
                    text=chunk_text,
                    document_id=document_id,
                    chunk_index=chunk_index,
                    pages=pages,
                ))

        return chunks

    def _chunk_pages(
        self,
        pages: list,
        document_id: str,
    ) -> list[ChunkRecord]:
        """按页切块，避免一个 chunk 跨页后导致来源页码错位。"""
        chunks: list[ChunkRecord] = []
        chunk_index = 0

        for page in pages:
            page_text = page.text.strip()
            if not page_text:
                continue

            paragraphs = page_text.split("\n\n")
            current_chunk: list[str] = []
            current_len = 0

            for para in paragraphs:
                para = para.strip()
                if not para:
                    continue

                para_len = len(para)
                if current_len + para_len > self.chunk_size and current_chunk:
                    chunk_index += 1
                    chunks.append(self._make_chunk_record(
                        text="\n\n".join(current_chunk),
                        document_id=document_id,
                        chunk_index=chunk_index,
                        pages=pages,
                        page_number=page.page_number,
                    ))

                    if self.chunk_overlap > 0 and current_chunk:
                        overlap_para = current_chunk[-1]
                        current_chunk = [overlap_para]
                        current_len = len(overlap_para)
                    else:
                        current_chunk = []
                        current_len = 0

                current_chunk.append(para)
                current_len += para_len

            if current_chunk:
                chunk_index += 1
                chunks.append(self._make_chunk_record(
                    text="\n\n".join(current_chunk),
                    document_id=document_id,
                    chunk_index=chunk_index,
                    pages=pages,
                    page_number=page.page_number,
                ))

        return chunks

    def _make_chunk_record(
        self,
        text: str,
        document_id: str,
        chunk_index: int,
        pages: list,
        page_number: int | None = None,
    ) -> ChunkRecord:
        """构建单个 ChunkRecord，推断页码和标题。"""
        chunk_id = self._generate_chunk_id(document_id, chunk_index, text)

        page_number = page_number or self._find_page_number(text, pages)
        title = self._extract_title(text)

        return ChunkRecord(
            chunk_id=chunk_id,
            document_id=document_id,
            content=text,
            page_number=page_number,
            title=title,
        )

    # ── ID 生成 ─────────────────────────────────────────────

    @staticmethod
    def _generate_chunk_id(document_id: str, chunk_index: int, content: str) -> str:
        """基于文档 ID、序号和内容前 50 字符生成稳定的 chunk_id。"""
        raw = f"{document_id}:{chunk_index}:{content[:50]}"
        hash_suffix = hashlib.sha256(raw.encode()).hexdigest()[:8]
        return f"chunk_{hash_suffix}"

    # ── 元数据推断 ──────────────────────────────────────────

    @staticmethod
    def _find_page_number(chunk_text: str, pages: list) -> int | None:
        """根据 chunk 文本内容匹配页码。简单策略：在哪个页中找到就返回哪个页码。"""
        normalized_chunk = re.sub(r"\s+", "", chunk_text)
        for page in pages:
            normalized_page = re.sub(r"\s+", "", page.text)
            if normalized_chunk[:80] in normalized_page or normalized_chunk[-80:] in normalized_page:
                return page.page_number
        return None

    @staticmethod
    def _extract_title(text: str) -> str | None:
        """从文本中提取可能的 markdown 标题作为 chunk 标题。"""
        match = re.search(r"^#{1,4}\s+(.+)$", text, re.MULTILINE)
        if match:
            return match.group(1).strip()
        return None

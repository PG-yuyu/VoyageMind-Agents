"""候选块重排 —— 融合语义分数 + 关键词匹配的混合重排。

策略（无需 LLM 调用）：
1. 保留 Chroma 的语义相似度分数（主要信号）
2. 关键词重叠率作为加分项（次要信号）
3. 最终分数 = 0.7 * chroma_score + 0.3 * keyword_overlap
4. 不丢弃任何候选块（rerank_top_k 仅用于最终给 LLM 的上限）
"""

import logging
import re
from collections import OrderedDict

from contracts.models import RetrievedChunk
from rag.config import Settings, get_settings

logger = logging.getLogger("rag.reranker")


class Reranker:
    """融合语义相似度与关键词匹配的重排器。"""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.top_k = self.settings.rerank_top_k

    def rerank(
        self,
        query: str,
        chunks: list[RetrievedChunk],
    ) -> list[RetrievedChunk]:
        """对候选块重新排序，返回 top_k 个。

        Args:
            query: 查询文本。
            chunks: 候选文档块列表。

        Returns:
            重排后的 top_k 个块。
        """
        if not chunks:
            logger.info("Reranking: no chunks to rerank")
            return []

        if len(chunks) <= self.top_k:
            logger.info("Reranking: %d chunks (≤ top_k=%d), returning as-is", len(chunks), self.top_k)
            for chunk in chunks:
                chunk.score = self._compute_score(query, chunk)
            sorted_chunks = sorted(chunks, key=lambda c: c.score, reverse=True)
            return self._keep_document_diversity(sorted_chunks, min(self.top_k, len(sorted_chunks)))

        # 计算每个 chunk 的混合分数
        for chunk in chunks:
            keyword_score = self._keyword_overlap(query, chunk.content)
            # 融合：70% 语义分数 + 30% 关键词重叠
            chunk.score = 0.7 * chunk.score + 0.3 * keyword_score

        # 按分数降序排列
        sorted_chunks = sorted(chunks, key=lambda c: c.score, reverse=True)
        top_chunks = self._keep_document_diversity(sorted_chunks, self.top_k)

        logger.info(
            "Reranking: %d → %d chunks (top score=%.3f, bottom score=%.3f)",
            len(chunks), len(top_chunks),
            top_chunks[0].score if top_chunks else 0,
            top_chunks[-1].score if top_chunks else 0,
        )
        return top_chunks

    # ── 评分算法 ────────────────────────────────────────────

    @staticmethod
    def _keep_document_diversity(
        chunks: list[RetrievedChunk],
        top_k: int,
    ) -> list[RetrievedChunk]:
        """Keep top chunks while preventing one document from monopolizing context."""
        if top_k <= 0 or len(chunks) <= 1:
            return chunks[:top_k]

        doc_groups: OrderedDict[str, list[RetrievedChunk]] = OrderedDict()
        for chunk in chunks:
            doc_groups.setdefault(chunk.document_id, []).append(chunk)

        if len(doc_groups) <= 1:
            return chunks[:top_k]

        guaranteed = max(1, top_k // len(doc_groups))
        selected: list[RetrievedChunk] = []
        selected_ids: set[str] = set()

        for doc_chunks in doc_groups.values():
            for chunk in doc_chunks[:guaranteed]:
                if chunk.chunk_id in selected_ids:
                    continue
                selected.append(chunk)
                selected_ids.add(chunk.chunk_id)
                if len(selected) >= top_k:
                    return selected

        for chunk in chunks:
            if chunk.chunk_id in selected_ids:
                continue
            selected.append(chunk)
            selected_ids.add(chunk.chunk_id)
            if len(selected) >= top_k:
                break

        return selected

    @classmethod
    def _keyword_overlap(cls, query: str, content: str) -> float:
        """计算查询与内容的关键词 Jaccard 相似度。"""
        qk = cls._tokenize(query)
        ck = cls._tokenize(content)
        if not qk:
            return 0.0
        intersection = qk & ck
        return len(intersection) / len(qk)

    @classmethod
    def _compute_score(cls, query: str, chunk: RetrievedChunk) -> float:
        """计算单个 chunk 的混合分数。"""
        keyword_score = cls._keyword_overlap(query, chunk.content)
        return 0.7 * chunk.score + 0.3 * keyword_score

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        """简单的中英文分词：提取中文 2-gram 和英文单词。"""
        tokens: set[str] = set()

        # 英文单词
        english_words = re.findall(r"[a-zA-Z]+", text.lower())
        tokens.update(w for w in english_words if len(w) >= 2)

        # 中文 2-gram（字符级）
        chinese_text = re.sub(r"[^一-鿿]", "", text)
        for i in range(len(chinese_text) - 1):
            tokens.add(chinese_text[i:i + 2])
        # 也加入单字（用于短查询）
        tokens.update(chinese_text)

        return tokens

"""问题改写 —— 基于对话历史将用户问题改写为独立完整的表述。

特性：
- 利用 SessionStore 中的对话历史
- 可禁用（enable_query_rewrite=False）
- 失败时返回原问题（不阻塞流程）
"""

import logging

from rag.llm_client import LLMClient
from rag.prompt_builder import build_query_rewrite_prompt
from rag.session_store import SessionStore

logger = logging.getLogger("rag.query_rewriter")


class QueryRewriter:
    """基于对话历史的查询改写器。"""

    def __init__(
        self,
        llm_client: LLMClient,
        session_store: SessionStore,
        enabled: bool = True,
    ):
        self.llm = llm_client
        self.session_store = session_store
        self.enabled = enabled

    def rewrite(self, query: str, session_id: str) -> str:
        """改写查询，使其独立于对话历史。

        Args:
            query: 用户原始问题。
            session_id: 会话标识，用于获取对话历史。

        Returns:
            改写后的问题，如果不需要改写或失败则返回原问题。
        """
        if not self.enabled:
            logger.debug("Query rewriting disabled")
            return query

        if not query or len(query.strip()) <= 5:
            return query

        # 获取对话历史
        history = self.session_store.get_history(session_id, max_messages=6)
        if not history:
            # 没有历史，首次提问，不需要改写
            logger.debug("No history for session %s, skipping rewrite", session_id)
            return query

        try:
            messages = build_query_rewrite_prompt(query, history)
            rewritten = self.llm.chat(messages, temperature=0.1, max_tokens=256)
            rewritten = rewritten.strip()

            # 清理可能的引号包裹
            if (rewritten.startswith('"') and rewritten.endswith('"')) or \
               (rewritten.startswith("'") and rewritten.endswith("'")):
                rewritten = rewritten[1:-1]

            if rewritten and rewritten != query:
                logger.info("Query rewritten: '%s' → '%s'", query[:50], rewritten[:50])
                return rewritten

            return query

        except Exception as e:
            logger.warning("Query rewrite failed, using original: %s", e)
            return query

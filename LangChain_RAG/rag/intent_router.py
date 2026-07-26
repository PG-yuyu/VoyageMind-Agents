"""意图识别 —— 判断用户查询的意图类型。

三层策略：
1. 规则预检（快速路径，不调用 LLM）
2. LLM 分类（主要路径）
3. 安全回退（DOCUMENT_SEARCH）
"""

import logging
import re

from contracts.models import IntentType
from rag.llm_client import LLMClient
from rag.prompt_builder import build_intent_detection_prompt

logger = logging.getLogger("rag.intent_router")


class IntentRouter:
    """意图识别路由器。"""

    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    def detect(self, query: str) -> IntentType:
        """判断用户查询意图。

        快速路径规则预检 → LLM 分类 → 安全回退。
        """
        if not query or not query.strip():
            return IntentType.NORMAL_CHAT

        query_stripped = query.strip()

        # ── 规则预检（快速路径）──────────────────────────────
        heuristic = self._heuristic_check(query_stripped)
        if heuristic is not None:
            logger.info("Intent (heuristic): %s for query: %.50s...", heuristic.value, query_stripped)
            return heuristic

        # ── LLM 分类 ─────────────────────────────────────────
        try:
            messages = build_intent_detection_prompt(query_stripped)
            result = self.llm.chat_json(messages, temperature=0.0)
            intent_str = result.get("intent", "document_search").lower()

            intent_map = {
                "normal_chat": IntentType.NORMAL_CHAT,
                "document_search": IntentType.DOCUMENT_SEARCH,
                "graph_query": IntentType.GRAPH_QUERY,
            }
            intent = intent_map.get(intent_str, IntentType.DOCUMENT_SEARCH)
            logger.info("Intent (LLM): %s for query: %.50s...", intent.value, query_stripped)
            return intent

        except Exception as e:
            logger.warning("Intent detection failed, fallback to DOCUMENT_SEARCH: %s", e)
            return IntentType.DOCUMENT_SEARCH

    # ── 规则预检 ────────────────────────────────────────────

    @staticmethod
    def _heuristic_check(query: str) -> IntentType | None:
        """基于规则的快速意图判断，返回 None 表示需要 LLM 分类。"""

        # 1. 短问候 / 简单对话
        greetings = {
            "你好", "hi", "hello", "嗨", "早上好", "下午好", "晚上好",
            "谢谢", "感谢", "thanks", "thank you",
            "再见", "拜拜", "bye", "goodbye",
            "你是谁", "你能做什么", "你叫什么",
            "ok", "好的", "嗯", "哦",
        }
        if query.lower().rstrip("!！。.?？") in greetings:
            return IntentType.NORMAL_CHAT

        # 2. 非常短的输入（<= 3 个字符）视为普通聊天
        if len(query) <= 3:
            return IntentType.NORMAL_CHAT

        # 3. 关系/路径关键词 → graph_query
        graph_keywords = [
            r"关系", r"联系", r"关联", r"路径", r"连接",
            r"相关", r"有关", r"之间.*关系", r"和.*什么.*关系",
        ]
        for kw in graph_keywords:
            if re.search(kw, query):
                return IntentType.GRAPH_QUERY

        # 4. 包含实体类型词 + 关系疑问词
        entity_relation_patterns = [
            r".+(是|属于).+的(一种|子|分支|类型|哪种|什么类型|哪个类别)",
            r".+包含哪些",
            r".+由谁.*(提出|发明|创建|开发)",
            r".+和.+有(什么|何).+(区别|不同|关系|联系)",
        ]
        for pat in entity_relation_patterns:
            if re.search(pat, query):
                return IntentType.GRAPH_QUERY

        # 5. 历史事件/原因/意义/教训类问题 → document_search
        content_search_patterns = [
            r".*的?意义",
            r".*的?原因",
            r".*的?教训",
            r".*的?背景",
            r".*的?影响",
            r".*的?作用",
            r".*的?目的",
            r".*的?特点",
            r".*的?特征",
            r".*的?定义",
            r".*的?概念",
            r".*什么(是|叫|为).*",
            r".*如何.*",
            r".*为什么.*",
            r".*简述.*",
            r".*概述.*",
            r".*总结.*",
            r".*介绍.*",
            r".*分析.*",
            r".*比较.*区别",
            r".*对比.*",
        ]
        for pat in content_search_patterns:
            if re.search(pat, query):
                return IntentType.DOCUMENT_SEARCH

        # 6. 没有明确命中规则，需要 LLM 判断
        return None

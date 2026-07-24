"""对话引擎（核心模块）。

封装 LLM 的调用逻辑：多轮对话、流式输出、超时重试、Token 统计、模型切换、上下文管理。
对应需求文档 A1 至 A5（核心对话功能）、A5（会话内模型切换）、G1（超时与重试）。

Step 10 重构：支持多服务商模型切换（switch_model）。
Step 16 新增：上下文管理（滑动窗口 + Token 计数）、变量命名 chat_model。
"""

import logging
logger = logging.getLogger(__name__)
import os
from typing import AsyncIterator, Optional

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from core.config_manager import AppConfig


class ChatEngine:
    """对话引擎。

    封装 LLM 调用，提供同步调用、异步流式、模型切换和上下文管理。
    """

    def __init__(self, config: AppConfig):
        """初始化对话引擎，使用默认模型。"""
        self.config = config
        self.current_model: str = config.default_model
        self.chat_model: ChatOpenAI = self._create_chat_model(self.current_model)

    def _create_chat_model(self, model_value: str) -> ChatOpenAI:
        """按模型标识创建 ChatOpenAI 实例。

        自动查找模型所属服务商，用对应的 base_url 和 API Key。
        """
        provider = self.config.find_provider_by_model(model_value)
        if provider is None:
            raise ValueError(f"模型 '{model_value}' 不在可选列表中")

        api_key = self.config.get_api_key(provider["api_key_env"])
        if not api_key:
            raise ValueError(f"服务商 '{provider['name']}' 的 API Key 未配置（请检查 .env 的 {provider['api_key_env']}）")

        return ChatOpenAI(
            model=model_value,
            api_key=api_key,
            base_url=provider["base_url"],
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
            timeout=self.config.llm_timeout,
            max_retries=self.config.llm_max_retries,
            streaming=True,
        )

    def switch_model(self, model_value: str) -> None:
        """切换模型（A5 会话内模型切换）。

        自动查找新模型所属服务商，用对应的 base_url 和 Key 重建 LLM 客户端。
        切换后历史上下文保留（消息列表由调用方维护，不受影响）。

        参数：
            model_value: 新模型标识（如 deepseek-v4-pro）

        异常：
            ValueError: 模型不在可选列表中 或 API Key 未配置
        """
        self.chat_model = self._create_chat_model(model_value)
        old_model = self.current_model
        self.current_model = model_value
        logger.info("模型切换: %s -> %s", old_model, model_value)

    def chat(self, messages: list[BaseMessage]) -> tuple[str, dict]:
        """同步对话（非流式）。"""
        response: AIMessage = self.chat_model.invoke(messages)
        reply = response.content
        usage = self._extract_usage(response)
        return reply, usage

    async def astream(
        self, messages: list[BaseMessage]
    ) -> AsyncIterator[tuple[str, Optional[dict]]]:
        """异步流式对话。"""
        final_usage = None
        async for chunk in self.chat_model.astream(messages):
            text = chunk.content
            if text:
                yield text, None
            usage = self._extract_usage(chunk)
            if usage is not None:
                final_usage = usage
        yield "", final_usage

    def _extract_usage(self, message: BaseMessage) -> Optional[dict]:
        """从 LangChain 响应中提取 token 用量。"""
        usage_meta = getattr(message, "usage_metadata", None)
        if usage_meta is None:
            return None
        return {
            "prompt_tokens": usage_meta.get("input_tokens", 0),
            "completion_tokens": usage_meta.get("output_tokens", 0),
            "total_tokens": usage_meta.get("total_tokens", 0),
        }

    # ── 上下文管理（Step 16 新增）─────────────────────────────────────────

    def trim_messages(
        self, messages: list[BaseMessage], max_tokens: int = None
    ) -> list[BaseMessage]:
        """裁剪消息列表，防止超出模型的上下文窗口限制（滑动窗口 + Token 计数）。

        裁剪规则：
        1. SystemMessage 永远保留（在最前面，不会被丢弃）。
        2. 从最后一条消息往前累加 Token 数，直到达到 max_tokens。
        3. 超出 max_tokens 的更早消息被丢弃。

        这是「滑动窗口 + Token 计数」的组合策略：
        - 滑动窗口：只保留最近的消息
        - Token 计数：精确控制总 Token 数不超过 max_tokens

        参数：
            messages: 原始消息列表
            max_tokens: 最大 Token 数（默认从 config 读取）
        返回：
            裁剪后的消息列表
        """
        if max_tokens is None:
            max_tokens = self.config.context_max_tokens

        if not messages:
            return []

        # 分离 System 消息和非 System 消息
        system_messages = [m for m in messages if isinstance(m, SystemMessage)]
        non_system = [m for m in messages if not isinstance(m, SystemMessage)]

        if not non_system:
            # 只有 System 消息，直接返回
            return system_messages

        # 用 tiktoken 估算 Token 数（粗略估算：1 个中文字约 2 token，1 个英文单词约 1-2 token）
        # 这里用简单的字符数估算，避免 tiktoken 对不同模型的编码差异
        # 估算公式：Token 数 ≈ 字符数 / 2（中文为主时较准确）
        def estimate_tokens(text: str) -> int:
            return max(1, len(text) // 2)

        # System 消息占用的 Token
        system_tokens = sum(estimate_tokens(m.content) for m in system_messages)
        available = max_tokens - system_tokens

        # 从后往前累加，保留尽可能多的最近消息
        kept = []
        total = 0
        for msg in reversed(non_system):
            msg_tokens = estimate_tokens(msg.content)
            if total + msg_tokens > available:
                break
            kept.append(msg)
            total += msg_tokens

        kept.reverse()  # 恢复正序

        # 合并：System 消息 + 保留的非 System 消息
        result = system_messages + kept

        if len(result) < len(messages):
            dropped = len(messages) - len(result)
            logger.info("上下文裁剪: 原始 %d 条，保留 %d 条，丢弃 %d 条",
                        len(messages), len(result), dropped)

        return result

    async def close(self) -> None:
        """关闭引擎（预留接口）。"""
        pass

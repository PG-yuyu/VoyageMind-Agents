"""
DeepSeek LLM 调用封装
=====================

兼容 OpenAI SDK，只需改 base_url。

用法:
    from clients.deepseek_llm import DeepSeekLLM
    llm = DeepSeekLLM(api_key="sk-xxx", model="deepseek-v4-flash")
    response = llm("你好")
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


class DeepSeekLLM:
    """DeepSeek 大模型调用封装。

    使用 OpenAI 兼容接口调用 DeepSeek API。
    默认从环境变量 DEEPSEEK_API_KEY 读取密钥，DEFAULT_MODEL 读取模型名。

    Attributes:
        model: 模型名，默认 deepseek-v4-flash
        temperature: 生成温度，默认 0.3（偏低以得到更确定的结果）
        max_tokens: 最大输出 token
    """

    BASE_URL = "https://api.deepseek.com/v1"

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "deepseek-v4-flash",
        temperature: float = 0.3,
        max_tokens: int = 8192,
    ):
        """
        Args:
            api_key: DeepSeek API Key。不传则从 DEEPSEEK_API_KEY 环境变量读取。
            model: 模型名，默认 deepseek-v4-flash。
            temperature: 生成温度 (0-1)，越低越确定
            max_tokens: 最大输出 token 数
        """
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

        key = api_key or os.environ.get("DEEPSEEK_API_KEY")
        if not key:
            raise ValueError(
                "未提供 DeepSeek API Key。\n"
                "  方式1: export DEEPSEEK_API_KEY=sk-xxx\n"
                "  方式2: DeepSeekLLM(api_key='sk-xxx')"
            )

        try:
            from openai import OpenAI
            self._client = OpenAI(api_key=key, base_url=self.BASE_URL)
        except ImportError:
            raise ImportError("需要安装 openai: pip install openai")

    def __call__(self, prompt: str) -> str:
        """调用 DeepSeek 生成回复。

        Args:
            prompt: 输入提示词

        Returns:
            str: 模型生成的文本（已去除可能的 markdown 代码块包裹）
        """
        try:
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
            content = resp.choices[0].message.content or ""
            finish_reason = resp.choices[0].finish_reason or ""
            logger.info(
                "DeepSeek 调用成功: model=%s, input=%d chars, output=%d chars, finish=%s",
                self.model, len(prompt), len(content), finish_reason,
            )
            if not content:
                logger.warning(
                    "DeepSeek 返回空内容! finish_reason=%s, model=%s, prompt_head=%s",
                    finish_reason, self.model, prompt[:200],
                )
            return content

        except Exception as exc:
            logger.error("DeepSeek 调用失败: %s (model=%s, prompt_len=%d)",
                         exc, self.model, len(prompt))
            raise

    def chat(
        self,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> str:
        """多轮对话接口。

        Args:
            messages: [{"role": "user"/"assistant"/"system", "content": "..."}]
            **kwargs: 其他参数（temperature, max_tokens 等）

        Returns:
            str: 模型回复文本
        """
        resp = self._client.chat.completions.create(
            model=kwargs.get("model", self.model),
            messages=messages,
            temperature=kwargs.get("temperature", self.temperature),
            max_tokens=kwargs.get("max_tokens", self.max_tokens),
        )
        return resp.choices[0].message.content or ""

    def stream(
        self,
        prompt: str,
    ) -> str:
        """流式调用（逐步返回）。"""
        collected = []
        resp = self._client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=self.temperature,
            stream=True,
        )
        for chunk in resp:
            delta = chunk.choices[0].delta.content or ""
            collected.append(delta)
        return "".join(collected)

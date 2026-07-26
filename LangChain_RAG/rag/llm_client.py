"""LLM 调用封装 —— 支持 OpenAI 兼容 API (DeepSeek 等)。

特性：
- 自动重试（3 次，指数退避）
- 支持 JSON mode（response_format）
- 支持流式输出（chat_stream）
- 统一 ServiceError 包装
"""

import json
import logging
import time

import requests

from contracts.errors import (
    MODEL_CALL_FAILED,
    ServiceError,
)
from rag.config import Settings, get_settings

logger = logging.getLogger("rag.llm_client")


class LLMClient:
    """OpenAI 兼容 API 的统一调用客户端。"""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.api_key = self.settings.llm_api_key
        self.base_url = self.settings.llm_base_url.rstrip("/")
        self.model = self.settings.llm_model
        self.temperature = self.settings.llm_temperature
        self.max_tokens = self.settings.llm_max_tokens
        self.timeout = self.settings.llm_timeout

        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        })

    def _build_url(self) -> str:
        return f"{self.base_url}/chat/completions"

    # ── 非流式调用 ──────────────────────────────────────────

    def chat(
        self,
        messages: list[dict],
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: dict | None = None,
    ) -> str:
        """发送聊天补全请求，返回模型响应文本。

        Args:
            messages: 消息列表 [{"role": "system"|"user"|"assistant", "content": ...}]
            temperature: 覆盖默认温度
            max_tokens: 覆盖默认最大 token 数
            response_format: JSON mode {"type": "json_object"}

        Returns:
            模型返回的文本内容。

        Raises:
            ServiceError(MODEL_CALL_FAILED): 多次重试后仍失败。
        """
        body: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature if temperature is not None else self.temperature,
            "max_tokens": max_tokens if max_tokens is not None else self.max_tokens,
        }
        if response_format:
            body["response_format"] = response_format

        logger.debug("LLM request: model=%s, message_count=%d", self.model, len(messages))

        last_error: Exception | None = None
        for attempt in range(3):
            try:
                resp = self._session.post(
                    self._build_url(),
                    json=body,
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                logger.debug("LLM response: length=%d", len(content))
                return content

            except requests.exceptions.Timeout as e:
                last_error = e
                logger.warning("LLM timeout (attempt %d/3)", attempt + 1)
                time.sleep(1.0 * (attempt + 1))

            except requests.exceptions.HTTPError as e:
                status_code = e.response.status_code if e.response is not None else 0
                if status_code >= 500 and attempt < 2:
                    logger.warning("LLM server error %d (attempt %d/3)", status_code, attempt + 1)
                    time.sleep(1.0 * (attempt + 1))
                    continue
                raise ServiceError(
                    code=MODEL_CALL_FAILED,
                    message=f"LLM API 返回错误 (HTTP {status_code})",
                    retryable=status_code >= 500,
                    details={"status_code": status_code},
                ) from e

            except (requests.exceptions.ConnectionError, requests.exceptions.RequestException) as e:
                last_error = e
                logger.warning("LLM connection error (attempt %d/3): %s", attempt + 1, e)
                time.sleep(1.0 * (attempt + 1))

        raise ServiceError(
            code=MODEL_CALL_FAILED,
            message="LLM API 调用失败（已重试 3 次）",
            retryable=True,
        ) from last_error

    # ── JSON 模式调用 ──────────────────────────────────────

    def chat_json(
        self,
        messages: list[dict],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> dict:
        """调用 LLM 并解析为 JSON dict。

        Raises:
            ServiceError: LLM 调用失败或 JSON 解析失败。
        """
        raw = self.chat(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        try:
            # 去除可能的 markdown 代码块包裹
            text = raw.strip()
            if text.startswith("```"):
                # 去掉 ```json 开头和 ``` 结尾
                lines = text.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                text = "\n".join(lines)
            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.error("Failed to parse LLM JSON response: %s", raw[:200])
            raise ServiceError(
                code=MODEL_CALL_FAILED,
                message="LLM 返回的内容无法解析为 JSON",
                details={"raw_preview": raw[:500]},
            ) from e

    # ── 流式调用 ──────────────────────────────────────────

    def chat_stream(
        self,
        messages: list[dict],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ):
        """流式聊天补全，逐块 yield 文本。

        Yields:
            str: 每次 yield 一段增量文本。
        """
        body: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature if temperature is not None else self.temperature,
            "max_tokens": max_tokens if max_tokens is not None else self.max_tokens,
            "stream": True,
        }

        try:
            resp = self._session.post(
                self._build_url(),
                json=body,
                timeout=self.timeout,
                stream=True,
            )
            resp.raise_for_status()

            for line in resp.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data: "):
                    continue
                data_str = line[len("data: "):]
                if data_str.strip() == "[DONE]":
                    break
                try:
                    data = json.loads(data_str)
                    delta = data.get("choices", [{}])[0].get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        yield content
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue

        except requests.exceptions.RequestException as e:
            raise ServiceError(
                code=MODEL_CALL_FAILED,
                message="LLM 流式调用失败",
                retryable=True,
                details={"error": str(e)},
            ) from e

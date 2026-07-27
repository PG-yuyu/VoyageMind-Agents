"""大模型 JSON 决策调用服务。"""

from __future__ import annotations

import json
from typing import Any, Protocol


class ModelDecisionError(RuntimeError):
    """大模型决策失败，需要重新调用模型。"""


class ChatCompletionLike(Protocol):
    """推荐模块需要的最小聊天模型接口。"""

    def chat(self, system_prompt: str, user_prompt: str) -> str:
        """按系统提示词和用户提示词返回模型文本。"""


class LLMJsonService:
    """调用大模型并解析严格 JSON，不提供本地规则兜底。"""

    def __init__(self, chatbot_service: ChatCompletionLike | None = None) -> None:
        """注入聊天服务；未注入时复用成员一的 ChatbotService。"""

        if chatbot_service is None:
            from backend.services.chatbot_service import ChatbotService

            chatbot_service = ChatbotService()
        self.chatbot_service = chatbot_service

    def request_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        """请求大模型输出 JSON；调用或解析失败时直接要求重试。"""

        try:
            raw_reply = self.chatbot_service.chat(system_prompt, user_prompt)
        except Exception as exc:
            raise ModelDecisionError(
                f"大模型调用失败，请检查配置后重试。原因：{exc}"
            ) from exc

        parsed = self._parse_json_object(str(raw_reply))
        if parsed is None:
            retry_prompt = (
                f"{user_prompt}\n\n"
                "上一次输出不是合法 JSON。请严格只返回一个 JSON 对象，"
                "不要 Markdown，不要解释，不要代码块。"
            )
            try:
                raw_reply = self.chatbot_service.chat(system_prompt, retry_prompt)
            except Exception as exc:
                raise ModelDecisionError(
                    f"大模型调用失败（重试），请检查配置后重试。原因：{exc}"
                ) from exc
            parsed = self._parse_json_object(str(raw_reply))
        if parsed is None:
            raise ModelDecisionError("大模型输出不是合法 JSON，请重新调用模型重试")
        return parsed

    @staticmethod
    def _parse_json_object(text: str) -> dict[str, Any] | None:
        """从模型文本中提取 JSON 对象。"""

        clean = text.strip()
        if clean.startswith("```"):
            clean = clean.strip("`")
            clean = clean.removeprefix("json").strip()
        start = clean.find("{")
        end = clean.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            value = json.loads(clean[start : end + 1])
        except json.JSONDecodeError:
            return None
        return value if isinstance(value, dict) else None


__all__ = ["LLMJsonService", "ModelDecisionError"]

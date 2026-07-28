from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


class WebSearchService:
    """Use Qwen/DashScope web search when RAG cannot cover a travel query.

    The service calls the DashScope text-generation endpoint with
    ``enable_search`` enabled. It returns both the model answer and search
    sources so the caller can pass them into the final travel-answer prompt.
    """

    DEFAULT_MODEL = "qwen-plus"
    DEFAULT_STRATEGY = "agent"

    def __init__(self) -> None:
        project_root = Path(__file__).resolve().parents[2]
        load_dotenv(project_root / ".env", override=False, encoding="utf-8-sig")

        self.api_key = (
            os.environ.get("QWEN_API_KEY")
            or os.environ.get("DASHSCOPE_API_KEY")
            or ""
        ).strip()
        self.model = os.environ.get("QWEN_SEARCH_MODEL", self.DEFAULT_MODEL).strip()
        self.strategy = os.environ.get(
            "QWEN_SEARCH_STRATEGY", self.DEFAULT_STRATEGY
        ).strip()
        self.timeout = int(os.environ.get("QWEN_SEARCH_TIMEOUT", "60") or "60")
        self.base_url = self._resolve_base_url()

    def search(self, query: str, top_k: int = 5) -> dict[str, Any]:
        clean_query = " ".join((query or "").split())
        if not clean_query:
            return self._unavailable(clean_query, top_k, "搜索问题为空。")

        if not self.api_key:
            return self._unavailable(
                clean_query,
                top_k,
                "未配置 QWEN_API_KEY 或 DASHSCOPE_API_KEY，无法调用 Qwen 联网搜索。",
            )

        payload = {
            "model": self.model,
            "input": {
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "你是天津旅行信息检索助手。请优先检索官方网站、景区公告、"
                            "权威地图或旅游平台信息，回答要简洁，并避免编造实时规则。"
                        ),
                    },
                    {"role": "user", "content": clean_query},
                ]
            },
            "parameters": {
                "result_format": "message",
                "enable_search": True,
                "incremental_output": False,
                "search_options": {
                    "search_strategy": self.strategy,
                    "enable_source": True,
                },
            },
        }

        try:
            data = self._post_streaming_json(payload)
        except Exception as exc:
            return self._unavailable(clean_query, top_k, f"Qwen 联网搜索调用失败：{exc}")

        answer = self._extract_answer(data)
        sources = self._extract_sources(data, top_k)
        return {
            "query": clean_query,
            "top_k": top_k,
            "answer": answer,
            "sources": sources,
            "available": True,
            "provider": "qwen_dashscope",
            "model": self.model,
            "search_strategy": self.strategy,
            "raw_request_id": data.get("request_id"),
        }

    def _resolve_base_url(self) -> str:
        override = os.environ.get("QWEN_SEARCH_BASE_URL", "").strip()
        if override:
            return override.rstrip("/")

        workspace_id = os.environ.get("DASHSCOPE_WORKSPACE_ID", "").strip()
        if workspace_id:
            return f"https://{workspace_id}.cn-beijing.maas.aliyuncs.com/api/v1"

        return "https://dashscope.aliyuncs.com/api/v1"

    def _post_streaming_json(self, payload: dict[str, Any]) -> dict[str, Any]:
        endpoint = f"{self.base_url}/services/aigc/text-generation/generation"
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
                "X-DashScope-SSE": "enable",
            },
            method="POST",
        )
        try:
            events: list[dict[str, Any]] = []
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                for raw_line in response:
                    line = raw_line.decode("utf-8", errors="ignore").strip()
                    if not line or line.startswith(":"):
                        continue
                    if not line.startswith("data:"):
                        continue

                    data_text = line[len("data:") :].strip()
                    if data_text == "[DONE]":
                        break
                    try:
                        event = json.loads(data_text)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(event, dict):
                        events.append(event)
            return self._merge_stream_events(events)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"HTTP {exc.code}: {body}") from exc

    def _merge_stream_events(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        if not events:
            return {"output": {"choices": [{"message": {"content": ""}}]}}

        request_id = ""
        latest_answer = ""
        answer_parts: list[str] = []
        search_results: list[dict[str, Any]] = []
        seen_sources: set[str] = set()

        for event in events:
            request_id = str(event.get("request_id") or request_id)
            answer = self._extract_answer(event)
            if answer:
                if latest_answer and answer.startswith(latest_answer):
                    latest_answer = answer
                elif latest_answer and latest_answer.startswith(answer):
                    pass
                else:
                    answer_parts.append(answer)
                    latest_answer = "".join(answer_parts)

            for source in self._raw_search_results(event):
                url = str(source.get("url") or source.get("link") or "").strip()
                key = url or str(source.get("title") or source.get("name") or "")
                if key in seen_sources:
                    continue
                seen_sources.add(key)
                search_results.append(source)

        return {
            "request_id": request_id,
            "output": {
                "choices": [{"message": {"content": latest_answer}}],
                "search_info": {"search_results": search_results},
            },
        }

    @staticmethod
    def _extract_answer(data: dict[str, Any]) -> str:
        output = data.get("output") or {}
        choices = output.get("choices") or []
        if choices:
            message = choices[0].get("message") or {}
            content = message.get("content")
            if isinstance(content, str):
                return content.strip()
            if isinstance(content, list):
                text_parts = [
                    str(item.get("text") or "")
                    for item in content
                    if isinstance(item, dict)
                ]
                return "\n".join(part for part in text_parts if part).strip()

        text = output.get("text")
        return text.strip() if isinstance(text, str) else ""

    @staticmethod
    def _extract_sources(data: dict[str, Any], top_k: int) -> list[dict[str, Any]]:
        search_results = WebSearchService._raw_search_results(data)

        sources: list[dict[str, Any]] = []
        for fallback_index, item in enumerate(search_results, start=1):
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or item.get("link") or "").strip()
            title = str(item.get("title") or item.get("name") or "联网来源").strip()
            snippet = str(
                item.get("snippet")
                or item.get("content")
                or item.get("summary")
                or ""
            ).strip()
            try:
                index = int(item.get("index") or fallback_index)
            except (TypeError, ValueError):
                index = fallback_index
            sources.append(
                {
                    "index": index,
                    "title": title,
                    "url": url,
                    "snippet": snippet,
                    "content": snippet,
                    "source_type": "web",
                }
            )
            if len(sources) >= top_k:
                break
        return sources

    @staticmethod
    def _raw_search_results(data: dict[str, Any]) -> list[dict[str, Any]]:
        output = data.get("output") or {}
        candidates = [
            (output.get("search_info") or {}).get("search_results"),
            output.get("search_results"),
            data.get("search_results"),
        ]
        for value in candidates:
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return []

    def _unavailable(self, query: str, top_k: int, note: str) -> dict[str, Any]:
        return {
            "query": query,
            "top_k": top_k,
            "answer": "",
            "sources": [],
            "available": False,
            "provider": "qwen_dashscope",
            "model": self.model,
            "search_strategy": self.strategy,
            "base_url": self.base_url,
            "note": note,
        }

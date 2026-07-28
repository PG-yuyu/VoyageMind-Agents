from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any, AsyncIterator

from backend.services.chatbot_service import ChatbotService
from backend.services.rag_service import RAGService
from backend.services.web_search_service import WebSearchService


class GuideService:
    """地图 AI 导游服务。

    第一版只依赖现有本地天津数据、RAG 适配入口和成员一封装后的 Chatbot。
    后续如果成员二/三提供更完整的地点详情和路线接口，可以在这里替换数据源。
    """

    def __init__(
        self,
        chatbot_service: ChatbotService | None = None,
        rag_service: RAGService | None = None,
        web_search_service: WebSearchService | None = None,
    ) -> None:
        self.chatbot_service = chatbot_service or ChatbotService()
        self.rag_service = rag_service or RAGService()
        self.web_search_service = web_search_service or WebSearchService()
        self._places = self._load_place_index()
        self._rag_document_ids_by_filename: dict[str, str] | None = None

    def answer(self, payload: dict[str, Any]) -> dict[str, Any]:
        target_type = payload.get("target_type") or "place"
        target = payload.get("target") or {}
        message = (payload.get("message") or "").strip()
        history = payload.get("history") or []

        context = self._build_context(target_type, target)
        is_intro = payload.get("intro") is True or message in {
            "",
            "请先用导游身份介绍这里。",
        }
        rag_query = self._build_rag_query(message, context, is_intro)
        rag_result = self._query_rag(rag_query, context)
        chat_message = message or "请先用导游身份介绍这里。"
        search_result = None
        if self._should_web_search(chat_message, rag_result):
            search_query = self._build_search_query(chat_message, context, rag_result)
            search_result = self.web_search_service.search(search_query, top_k=5)
        answer = self._format_answer(
            self._chat(chat_message, context, history, rag_result, search_result)
        )
        return {
            "answer": answer,
            "target_type": target_type,
            "target_title": context["title"],
            "context": context,
            "sources": rag_result.get("sources", []) if isinstance(rag_result, dict) else [],
            "search_sources": (search_result or {}).get("sources", []),
            "used_rag": bool(rag_result and rag_result.get("sources")),
            "used_web_search": bool(search_result and search_result.get("sources")),
        }

    async def stream_answer(self, payload: dict[str, Any]) -> AsyncIterator[str]:
        result = self.answer(payload)
        answer = result["answer"]
        for chunk in self._stream_chunks(answer):
            yield chunk
            await asyncio.sleep(0.028)

    def _build_context(self, target_type: str, target: dict[str, Any]) -> dict[str, Any]:
        if target_type == "route":
            return self._build_route_context(target)
        return self._build_place_context(target)

    def _build_place_context(self, target: dict[str, Any]) -> dict[str, Any]:
        place_id = target.get("place_id") or target.get("id")
        name = target.get("name") or ""
        local = self._places.get(place_id) or self._find_by_name(name) or {}
        merged = {**local, **target}
        coordinate = merged.get("coordinate") or {}
        longitude = merged.get("longitude") or coordinate.get("longitude")
        latitude = merged.get("latitude") or coordinate.get("latitude")
        return {
            "kind": "place",
            "title": merged.get("name") or "当前地点",
            "place_id": merged.get("place_id") or place_id,
            "place_type": merged.get("place_type") or "place",
            "city": merged.get("city") or "天津",
            "area": merged.get("area"),
            "address": merged.get("address"),
            "description": merged.get("description")
            or merged.get("short_description")
            or merged.get("recommend_reason"),
            "recommend_reason": merged.get("recommend_reason"),
            "open_time": merged.get("open_time"),
            "price": merged.get("price"),
            "tags": merged.get("tags") or [],
            "longitude": longitude,
            "latitude": latitude,
        }

    def _build_route_context(self, target: dict[str, Any]) -> dict[str, Any]:
        origin = self._places.get(target.get("origin_place_id")) or {}
        destination = self._places.get(target.get("destination_place_id")) or {}
        origin_name = origin.get("name") or target.get("origin_name") or "上一站"
        destination_name = (
            destination.get("name") or target.get("destination_name") or "下一站"
        )
        return {
            "kind": "route",
            "title": f"{origin_name} → {destination_name}",
            "origin": origin or {"place_id": target.get("origin_place_id"), "name": origin_name},
            "destination": destination
            or {"place_id": target.get("destination_place_id"), "name": destination_name},
            "travel_mode": target.get("travel_mode") or target.get("mode") or "walking",
            "distance_m": target.get("distance_m") or target.get("distance"),
            "duration_min": target.get("duration_min") or target.get("duration"),
            "source": target.get("source"),
            "verified": target.get("verified"),
        }

    def _query_rag(self, message: str, context: dict[str, Any]) -> dict[str, Any]:
        if not message:
            message = f"介绍{context['title']}"
        try:
            retrieve = getattr(self.rag_service, "retrieve_evidence", self.rag_service.query)
            return retrieve(
                question=message,
                category=context.get("place_type") or context.get("kind"),
                place_name=context.get("title"),
                top_k=12,
                selected_document_ids=self._document_ids_for_context(context),
            )
        except Exception:
            return {"sources": [], "sufficient": False}

    def _chat(
        self,
        message: str,
        context: dict[str, Any],
        history: list[dict[str, Any]],
        rag_result: dict[str, Any],
        search_result: dict[str, Any] | None = None,
    ) -> str:
        if not self.chatbot_service.available or self.chatbot_service.engine is None:
            return self._fallback_answer(message, context, rag_result, search_result)

        system = (
            "你是天津自由行系统里的 AI 导游，只讲天津旅行。"
            "你要像现场导游一样讲解当前地图上被点击的景点、餐厅、酒店或路线。"
            "回答优先级如下：1. RAG资料；2. 联网搜索结果；3. 当前地点或行程上下文；4. 通用旅行常识。"
            "如果 RAG 资料充足，必须以 RAG检索.answer 与 RAG检索.sources 中的文档片段为主要依据。"
            "如果 RAG 没覆盖用户问题，可以使用联网搜索结果补充，并说明这些信息来自联网检索。"
            "当前导游对象用于解释点击目标、坐标、路线元数据、停留时间和衔接建议。"
            "回答要具体、自然、可执行；不要伪造具体票价、开放时间或官方规则。"
            "不要伪造来源；RAG 和联网搜索都没有结果时，才使用通用旅行常识兜底。"
            "输出必须适合聊天气泡展示：不要 Markdown 粗体符号，不要表格，不要标题层级。"
            "先用一小段直接回答，再换行列出 2-4 条短要点，每条以“· ”开头。"
        )
        user_payload = {
            "用户问题": message or "请先介绍这里",
            "最近对话": history[-6:],
            "RAG资料": rag_result,
            "联网搜索结果": search_result or {},
            "地点或行程上下文": self._guide_payload_context(context),
        }
        try:
            return self.chatbot_service.chat(
                system,
                json.dumps(user_payload, ensure_ascii=False),
            )
        except Exception:
            return self._fallback_answer(message, context, rag_result, search_result)

    def _build_rag_query(
        self,
        message: str,
        context: dict[str, Any],
        is_intro: bool,
    ) -> str:
        if not is_intro and message:
            return message
        if context["kind"] == "route":
            origin = context.get("origin") or {}
            destination = context.get("destination") or {}
            origin_name = origin.get("name") or "上一站"
            destination_name = destination.get("name") or "下一站"
            return (
                f"请基于知识库文档，以天津 AI 导游身份讲解从{origin_name}到{destination_name}"
                "这段路线如何衔接，包括两端地点的行程角色、适合停留的问题和注意事项。"
            )
        return (
            f"请基于知识库文档，以天津 AI 导游身份介绍{context['title']}，"
            "包括行程角色、主要看点、预算或开放时间注意、附近衔接和适合继续追问的问题。"
        )

    def _intro_answer(self, context: dict[str, Any]) -> str:
        if context["kind"] == "route":
            return self._route_intro(context)
        return self._place_intro(context)

    def _place_intro(self, context: dict[str, Any]) -> str:
        title = context["title"]
        type_label = self._type_label(context.get("place_type"))
        description = context.get("description") or "这里是本次天津行程中的一个推荐地点。"
        reason = context.get("recommend_reason")
        area = context.get("area")
        address = context.get("address")
        open_time = context.get("open_time") or "开放时间建议出发前再确认"
        price = context.get("price")
        price_text = f"参考费用约 {price} 元" if price is not None else "费用以现场或官方信息为准"
        tags = "、".join((context.get("tags") or [])[:4])
        location = address or (f"位于天津{area}" if area else "位于天津")

        lines = [
            f"欢迎来到{title}。这是本次路线中的{type_label}节点，{description}",
            "",
            f"· 位置：{location}。",
            f"· 时间：{open_time}。",
            f"· 预算：{price_text}。",
        ]
        if tags:
            lines.append(f"· 看点：{tags}。")
        if reason:
            lines.append(f"· 安排原因：{reason}")
        lines.append("")
        lines.append("你可以继续问我这里适合停留多久、怎么拍照、附近吃什么，或者怎么衔接下一站。")
        return "\n".join(lines)

    def _route_intro(self, context: dict[str, Any]) -> str:
        title = context["title"]
        mode = self._mode_label(context.get("travel_mode"))
        distance = self._distance_text(context.get("distance_m"))
        duration = self._duration_text(context.get("duration_min"))
        route_meta = "，".join([item for item in (mode, distance, duration) if item])
        if route_meta:
            route_meta = f"这段路预计{route_meta}。"
        else:
            route_meta = "这段路适合用来判断两站之间的衔接是否顺。"

        return (
            f"现在看的是 {title} 这段路线。{route_meta}\n\n"
            "· 路线作用：连接当前行程中的两个节点，重点看是否绕路、是否太累。\n"
            "· 体验建议：中间预留 10-15 分钟缓冲，方便拍照、补水或临时排队。\n"
            "· 调整方向：如果下雨、老人同行或体力下降，可以优先保留目的地，把中途步行压缩。\n\n"
            "你可以继续问我怎么走更轻松、沿途有没有看点，或者是否建议改成打车。"
        )

    def _fallback_answer(
        self,
        message: str,
        context: dict[str, Any],
        rag_result: dict[str, Any] | None = None,
        search_result: dict[str, Any] | None = None,
    ) -> str:
        if self._has_rag_sources(rag_result or {}):
            rag_answer = str((rag_result or {}).get("answer") or "").strip()
            if rag_answer:
                return rag_answer

        search_sources = (search_result or {}).get("sources") or []
        if search_sources:
            lines = ["知识库没有充分覆盖这个问题，我用联网检索补充到这些结果："]
            for index, source in enumerate(search_sources[:3], start=1):
                title = source.get("title") or source.get("name") or "联网来源"
                snippet = source.get("snippet") or source.get("content") or ""
                url = source.get("url") or source.get("link") or ""
                suffix = f"（{url}）" if url else ""
                lines.append(f"{index}. {title}{suffix}：{snippet}")
            lines.append("以上内容来自联网检索，请以官方页面或现场信息为准。")
            return "\n".join(lines)

        if context["kind"] == "route":
            return (
                f"{context['title']} 这段路线可以作为当前行程的衔接段来看。\n\n"
                "- 建议先确认两点之间的实际交通方式，如果步行时间过长，可以改成地铁或打车。\n"
                "- 路线中间可以预留 10-15 分钟缓冲，方便拍照、补水或临时排队。\n"
                "- 如果遇到下雨、老人同行或体力下降，可以优先保留目的地，把中途步行压缩。"
            )

        return (
            f"我暂时没有从知识库检索到{context['title']}的长文档依据，所以不能只靠 data 里的简短字段展开导游讲解。\n\n"
            "· 请确认 LangChain_RAG/docs/tianjin 中对应文档已经入库。\n"
            "· 如果刚刚更新过文档或数据库，请重启后端后再点击地图地点。\n"
            "· 重新提问时可以带上地点名、预算、开放时间或周边衔接等关键词。"
        )

    def _guide_payload_context(self, context: dict[str, Any]) -> dict[str, Any]:
        if context["kind"] == "route":
            origin = context.get("origin") or {}
            destination = context.get("destination") or {}
            return {
                "kind": "route",
                "title": context.get("title"),
                "origin": self._minimal_place_payload(origin),
                "destination": self._minimal_place_payload(destination),
                "travel_mode": context.get("travel_mode"),
                "distance_m": context.get("distance_m"),
                "duration_min": context.get("duration_min"),
                "verified": context.get("verified"),
                "rag_document_filenames": self._document_filenames_for_context(context),
            }
        return {
            "kind": "place",
            "title": context.get("title"),
            "place_id": context.get("place_id"),
            "place_type": context.get("place_type"),
            "city": context.get("city"),
            "area": context.get("area"),
            "address": context.get("address"),
            "longitude": context.get("longitude"),
            "latitude": context.get("latitude"),
            "rag_document_filenames": self._document_filenames_for_context(context),
        }

    def _minimal_place_payload(self, item: dict[str, Any]) -> dict[str, Any]:
        return {
            "name": item.get("name"),
            "place_id": item.get("place_id") or item.get("id"),
            "place_type": item.get("place_type"),
            "area": item.get("area"),
        }

    def _document_ids_for_context(self, context: dict[str, Any]) -> list[str]:
        filenames = self._document_filenames_for_context(context)
        if not filenames:
            return []
        try:
            if self._rag_document_ids_by_filename is None:
                self._rag_document_ids_by_filename = {
                    str(doc.get("filename") or doc.get("name")): str(doc.get("document_id"))
                    for doc in self.rag_service.list_documents()
                    if doc.get("document_id") and (doc.get("filename") or doc.get("name"))
                }
            return [
                self._rag_document_ids_by_filename[filename]
                for filename in filenames
                if filename in self._rag_document_ids_by_filename
            ]
        except Exception:
            return []

    def _document_filenames_for_context(self, context: dict[str, Any]) -> list[str]:
        if context["kind"] == "route":
            filenames = [
                self._document_filename_for_place(context.get("origin") or {}),
                self._document_filename_for_place(context.get("destination") or {}),
            ]
            return [filename for filename in filenames if filename]
        filename = self._document_filename_for_place(context)
        return [filename] if filename else []

    @staticmethod
    def _document_filename_for_place(item: dict[str, Any]) -> str | None:
        place_id = item.get("place_id") or item.get("id")
        if not isinstance(place_id, str):
            return None
        if not re.match(r"^tj_(place|restaurant|hotel)_\d+$", place_id):
            return None
        return f"{place_id}.md"

    def _should_web_search(self, question: str, rag_result: dict | None) -> bool:
        if not rag_result:
            return True
        sources = rag_result.get("sources") or []
        if not sources:
            return True
        if not rag_result.get("sufficient"):
            return True
        if self._rag_content_too_short(rag_result):
            return True
        realtime_words = [
            "开放时间", "营业时间", "票价", "门票", "预约", "闭馆",
            "今天", "明天", "现在", "天气", "交通", "堵车", "营业",
        ]
        return any(word in question for word in realtime_words)

    @staticmethod
    def _build_search_query(
        question: str,
        context: dict[str, Any],
        rag_result: dict | None,
    ) -> str:
        parts = [question.strip(), str(context.get("title") or "").strip()]
        if isinstance(rag_result, dict):
            rewritten_query = str(rag_result.get("rewritten_query") or "").strip()
            if rewritten_query:
                parts.append(rewritten_query)
        query = " ".join(part for part in parts if part)
        if "天津" not in query:
            query = f"天津 {query}"
        return " ".join(query.split())

    @staticmethod
    def _rag_content_too_short(rag_result: dict[str, Any]) -> bool:
        answer = str(rag_result.get("answer") or "").strip()
        sources = rag_result.get("sources") or []
        source_text = " ".join(
            str(source.get("content") or "").strip() for source in sources
        ).strip()
        return len(answer) < 80 and len(source_text) < 160

    @staticmethod
    def _has_rag_sources(rag_result: dict[str, Any]) -> bool:
        return bool(rag_result and rag_result.get("sources"))

    @staticmethod
    def _stream_chunks(text: str) -> list[str]:
        chunks: list[str] = []
        buffer = ""
        for char in text:
            buffer += char
            if char in "\n。！？；，、" or len(buffer) >= 5:
                chunks.append(buffer)
                buffer = ""
        if buffer:
            chunks.append(buffer)
        return chunks

    @staticmethod
    def _format_answer(answer: str) -> str:
        text = (answer or "").strip()
        text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
        text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)
        text = re.sub(r"\n?\s*[-*]\s+", "\n· ", text)
        text = re.sub(r"\s+(\d+[.、])\s+", r"\n\1 ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    @staticmethod
    def _distance_text(value: Any) -> str:
        try:
            distance = float(value)
        except (TypeError, ValueError):
            return ""
        if distance >= 1000:
            return f"约 {distance / 1000:.1f} 公里"
        return f"约 {int(distance)} 米"

    @staticmethod
    def _duration_text(value: Any) -> str:
        try:
            duration = float(value)
        except (TypeError, ValueError):
            return ""
        return f"约 {int(round(duration))} 分钟"

    @staticmethod
    def _mode_label(value: str | None) -> str:
        return {
            "walking": "步行",
            "transit": "公共交通",
            "driving": "打车/驾车",
            "bicycling": "骑行",
        }.get(value or "", value or "")

    def _load_place_index(self) -> dict[str, dict[str, Any]]:
        root = Path(__file__).resolve().parents[2]
        index: dict[str, dict[str, Any]] = {}
        for filename in ("places.json", "restaurants.json", "hotels.json"):
            path = root / "data" / filename
            if not path.exists():
                continue
            try:
                items = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            for item in items:
                place_id = item.get("place_id")
                if place_id:
                    index[place_id] = item
        return index

    def _find_by_name(self, name: str) -> dict[str, Any] | None:
        if not name:
            return None
        for item in self._places.values():
            item_name = item.get("name", "")
            if item_name and (item_name == name or item_name in name or name in item_name):
                return item
        return None

    @staticmethod
    def _type_label(place_type: str | None) -> str:
        return {
            "attraction": "景点",
            "restaurant": "餐饮地点",
            "hotel": "酒店",
        }.get(place_type or "", "地点")

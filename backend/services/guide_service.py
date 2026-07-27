from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any, AsyncIterator

from backend.services.chatbot_service import ChatbotService
from backend.services.rag_service import RAGService


class GuideService:
    """地图 AI 导游服务。

    第一版只依赖现有本地天津数据、RAG 适配入口和成员一封装后的 Chatbot。
    后续如果成员二/三提供更完整的地点详情和路线接口，可以在这里替换数据源。
    """

    def __init__(
        self,
        chatbot_service: ChatbotService | None = None,
        rag_service: RAGService | None = None,
    ) -> None:
        self.chatbot_service = chatbot_service or ChatbotService()
        self.rag_service = rag_service or RAGService()
        self._places = self._load_place_index()

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
        rag_result = {} if is_intro else self._query_rag(message, context)
        answer = (
            self._intro_answer(context)
            if is_intro
            else self._format_answer(self._chat(message, context, history, rag_result))
        )
        return {
            "answer": answer,
            "target_type": target_type,
            "target_title": context["title"],
            "context": context,
            "sources": rag_result.get("sources", []) if isinstance(rag_result, dict) else [],
            "used_rag": bool(rag_result and rag_result.get("sources")),
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
            return self.rag_service.query(
                question=message,
                category=context.get("place_type") or context.get("kind"),
                place_name=context.get("title"),
                top_k=4,
            )
        except Exception:
            return {"sources": [], "sufficient": False}

    def _chat(
        self,
        message: str,
        context: dict[str, Any],
        history: list[dict[str, Any]],
        rag_result: dict[str, Any],
    ) -> str:
        system = (
            "你是天津自由行系统里的 AI 导游，只讲天津旅行。"
            "你要像现场导游一样讲解当前地图上被点击的景点、餐厅、酒店或路线。"
            "回答要具体、自然、可执行，优先结合传入地点数据、路线数据和 RAG 资料。"
            "如果资料不足，可以基于天津旅行常识回答，但不要伪造具体票价、开放时间或官方规则。"
            "输出必须适合聊天气泡展示：不要 Markdown 粗体符号，不要表格，不要标题层级。"
            "先用一小段直接回答，再换行列出 2-4 条短要点，每条以“· ”开头。"
        )
        user_payload = {
            "用户问题": message or "请先介绍这里",
            "当前导游对象": context,
            "最近对话": history[-6:],
            "RAG检索": rag_result,
        }
        try:
            return self.chatbot_service.chat(
                system,
                json.dumps(user_payload, ensure_ascii=False),
            )
        except Exception:
            return self._fallback_answer(message, context)

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

    def _fallback_answer(self, message: str, context: dict[str, Any]) -> str:
        if context["kind"] == "route":
            return (
                f"{context['title']} 这段路线可以作为当前行程的衔接段来看。\n\n"
                "- 建议先确认两点之间的实际交通方式，如果步行时间过长，可以改成地铁或打车。\n"
                "- 路线中间可以预留 10-15 分钟缓冲，方便拍照、补水或临时排队。\n"
                "- 如果遇到下雨、老人同行或体力下降，可以优先保留目的地，把中途步行压缩。"
            )

        tags = "、".join(context.get("tags") or [])
        description = context.get("description") or "这里适合放进天津自由行路线。"
        open_time = context.get("open_time") or "开放时间建议出发前再确认"
        price = context.get("price")
        price_text = f"参考费用约 {price} 元" if price is not None else "费用以现场或官方信息为准"
        return (
            f"{context['title']} 是当前地图上的{self._type_label(context.get('place_type'))}，{description}\n\n"
            f"· 适合看点：{tags or '结合当前行程偏好安排'}。\n"
            f"· 时间建议：{open_time}，游览前最好再核对官方公告。\n"
            f"· 预算提醒：{price_text}。\n"
            "· 你可以继续问我适合停留多久、附近吃什么、怎么和下一站衔接。"
        )

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

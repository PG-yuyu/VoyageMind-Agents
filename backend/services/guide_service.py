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
        """初始化地图导游服务。

        可注入 ChatbotService 和 RAGService 便于测试复用；初始化时会加载本地地点索引，
        后续回答景点或路线问题时可以用 place_id/name 补全地址、简介、标签和坐标等上下文。
        """
        self.chatbot_service = chatbot_service or ChatbotService()
        self.rag_service = rag_service or RAGService()
        self._places = self._load_place_index()

    def answer(self, payload: dict[str, Any]) -> dict[str, Any]:
        """生成一次地图导游问答结果。

        payload 包含 target_type、target、message、history 和 intro 标记。
        函数先构建当前景点或路线上下文；如果是首次介绍就走固定导游介绍模板，
        否则查询 RAG 并调用 Chatbot 生成回答，最后返回答案、上下文和资料来源状态。
        """
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
        """以流式 chunk 输出导游回答。

        先复用 answer 生成完整导游答案，再按标点和短长度切块异步返回，
        供前端在聊天窗口里实现逐段播放或逐段显示。
        """
        result = self.answer(payload)
        answer = result["answer"]
        for chunk in self._stream_chunks(answer):
            yield chunk
            await asyncio.sleep(0.028)

    def _build_context(self, target_type: str, target: dict[str, Any]) -> dict[str, Any]:
        """根据目标类型构建统一导游上下文。

        target_type 为 route 时生成路线上下文；其他情况按景点、餐厅或酒店地点处理。
        统一上下文会被 RAG 检索、Chatbot 提示词和前端展示共同使用。
        """
        if target_type == "route":
            return self._build_route_context(target)
        return self._build_place_context(target)

    def _build_place_context(self, target: dict[str, Any]) -> dict[str, Any]:
        """构建地点类导游上下文。

        先用 place_id 或名称从本地索引补全地点数据，再用前端传入 target 覆盖最新字段。
        返回内容包括标题、类型、城市、区域、地址、简介、推荐理由、开放时间、价格、标签和坐标。
        """
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
        """构建路线类导游上下文。

        根据 origin_place_id 和 destination_place_id 查找起终点名称和详情，
        并合并交通方式、距离、耗时、数据来源和校验状态，供导游解释两站之间怎么衔接。
        """
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
        """按当前导游对象查询 RAG 资料库。

        如果用户问题为空，会自动改成“介绍当前地点”；查询时带上地点类型和名称，
        帮助 RAGService 优先命中当前景点、餐厅、酒店或路线相关资料。
        RAG 异常时返回空来源，避免导游功能中断。
        """
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
        """调用 Chatbot 生成导游回答。

        系统提示限定回答范围为天津旅行，并要求优先使用当前地点/路线数据和 RAG 资料。
        user_payload 会携带用户问题、当前导游对象、最近对话和检索结果；
        如果模型失败，则降级到 _fallback_answer。
        """
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
        """生成首次点击对象时的导游开场介绍。

        路线对象走 _route_intro，地点对象走 _place_intro。
        这个分支不查 RAG，目的是快速给前端一个稳定、自然的首屏讲解。
        """
        if context["kind"] == "route":
            return self._route_intro(context)
        return self._place_intro(context)

    def _place_intro(self, context: dict[str, Any]) -> str:
        """生成景点、餐厅或酒店的固定介绍模板。

        从上下文中读取名称、类型、简介、推荐理由、区域、地址、开放时间、价格和标签，
        组织成适合聊天气泡展示的短段落和要点，并提示用户可以继续追问。
        """
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
        """生成路线对象的固定介绍模板。

        读取路线标题、交通方式、距离和耗时，说明这段路线在行程衔接中的作用，
        并给出缓冲时间、体力下降或下雨时的调整建议。
        """
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
        """在 Chatbot 不可用时生成导游兜底回答。

        路线对象返回交通衔接和调整建议；地点对象返回简介、看点、时间和预算提醒。
        该函数只使用上下文已有字段，不伪造官方开放时间、票价或资料来源。
        """
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
        """把完整回答切成适合流式展示的小片段。

        遇到中文标点或缓冲区达到一定长度就切一段，既保证前端有流式效果，
        又避免每个字符都触发一次渲染造成卡顿。
        """
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
        """清理模型回答的 Markdown 样式。

        导游聊天气泡不需要标题、粗体和复杂列表；这里把 Markdown 粗体、标题和列表符号
        转成统一的纯文本要点格式，避免前端展示过重。
        """
        text = (answer or "").strip()
        text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
        text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)
        text = re.sub(r"\n?\s*[-*]\s+", "\n· ", text)
        text = re.sub(r"\s+(\d+[.、])\s+", r"\n\1 ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    @staticmethod
    def _distance_text(value: Any) -> str:
        """把米制距离格式化成人类可读文本。

        1000 米及以上显示为公里，一公里以下显示为米；无法转换的值返回空字符串，
        方便调用方拼接路线说明时自动跳过缺失字段。
        """
        try:
            distance = float(value)
        except (TypeError, ValueError):
            return ""
        if distance >= 1000:
            return f"约 {distance / 1000:.1f} 公里"
        return f"约 {int(distance)} 米"

    @staticmethod
    def _duration_text(value: Any) -> str:
        """把分钟数格式化成“约 N 分钟”。

        接受数字或可转换成数字的字符串；无法转换时返回空字符串，
        供路线介绍里按需拼接。
        """
        try:
            duration = float(value)
        except (TypeError, ValueError):
            return ""
        return f"约 {int(round(duration))} 分钟"

    @staticmethod
    def _mode_label(value: str | None) -> str:
        """把内部交通方式枚举转换成中文展示文本。

        支持 walking、transit、driving、bicycling；未知值原样返回，
        避免新交通方式暂未配置时显示为空。
        """
        return {
            "walking": "步行",
            "transit": "公共交通",
            "driving": "打车/驾车",
            "bicycling": "骑行",
        }.get(value or "", value or "")

    def _load_place_index(self) -> dict[str, dict[str, Any]]:
        """加载本地地点、餐厅和酒店数据索引。

        从 data/places.json、data/restaurants.json、data/hotels.json 读取数据，
        按 place_id 建立字典索引。文件不存在或解析失败时跳过，
        确保导游服务不会因为某个数据文件异常而无法启动。
        """
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
        """按名称在本地地点索引中做宽松匹配。

        当前端只传了名称没有传 place_id 时，用完全相等、包含和被包含三种方式查找地点。
        找到后返回地点详情，找不到返回 None。
        """
        if not name:
            return None
        for item in self._places.values():
            item_name = item.get("name", "")
            if item_name and (item_name == name or item_name in name or name in item_name):
                return item
        return None

    @staticmethod
    def _type_label(place_type: str | None) -> str:
        """把地点类型枚举转换成中文标签。

        attraction 显示为景点，restaurant 显示为餐饮地点，hotel 显示为酒店；
        未知类型统一显示为地点。
        """
        return {
            "attraction": "景点",
            "restaurant": "餐饮地点",
            "hotel": "酒店",
        }.get(place_type or "", "地点")

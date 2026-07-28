import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, AsyncIterator

from dotenv import load_dotenv


class ChatbotService:
    """成员一对 langchain-chat Chatbot 的封装。

    优先复用本项目内置的 backend/vendor/langchain_chat/src/core/chat_engine.py。
    如果本地依赖或模型配置不可用，接口仍返回规则兜底结果，方便三人并行联调。
    """

    def __init__(self) -> None:
        self.engine = None
        self.available = False
        self.error = None
        self._try_load_chat_engine()

    def _try_load_chat_engine(self) -> None:
        project_root = Path(__file__).resolve().parents[2]
        vendor_root = project_root / "backend" / "vendor" / "langchain_chat"
        chat_root = vendor_root
        chat_src = chat_root / "src"

        if not chat_src.exists():
            self.error = "未找到内置 Chatbot：backend/vendor/langchain_chat/src"
            return

        try:
            load_dotenv(project_root / ".env", override=True, encoding="utf-8-sig")
            if str(chat_src) not in sys.path:
                sys.path.insert(0, str(chat_src))
            cwd = Path.cwd()
            os.chdir(chat_root)
            from core.chat_engine import ChatEngine
            from core.config_manager import get_config

            if not os.environ.get("DEFAULT_MODEL"):
                os.environ["DEFAULT_MODEL"] = "deepseek-v4-flash"
            self.engine = ChatEngine(get_config())
            self.available = True
            os.chdir(cwd)
        except Exception as exc:
            self.error = str(exc)
            try:
                os.chdir(project_root)
            except OSError:
                pass

    def chat(self, system_prompt: str, user_prompt: str) -> str:
        """调用改进封装后的 Chatbot。

        这里复用内置 langchain-chat 的 ChatEngine，因此成员一的 Agent 不直接接触模型 SDK。
        """
        if not self.available or self.engine is None:
            raise RuntimeError(self.error or "ChatbotService 不可用")

        from langchain_core.messages import HumanMessage, SystemMessage

        reply, _usage = self.engine.chat(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt),
            ]
        )
        return str(reply)

    def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
        fallback: dict[str, Any],
    ) -> dict[str, Any]:
        """要求 Chatbot 返回 JSON；非法 JSON 时固定格式重试一次。

        这对应功能清单中的“模型输出异常：固定格式重试一次”。
        """
        if not self.available or self.engine is None:
            return fallback

        try:
            first_reply = self.chat(system_prompt, user_prompt)
        except Exception as exc:
            self.error = str(exc)
            return fallback
        parsed = self._parse_json_object(first_reply)
        if parsed is not None:
            return parsed

        retry_prompt = (
            f"{user_prompt}\n\n"
            "上一次输出不是合法 JSON。请只返回一个 JSON 对象，不要 Markdown，不要解释。"
        )
        try:
            second_reply = self.chat(system_prompt, retry_prompt)
        except Exception as exc:
            self.error = str(exc)
            return fallback
        parsed = self._parse_json_object(second_reply)
        return parsed if parsed is not None else fallback

    def summarize_agent_reply(self, message: str, context: dict) -> str:
        branch = context.get("branch")
        if branch in {"create_trip", "modify_trip"}:
            return self._fallback_reply(context)

        if not self.available or self.engine is None:
            return self._fallback_reply(context)

        system = (
            "你是天津自由行智能规划系统的成员一 Agent，本项目只处理天津旅游。你只负责意图识别、需求提取、"
            "会话状态、工作流编排和结果组织。不要伪造 RAG 来源、路线、坐标或预算。"
            "用简洁中文返回面向用户的下一步说明。"
        )
        payload = json.dumps(context, ensure_ascii=False, default=str)
        try:
            return self.chat(system, f"用户输入：{message}\n当前结构化上下文：{payload}")
        except Exception as exc:
            self.error = str(exc)
            return self._fallback_reply(context)

    def answer_travel_question(
        self,
        question: str,
        rag_result: dict | None = None,
        search_result: dict | None = None,
        place_context: dict | None = None,
    ) -> str:
        if not self.available or self.engine is None:
            return self._fallback_travel_answer(
                question, rag_result, search_result, place_context
            )

        system = (
            "你是天津本地旅行问答助手。只回答天津旅行相关问题。回答优先级如下："
            "1. 如果 RAG 资料充足，优先基于 RAG 回答，并保留资料库来源。"
            "2. 如果 RAG 没覆盖用户问题，使用联网搜索结果补充，并说明这些信息来自联网检索。"
            "3. 如果有当前地点或行程上下文，可以用于解释路线、停留时间、游玩建议。"
            "4. 如果 RAG 和联网搜索都没有结果，才使用通用旅行常识兜底。"
            "不要伪造来源；不要编造具体票价、开放时间、预约规则。"
            "请使用 Markdown 输出：短开头 + 编号列表或项目符号列表；不要把多个编号挤在同一段。"
        )
        context = json.dumps(
            {
                "用户问题": question,
                "RAG检索结果": rag_result or {},
                "联网搜索结果": search_result or {},
                "地点或行程上下文": place_context or {},
            },
            ensure_ascii=False,
        )
        try:
            return self.chat(system, context)
        except Exception as exc:
            self.error = str(exc)
            return self._fallback_travel_answer(
                question, rag_result, search_result, place_context
            )

    async def stream_travel_question(
        self,
        question: str,
        rag_result: dict | None = None,
        search_result: dict | None = None,
        place_context: dict | None = None,
    ) -> AsyncIterator[str]:
        answer = self.answer_travel_question(
            question=question,
            rag_result=rag_result,
            search_result=search_result,
            place_context=place_context,
        )
        for index in range(0, len(answer), 12):
            yield answer[index : index + 12]
            await asyncio.sleep(0.015)

    def _parse_json_object(self, text: str) -> dict[str, Any] | None:
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

    def _fallback_reply(self, context: dict) -> str:
        branch = context.get("branch")
        if branch == "create_trip":
            requirements = (context.get("requirements") or {}).get("requirements") or {}
            itinerary = context.get("itinerary") or {}
            days = itinerary.get("days") or []
            city = requirements.get("city") or "天津"
            day_count = requirements.get("days") or len(days) or "多"
            route_count = len(context.get("routes") or [])
            if days:
                return (
                    f"已生成{city}{day_count}日自由行方案，包含{len(days)}天行程、"
                    f"{route_count}条路线参考和预算/步行强度估算。你可以到「我的行程」查看每日安排，"
                    "也可以继续告诉我天气、体力、餐饮或时间变化来智能调整。"
                )
            return (
                f"已完成{city}旅行需求解析和地点推荐，但完整每日行程还在等待规划模块返回。"
                "你可以先查看推荐地点和地图路线。"
            )

        if branch == "modify_trip":
            result = context.get("modification_result") or {}
            affected_days = result.get("affected_days") or []
            changes = result.get("changes") or []
            day_text = f"第{','.join(str(day) for day in affected_days)}天" if affected_days else "当前行程"
            return (
                f"已根据你的要求调整{day_text}，本次更新包含{len(changes)}处变化。"
                "你可以在「我的行程」里查看新版安排。"
            )

        intent = context.get("intent", {}).get("intent")
        missing = context.get("requirements", {}).get("missing_fields", [])
        if missing:
            return (
                context.get("requirements", {}).get("follow_up_question")
                or "还需要补充关键信息。"
            )
        if intent == "travel_qa":
            return "这是旅游问答意图，应转交 RAGService 返回答案、来源文档、证据片段和页码。"
        if intent == "modify_trip":
            return "已识别为修改方案，下一步会定位受影响日期，并调用局部重规划接口。"
        return "已完成需求提取，可以进入推荐、路线、行程规划和规则校验工作流。"

    def _fallback_travel_answer(
        self,
        question: str,
        rag_result: dict | None = None,
        search_result: dict | None = None,
        place_context: dict | None = None,
    ) -> str:
        sources = (rag_result or {}).get("sources") or []
        if sources:
            lines = ["我在资料库里找到了这些依据："]
            for source in sources[:3]:
                index = source.get("citation_index") or len(lines)
                filename = source.get("filename") or source.get("title") or "资料库文档"
                content = source.get("content") or ""
                lines.append(f"{index}. {filename}：{content}")
            lines.append("这些内容来自已上传并入库的旅行资料，可作为当前问答的主要依据。")
            return "\n".join(lines)

        search_sources = (search_result or {}).get("sources") or []
        if search_sources:
            lines = ["资料库没有充分覆盖这个问题，我用联网检索补充到这些结果："]
            for index, source in enumerate(search_sources[:3], start=1):
                title = source.get("title") or source.get("name") or "联网来源"
                snippet = source.get("snippet") or source.get("content") or ""
                url = source.get("url") or source.get("link") or ""
                suffix = f"（{url}）" if url else ""
                lines.append(f"{index}. {title}{suffix}：{snippet}")
            lines.append("以上内容来自联网检索，请以官方页面或现场信息为准。")
            return "\n".join(lines)

        text = question.strip()
        search_available = (search_result or {}).get("available")
        unavailable_note = ""
        if search_available is False:
            unavailable_note = "联网搜索服务尚未接入真实搜索 API；"
        if "好玩" in text or "景点" in text or "玩" in text:
            return (
                f"当前未引用资料库来源；{unavailable_note}先按通用天津旅行常识回答。"
                "天津比较适合第一次游玩的地方有：五大道文化旅游区、意式风情区、"
                "海河沿线、古文化街、天津之眼、瓷房子、张学良故居和天津博物馆。"
                "如果是两日游，可以第一天安排五大道、民园广场、瓷房子、意式风情区和海河夜景；"
                "第二天安排古文化街、天后宫、南市食品街、天津博物馆或滨海新区。"
            )
        if "雨" in text or "下雨" in text:
            return (
                f"当前未引用资料库来源；{unavailable_note}先按通用天津旅行常识回答。"
                "天津雨天更适合安排室内或低步行景点，比如天津博物馆、"
                "张学良故居、瓷房子室内参观、商场休息和相声茶馆。海河夜景可以改成车览，"
                "五大道如果雨不大也可以缩短为重点建筑外观拍照。"
            )
        if "五大道" in text:
            return (
                f"当前未引用资料库来源；{unavailable_note}先按通用天津旅行常识回答。"
                "五大道更适合上午或傍晚去，上午人少、光线稳定，适合慢慢看建筑；"
                "下午如果时间紧，可以只走民园广场、重庆道、大理道一带，控制在 1.5 到 2 小时。"
            )
        return (
            f"当前未引用资料库来源；{unavailable_note}这个问题可以先按天津旅行常识处理：优先把景点按区域串联，"
            "比如五大道和民园广场放一起，意式风情区和海河夜景放一起，古文化街和南市食品街放一起。"
            "如果涉及开放时间、票价或预约规则，出发前再以景区官方信息为准。"
        )

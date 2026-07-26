from __future__ import annotations

from typing import Any

from backend.agents.adjustment_agent import AdjustmentAgent
from backend.agents.intent_agent import IntentAgent
from backend.schemas import ChatResponse
from backend.schemas.modification import ModificationRequest
from backend.services.chatbot_service import ChatbotService
from backend.services.rag_service import RAGService
from backend.services.recommendation_integration_service import (
    RecommendationIntegrationService,
)
from backend.services.requirement_adapter import RequirementAdapter
from backend.services.session_store import store
from backend.services.workflow_service import WorkflowService


class CoordinatorAgent:
    """成员一协调总控 Agent。

    这是项目中的总控智能体，负责：
    - 接收 Chatbot 对话输入；
    - 调用 IntentAgent 做三类意图识别；
    - 调用需求提取适配器产出 TravelRequest；
    - 按 create_trip / modify_trip / travel_qa 分支编排工作流；
    - 记录 Agent 执行轨迹；
    - 为成员二和成员三预留 Tool Call 接口位置。
    """

    def __init__(
        self,
        chatbot_service: ChatbotService | None = None,
        rag_service: RAGService | None = None,
        recommendation_integration_service: RecommendationIntegrationService
        | None = None,
        adjustment_agent: AdjustmentAgent | None = None,
    ) -> None:
        self.chatbot_service = chatbot_service or ChatbotService()
        self.intent_agent = IntentAgent(self.chatbot_service)
        self.requirement_adapter = RequirementAdapter(self.chatbot_service)
        self.workflow_service = WorkflowService()
        self.rag_service = rag_service or RAGService()
        self.recommendation_integration_service = (
            recommendation_integration_service or RecommendationIntegrationService()
        )
        self.adjustment_agent = adjustment_agent or AdjustmentAgent()

    def run(self, session_id: str, message: str) -> ChatResponse:
        store.ensure_session(session_id)
        user_message = store.add_message(session_id, "user", message)

        intent = self.intent_agent.run(message)
        if intent.intent == "travel_qa":
            trace = self.workflow_service.build_trace(
                session_id=session_id,
                intent=intent.intent,
                has_missing_fields=False,
            )
            store.agent_traces[session_id] = trace.model_dump()
            rag_result = self.rag_service.query(question=message, top_k=5)
            reply = self.chatbot_service.answer_travel_question(message, rag_result)
            store.add_message(session_id, "assistant", reply)
            return ChatResponse(
                message_id=user_message.message_id,
                intent=intent,
                reply=reply,
                workflow_status="completed",
                requirements=store.requirements.get(session_id),
                itinerary=None,
                agent_trace=trace.model_dump(),
            )

        extraction = self.requirement_adapter.extract(
            session_id=session_id,
            message=message,
            existing_requirements=store.requirements.get(session_id),
        )
        store.update_requirements(session_id, extraction.requirements)

        trace = self.workflow_service.build_trace(
            session_id=session_id,
            intent=intent.intent,
            has_missing_fields=extraction.need_follow_up,
        )
        store.agent_traces[session_id] = trace.model_dump()

        recommendation_output = None
        itinerary = None
        itinerary_modified = False

        if extraction.need_follow_up:
            reply = extraction.follow_up_question or "还需要补充关键信息。"
            workflow_status = "waiting_for_user"

        elif intent.intent == "modify_trip":
            # 查找当前会话的行程 ID 和版本
            session = store.sessions.get(session_id)
            current_itinerary_id = session.current_itinerary_id if session else None
            current_version = session.current_version if session else 1

            if current_itinerary_id:
                try:
                    # 构建修改请求
                    mod_request = ModificationRequest(
                        session_id=session_id,
                        itinerary_id=current_itinerary_id,
                        base_version=current_version,
                        action=intent.sub_intent or "replace_attraction",
                        original_text=message,
                    )
                    # 调用成员三调整 Agent
                    mod_result = self.adjustment_agent.modify(
                        request=mod_request,
                        requirements=extraction.requirements.model_dump()
                            if hasattr(extraction.requirements, "model_dump")
                            else {},
                    )

                    itinerary = mod_result.get("itinerary")
                    trip_diff = mod_result.get("diff")
                    evaluation = mod_result.get("evaluation")
                    budget = mod_result.get("budget")
                    affected_days = mod_result.get("affected_days", [])

                    trace = self.workflow_service.build_trace(
                        session_id=session_id,
                        intent=intent.intent,
                        has_missing_fields=False,
                        member2_recommendation_status="success",
                        member2_route_status="success",
                    )

                    reply = self.chatbot_service.summarize_agent_reply(
                        message,
                        {
                            "branch": "modify_trip",
                            "intent": intent.model_dump(),
                            "requirements": extraction.model_dump(),
                            "modification_result": {
                                "affected_days": affected_days,
                                "changes": trip_diff.get("changes", [])
                                    if trip_diff else [],
                                "evaluation_passed": evaluation.get("passed", True)
                                    if evaluation else True,
                            },
                        },
                    )
                    workflow_status = "completed"
                    itinerary_modified = True
                except Exception as exc:
                    trace = self.workflow_service.build_trace(
                        session_id=session_id,
                        intent=intent.intent,
                        has_missing_fields=False,
                        member2_recommendation_status="failed",
                        member2_route_status="failed",
                    )
                    reply = f"行程修改处理失败: {exc}"
                    workflow_status = "failed"
            else:
                # 没有行程可修改
                reply = "当前没有已生成的行程可供修改。请先通过「智能规划」创建一个行程。"
                workflow_status = "failed"

        else:
            # create_trip 分支
            try:
                recommendation_output = (
                    self.recommendation_integration_service.recommend_for_request(
                        requirements=extraction.requirements,
                        original_text=message,
                        conversation_context=self._conversation_context(session_id),
                        assumptions=extraction.assumptions,
                    )
                )
            except Exception as exc:
                trace = self.workflow_service.build_trace(
                    session_id=session_id,
                    intent=intent.intent,
                    has_missing_fields=False,
                    member2_recommendation_status="failed",
                    member2_route_status="failed",
                )
                reply = (
                    "成员二推荐模块调用失败，请检查大模型、RAG 或高德地图配置后重试："
                    f"{exc}"
                )
                workflow_status = "failed"
            else:
                # ── 调用成员三生成行程 ──────────────────────────────
                try:
                    itinerary = self._generate_itinerary(
                        requirements=extraction.requirements,
                        recommendation_output=recommendation_output,
                        original_text=message,
                    )
                except Exception as plan_exc:
                    itinerary = None
                    # 行程生成失败不阻断流程，记录到 trace
                    import logging
                    logging.getLogger(__name__).warning(
                        "行程生成失败（将返回无行程的推荐结果）: %s", plan_exc
                    )

                trace = self.workflow_service.build_trace(
                    session_id=session_id,
                    intent=intent.intent,
                    has_missing_fields=False,
                    member2_recommendation_status="success",
                    member2_route_status="success",
                )
                reply = self.chatbot_service.summarize_agent_reply(
                    message,
                    {
                        "branch": "create_trip",
                        "intent": intent.model_dump(),
                        "requirements": extraction.model_dump(),
                        "recommendation_result": recommendation_output[
                            "recommendation_result"
                        ],
                        "map_resources": recommendation_output["map_resources"],
                        "routes": recommendation_output["routes"],
                        "itinerary_generated": itinerary is not None,
                        "next_tool_calls": [
                            "itineraries.generate",
                            "itineraries.validate",
                        ],
                    },
                )
                workflow_status = "planning"
            store.agent_traces[session_id] = trace.model_dump()

        if recommendation_output is not None:
            recommendation_result = recommendation_output["recommendation_result"]
            map_resources = recommendation_output["map_resources"]
            routes = recommendation_output["routes"]
        else:
            recommendation_result = None
            map_resources = None
            routes = None

        store.add_message(session_id, "assistant", reply)
        # 如果行程被修改，更新会话中的版本号
        if itinerary_modified and itinerary:
            session = store.sessions.get(session_id)
            if session:
                session.current_version = itinerary.get("version", session.current_version)

        return ChatResponse(
            message_id=user_message.message_id,
            intent=intent,
            reply=reply,
            workflow_status=workflow_status,
            requirements=extraction.requirements,
            itinerary=itinerary,
            recommendation_result=recommendation_result,
            map_resources=map_resources,
            routes=routes,
            agent_trace=trace.model_dump(),
        )

    def _generate_itinerary(
        self,
        requirements: Any,
        recommendation_output: dict,
        original_text: str = "",
    ) -> dict | None:
        """调用成员三生成行程：优先 LLM PlanningAgent，不可用时降级为规则引擎。

        Returns:
            dict: 行程字典，或 None（生成失败时）
        """
        import logging
        logger = logging.getLogger(__name__)

        req = requirements.model_dump() if hasattr(requirements, "model_dump") else {}
        rec = recommendation_output.get("recommendation_result", {})

        # 合并所有地点
        places: list[dict] = []
        for key in ("attractions", "hotels", "restaurants"):
            items = rec.get(key, [])
            if isinstance(items, list):
                places.extend(items)
        routes = recommendation_output.get("routes", [])

        # ── 尝试 LLM PlanningAgent ──────────────────────────────
        itinerary = None
        try:
            from backend.clients.deepseek_llm import DeepSeekLLM
            from backend.agents.planning_agent import PlanningAgent

            llm = DeepSeekLLM()
            agent = PlanningAgent(llm_callable=llm)
            result = agent.plan(
                requirements=req,
                places=places,
                routes=routes,
                recommendation_context=recommendation_output.get(
                    "recommendation_context", {}
                ),
                recommendation_policy=rec.get("policy_summary", {}),
            )
            logger.info("PlanningAgent 生成行程成功: days=%d",
                        len(result.get("itinerary", {}).get("days", [])))
            itinerary = result.get("itinerary")
        except (ImportError, ValueError) as exc:
            logger.warning("PlanningAgent 不可用 (%s)，降级到规则引擎", exc)
        except Exception as exc:
            logger.warning("PlanningAgent 调用失败 (%s)，降级到规则引擎", exc)

        # ── 降级：规则引擎 ──────────────────────────────────────
        if itinerary is None:
            try:
                from backend.services.itinerary_planner import generate_itinerary

                hotel = next((p for p in places if p.get("place_type") == "hotel"), None)
                attractions = [p for p in places if p.get("place_type") == "attraction"]
                restaurants = [p for p in places if p.get("place_type") == "restaurant"]

                it = generate_itinerary(
                    requirements=req,
                    hotel=hotel,
                    attractions=attractions,
                    restaurants=restaurants,
                )
                logger.info("规则引擎生成行程: days=%d", len(it.days))
                itinerary = it.model_dump()
            except Exception as exc:
                logger.error("规则引擎行程生成也失败: %s", exc)
                return None

        # ── 后处理：注入 _place 引用 + 补全 note ─────────────────
        if itinerary:
            _enrich_itinerary_display(itinerary, places)

        return itinerary

    def _conversation_context(self, session_id: str) -> list[str]:
        """读取当前会话历史，传给成员二保留上下文。"""

        return [
            message.content
            for message in store.messages.get(session_id, [])
            if message.role in {"user", "assistant"} and message.content.strip()
        ]

    def _is_smalltalk(self, message: str) -> bool:
        text = message.strip()
        return text in {"你好", "您好", "hi", "hello", "嗨", "你猜"} or len(text) <= 2

    async def stream_run(self, session_id: str, message: str):
        store.ensure_session(session_id)

        intent = self.intent_agent.run(message)
        if intent.intent != "travel_qa":
            response = self.run(session_id, message)
            yield response.reply
            return

        store.add_message(session_id, "user", message)

        trace = self.workflow_service.build_trace(
            session_id=session_id,
            intent=intent.intent,
            has_missing_fields=False,
        )
        store.agent_traces[session_id] = trace.model_dump()

        rag_result = self.rag_service.query(question=message, top_k=5)
        parts: list[str] = []
        async for chunk in self.chatbot_service.stream_travel_question(
            message, rag_result
        ):
            parts.append(chunk)
            yield chunk
        store.add_message(session_id, "assistant", "".join(parts))


# ============================================================================
# 模块级辅助函数
# ============================================================================


def _enrich_itinerary_display(itinerary: dict, places: list[dict]) -> None:
    """为行程 items 注入 _place 引用 + 补全空 note，确保前端能显示中文名。

    修改是原地进行的（mutates itinerary dict）。
    """
    # 建立 place_id → place 索引
    place_map: dict[str, dict] = {}
    for p in places:
        pid = p.get("place_id", "")
        if pid:
            place_map[pid] = p

    for day_data in itinerary.get("days", []):
        for item in day_data.get("items", []):
            pid = item.get("place_id", "")
            place = place_map.get(pid)

            # 注入 _place 引用
            if place:
                item["_place"] = place

            # 如果 note 为空，用地点名称补全
            if not item.get("note") and place:
                item["note"] = place.get("name") or place.get("short_description", "")

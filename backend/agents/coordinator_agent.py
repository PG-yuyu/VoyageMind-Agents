from __future__ import annotations

import json
import logging
import math
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
from backend.services.itinerary_planner import generate_itinerary
from backend.services.version_service import save_version
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
        self.adjustment_agent = adjustment_agent or AdjustmentAgent(
            alternative_place_fetcher=self._fetch_alternative_places,
        )

    def run(self, session_id: str, message: str) -> ChatResponse:
        import time as _time
        _t0 = _time.time()
        store.ensure_session(session_id)
        user_message = store.add_message(session_id, "user", message)

        intent = self.intent_agent.run(message)
        _t1 = _time.time()
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
        _t2 = _time.time()

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
                    # 修改后：修复非法字段 + 同步 place_id + 补全名称 + 重算路线
                    if itinerary:
                        _normalize_item_types(itinerary)
                        _sync_replaced_places(itinerary)
                        _places = _extract_places_from_itinerary(itinerary)
                        if _places:
                            _enrich_itinerary_display(itinerary, _places)
                            _compute_itinerary_routes(itinerary, _places)
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
            _t_rec = 0.0
            try:
                _t_rec_start = _time.time()
                recommendation_output = (
                    self.recommendation_integration_service.recommend_for_request(
                        requirements=extraction.requirements,
                        original_text=message,
                        conversation_context=self._conversation_context(session_id),
                        assumptions=extraction.assumptions,
                        enrich_evidence=False,
                    )
                )
                _t_rec = _time.time() - _t_rec_start
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
                _t_plan = 0.0
                _t_plan_start = _time.time()
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
                        "itinerary": itinerary,
                        "map_resources": recommendation_output["map_resources"],
                        "routes": recommendation_output["routes"],
                        "itinerary_generated": itinerary is not None,
                        "next_tool_calls": [
                            "itineraries.generate",
                            "itineraries.validate",
                        ],
                    },
                )
                workflow_status = "completed" if itinerary else "planning"
                _t_plan = _time.time() - _t_plan_start
                _t_total = _time.time() - _t0
                import logging
                _logger = logging.getLogger(__name__)
                _logger.warning(
                    "⏱ 全链路耗时: 意图识别=%.1fs | 需求提取=%.1fs | 推荐=%.1fs | 行程生成=%.1fs | 总计=%.1fs",
                    _t1 - _t0, _t2 - _t1, _t_rec, _t_plan, _t_total,
                )
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

    async def run_with_progress(self, session_id: str, message: str):
        """按真实执行节点输出规划进度事件，最后输出 ChatResponse。"""

        def event(payload: dict[str, Any]) -> str:
            return json.dumps(payload, ensure_ascii=False) + "\n"

        def progress(index: int, status: str, desc: str) -> str:
            return event(
                {
                    "type": "progress",
                    "index": index,
                    "status": status,
                    "desc": desc,
                }
            )

        store.ensure_session(session_id)
        user_message = store.add_message(session_id, "user", message)

        yield progress(0, "active", "正在识别意图并抽取旅行需求")
        intent = self.intent_agent.run(message)
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

        if intent.intent == "travel_qa":
            yield progress(0, "done", "已识别为旅行问答，转入知识问答流程")
            rag_result = self.rag_service.query(question=message, top_k=5)
            reply = self.chatbot_service.answer_travel_question(message, rag_result)
            store.add_message(session_id, "assistant", reply)
            response = ChatResponse(
                message_id=user_message.message_id,
                intent=intent,
                reply=reply,
                workflow_status="completed",
                requirements=store.requirements.get(session_id),
                itinerary=None,
                agent_trace=trace.model_dump(),
            )
            yield event({"type": "final", "data": response.model_dump(mode="json")})
            return

        if extraction.need_follow_up:
            yield progress(0, "done", "已识别需求，但仍缺少关键信息")
            reply = extraction.follow_up_question or "还需要补充关键信息。"
            store.add_message(session_id, "assistant", reply)
            response = ChatResponse(
                message_id=user_message.message_id,
                intent=intent,
                reply=reply,
                workflow_status="waiting_for_user",
                requirements=extraction.requirements,
                itinerary=None,
                agent_trace=trace.model_dump(),
            )
            yield event({"type": "final", "data": response.model_dump(mode="json")})
            return

        if intent.intent == "modify_trip":
            yield progress(0, "done", "已识别为行程修改需求")
            yield progress(2, "active", "正在进入行程修改流程")
            reply = "请在「我的行程」页使用智能修改入口调整当前行程。"
            store.add_message(session_id, "assistant", reply)
            response = ChatResponse(
                message_id=user_message.message_id,
                intent=intent,
                reply=reply,
                workflow_status="planning",
                requirements=extraction.requirements,
                itinerary=None,
                agent_trace=trace.model_dump(),
            )
            yield event({"type": "final", "data": response.model_dump(mode="json")})
            return

        yield progress(0, "done", "已完成意图识别和需求抽取")
        yield progress(1, "active", "正在调用推荐模块筛选景点、餐厅和住宿")

        recommendation_output = None
        itinerary = None
        workflow_status = "failed"
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
            yield progress(1, "failed", f"推荐模块调用失败：{exc}")
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
        else:
            yield progress(1, "done", "推荐模块已返回地点候选和路线资源")
            yield progress(2, "active", "正在根据推荐结果生成每日行程")
            try:
                itinerary = self._generate_itinerary(
                    requirements=extraction.requirements,
                    recommendation_output=recommendation_output,
                    original_text=message,
                )
            except Exception as plan_exc:
                itinerary = None
                yield progress(2, "failed", f"行程生成失败：{plan_exc}")
            else:
                if itinerary:
                    yield progress(2, "done", "已生成真实每日行程")
                    yield progress(3, "active", "正在汇总预算、步行距离和路线强度")
                    yield progress(3, "done", "已完成基础预算与路线强度汇总")
                else:
                    yield progress(2, "failed", "行程生成模块没有返回可用行程")

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
                    "itinerary": itinerary,
                    "map_resources": recommendation_output["map_resources"],
                    "routes": recommendation_output["routes"],
                    "itinerary_generated": itinerary is not None,
                    "next_tool_calls": [
                        "itineraries.generate",
                        "itineraries.validate",
                    ],
                },
            )
            workflow_status = "completed" if itinerary else "planning"

        store.agent_traces[session_id] = trace.model_dump()
        recommendation_result = (
            recommendation_output["recommendation_result"]
            if recommendation_output is not None
            else None
        )
        map_resources = (
            recommendation_output["map_resources"]
            if recommendation_output is not None
            else None
        )
        routes = recommendation_output["routes"] if recommendation_output is not None else None

        store.add_message(session_id, "assistant", reply)

        # ── 诊断日志：检查 itinerary 状态 ──────────────────────────
        _logger = logging.getLogger(__name__)
        if itinerary is None:
            _logger.warning("🔍 DEBUG: itinerary is None — 前端将回退到演示数据")
        elif not isinstance(itinerary, dict):
            _logger.error("🔍 DEBUG: itinerary 不是 dict, type=%s", type(itinerary).__name__)
        else:
            _days = itinerary.get("days", [])
            _total_items = sum(len(d.get("items", [])) for d in _days if isinstance(d, dict))
            _logger.warning(
                "🔍 DEBUG: itinerary 有效 — days=%d, total_items=%d, itinerary_id=%s, version=%s",
                len(_days), _total_items,
                itinerary.get("itinerary_id", "?"),
                itinerary.get("version", "?"),
            )

        try:
            response = ChatResponse(
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
            _dumped = response.model_dump(mode="json")
            _logger.warning("🔍 DEBUG: ChatResponse 序列化成功, reply长度=%d", len(reply))
            yield event({"type": "final", "data": _dumped})
        except Exception as _serialize_exc:
            _logger.error(
                "🔍 DEBUG: final event 序列化失败! error=%s",
                _serialize_exc, exc_info=True,
            )
            raise

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

        # ── RAG 实时补全：从 RAG 文档索引补全价格等缺失字段 ──────
        try:
            from backend.services.rag_place_enricher import rag_index
            enriched_count = 0
            for p in places:
                pid = p.get("place_id", "")
                old_price = p.get("price")
                rag_index.enrich(p)
                if p.get("price") != old_price:
                    enriched_count += 1
            if enriched_count:
                logger.warning(
                    "RAG 实时补全: %d/%d 个地点价格已从 RAG 文档更新",
                    enriched_count, len(places),
                )
        except Exception as _rag_exc:
            logger.warning("RAG 实时补全失败（不影响流程）: %s", _rag_exc)

        logger.warning(
            "🔍 DEBUG: _generate_itinerary 入口 — places=%d (attr=%d, hotel=%d, rest=%d), routes=%d",
            len(places),
            len(rec.get("attractions", []) if isinstance(rec.get("attractions"), list) else []),
            len(rec.get("hotels", []) if isinstance(rec.get("hotels"), list) else []),
            len(rec.get("restaurants", []) if isinstance(rec.get("restaurants"), list) else []),
            len(recommendation_output.get("routes", [])),
        )
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
            itinerary = result.get("itinerary")
            # 校验 LLM 产出：必须有 days 且至少一天有 items，
            # 否则视为生成失败，让规则引擎兜底。
            if itinerary and itinerary.get("days") and any(
                d.get("items") for d in itinerary.get("days", [])
            ):
                logger.warning(
                    "🔍 DEBUG: PlanningAgent 生成成功 — days=%d, total_items=%d",
                    len(itinerary.get("days", [])),
                    sum(len(d.get("items", [])) for d in itinerary.get("days", []) if isinstance(d, dict)),
                )
            else:
                logger.warning(
                    "🔍 DEBUG: PlanningAgent 返回空行程 (days=%d)，降级到规则引擎",
                    len(itinerary.get("days", [])) if itinerary else 0,
                )
                itinerary = None
        except (ImportError, ValueError) as exc:
            logger.warning("🔍 DEBUG: PlanningAgent 不可用 (%s)，降级到规则引擎", exc)
        except Exception as exc:
            logger.warning("🔍 DEBUG: PlanningAgent 调用失败 (%s)，降级到规则引擎", exc)

        # ── 降级：规则引擎 ──────────────────────────────────────
        if itinerary is None:
            try:
                from backend.services.itinerary_planner import generate_itinerary

                hotel = next((p for p in places if p.get("place_type") == "hotel"), None)
                attractions = [p for p in places if p.get("place_type") == "attraction"]
                restaurants = [p for p in places if p.get("place_type") == "restaurant"]

                logger.warning(
                    "🔍 DEBUG: 规则引擎降级 — hotel=%s, attractions=%d, restaurants=%d",
                    hotel.get("name", "无") if hotel else "无",
                    len(attractions),
                    len(restaurants),
                )

                it = generate_itinerary(
                    requirements=req,
                    hotel=hotel,
                    attractions=attractions,
                    restaurants=restaurants,
                )
                logger.warning("🔍 DEBUG: 规则引擎生成成功 — days=%d", len(it.days))
                itinerary = it.model_dump()
            except Exception as exc:
                logger.error("🔍 DEBUG: 规则引擎也失败! error=%s", exc, exc_info=True)
                return None

        # ── 后处理：标准化结构 + 注入 _place + 路线计算 ──
        if itinerary:
            _normalize_itinerary(itinerary, places)

            # 保存到版本库，确保后续调整 Agent 能查到
            try:
                from backend.schemas.itinerary import Itinerary
                itinerary_obj = Itinerary(**itinerary)
                save_version(itinerary_obj)
                logger.warning(
                    "🔍 DEBUG: 行程已保存到版本库 — id=%s, version=%s",
                    itinerary_obj.itinerary_id, itinerary_obj.version,
                )
            except Exception as _save_exc:
                logger.error("🔍 DEBUG: 保存行程版本失败: %s", _save_exc, exc_info=True)

        # ── 缓存推荐候选地点，供调整 Agent 筛选替代项 ──
        if places:
            sid = req.get("session_id", "")
            if sid:
                store.recommended_places[sid] = places
                logger.warning("🔍 DEBUG: 缓存 %d 个推荐候选地点到 session[%s]", len(places), sid)

        return itinerary

    def _fetch_alternative_places(
        self,
        original_place_id: str,
        constraints: dict | None = None,
        limit: int = 5,
    ) -> list[dict]:
        """为 AdjustmentAgent 获取替代地点候选。

        优先调用成员二推荐服务（基于用户偏好个性化推荐），
        不可用时降级到 PlaceRepository 全量筛选。
        """
        constraints = constraints or {}
        indoor_only = constraints.get("indoor") or constraints.get("change_to_indoor")

        # ── 方案 A：调用成员二推荐服务（个性化） ──────────────
        try:
            # 用成员二推荐 Agent 按用户偏好重新推荐
            candidates = self._recommend_alternatives_via_member2(
                original_place_id=original_place_id,
                constraints=constraints,
                indoor_only=indoor_only,
                limit=limit,
            )
            if candidates:
                return candidates
        except Exception:
            pass

        # ── 方案 B：降级到 PlaceRepository 全量筛选 ──────────
        try:
            from backend.app.repositories import PlaceRepository
            repo = PlaceRepository()
            orig_place = repo.get_by_id(original_place_id)
            target_type = getattr(orig_place, "place_type", None) if orig_place else None
            if target_type == "attraction":
                all_places = repo.list_attractions()
            elif target_type == "restaurant":
                all_places = repo.list_restaurants()
            else:
                all_places = repo.list_attractions() + repo.list_restaurants()
            candidates = []
            for p in all_places:
                pid = getattr(p, "place_id", "")
                if pid == original_place_id:
                    continue
                if indoor_only:
                    tags = getattr(p, "tags", []) or []
                    if not any("室内" in (t or "") for t in tags):
                        continue
                candidates.append(p.to_dict())
            return candidates[:limit]
        except Exception:
            return []

    def _recommend_alternatives_via_member2(
        self,
        original_place_id: str,
        constraints: dict,
        indoor_only: bool,
        limit: int,
    ) -> list[dict]:
        """通过成员二推荐服务获取个性化替代地点。"""
        try:
            integration = self.recommendation_integration_service
            agent = integration.recommendation_agent
            # 构造最小推荐上下文：复用已存储的用户需求
            from backend.app.schemas import RecommendationContext
            stored_req = None
            # 尝试从 session store 获取最近的需求
            for sid in list(store.requirements.keys()):
                stored_req = store.requirements.get(sid)
                if stored_req:
                    break
            if stored_req is None:
                return []
            # 注入约束条件
            ctx = RecommendationContext(
                session_id="alt_fetch",
                requirements=stored_req,
                original_text=f"替换 {original_place_id}",
                semantic_preferences=[],
            )
            result = agent.recommend(ctx)
            # 筛选同类型 + 匹配约束
            candidates = []
            for p in result.attractions + result.restaurants:
                pd = p.to_dict()
                if pd.get("place_id") == original_place_id:
                    continue
                if indoor_only:
                    tags = pd.get("tags", []) or []
                    if not any("室内" in (t or "") for t in tags):
                        continue
                candidates.append(pd)
            return candidates[:limit]
        except Exception:
            return []

    def _conversation_context(self, session_id: str) -> list[str]:
        """读取当前会话历史，传给成员二保留上下文。"""

        return [
            message.content
            for message in store.messages.get(session_id, [])
            if message.role in {"user", "assistant"} and message.content.strip()
        ]

    def _generate_itinerary_from_recommendation(
        self,
        session_id: str,
        requirements,
        recommendation_output: dict,
    ) -> dict | None:
        """把成员二候选资源编排成成员三可继续修改的初始行程。"""

        result = recommendation_output.get("recommendation_result") or {}
        attractions = result.get("attractions") or []
        restaurants = result.get("restaurants") or []
        hotels = result.get("hotels") or []
        if not attractions and not restaurants:
            return None

        requirements_payload = requirements.model_dump()
        requirements_payload["session_id"] = session_id

        itinerary = generate_itinerary(
            requirements=requirements_payload,
            hotel=hotels[0] if hotels else None,
            attractions=attractions,
            restaurants=restaurants,
            route_mode_priority=requirements.transport_modes or ["walking", "transit"],
            max_candidates_per_day=5,
        )
        saved_itinerary = save_version(itinerary)

        session = store.sessions.get(session_id)
        if session:
            session.current_itinerary_id = saved_itinerary.itinerary_id
            session.current_version = saved_itinerary.version

        return saved_itinerary.model_dump(mode="json")

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


def _normalize_itinerary(itinerary: dict, places: list[dict]) -> dict:
    """行程结构标准化后处理——规划 Agent 和调整 Agent 共用。

    确保 departure/hotel/return 的 note 和位置与 itinerary_builder 一致。
    """
    total_days = len(itinerary.get("days", []))
    hotel_place_id = itinerary.get("hotel_place_id", "")

    for day_data in itinerary.get("days", []):
        day_num = day_data.get("day", 1)
        is_last_day = (day_num == total_days)
        items = day_data.get("items", [])

        for item in items:
            itype = item.get("item_type", "")
            if itype == "departure":
                item["note"] = "出发"
            elif itype == "return":
                item["note"] = "返程" if is_last_day else "返回酒店"

        # 移除旧 hotel item（逻辑统一重建）
        items = [it for it in items if it.get("item_type") != "hotel"]
        day_data["items"] = items

        # 最后一天不需要酒店
        if is_last_day or not hotel_place_id:
            continue

        # 在 return 之前插入 hotel item
        insert_at = len(items)
        for i, it in enumerate(items):
            if it.get("item_type") == "return":
                insert_at = i
                break

        # 获取酒店名称和价格
        hotel_name = ""
        hotel_price = 0.0
        for p in places:
            if p.get("place_id") == hotel_place_id:
                hotel_name = p.get("name", "")
                hotel_price = float(p.get("price", 0) or 0)
                break
        # places 列表中没有则从 RAG 索引查找
        if hotel_price == 0:
            try:
                from backend.services.rag_place_enricher import rag_index
                p = rag_index.get_price(hotel_place_id)
                if p is not None and p > 0:
                    hotel_price = float(p)
            except Exception:
                pass

        hotel_item = {
            "item_id": f"day{day_num}_item_hotel",
            "day": day_num,
            "item_type": "hotel",
            "place_id": hotel_place_id,
            "start_time": day_data.get("start_time", "09:00"),
            "end_time": day_data.get("end_time", "18:00"),
            "duration_minutes": 0,
            "route_from_previous_id": None,
            "cost_per_person": hotel_price,
            "total_cost": hotel_price,
            "locked": True,
            "note": hotel_name or "酒店",
        }
        items.insert(insert_at, hotel_item)

    # 注入 _place + RAG 介绍 + 路线计算
    _enrich_itinerary_display(itinerary, places)
    _compute_itinerary_routes(itinerary, places)

    return itinerary


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

    # item_type → 兜底显示名（当所有查找都失败时使用）
    _fallback_labels: dict[str, str] = {
        "attraction": "未命名景点",
        "hotel": "住宿",
        "lunch": "午餐",
        "dinner": "晚餐",
        "departure": "出发",
        "return": "返回酒店",
        "rest": "休息",
        "transport": "交通",
    }

    # 从 RAG 文档补全所有地点的自然语言介绍
    try:
        from backend.services.rag_place_enricher import rag_index
        for p in place_map.values():
            rag_index.enrich(p)
            # 清理旧数据污染：若 description 过长（RAG 文本），重置为短描述
            desc = p.get("description") or ""
            if len(desc) > 120:
                p["description"] = ""
    except Exception:
        pass

    for day_data in itinerary.get("days", []):
        for item in day_data.get("items", []):
            pid = item.get("place_id") or ""
            place = place_map.get(pid) if pid else None

            # 注入 _place 引用（已含 RAG 描述）
            if place:
                item["_place"] = place

            # 如果 note 为空，用地点名称补全（仅用 name，不使用可能被污染的 description 字段）
            if not item.get("note") and place:
                item["note"] = place.get("name") or ""

            # 检测 _place 与 note 是否指向不同地点（LLM 替换了但没同步 place_id）
            if place and item.get("note"):
                note_full = item["note"].strip()
                place_name = (place.get("name") or "").strip()
                if not place_name:
                    continue
                # 提取 note 中的候选地名：取逗号/顿号前的第一段
                candidate_name = note_full.split("，")[0].split(",")[0].split("、")[0].strip()
                if (
                    candidate_name != place_name
                    and len(candidate_name) >= 2
                    and not any(kw in candidate_name for kw in ("替换", "替代", "换成", "改为", "已调整"))
                ):
                    # 在 PlaceRepository 中按名称查找（比 places 列表更全）
                    found = False
                    for p in places:
                        pname = (p.get("name") or "").strip()
                        if pname == candidate_name or pname == note_full:
                            item["_place"] = p
                            item["place_id"] = p.get("place_id", item.get("place_id", ""))
                            item["note"] = pname  # 精简 note 为干净地名
                            found = True
                            break
                    # places 列表没找到，回查 PlaceRepository
                    if not found:
                        try:
                            from backend.app.repositories import PlaceRepository
                            repo = PlaceRepository()
                            for p in repo.list_attractions() + repo.list_hotels() + repo.list_restaurants():
                                pd = p.to_dict()
                                pname = (pd.get("name") or "").strip()
                                if pname == candidate_name:
                                    item["_place"] = pd
                                    item["place_id"] = pd.get("place_id", item.get("place_id", ""))
                                    item["note"] = pname
                                    break
                        except Exception:
                            pass

            # 终极兜底：note 仍为空时，根据 item_type 给出合理标签，
            # 避免前端回退到展示原始 place_id 或 "attraction"
            if not item.get("note"):
                itype = item.get("item_type", "")
                item["note"] = _fallback_labels.get(itype, itype or "未指定")


def _sync_replaced_places(itinerary: dict) -> None:
    """检测 LLM 只在 note 中写了替换但没改 place_id，从数据库回补。

    当 note 包含"替换"/"换成"/"替代"等关键词但没有对应 place_id 变更时，
    尝试从 PlaceRepository 按名称查找新地点并更新 place_id 和 _place。
    """
    import re

    # 预加载地点数据库（名称 → 地点）
    name_index: dict[str, dict] = {}
    try:
        from backend.app.repositories import PlaceRepository
        repo = PlaceRepository()
        for p in repo.list_attractions() + repo.list_hotels() + repo.list_restaurants():
            pd = p.to_dict()
            nm = (pd.get("name") or "").strip()
            if nm:
                name_index[nm] = pd
    except Exception:
        pass

    for day_data in itinerary.get("days", []):
        for item in day_data.get("items", []):
            # 跳过结构性标记项（departure/return/hotel/dinner/lunch），
            # 这些不是景点，note 中的"酒店""返回"等文字不应被当作地点名匹配
            itype = item.get("item_type", "")
            if itype in ("departure", "return", "hotel", "lunch", "dinner", "rest"):
                continue

            note = item.get("note") or ""
            pid = item.get("place_id") or ""
            place = item.get("_place") or {}

            # 检测替换意图：note 中提到新景点名称
            patterns = [
                r'替换[^为].*?为\s*(\S{2,20})',
                r'换[成为]\s*(\S{2,20})',
                r'替代[^景].*?为\s*(\S{2,20})',
                r'改为\s*(\S{2,20})',
            ]
            new_name = None
            for pat in patterns:
                m = re.search(pat, note)
                if m:
                    new_name = m.group(1).strip()
                    break

            if not new_name:
                # 没有匹配到替换模式，但 note 本身可能就是一个干净的地名
                # （LLM 直接设置了 note 为新地名而非替换描述）
                place_name = (place.get("name") or "").strip()
                note_name = note.strip()
                if (
                    len(note_name) >= 2 and len(note_name) <= 30
                    and note_name != place_name
                    and not note_name.startswith("已")
                ):
                    new_name = note_name
                else:
                    continue

            # 已经是当前地点名 → 无需替换
            place_name = (place.get("name") or "").strip()
            if new_name == place_name:
                continue

            # 查找新地点：精确 → 模糊 → 子串匹配
            new_place = name_index.get(new_name)
            if not new_place:
                for nm, pd in name_index.items():
                    if new_name in nm or nm in new_name:
                        new_place = pd
                        break
            # 更宽松的匹配：拆词逐段匹配
            if not new_place and len(new_name) >= 2:
                for nm, pd in name_index.items():
                    # 2字以上的公共子串
                    for i in range(len(new_name) - 1):
                        chunk = new_name[i:i+2]
                        if chunk in nm:
                            new_place = pd
                            break
                    if new_place:
                        break

            if new_place:
                new_pid = new_place.get("place_id", "")
                if new_pid and new_pid != pid:
                    item["place_id"] = new_pid
                    item["_place"] = new_place
                    item["note"] = new_place.get("name", new_name)
                    new_price = new_place.get("price")
                    if new_price is not None:
                        item["cost_per_person"] = float(new_price)
                        item["total_cost"] = float(new_price)


def _normalize_item_types(itinerary: dict) -> None:
    """修正 LLM 可能输出的非法 item_type（如 restaurant → lunch/dinner）。"""
    _valid_types = {
        "departure", "transport", "attraction", "lunch", "dinner",
        "hotel", "rest", "return",
    }
    for day_data in itinerary.get("days", []):
        for item in day_data.get("items", []):
            itype = item.get("item_type", "")
            if itype in _valid_types:
                continue
            # 修正：restaurant → lunch（默认），如果时间在 17:00 后 → dinner
            if itype == "restaurant":
                start = item.get("start_time", "12:00")
                item["item_type"] = "dinner" if start >= "17:00" else "lunch"
            else:
                item["item_type"] = "attraction"  # 兜底


def _extract_places_from_itinerary(itinerary: dict) -> list[dict]:
    """从行程 items 中提取地点列表（用于修改后补全名称和重算路线）。

    优先级：_place 引用 → PlaceRepository 查找 → item 字段重建。
    """
    places: list[dict] = []
    seen: set[str] = set()

    # 预加载 PlaceRepository（一次性查所有可能需要的地点）
    repo_places: dict[str, dict] = {}
    try:
        from backend.app.repositories import PlaceRepository
        repo = PlaceRepository()
        for p in repo.list_attractions() + repo.list_hotels() + repo.list_restaurants():
            pd = p.to_dict()
            pid = pd.get("place_id", "")
            if pid:
                repo_places[pid] = pd
    except Exception:
        pass

    for day_data in itinerary.get("days", []):
        for item in day_data.get("items", []):
            pid = item.get("place_id") or ""
            if not pid or pid in seen:
                continue
            # 来源1: 已有的 _place 引用
            place = item.get("_place")
            if place and isinstance(place, dict) and place.get("place_id"):
                seen.add(pid)
                places.append(place)
                continue
            # 来源2: PlaceRepository 查找（新替换的地点从这里补全）
            if pid in repo_places:
                seen.add(pid)
                repo_place = repo_places[pid]
                places.append(repo_place)
                # 回写到 item，后续 enrichment 可用
                item["_place"] = repo_place
                continue
            # 来源3: 从 item 字段重建最小信息
            seen.add(pid)
            places.append({
                "place_id": pid,
                "name": item.get("note", ""),
                "place_type": item.get("item_type", ""),
            })
    return places


def _compute_itinerary_routes(itinerary: dict, places: list[dict]) -> None:
    """为行程中相邻地点之间计算实际距离和耗时。

    使用 Haversine 公式基于经纬度计算直线距离，并估算步行时长。
    修改是原地进行的（mutates itinerary dict）。

    策略：
    - 从 places 列表建立 place_id → 坐标的索引
    - 对每天逐对相邻项（有地点坐标的）计算直线距离
    - 将每日的总步行距离和每项的路线信息写入 itinerary
    """
    # ── 建立 place_id → (lat, lng) 索引 ─────────────────────────
    coord_map: dict[str, tuple[float, float]] = {}
    for p in places:
        pid = p.get("place_id", "")
        coord = p.get("coordinate", {}) or {}
        lat = coord.get("latitude")
        lng = coord.get("longitude")
        if pid and lat is not None and lng is not None:
            coord_map[pid] = (float(lat), float(lng))

    if not coord_map:
        return

    # ── 遍历每天，计算相邻项之间的距离 ─────────────────────────
    for day_data in itinerary.get("days", []):
        items = day_data.get("items", [])
        total_walking = 0.0
        prev_pid: str | None = None
        prev_coord: tuple[float, float] | None = None
        prev_item: dict | None = None

        for item in items:
            pid = item.get("place_id") or ""
            if not pid:
                continue

            coord = coord_map.get(pid)
            if coord is None:
                continue

            # 记录"从上一项到此"的路线
            if prev_coord is not None and prev_pid != pid:
                dist_m = _haversine_distance(prev_coord, coord)
                dur_min, mode = _travel_duration_minutes(dist_m)
                item["_route_from_prev_place_id"] = prev_pid
                item["_route_distance_m"] = round(dist_m, 1)
                item["_route_duration_minutes"] = dur_min
                item["_route_mode"] = mode
                # 前端可直接展示的路线文本
                if dist_m >= 1000:
                    item["route"] = f"{mode}约 {dur_min} 分钟 ({dist_m / 1000:.1f} 公里)"
                else:
                    item["route"] = f"{mode}约 {dur_min} 分钟 ({dist_m:.0f} 米)"
                # 仅步行路段计入步行距离
                if mode == "步行":
                    total_walking += dist_m
                # 将这段路线耗时写入上一个 item，供 _resequence_times 使用
                if prev_item is not None:
                    prev_item["_route_to_next_duration_minutes"] = dur_min

            prev_pid = pid
            prev_coord = coord
            prev_item = item

        # 更新每日步行总距离（仅步行路段，非公交/驾车），转为 int 匹配 schema
        day_data["walking_distance_m"] = int(round(total_walking)) if total_walking > 0 else 0

    # ── 用实际路线耗时重新计算时间轴 ─────────────────────────
    for day_data in itinerary.get("days", []):
        daily_start = day_data.get("start_time", "09:00")
        daily_end = day_data.get("end_time", "18:00")
        _resequence_times(day_data, daily_start, daily_end)


def _haversine_distance(
    coord1: tuple[float, float],
    coord2: tuple[float, float],
) -> float:
    """Haversine 公式计算两点间的地表距离（米）。"""
    lat1, lng1 = math.radians(coord1[0]), math.radians(coord1[1])
    lat2, lng2 = math.radians(coord2[0]), math.radians(coord2[1])
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return 6371000.0 * c  # 地球半径 ~6371km


def _travel_duration_minutes(distance_meters: float) -> tuple[int, str]:
    """根据距离智能估算交通耗时和方式。

    规则：
    - < 800m：步行，~80m/min
    - 800m ~ 5km：公交/骑行，~250m/min
    - > 5km：驾车/打车，~500m/min
    """
    if distance_meters < 800:
        return max(1, round(distance_meters / 80.0)), "步行"
    elif distance_meters < 5000:
        return max(1, round(distance_meters / 250.0)), "公交"
    else:
        return max(1, round(distance_meters / 500.0)), "驾车"


# ============================================================================
# 行程结构标准化 —— LLM 输出后处理
# ============================================================================


def _normalize_itinerary_structure(
    itinerary: dict, places: list[dict], requirements: dict
) -> dict:
    """对 LLM 生成的行程进行结构标准化。

    解决 LLM 输出常见的三个问题：
    1. 景点分配不均（某天 7 个、另一天 3 个）
    2. 缺少 hotel 项目
    3. 缺少 lunch/dinner 项目

    策略：
    - 保留 LLM 对景点的逐日分配（不全局打散重排）
    - 同一景点不会出现在多天（去重，保留首次出现）
    - 仅在严重不均衡时才跨天迁移景点
    - 每天按标准模板重建时间轴，同时保留 _place 引用和景点名称。
    修改是原地进行的（mutates itinerary dict）。
    """
    if not itinerary or not itinerary.get("days"):
        return itinerary

    days = itinerary["days"]
    days_count = len(days)
    if days_count == 0:
        return itinerary

    # ── 构建 place_id → place 索引（用于补全名称） ──────────────
    place_map: dict[str, dict] = {}
    for p in places:
        pid = p.get("place_id", "")
        if pid:
            place_map[pid] = p

    # 按类型分类 places
    hotel = next((p for p in places if p.get("place_type") == "hotel"), None)
    restaurants = [p for p in places if p.get("place_type") == "restaurant"]

    daily_start = requirements.get("daily_start_time", "09:00") or "09:00"
    daily_end = requirements.get("daily_end_time", "18:00") or "18:00"
    people = requirements.get("people", 1) or 1

    # ── 1. 收集每天景点 + 去重 + 保留每日框架信息 ───────────────
    day_attrs_list: list[list[dict]] = []
    seen_place_ids: set[str] = set()

    for day_data in days:
        dep_place_id = None
        ret_place_id = None
        day_attrs: list[dict] = []

        for it in day_data.get("items", []):
            itype = it.get("item_type", "")
            if itype == "departure":
                dep_place_id = it.get("place_id")
            elif itype == "return":
                ret_place_id = it.get("place_id")
            elif itype == "attraction":
                pid = it.get("place_id", "")
                # 去重：同一景点只保留在第一次出现的天
                if pid and pid in seen_place_ids:
                    continue
                if pid:
                    seen_place_ids.add(pid)
                # 补全 _place 引用（如果还没有）
                if not it.get("_place") and pid in place_map:
                    it["_place"] = place_map[pid]
                day_attrs.append(it)

        day_data["_dep_place_id"] = dep_place_id
        day_data["_ret_place_id"] = ret_place_id
        day_attrs_list.append(day_attrs)

        # 保留原有 lunch/dinner 的 place_id（如果 LLM 选了的话）
        for meal_type in ("lunch", "dinner"):
            for it in day_data.get("items", []):
                if it.get("item_type") == meal_type:
                    day_data[f"_{meal_type}_place_id"] = it.get("place_id")
                    break

    # ── 2. LLM 数据质量检测 + 兜底替换 ────────────────────────
    # 统计 LLM 输出的景点中有多少 place_id 是有效的（能匹配到 place_map）
    valid_attrs_count = sum(
        1 for attrs in day_attrs_list
        for a in attrs
        if a.get("place_id") and a.get("place_id") in place_map
    )
    total_attrs = sum(len(attrs) for attrs in day_attrs_list)

    # 如果 LLM 输出的景点全部或大部分无法匹配到推荐地点，
    # 说明 LLM 没有正确输出 place_id，直接使用推荐列表中的真实景点替换
    real_attractions = [
        p for p in places
        if p.get("place_type") == "attraction" and p.get("place_id")
    ]
    if total_attrs == 0 or valid_attrs_count < max(1, total_attrs // 2):
        import logging
        _logger = logging.getLogger(__name__)
        _logger.warning(
            "LLM 输出的景点 place_id 匹配率过低 (%d/%d)，"
            "使用推荐列表中的 %d 个真实景点替换",
            valid_attrs_count, total_attrs, len(real_attractions),
        )
        # 将真实景点均匀分配到每天
        day_attrs_list = [[] for _ in range(days_count)]
        seen_place_ids.clear()
        for i, p in enumerate(real_attractions):
            day_idx = i % days_count
            # 注意：不能设置 p["_place"] = p，会导致循环引用使 JSON 序列化崩溃
            day_attrs_list[day_idx].append(dict(p))
            seen_place_ids.add(p.get("place_id", ""))
        total_attrs = len(real_attractions)

    # ── 3. 检测并修复严重不均衡 ────────────────────────────────
    if total_attrs > 0 and days_count > 1:
        max_count = max(len(attrs) for attrs in day_attrs_list)
        min_count = min(len(attrs) for attrs in day_attrs_list)
        # 严重不均衡：最多的一天是最少一天的 2 倍以上，且差值 > 2
        if max_count > min_count * 2 and max_count - min_count > 2:
            # 从最多的一天移动景点到最少的一天
            max_day_idx = max(
                range(days_count), key=lambda i: len(day_attrs_list[i])
            )
            min_day_idx = min(
                range(days_count), key=lambda i: len(day_attrs_list[i])
            )
            move_count = (len(day_attrs_list[max_day_idx]) - len(day_attrs_list[min_day_idx])) // 2
            moved = day_attrs_list[max_day_idx][-move_count:]
            day_attrs_list[max_day_idx] = day_attrs_list[max_day_idx][:-move_count]
            # 插入到最前面（让最少天有一些景点）
            day_attrs_list[min_day_idx] = moved + day_attrs_list[min_day_idx]

    # ── 4. 按标准模板重建每天的 items ──────────────────────────
    used_restaurant_ids: set[str] = set()  # 跨天追踪已用餐厅，避免重复
    for day_idx, day_data in enumerate(days):
        # 强制按数组位置设置 day 编号，避免 LLM 输出错误的 day 值导致前端显示混乱
        day_num = day_idx + 1
        day_data["day"] = day_num
        day_attrs = day_attrs_list[day_idx]

        # 上午/下午拆分：ceil(n/2) 上午，floor(n/2) 下午
        n = len(day_attrs)
        morning_count = (n + 1) // 2
        morning_attrs = day_attrs[:morning_count]
        afternoon_attrs = day_attrs[morning_count:]

        hotel_place_id = hotel.get("place_id", "") if hotel else ""
        dep_pid = day_data.pop("_dep_place_id", None) or hotel_place_id
        ret_pid = day_data.pop("_ret_place_id", None) or hotel_place_id

        new_items: list[dict] = []
        item_idx = 0

        # --- departure ---
        new_items.append({
            "item_id": f"day{day_num}_item_{item_idx:03d}",
            "day": day_num,
            "item_type": "departure",
            "place_id": dep_pid,
            "start_time": daily_start,
            "end_time": daily_start,
            "duration_minutes": 0,
            "cost_per_person": 0,
            "total_cost": 0,
            "locked": True,
            "note": f"从{(hotel or {}).get('name', '酒店')}出发",
        })
        item_idx += 1

        # --- hotel ---
        if hotel:
            hotel_price = float(hotel.get("price", 0) or 0)
            new_items.append({
                "item_id": f"day{day_num}_item_{item_idx:03d}",
                "day": day_num,
                "item_type": "hotel",
                "place_id": hotel_place_id,
                "start_time": daily_start,
                "end_time": daily_end,
                "duration_minutes": 0,
                "cost_per_person": hotel_price,
                "total_cost": hotel_price * people,
                "locked": False,
                "note": hotel.get("name", "酒店"),
            })
            item_idx += 1

        # --- morning attractions ---
        for attr in morning_attrs:
            dur = attr.get("duration_minutes") or 90
            # 兼容 LLM 输出 (cost_per_person) 和 Place 字典 (price)
            price = float(
                attr.get("cost_per_person")
                or attr.get("price")
                or 0
            )
            # 补全景点名称：优先 note → _place.name → place_map 查找
            place = attr.get("_place") or place_map.get(attr.get("place_id", ""), {})
            note = (
                attr.get("note")
                or place.get("name")
                or place.get("short_description", "")
            )
            new_items.append({
                "item_id": f"day{day_num}_item_{item_idx:03d}",
                "day": day_num,
                "item_type": "attraction",
                "place_id": attr.get("place_id", ""),
                "start_time": "",
                "end_time": "",
                "duration_minutes": dur,
                "cost_per_person": price,
                "total_cost": price * people,
                "locked": attr.get("locked", False),
                "note": note,
                "_place": attr.get("_place") or place or None,
            })
            item_idx += 1

        # --- lunch (only if there are attractions) ---
        if n > 0:
            lunch_place_id = day_data.pop("_lunch_place_id", None)
            lunch = _pick_best_restaurant(restaurants, "lunch", used_restaurant_ids)
            lunch_price = float(lunch.get("price", 0) or 0) if lunch else 0
            lunch_pid = lunch_place_id or (lunch.get("place_id", "") if lunch else "")
            if lunch_pid:
                used_restaurant_ids.add(lunch_pid)
            new_items.append({
                "item_id": f"day{day_num}_item_{item_idx:03d}",
                "day": day_num,
                "item_type": "lunch",
                "place_id": lunch_pid,
                "start_time": "",
                "end_time": "",
                "duration_minutes": 60,
                "cost_per_person": lunch_price,
                "total_cost": lunch_price * people,
                "locked": False,
                "note": lunch.get("name", "") if lunch else "午餐（未指定餐厅）",
                "_place": lunch or None,
            })
            item_idx += 1

        # --- afternoon attractions ---
        for attr in afternoon_attrs:
            dur = attr.get("duration_minutes") or 90
            price = float(
                attr.get("cost_per_person")
                or attr.get("price")
                or 0
            )
            place = attr.get("_place") or place_map.get(attr.get("place_id", ""), {})
            note = (
                attr.get("note")
                or place.get("name")
                or place.get("short_description", "")
            )
            new_items.append({
                "item_id": f"day{day_num}_item_{item_idx:03d}",
                "day": day_num,
                "item_type": "attraction",
                "place_id": attr.get("place_id", ""),
                "start_time": "",
                "end_time": "",
                "duration_minutes": dur,
                "cost_per_person": price,
                "total_cost": price * people,
                "locked": attr.get("locked", False),
                "note": note,
                "_place": attr.get("_place") or place or None,
            })
            item_idx += 1

        # --- dinner (只有下午有景点时才添加) ---
        if afternoon_attrs:
            dinner_place_id = day_data.pop("_dinner_place_id", None)
            dinner = _pick_best_restaurant(restaurants, "dinner", used_restaurant_ids)
            dinner_price = float(dinner.get("price", 0) or 0) if dinner else 0
            dinner_pid = dinner_place_id or (dinner.get("place_id", "") if dinner else "")
            if dinner_pid:
                used_restaurant_ids.add(dinner_pid)
            new_items.append({
                "item_id": f"day{day_num}_item_{item_idx:03d}",
                "day": day_num,
                "item_type": "dinner",
                "place_id": dinner_pid,
                "start_time": "",
                "end_time": "",
                "duration_minutes": 60,
                "cost_per_person": dinner_price,
                "total_cost": dinner_price * people,
                "locked": False,
                "note": dinner.get("name", "") if dinner else "晚餐（未指定餐厅）",
                "_place": dinner or None,
            })
            item_idx += 1

        # --- return ---
        new_items.append({
            "item_id": f"day{day_num}_item_{item_idx:03d}",
            "day": day_num,
            "item_type": "return",
            "place_id": ret_pid,
            "start_time": "",
            "end_time": "",
            "duration_minutes": 15,
            "cost_per_person": 0,
            "total_cost": 0,
            "locked": True,
            "note": "返回酒店",
        })

        day_data["items"] = new_items

    # ── 5. 重新计算时间 ────────────────────────────────────────
    for day_data in days:
        _resequence_times(day_data, daily_start, daily_end)

    # ── 6. 更新每日统计 ────────────────────────────────────────
    for day_data in days:
        items = day_data.get("items", [])
        day_data["daily_cost"] = round(
            sum(float(it.get("total_cost", 0) or 0) for it in items), 2
        )
        # 步行距离：保留原值；若为 0 则按景点数量估算（每景点 ~800m）
        orig_walking = day_data.get("walking_distance_m", 0) or 0
        if orig_walking == 0:
            attr_count = sum(
                1 for it in items if it.get("item_type") == "attraction"
            )
            orig_walking = attr_count * 800
        day_data["walking_distance_m"] = orig_walking
        if items:
            day_data["start_time"] = items[0].get("start_time", daily_start)
            day_data["end_time"] = items[-1].get("end_time", daily_end)

    # 更新总费用
    itinerary["total_cost"] = round(
        sum(d.get("daily_cost", 0) for d in days), 2
    )

    return itinerary


def _pick_best_restaurant(
    restaurants: list[dict],
    meal_type: str,
    exclude_ids: set[str] | None = None,
) -> dict | None:
    """从餐厅列表中选择一个合适的，优先排除已用过的。"""
    if not restaurants:
        return None
    exclude = exclude_ids or set()
    # 优先选 meal_type 匹配且未用过的
    matching = [r for r in restaurants if r.get("meal_type") == meal_type]
    candidates = matching if matching else restaurants
    # 先选未用过的，再选用过的（但避免完全相同的）
    fresh = [r for r in candidates if r.get("place_id", "") not in exclude]
    if fresh:
        return fresh[0]
    # 都用过了，选与排除列表中最不重复的（如果 candidates 够多，取第二个）
    if len(candidates) > 1:
        for r in candidates:
            if r.get("place_id", "") not in exclude:
                return r
    return candidates[0] if candidates else None


def _resequence_times(
    day_data: dict, daily_start: str, daily_end: str
) -> None:
    """重新计算每项的时间，确保时间连续合理。

    规则：
    - departure 固定出发时间
    - attraction 每项 90-120 分钟 + 15 分钟缓冲
    - lunch/dinner 各 60 分钟
    - hotel 跨越整天
    - rest 弹性调整
    - return 固定返回时间
    """
    items = day_data.get("items", [])
    if not items:
        return

    # 解析时间
    def _parse(t: str) -> int:
        try:
            h, m = map(int, t.split(":"))
            return h * 60 + m
        except (ValueError, AttributeError):
            return 0

    def _fmt(minutes: int) -> str:
        h = (minutes // 60) % 24
        m = minutes % 60
        return f"{h:02d}:{m:02d}"

    current = _parse(daily_start)
    end_limit = _parse(daily_end)

    for idx, item in enumerate(items):
        itype = item.get("item_type", "")

        if itype == "departure":
            item["start_time"] = _fmt(current)
            item["end_time"] = _fmt(current)
            item["duration_minutes"] = 0
            # 出发后留 15 分钟缓冲，避免第一个景点与出发时间重叠
            current = current + 15
        elif itype == "hotel":
            # 酒店费用项：不占时间槽，放在返程之前显示
            # current 此时处于 dinner 之后、return 之前
            item["start_time"] = _fmt(current)
            item["end_time"] = _fmt(current)
            item["duration_minutes"] = 0
        elif itype == "attraction":
            dur = item.get("duration_minutes") or 90
            item["start_time"] = _fmt(current)
            item["end_time"] = _fmt(current + dur)
            item["duration_minutes"] = dur
            # 缓冲：优先使用已计算的路线耗时，否则 15 分钟默认
            buffer = int(item.get("_route_to_next_duration_minutes", 0) or 0)
            if buffer <= 0:
                buffer = 15
            current = current + dur + buffer
        elif itype in ("lunch", "dinner"):
            dur = 60
            if itype == "lunch":
                earliest = _parse("11:30")
            else:
                earliest = _parse("17:30")
            # 只向前钳制（若还没到用餐窗口），不向后倒退
            if current < earliest:
                current = earliest
            item["start_time"] = _fmt(current)
            item["end_time"] = _fmt(current + dur)
            item["duration_minutes"] = dur
            current = current + dur + 5
        elif itype == "rest":
            # 弹性休息：如果时间充裕则休息久一点
            remaining = max(30, end_limit - current - 30)
            dur = min(remaining, 90)
            item["start_time"] = _fmt(current)
            item["end_time"] = _fmt(current + dur)
            item["duration_minutes"] = dur
            current = current + dur
        elif itype == "return":
            # return 尽量靠近 daily_end，但至少保证 15 分钟
            ret_start = max(current, end_limit - 15)
            ret_end = max(ret_start + 15, end_limit)
            item["start_time"] = _fmt(ret_start)
            item["end_time"] = _fmt(ret_end)
            item["duration_minutes"] = max(15, ret_end - ret_start)
        else:
            # transport / 其他
            dur = item.get("duration_minutes") or 15
            item["start_time"] = _fmt(current)
            item["end_time"] = _fmt(current + dur)
            current = current + dur + 5

    # 按 start_time 排序，保证时间线始终按时间递增展示
    day_data["items"].sort(key=lambda it: it.get("start_time", "00:00"))

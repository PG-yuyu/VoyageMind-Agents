"""
行程规划 Agent 主控
===================

LMM 主导 + 规则循环的行程规划 Agent。

工作流程:
  1. LLM 理解行程层面隐含偏好 → 生成 ItineraryPlanningPolicy
  2. LLM 组合每日地点、顺序和节奏 → 初始行程草稿
  3. Python 工具计算路线、费用和时间 → 充实行程
  4. HardConstraintValidator 校验硬约束
     - 不通过 → LLM 修复（最多 2 次）→ 回到步骤 3
  5. ItineraryPreferenceCritic 评价软偏好
     - 不满足 → LLM 优化（最多 1 次）→ 回到步骤 4
  6. 输出最终 PlanningAgentResult
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

from agents.planning_state import PlanningPhase, PlanningState
from agents.itinerary_preference_critic import ItineraryPreferenceCritic

from prompts.planning_preference_interpretation_prompt import (
    PLANNING_PREFERENCE_INTERPRETATION_PROMPT,
)
from prompts.itinerary_planning_prompt import ITINERARY_PLANNING_PROMPT
from prompts.hard_constraint_repair_prompt import HARD_CONSTRAINT_REPAIR_PROMPT
from prompts.soft_preference_optimization_prompt import (
    SOFT_PREFERENCE_OPTIMIZATION_PROMPT,
)

from schemas.planning_policy import ItineraryPlanningPolicy
from schemas.preference_evaluation import SoftPreferenceEvaluation

from services.budget_service import calculate_budget
from services.version_service import save_version, clone_for_modification, lock_all_items
from validators.hard_constraint_validator import (
    validate_hard_constraints,
    enrich_items_with_places,
)

logger = logging.getLogger(__name__)


class PlanningAgent:
    """行程规划 Agent —— LLM 主导 + 规则循环。"""

    def __init__(
        self,
        llm_callable: Callable[[str], str],
        preference_critic: ItineraryPreferenceCritic | None = None,
    ):
        """
        Args:
            llm_callable: LLM 调用函数，签名 (prompt: str) -> str
            preference_critic: 软偏好评价器，不传则使用默认实例
        """
        self._llm = llm_callable
        self._critic = preference_critic or ItineraryPreferenceCritic(llm_callable)

    # ====================================================================
    # 主入口
    # ====================================================================

    def plan(
        self,
        requirements: dict[str, Any],
        places: list[dict[str, Any]],
        routes: list[dict[str, Any]] | None = None,
        hard_constraints: list[dict[str, Any]] | None = None,
        semantic_preferences: list[dict[str, Any]] | None = None,
        recommendation_context: dict[str, Any] | None = None,
        recommendation_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """执行完整行程规划流程。

        Args:
            requirements: TravelRequest 字典
            places: 候选地点列表（景点 + 酒店 + 餐厅）
            routes: 路线列表
            hard_constraints: 明确硬约束
            semantic_preferences: 隐含偏好
            recommendation_context: 完整推荐上下文
            recommendation_policy: 推荐策略

        Returns:
            PlanningAgentResult 字典:
            {
                "itinerary": Itinerary,
                "planning_policy": ItineraryPlanningPolicy,
                "budget": BudgetSummary,
                "hard_evaluation": HardConstraintEvaluation,
                "soft_evaluation": SoftPreferenceEvaluation,
                "trip_diff": None,
                "need_follow_up": False,
                "agent_trace": [...]
            }
        """
        # ── 初始化状态 ──────────────────────────────────────────────
        state = PlanningState(
            session_id=requirements.get("session_id", ""),
            requirements=requirements,
            recommendation_context=recommendation_context or {},
            recommendation_policy=recommendation_policy or {},
            places=places,
            routes=routes or [],
            hard_constraints=hard_constraints or [],
            semantic_preferences=semantic_preferences or [],
        )

        try:
            # ── Step 1: 偏好解释 → PlanningPolicy ──────────────────
            state.transition_to(PlanningPhase.PREFERENCE_INTERPRETATION)
            planning_policy = self._interpret_preferences(state)
            state.planning_policy = planning_policy

            # ── Step 2: 生成初始行程 ────────────────────────────────
            state.transition_to(PlanningPhase.ITINERARY_PLANNING)
            itinerary = self._plan_itinerary(state)
            state.itinerary = itinerary

            # ── Step 3: 硬约束校验 + 修复循环 ──────────────────────
            state.transition_to(PlanningPhase.HARD_VALIDATING)
            hard_ok = self._hard_validation_loop(state)
            if not hard_ok:
                state.add_error("硬约束修复达到最大次数仍未通过")
                return self._build_result(state)

            # ── Step 4: 软偏好评价 + 优化循环 ──────────────────────
            state.transition_to(PlanningPhase.SOFT_EVALUATING)
            soft_ok = self._soft_optimization_loop(state)
            if not soft_ok:
                logger.warning(
                    "软偏好优化达到最大次数，以当前结果输出"
                )

            # ── Step 5: 完成 ────────────────────────────────────────
            state.transition_to(PlanningPhase.COMPLETED)

            # 保存首版行程
            try:
                itinerary_id = state.itinerary.get("itinerary_id", "")
                if itinerary_id:
                    from schemas.itinerary import Itinerary
                    itinerary_obj = Itinerary(**state.itinerary)
                    save_version(itinerary_obj)
            except Exception as exc:
                logger.warning("保存行程版本失败: %s", exc)

            return self._build_result(state)

        except Exception as exc:
            logger.exception("规划过程异常")
            state.add_error(f"规划异常: {exc}")
            return self._build_result(state)

    # ====================================================================
    # Step 1: 偏好解释
    # ====================================================================

    def _interpret_preferences(self, state: PlanningState) -> dict[str, Any]:
        """LLM 理解行程层面隐含偏好，生成规划策略。"""
        req = state.requirements
        sp = state.semantic_preferences
        rp = state.recommendation_policy or {}

        # 统计资源
        attractions = [p for p in state.places if p.get("place_type") == "attraction"]
        hotels = [p for p in state.places if p.get("place_type") == "hotel"]
        restaurants = [p for p in state.places if p.get("place_type") == "restaurant"]

        pref_lines = []
        for p in sp:
            pref_lines.append(
                f"- {p.get('text', '')} (scope: {p.get('scope', 'overall')})"
            )
        pref_str = "\n".join(pref_lines) if pref_lines else "（无）"

        prompt = PLANNING_PREFERENCE_INTERPRETATION_PROMPT.format(
            original_text=req.get("original_text", "（无）"),
            conversation_context=json.dumps(
                req.get("conversation_context", []), ensure_ascii=False
            ),
            city=req.get("city", "未知"),
            days=req.get("days", 1),
            people=req.get("people", 1),
            total_budget=req.get("total_budget", 0),
            interests=req.get("interests", []),
            travel_pace=req.get("travel_pace", "normal"),
            semantic_preferences=pref_str,
            recommendation_policy=json.dumps(rp, ensure_ascii=False, indent=2),
            attraction_count=len(attractions),
            hotel_count=len(hotels),
            restaurant_count=len(restaurants),
        )

        raw = self._llm(prompt)
        data = self._parse_json(raw)

        # 验证并转换为 ItineraryPlanningPolicy
        try:
            policy = ItineraryPlanningPolicy(**data)
            return policy.model_dump()
        except Exception as exc:
            logger.warning("Policy 解析失败，使用默认值: %s", exc)
            return ItineraryPlanningPolicy().model_dump()

    # ====================================================================
    # Step 2: 生成初始行程
    # ====================================================================

    def _plan_itinerary(self, state: PlanningState) -> dict[str, Any]:
        """LLM 生成初始行程。"""
        req = state.requirements
        policy = state.planning_policy or {}
        sp = state.semantic_preferences

        # 准备资源描述
        attractions = [p for p in state.places if p.get("place_type") == "attraction"]
        hotels = [p for p in state.places if p.get("place_type") == "hotel"]
        restaurants = [p for p in state.places if p.get("place_type") == "restaurant"]

        # 格式化景点信息
        attr_lines = []
        for i, a in enumerate(attractions, 1):
            attr_lines.append(
                f"  {i}. {a.get('name', '?')} (ID: {a.get('place_id', '?')}) "
                f"| 门票: ¥{a.get('price', 0)} | 建议时长: {a.get('duration_minutes', 120)}分 "
                f"| 开放: {a.get('open_time', '?')}-{a.get('close_time', '?')} "
                f"| 兴趣: {a.get('categories', [])} "
                f"| 室内: {a.get('indoor', '?')}"
            )
        attrs_str = "\n".join(attr_lines) if attr_lines else "（无景点推荐）"

        hotel_lines = []
        for i, h in enumerate(hotels, 1):
            hotel_lines.append(
                f"  {i}. {h.get('name', '?')} (ID: {h.get('place_id', '?')}) "
                f"| ¥{h.get('price', 0)}/晚 | {h.get('address', '')}"
            )
        hotels_str = "\n".join(hotel_lines) if hotel_lines else "（无酒店推荐）"

        rest_lines = []
        for i, r in enumerate(restaurants, 1):
            rest_lines.append(
                f"  {i}. {r.get('name', '?')} (ID: {r.get('place_id', '?')}) "
                f"| 人均: ¥{r.get('price', 0)} | {r.get('categories', [])}"
            )
        rests_str = "\n".join(rest_lines) if rest_lines else "（无餐厅推荐）"

        route_str = json.dumps(state.routes, ensure_ascii=False, indent=2) if state.routes else "（无路线数据）"

        pref_lines = []
        for p in sp:
            pref_lines.append(f"- {p.get('text', '')}")
        pref_str = "\n".join(pref_lines) if pref_lines else "（无）"

        prompt = ITINERARY_PLANNING_PROMPT.format(
            daily_themes=json.dumps(policy.get("daily_themes", []), ensure_ascii=False),
            pace_strategy=policy.get("pace_strategy", "normal"),
            combination_rationale=policy.get("combination_rationale", ""),
            priority_order=json.dumps(policy.get("priority_order", []), ensure_ascii=False),
            buffer_minutes=policy.get("buffer_minutes", 15),
            city=req.get("city", "未知"),
            days=req.get("days", 1),
            people=req.get("people", 1),
            daily_start=req.get("daily_start_time", "09:00"),
            daily_end=req.get("daily_end_time", "18:00"),
            walking_limit_m=req.get("walking_limit_m", 99999),
            transport_modes=req.get("transport_modes", ["walking"]),
            attractions=attrs_str,
            hotels=hotels_str,
            restaurants=rests_str,
            routes=route_str,
            semantic_preferences=pref_str,
        )

        raw = self._llm(prompt)
        data = self._parse_json(raw)

        # 构建标准行程结构
        itinerary = self._build_itinerary_dict(data, req)
        return itinerary

    # ====================================================================
    # Step 3: 硬约束校验 + 修复循环
    # ====================================================================

    def _hard_validation_loop(self, state: PlanningState) -> bool:
        """硬约束校验 + LLM 修复（最多 max_repairs 次）。"""
        while state.can_repair():
            # 注入 _place 引用
            it = state.itinerary
            if it and state.places:
                enrich_items_with_places(it, state.places)

            # 校验
            evaluation = validate_hard_constraints(it, state.requirements)
            state.hard_evaluation = evaluation.model_dump()

            if evaluation.passed:
                logger.info("硬约束校验通过")
                return True

            # 记录修复次数
            state.repair_count += 1
            if not state.can_repair():
                logger.warning("硬约束修复次数已达上限 (%d)", state.max_repairs)
                return False

            # LLM 修复
            logger.info(
                "硬约束校验未通过 (%d issues)，开始第 %d 次修复",
                len(evaluation.issues),
                state.repair_count,
            )
            state.transition_to(PlanningPhase.HARD_REPAIRING)
            state.itinerary = self._repair_itinerary(state)

        return False

    def _repair_itinerary(self, state: PlanningState) -> dict[str, Any]:
        """LLM 修复行程中的硬约束问题。"""
        prompt = HARD_CONSTRAINT_REPAIR_PROMPT.format(
            current_itinerary=json.dumps(state.itinerary, ensure_ascii=False, indent=2),
            validation_issues=json.dumps(
                state.hard_evaluation.get("issues", []),
                ensure_ascii=False,
                indent=2,
            ),
            places=json.dumps(state.places, ensure_ascii=False, indent=2),
        )
        raw = self._llm(prompt)
        data = self._parse_json(raw)
        # 合并回行程主体
        if "days" in data:
            state.itinerary["days"] = data["days"]
        return state.itinerary

    # ====================================================================
    # Step 4: 软偏好评价 + 优化循环
    # ====================================================================

    def _soft_optimization_loop(self, state: PlanningState) -> bool:
        """软偏好评价 + LLM 优化（最多 max_optimizes 次）。"""
        while state.can_optimize():
            evaluation = self._critic.evaluate(
                itinerary=state.itinerary,
                requirements=state.requirements,
                semantic_preferences=state.semantic_preferences,
                hard_constraint_result=state.hard_evaluation,
            )
            state.soft_evaluation = evaluation.model_dump()

            if evaluation.soft_preference_passed:
                logger.info("软偏好评价通过")
                return True

            state.optimize_count += 1
            if not state.can_optimize():
                logger.warning("软偏好优化次数已达上限 (%d)", state.max_optimizes)
                return False

            logger.info(
                "软偏好未通过 (%d issues)，开始第 %d 次优化",
                len(evaluation.issues),
                state.optimize_count,
            )
            state.transition_to(PlanningPhase.SOFT_OPTIMIZING)
            state.itinerary = self._optimize_itinerary(state)

        return False

    def _optimize_itinerary(self, state: PlanningState) -> dict[str, Any]:
        """LLM 优化行程中的软偏好问题。"""
        prompt = SOFT_PREFERENCE_OPTIMIZATION_PROMPT.format(
            current_itinerary=json.dumps(state.itinerary, ensure_ascii=False, indent=2),
            preference_evaluation=json.dumps(
                state.soft_evaluation.get("issues", []),
                ensure_ascii=False,
                indent=2,
            ),
            places=json.dumps(state.places, ensure_ascii=False, indent=2),
        )
        raw = self._llm(prompt)
        data = self._parse_json(raw)
        if "days" in data:
            state.itinerary["days"] = data["days"]
        return state.itinerary

    # ====================================================================
    # 结果构建
    # ====================================================================

    def _build_result(self, state: PlanningState) -> dict[str, Any]:
        """构建最终输出。"""
        # 计算预算
        budget = None
        if state.itinerary:
            try:
                budget = calculate_budget(
                    state.itinerary, state.requirements
                ).model_dump()
            except Exception as exc:
                logger.warning("预算计算失败: %s", exc)

        return {
            "itinerary": state.itinerary,
            "planning_policy": state.planning_policy,
            "budget": budget,
            "hard_evaluation": state.hard_evaluation,
            "soft_evaluation": state.soft_evaluation,
            "trip_diff": None,  # 初次规划无 diff
            "need_follow_up": bool(state.errors),
            "follow_up_message": state.errors[-1] if state.errors else None,
            "agent_trace": state.trace_steps,
            "phase": state.phase.value,
        }

    # ====================================================================
    # 辅助
    # ====================================================================

    def _build_itinerary_dict(
        self, data: dict, requirements: dict
    ) -> dict[str, Any]:
        """构建标准行程字典（自动补全 LLM 输出缺失的必填字段）。"""
        import uuid

        total_cost = data.get("total_cost_estimate", 0) or 0

        days = []
        for day_data in data.get("days", []):
            day_num = day_data.get("day", 1)
            raw_items = day_data.get("items", [])

            # 补全每个 item 的必填字段
            items = []
            for idx, it in enumerate(raw_items):
                item_id = it.get("item_id") or f"day{day_num}_item_{idx:03d}"
                items.append({
                    "item_id": item_id,
                    "day": day_num,
                    "item_type": it.get("item_type", "attraction"),
                    "place_id": it.get("place_id"),
                    "start_time": it.get("start_time", "09:00"),
                    "end_time": it.get("end_time", "10:00"),
                    "duration_minutes": it.get("duration_minutes", 60) or 60,
                    "route_from_previous_id": it.get("route_from_previous_id"),
                    "cost_per_person": float(it.get("cost_per_person", 0) or 0),
                    "total_cost": float(it.get("total_cost", 0) or 0),
                    "locked": it.get("locked", False),
                    "note": it.get("note"),
                })

            daily_cost = sum(float(it["total_cost"]) for it in items)
            walking = day_data.get("walking_distance_m", 0) or 0
            days.append({
                "day": day_num,
                "date": day_data.get("date", ""),
                "items": items,
                "daily_cost": round(daily_cost, 2),
                "walking_distance_m": walking,
                "start_time": items[0]["start_time"] if items else "09:00",
                "end_time": items[-1]["end_time"] if items else "18:00",
            })

        return {
            "itinerary_id": f"trip_{uuid.uuid4().hex[:8]}",
            "session_id": requirements.get("session_id", ""),
            "version": 1,
            "parent_version": None,
            "requirements_snapshot": requirements,
            "days": days,
            "hotel_place_id": None,
            "total_cost": round(total_cost, 2),
            "status": "draft",
        }

    def _parse_json(self, raw: str) -> dict:
        """解析 LLM 返回的 JSON，处理 markdown 代码块包裹。"""
        text = raw.strip()
        if text.startswith("```"):
            first_nl = text.index("\n")
            start = first_nl + 1
            end = text.rfind("```")
            if end > start:
                text = text[start:end].strip()
            else:
                text = text[first_nl + 1:].strip()
        return json.loads(text)

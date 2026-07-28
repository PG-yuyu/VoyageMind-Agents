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
import re
from typing import Any, Callable

from backend.agents.planning_state import PlanningPhase, PlanningState
from backend.agents.itinerary_preference_critic import ItineraryPreferenceCritic

from backend.prompts.planning_preference_interpretation_prompt import (
    PLANNING_PREFERENCE_INTERPRETATION_PROMPT,
)
from backend.prompts.itinerary_planning_prompt import ITINERARY_PLANNING_PROMPT
from backend.prompts.hard_constraint_repair_prompt import HARD_CONSTRAINT_REPAIR_PROMPT
from backend.prompts.soft_preference_optimization_prompt import (
    SOFT_PREFERENCE_OPTIMIZATION_PROMPT,
)

from backend.schemas.planning_policy import ItineraryPlanningPolicy
from backend.schemas.preference_evaluation import SoftPreferenceEvaluation

from backend.services.budget_service import calculate_budget
from backend.services.version_service import save_version, clone_for_modification, lock_all_items
from backend.validators.hard_constraint_validator import (
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
        max_repairs: int = 0,
        max_optimizes: int = 0,
    ):
        """
        Args:
            llm_callable: LLM 调用函数，签名 (prompt: str) -> str
            preference_critic: 软偏好评价器，不传则使用默认实例
            max_repairs: 硬约束 LLM 修复轮数。默认 0，优先保证生成速度
            max_optimizes: 软偏好 LLM 优化轮数。默认 0，优先保证生成速度
        """
        self._llm = llm_callable
        self._critic = preference_critic or ItineraryPreferenceCritic(llm_callable)
        self.max_repairs = max(0, max_repairs)
        self.max_optimizes = max(0, max_optimizes)

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
        state.max_repairs = self.max_repairs
        state.max_optimizes = self.max_optimizes

        try:
            # ── Step 1: 生成初始行程 ────────────────────────────────
            state.transition_to(PlanningPhase.ITINERARY_PLANNING)
            itinerary = self._plan_itinerary(state)
            state.itinerary = itinerary

            # ── Step 2: 硬约束校验 + 修复循环（最多 2 次） ──────────
            state.transition_to(PlanningPhase.HARD_VALIDATING)
            hard_passed = self._hard_validation_loop(state)
            if not hard_passed:
                logger.warning(
                    "硬约束修复未完全通过: %d issues",
                    len(state.hard_evaluation.get("issues", [])),
                )

            # ── Step 3: 软偏好评价 + 优化循环（最多 1 次） ──────────
            if hard_passed or state.itinerary:
                state.transition_to(PlanningPhase.SOFT_EVALUATING)
                soft_passed = self._soft_optimization_loop(state)
                if not soft_passed:
                    logger.warning(
                        "软偏好优化未完全通过: %d issues",
                        len(state.soft_evaluation.get("issues", [])),
                    )

            # ── Step 4: 完成 ────────────────────────────────────────
            state.transition_to(PlanningPhase.COMPLETED)

            # 保存首版行程
            try:
                itinerary_id = state.itinerary.get("itinerary_id", "")
                if itinerary_id:
                    from backend.schemas.itinerary import Itinerary
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
        """LLM 仅输出核心决策（选景点+排序+理由），Python 补全所有结构化字段。"""
        req = state.requirements
        policy = state.planning_policy or {}
        sp = state.semantic_preferences

        # 缓存 places 供 _build_itinerary_dict 使用
        self._current_places = state.places

        # 准备资源描述
        attractions = [p for p in state.places if p.get("place_type") == "attraction"]
        hotels = [p for p in state.places if p.get("place_type") == "hotel"]
        restaurants = [p for p in state.places if p.get("place_type") == "restaurant"]

        # 格式化景点信息：ID + 名称 + 价格 + 区域 + 时长
        attr_lines = []
        for i, a in enumerate(attractions, 1):
            area = a.get('area', '') or ''
            attr_lines.append(
                f"  {i}. {a.get('name', '?')} (ID: {a.get('place_id', '?')}) "
                f"| ¥{a.get('price', 0)} | {area} | {a.get('duration_minutes', 90)}分"
            )
        attrs_str = "\n".join(attr_lines) if attr_lines else "（无景点推荐）"

        hotel_lines = []
        for i, h in enumerate(hotels, 1):
            hotel_lines.append(
                f"  {i}. {h.get('name', '?')} (ID: {h.get('place_id', '?')}) "
                f"| ¥{h.get('price', 0)}/晚"
            )
        hotels_str = "\n".join(hotel_lines) if hotel_lines else "（无酒店推荐）"

        rest_lines = []
        for i, r in enumerate(restaurants, 1):
            rest_lines.append(
                f"  {i}. {r.get('name', '?')} (ID: {r.get('place_id', '?')}) "
                f"| 人均 ¥{r.get('price', 0)}"
            )
        rests_str = "\n".join(rest_lines) if rest_lines else "（无餐厅推荐）"

        pref_lines = []
        for p in sp:
            pref_lines.append(f"- {p.get('text', '')}")
        pref_str = "\n".join(pref_lines) if pref_lines else "（无）"

        area_lines = []
        preferred = req.get("preferred_areas", [])
        avoided = req.get("avoid_areas", [])
        if preferred:
            area_lines.append(f"优先区域: {', '.join(preferred)}")
        if avoided:
            area_lines.append(f"回避区域: {', '.join(avoided)}")
        area_str = "; ".join(area_lines) if area_lines else "无"

        prompt = ITINERARY_PLANNING_PROMPT.format(
            city=req.get("city", "未知"),
            days=req.get("days", 1),
            people=req.get("people", 1),
            total_budget=req.get("total_budget", 0),
            interests=req.get("interests", []),
            daily_start=req.get("daily_start_time", "09:00"),
            daily_end=req.get("daily_end_time", "18:00"),
            walking_limit_m=req.get("walking_limit_m", 99999),
            pace_strategy=policy.get("pace_strategy", "normal"),
            attractions=attrs_str,
            hotels=hotels_str,
            restaurants=rests_str,
            semantic_preferences=pref_str,
            area_constraints=area_str,
        )

        raw = self._llm(prompt)

        # 第一次调用：解析 JSON 并验证有 attractions
        if raw and raw.strip():
            try:
                data = self._parse_json(raw)
                itinerary = self._build_itinerary_dict(data, req)
                if itinerary.get("days") and any(
                    d.get("items") for d in itinerary.get("days", [])
                ):
                    return itinerary
                logger.warning("LLM 返回了空 days/items，重试")
            except Exception as e:
                logger.warning("LLM 返回数据无法使用 (%s)，重试", e)

        # 重试：简洁 prompt，只要求输出核心决策
        logger.warning("使用简化提示词重试")
        retry_names = []
        for a in attractions[:8]:
            nm = a.get("name", "?")
            pid = a.get("place_id", "?")
            retry_names.append(f"{nm}(ID:{pid})")
        total_attrs = len(attractions)
        per_day = max(1, total_attrs // max(1, req.get("days", 1)))
        retry_prompt = (
            f"为{req.get('days', 1)}天{req.get('city', '天津')}行程选景点和餐厅。"
            f"候选景点: {', '.join(retry_names)}。"
            f"每天约 {per_day} 个景点。"
            f"输出 JSON: {{\"days\":[{{\"day\":1,\"attractions\":[{{\"place_id\":\"...\",\"note\":\"理由\"}}],\"lunch_place_id\":\"...\"}}]}}"
        )
        raw = self._llm(retry_prompt)
        data = self._parse_json(raw)
        itinerary = self._build_itinerary_dict(data, req)
        if not itinerary.get("days") or not any(
            d.get("items") for d in itinerary.get("days", [])
        ):
            raise ValueError("重试后 LLM 仍然返回空 days/items，需降级到规则引擎")
        return itinerary

    # ====================================================================
    # Step 3: 硬约束校验 + 修复循环
    # ====================================================================

    def _hard_validation_loop(self, state: PlanningState) -> bool:
        """硬约束校验 + LLM 修复（最多 max_repairs 次）。"""
        while True:
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

            if not state.can_repair():
                logger.warning("硬约束未通过，快速模式下跳过 LLM 修复")
                return False

            # 记录修复次数
            state.repair_count += 1

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
        """LLM 修复行程中的硬约束问题。只替换 days 数组，保留 itinerary_id 等顶层字段。"""
        issues = state.hard_evaluation.get("issues", [])
        prompt = HARD_CONSTRAINT_REPAIR_PROMPT.format(
            current_itinerary=json.dumps(state.itinerary, ensure_ascii=False, indent=2),
            validation_issues=json.dumps(issues, ensure_ascii=False, indent=2),
            places=json.dumps(state.places, ensure_ascii=False, indent=2),
        )
        raw = self._llm(prompt)
        data = self._parse_json(raw)
        if "days" in data and isinstance(data["days"], list) and len(data["days"]) > 0:
            state.itinerary["days"] = data["days"]
            logger.info("LLM 硬约束修复完成，更新了 %d 天", len(data["days"]))
        else:
            logger.warning("LLM 修复返回空或无效 days，保留原行程")
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
            "trip_diff": None,
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
        """LLM 只输出核心决策（place_id + note + 顺序），
        委托 bridge 函数从 place 数据确定性构建完整行程结构。"""
        from backend.services.itinerary_builder import build_complete_itinerary

        places = getattr(self, "_current_places", [])
        return build_complete_itinerary(
            decisions=data,
            places=places,
            requirements=requirements,
        )

    def _parse_json(self, raw: str) -> dict:
        """解析 LLM 返回的 JSON，处理 markdown 代码块包裹。

        相比成员二的 JSON 解析，这里增加了：
        1. 空/无效输入保护
        2. 更宽松的 markdown 代码块提取
        3. 失败时抛出明确错误（包含原始输出片段，便于调试）
        """

        if not raw or not raw.strip():
            raise ValueError(
                "LLM 返回了空文本，请检查模型配置或提示词长度是否超限"
            )

        text = raw.strip()

        # 1) 尝试直接解析纯 JSON
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 2) 尝试从 markdown 代码块中提取 JSON
        #    ```json ... ``` 或 ``` ... ```
        code_block_patterns = [
            (r"```json\s*\n(.*?)```", re.DOTALL),
            (r"```\s*\n(.*?)```", re.DOTALL),
        ]
        for pattern, flags in code_block_patterns:
            match = re.search(pattern, text, flags)
            if match:
                try:
                    return json.loads(match.group(1).strip())
                except json.JSONDecodeError:
                    continue

        # 3) 尝试提取最外层 {...} 对象
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass

        # 3.5) 尝试修复截断的 JSON（LLM 输出超 token 限制时常见）
        #       策略：去掉最后一行不完整的内容，补全未闭合的括号
        if start != -1:
            truncated = self._repair_truncated_json(text, start)
            if truncated is not None:
                return truncated

        # 4) 全部失败 → 抛出包含原始输出片段的错误
        preview = raw[:300] if len(raw) > 300 else raw
        raise ValueError(
            f"LLM 返回内容无法解析为 JSON。前 300 字符: {preview}"
        )

    @staticmethod
    def _repair_truncated_json(text: str, start: int) -> dict | None:
        """尝试修复因 token 限制被截断的 JSON。

        策略：
        1. 去掉最后一行（可能不完整）
        2. 补全未闭合的字符串、数组和对象
        3. 如果仍然不合法，逐步去掉尾部内容重试
        """
        # 从第一个 { 开始
        json_text = text[start:]

        # 去掉最后一行不完整的内容
        lines = json_text.split("\n")
        # 如果最后一行看起来不完整（没有逗号、括号等结束符）
        last_line = lines[-1].strip() if lines else ""
        if last_line and not last_line.rstrip().endswith((",", "{", "}", "[", "]")):
            # 去掉最后不完整的行
            json_text = "\n".join(lines[:-1])

        # 补全未闭合的结构
        # 统计未闭合的括号
        open_braces = json_text.count("{") - json_text.count("}")
        open_brackets = json_text.count("[") - json_text.count("]")

        # 检查是否在字符串中间截断（奇数个引号）
        in_string = False
        repaired = []
        i = 0
        while i < len(json_text):
            ch = json_text[i]
            if ch == '"' and (i == 0 or json_text[i - 1] != "\\"):
                in_string = not in_string
            repaired.append(ch)
            i += 1

        # 如果在字符串中间截断，补一个引号
        if in_string:
            repaired.append('"')
        json_text = "".join(repaired)

        # 补全未闭合的括号
        json_text += "]" * open_brackets
        json_text += "}" * open_braces

        try:
            return json.loads(json_text)
        except json.JSONDecodeError:
            pass

        return None

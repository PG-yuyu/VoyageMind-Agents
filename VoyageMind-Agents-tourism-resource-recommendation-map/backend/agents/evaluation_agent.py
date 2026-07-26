"""
评价系统 Agent (Itinerary Evaluation & Critic Agent)
=====================================================

融合 HardConstraintValidator（轨1：确定性规则）和 ItineraryPreferenceCritic（轨2：LLM 软偏好评价）
为统一的评价结果，并生成重规划指导指令。

工作流程:
  1. 硬约束校验 → HardConstraintEvaluation（Python 规则）
  2. 软偏好评价 → SoftPreferenceEvaluation（LLM 评价器）
  3. 计算综合评分（5 项客观量化指标）
  4. 生成重规划指导指令（LLM 综合分析）
  5. 输出 OverallEvaluationResult

设计依据: docs/评价系统AGENT.md — 双轨并行评价机制
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

from backend.agents.itinerary_preference_critic import ItineraryPreferenceCritic
from backend.prompts.evaluation_replan_directive_prompt import (
    EVALUATION_REPLAN_DIRECTIVE_PROMPT,
)
from backend.schemas.evaluation import EvaluationMetrics, ValidationIssue
from backend.schemas.evaluation_agent import (
    OverallEvaluationResult,
    ReplanDirective,
)
from backend.schemas.preference_evaluation import SoftPreferenceIssue

from backend.validators.hard_constraint_validator import (
    enrich_items_with_places,
    validate_hard_constraints,
)

logger = logging.getLogger(__name__)


class EvaluationAgent:
    """行程评价系统 Agent —— 双轨并行评价 + 重规划指令生成。

    将确定性硬约束校验（Python 规则）和软偏好评价（LLM 智能体）
    融合为统一的综合评价结果，并输出可执行的重规划指导指令。
    """

    def __init__(
        self,
        llm_callable: Callable[[str], str] | None = None,
        preference_critic: ItineraryPreferenceCritic | None = None,
    ):
        """
        Args:
            llm_callable: LLM 调用函数（用于生成重规划指令），签名 (prompt: str) -> str
            preference_critic: 软偏好评价器，不传则使用默认实例
        """
        self._llm = llm_callable
        self._critic = preference_critic

    # ====================================================================
    # 主入口
    # ====================================================================

    def evaluate(
        self,
        itinerary: dict[str, Any],
        requirements: dict[str, Any],
        places: list[dict[str, Any]] | None = None,
        routes: list[dict[str, Any]] | None = None,
        semantic_preferences: list[dict[str, Any]] | None = None,
        generate_replan_directives: bool = True,
    ) -> OverallEvaluationResult:
        """执行完整双轨评价。

        Args:
            itinerary: 完整行程字典
            requirements: TravelRequest 字典
            places: 候选地点列表（用于注入 place 引用）
            routes: 路线列表
            semantic_preferences: 隐含偏好列表
            generate_replan_directives: 是否生成重规划指令

        Returns:
            OverallEvaluationResult: 综合评价结果
        """
        # ── 前置：注入 place 引用 ───────────────────────────────────
        if places:
            enrich_items_with_places(itinerary, places)

        # ── 轨 1：硬约束校验（Python 规则） ──────────────────────────
        logger.info("EvaluationAgent: 执行硬约束校验...")
        hard_result = validate_hard_constraints(itinerary, requirements)
        hard_issues = hard_result.issues
        metrics = hard_result.metrics
        logger.info(
            "硬约束校验: passed=%s, issues=%d",
            hard_result.passed,
            len(hard_issues),
        )

        # ── 轨 2：软偏好评价（LLM 评价器） ───────────────────────────
        soft_issues: list[SoftPreferenceIssue] = []
        soft_passed = True
        soft_raw: dict[str, Any] | None = None

        if semantic_preferences and self._critic:
            try:
                logger.info("EvaluationAgent: 执行软偏好评价...")
                soft_result = self._critic.evaluate(
                    itinerary=itinerary,
                    requirements=requirements,
                    semantic_preferences=semantic_preferences,
                    hard_constraint_result=hard_result.model_dump(),
                )
                soft_passed = soft_result.soft_preference_passed
                soft_issues = soft_result.issues
                soft_raw = soft_result.model_dump()
                logger.info(
                    "软偏好评价: passed=%s, issues=%d",
                    soft_passed,
                    len(soft_issues),
                )
            except Exception as exc:
                logger.warning("软偏好评价失败，已跳过: %s", exc)

        # ── 计算 5 项客观量化指标 ────────────────────────────────────
        time_reasonableness = self._compute_time_reasonableness(
            itinerary, requirements,
        )
        overall_score = self._compute_overall_score(
            metrics, time_reasonableness,
        )

        # ── 综合状态判定 ─────────────────────────────────────────────
        passed = hard_result.passed and soft_passed

        # ── 生成重规划指导指令 ───────────────────────────────────────
        replan_directives: list[ReplanDirective] = []
        if generate_replan_directives and self._llm and (not passed):
            try:
                replan_directives = self._generate_replan_directives(
                    itinerary=itinerary,
                    requirements=requirements,
                    hard_issues=hard_issues,
                    soft_issues=soft_issues,
                )
                logger.info(
                    "生成了 %d 条重规划指令", len(replan_directives),
                )
            except Exception as exc:
                logger.warning("生成重规划指令失败: %s", exc)

        # ── 组装结果 ─────────────────────────────────────────────────
        return OverallEvaluationResult(
            passed=passed,
            soft_preference_passed=soft_passed,
            overall_score=overall_score,
            hard_issues=hard_issues,
            soft_issues=soft_issues,
            metrics=metrics,
            time_reasonableness_score=time_reasonableness,
            replan_directives=replan_directives,
            hard_evaluation_raw=hard_result.model_dump(),
            soft_evaluation_raw=soft_raw,
        )

    # ====================================================================
    # 轨 1.5: 额外量化指标计算
    # ====================================================================

    def _compute_time_reasonableness(
        self,
        itinerary: dict[str, Any],
        requirements: dict[str, Any],
    ) -> float:
        """计算时间合理性得分（第 5 项指标）。

        评价维度:
        - 游览时间 vs 交通时间的比例是否合理
        - 每日结束时间是否在规定范围内

        Returns:
            float: 0.0 ~ 1.0 的得分
        """
        days_data = itinerary.get("days", [])
        if not days_data:
            return 1.0

        daily_end = requirements.get("daily_end_time", "18:00")

        total_play_minutes = 0
        total_transport_minutes = 0
        end_time_ok_days = 0

        for day_data in days_data:
            # 检查每日结束时间
            day_end = day_data.get("end_time", "")
            if day_end and day_end <= daily_end:
                end_time_ok_days += 1

            # 统计游览和交通时间
            for item in day_data.get("items", []):
                item_type = item.get("item_type", "")
                duration = item.get("duration_minutes", 0) or 0
                if item_type in ("attraction", "lunch", "dinner", "rest"):
                    total_play_minutes += duration
                elif item_type in ("transport",):
                    total_transport_minutes += duration

        # 时间合理比率
        end_time_ratio = end_time_ok_days / len(days_data)

        # 交通时间占比越少越好（默认阈值：交通时间不超过总活动时间的 30%）
        total = total_play_minutes + total_transport_minutes
        transport_ratio = 0.0
        if total > 0:
            transport_ratio = total_transport_minutes / total
        transport_score = max(0.0, 1.0 - transport_ratio * 2)

        # 综合
        score = end_time_ratio * 0.5 + transport_score * 0.5
        return round(min(1.0, max(0.0, score)), 2)

    def _compute_overall_score(
        self,
        metrics: EvaluationMetrics,
        time_reasonableness: float,
    ) -> float:
        """基于 5 项量化指标计算综合评分。

        5 项指标:
          1. budget_match_rate      (预算符合度)
          2. interest_coverage_rate (兴趣覆盖率)
          3. must_visit_coverage_rate (必去景点覆盖率)
          4. time_valid → 转为分数  (时间有效性)
          5. walking_limit_valid → 转为分数 (步行限制符合度)

        Returns:
            float: 0.0 ~ 1.0
        """
        scores = [
            metrics.budget_match_rate,
            metrics.interest_coverage_rate,
            metrics.must_visit_coverage_rate,
            1.0 if metrics.time_valid else 0.0,
            1.0 if metrics.walking_limit_valid else 0.0,
            time_reasonableness,
        ]
        raw = sum(scores) / len(scores)
        return round(min(1.0, max(0.0, raw)), 2)

    # ====================================================================
    # 重规划指令生成（LLM 驱动）
    # ====================================================================

    def _generate_replan_directives(
        self,
        itinerary: dict[str, Any],
        requirements: dict[str, Any],
        hard_issues: list[ValidationIssue],
        soft_issues: list[SoftPreferenceIssue],
    ) -> list[ReplanDirective]:
        """LLM 综合分析校验结果，生成重规划指导指令。"""
        # 渲染行程详情
        itinerary_lines = []
        for day_data in itinerary.get("days", []):
            day_num = day_data.get("day", 1)
            date = day_data.get("date", "")
            walking = day_data.get("walking_distance_m", 0)
            cost = day_data.get("daily_cost", 0)
            itinerary_lines.append(f"第{day_num}天 ({date})")
            itinerary_lines.append(f"  步行: {walking}米 | 费用: ¥{cost}")
            for item in day_data.get("items", []):
                itype = item.get("item_type", "?")
                pid = item.get("place_id", "")
                start = item.get("start_time", "")
                end = item.get("end_time", "")
                note = item.get("note", "")
                note_str = f" — {note}" if note else ""
                itinerary_lines.append(f"  [{start}-{end}] {itype}: {pid}{note_str}")
            itinerary_lines.append("")
        itinerary_details = "\n".join(itinerary_lines)

        # 渲染硬约束问题
        hard_lines = []
        for i, iss in enumerate(hard_issues, 1):
            hard_lines.append(
                f"  {i}. [{iss.code.value}] (day={iss.day}) "
                f"severity={iss.severity.value}: {iss.message}"
            )
            if iss.suggestion:
                hard_lines.append(f"     建议: {iss.suggestion}")
        hard_str = "\n".join(hard_lines) if hard_lines else "（无硬约束问题）"

        # 渲染软偏好问题
        soft_lines = []
        for i, iss in enumerate(soft_issues, 1):
            soft_lines.append(
                f"  {i}. [{iss.preference}] (confidence={iss.confidence}): "
                f"{iss.assessment}"
            )
            if iss.suggestion:
                soft_lines.append(f"     建议: {iss.suggestion}")
        soft_str = "\n".join(soft_lines) if soft_lines else "（无软偏好问题）"

        prompt = EVALUATION_REPLAN_DIRECTIVE_PROMPT.format(
            city=requirements.get("city", "未知"),
            days=requirements.get("days", 1),
            people=requirements.get("people", 1),
            total_budget=requirements.get("total_budget", 0),
            total_cost=itinerary.get("total_cost", 0),
            original_text=requirements.get("original_text", "（无）"),
            hard_issues=hard_str,
            soft_issues=soft_str,
            itinerary_details=itinerary_details,
        )

        raw = self._llm(prompt)
        data = self._parse_json(raw)

        directives_data = data.get("replan_directives", [])
        directives = []
        for d in directives_data:
            try:
                directives.append(ReplanDirective(**d))
            except Exception as exc:
                logger.warning("跳过无效的重规划指令: %s", exc)

        return directives

    # ====================================================================
    # 辅助
    # ====================================================================

    @staticmethod
    def _parse_json(raw: str) -> dict:
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

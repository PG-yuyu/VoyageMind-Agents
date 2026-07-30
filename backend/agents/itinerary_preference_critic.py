"""
软偏好评价器
============

ItineraryPreferenceCritic — LLM 对行程的隐含偏好满足度进行评价。

与 HardConstraintValidator（Python 规则）互补：
- 硬约束：开放时间、预算上限、步行上限、必去景点 → Python 代码
- 软偏好：是否太累、是否同质化、是否体现当地特色、是否符合上下文 → LLM 评价
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

from backend.prompts.itinerary_preference_critic_prompt import (
    ITINERARY_PREFERENCE_CRITIC_PROMPT,
)
from backend.schemas.preference_evaluation import SoftPreferenceEvaluation

logger = logging.getLogger(__name__)


class ItineraryPreferenceCritic:
    """LLM 软偏好评价器。

    调用 LLM 对已通过硬约束校验的行程进行隐含偏好满足度评价。
    输出 SoftPreferenceEvaluation，供后续优化循环使用。
    """

    def __init__(self, llm_callable: Callable[[str], str]):
        """
        Args:
            llm_callable: LLM 调用函数，签名 (prompt: str) -> str（返回 JSON 字符串）
        """
        self._llm: Callable[[str], str] = llm_callable

    def evaluate(
        self,
        itinerary: dict[str, Any],
        requirements: dict[str, Any],
        semantic_preferences: list[dict[str, Any]],
        hard_constraint_result: dict[str, Any] | None = None,
    ) -> SoftPreferenceEvaluation:
        """对行程进行软偏好评价。

        Args:
            itinerary: 完整行程字典
            requirements: TravelRequest 字典
            semantic_preferences: 隐含偏好列表
            hard_constraint_result: 硬约束校验结果（可选，仅供参考）

        Returns:
            SoftPreferenceEvaluation: 软偏好评价结果
        """
        # ── 构造 Prompt ──────────────────────────────────────────────
        original_text = requirements.get("original_text", "")
        city = requirements.get("city", "")
        days = requirements.get("days", 1)
        people = requirements.get("people", 1)
        total_budget = requirements.get("total_budget", 0)
        total_cost = itinerary.get("total_cost", 0)

        # 行程详情渲染
        itinerary_details = self._render_itinerary(itinerary)

        # 偏好渲染
        pref_lines = []
        for sp in (semantic_preferences or []):
            pref_lines.append(f"- {sp.get('text', '')}（作用域: {sp.get('scope', 'overall')}）")
        preferences_str = "\n".join(pref_lines) if pref_lines else "（无明确隐含偏好）"

        prompt = ITINERARY_PREFERENCE_CRITIC_PROMPT.format(
            original_text=original_text or "（无原始文本）",
            semantic_preferences=preferences_str,
            city=city,
            days=days,
            people=people,
            total_budget=total_budget,
            total_cost=total_cost,
            itinerary_details=itinerary_details,
            hard_constraint_result=json.dumps(hard_constraint_result, ensure_ascii=False, indent=2)
            if hard_constraint_result else "（无硬约束数据）",
        )

        # ── 调用 LLM ────────────────────────────────────────────────
        try:
            raw = self._llm(prompt)
            result = self._parse_response(raw)
            logger.info(
                "Preference critic: passed=%s, issues=%d",
                result.soft_preference_passed,
                len(result.issues),
            )
            return result
        except Exception as exc:
            logger.error("Preference critic LLM call failed: %s", exc)
            # 失败时返回一个宽松的结果（视为通过，避免阻塞流程）
            return SoftPreferenceEvaluation(
                soft_preference_passed=True,
                issues=[],
                overall_assessment=f"软偏好评价失败: {exc}，已默认通过",
            )

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------

    def _render_itinerary(self, itinerary: dict[str, Any]) -> str:
        """将行程渲染为可读的文本格式。"""
        lines = []
        for day_data in itinerary.get("days", []):
            day_num = day_data.get("day", 1)
            date = day_data.get("date", "")
            walking = day_data.get("walking_distance_m", 0)
            cost = day_data.get("daily_cost", 0)
            lines.append(f"\n--- 第{day_num}天 ({date}) ---")
            lines.append(f"  步行: {walking}米 | 费用: ¥{cost}")
            for item in day_data.get("items", []):
                itype = item.get("item_type", "?")
                place_id = item.get("place_id", "")
                start = item.get("start_time", "")
                end = item.get("end_time", "")
                note = item.get("note", "")
                note_str = f" — {note}" if note else ""
                lines.append(f"  [{start}-{end}] {itype}: {place_id}{note_str}")
        return "\n".join(lines)

    def _parse_response(self, raw: str) -> SoftPreferenceEvaluation:
        """解析 LLM 返回的 JSON 为 SoftPreferenceEvaluation。"""
        # 尝试提取 JSON
        text = raw.strip()
        if text.startswith("```"):
            # 找到第一个 ``` 和最后一个 ```
            start = text.find("\n", text.index("```")) + 1
            end = text.rfind("```")
            if end > start:
                text = text[start:end].strip()

        data = json.loads(text)
        return SoftPreferenceEvaluation(**data)

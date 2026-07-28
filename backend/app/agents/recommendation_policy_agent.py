"""推荐策略 Agent。"""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from backend.app.prompts import RECOMMENDATION_POLICY_PROMPT
from backend.app.schemas import (
    HardConstraint,
    RecommendationContext,
    RecommendationPolicy,
    ResourceFilterPolicy,
)
from backend.app.services import LLMJsonService, ModelDecisionError


class RecommendationPolicyAgent:
    """使用大模型把推荐上下文转换为资源推荐策略。"""

    def __init__(self, model_service: LLMJsonService | None = None) -> None:
        """注入大模型 JSON 服务；默认使用成员一 ChatbotService。"""

        self.model_service = model_service or LLMJsonService()

    def generate_policy(self, context: RecommendationContext) -> RecommendationPolicy:
        """生成推荐策略；隐含偏好必须由大模型判断。"""

        if not isinstance(context, RecommendationContext):
            raise TypeError("策略 Agent 只能处理 RecommendationContext")

        payload = self._context_to_payload(context)
        model_output = self.model_service.request_json(
            RECOMMENDATION_POLICY_PROMPT,
            json.dumps(payload, ensure_ascii=False, indent=2),
        )
        policy = self._policy_from_model_output(model_output)
        self._validate_price_limits_are_explicit(context, policy.filters)

        # 诊断日志
        import logging
        _log = logging.getLogger(__name__)
        for fp in policy.filters:
            _log.warning(
                "[POLICY DEBUG] type=%s area=%s min_price=%s max_price=%s tags=%s",
                fp.place_type, fp.area, fp.min_price, fp.max_price, fp.tags,
            )

        return policy

    def _context_to_payload(self, context: RecommendationContext) -> dict[str, Any]:
        """转换为可交给大模型理解的上下文 JSON。"""

        req = context.requirements
        return {
            "city": req.city,
            "days": req.days,
            "people": req.people,
            "total_budget": req.total_budget,
            "interests": req.interests,
            "food_preferences": req.food_preferences,
            "preferred_areas": req.preferred_areas,
            "avoid_areas": req.avoid_areas,
            "travel_pace": req.travel_pace,
            "original_text": context.original_text,
            "conversation_context": list(context.conversation_context)[-3:],
            "explicit_hard_constraints": [
                asdict(c) for c in context.explicit_hard_constraints
            ],
            "semantic_preferences": [
                asdict(p) for p in context.semantic_preferences
            ],
            "instruction": "total_budget 是总预算，不要拆成单项价格上限。只输出 JSON。",
        }

    def _policy_from_model_output(
        self, model_output: dict[str, Any]
    ) -> RecommendationPolicy:
        """把大模型 JSON 转换为 RecommendationPolicy。"""

        filters_data = model_output.get("filters")
        if not isinstance(filters_data, list):
            raise ModelDecisionError("大模型未返回 filters，请重新调用模型重试")

        filters = [
            ResourceFilterPolicy(
                place_type=self._required_str(item, "place_type"),
                tags=self._str_list(item.get("tags"), "tags"),
                area=self._nullable_str(item.get("area"), "area"),
                min_price=self._nullable_float(item.get("min_price"), "min_price"),
                max_price=self._nullable_float(item.get("max_price"), "max_price"),
            )
            for item in filters_data
            if isinstance(item, dict)
        ]
        if len(filters) != len(filters_data):
            raise ModelDecisionError("大模型 filters 中存在非法对象，请重新调用模型重试")

        return RecommendationPolicy(
            focus=self._str_list(model_output.get("focus"), "focus"),
            filters=filters,
            preference_notes=self._str_list(
                model_output.get("preference_notes"), "preference_notes"
            ),
            budget_direction=self._required_str(
                model_output, "budget_direction"
            ),
            people_direction=self._str_list(
                model_output.get("people_direction"), "people_direction"
            ),
        )

    def _validate_price_limits_are_explicit(
        self,
        context: RecommendationContext,
        filters: list[ResourceFilterPolicy],
    ) -> None:
        """禁止大模型把软偏好擅自转换为价格硬过滤。"""

        for filter_policy in filters:
            self._validate_one_price_limit(
                context=context,
                filter_policy=filter_policy,
                field_name="min_price",
                value=filter_policy.min_price,
            )
            self._validate_one_price_limit(
                context=context,
                filter_policy=filter_policy,
                field_name="max_price",
                value=filter_policy.max_price,
            )

    def _validate_one_price_limit(
        self,
        context: RecommendationContext,
        filter_policy: ResourceFilterPolicy,
        field_name: str,
        value: float | None,
    ) -> None:
        """校验单个价格过滤值是否来自明确硬约束。"""

        if value is None:
            return

        allowed_values = self._explicit_price_values(
            context=context,
            place_type=filter_policy.place_type,
            field_name=field_name,
        )
        if value not in allowed_values:
            raise ModelDecisionError(
                "大模型输出了未由明确硬约束支持的价格过滤条件，请重新生成策略"
            )

    def _explicit_price_values(
        self,
        context: RecommendationContext,
        place_type: str,
        field_name: str,
    ) -> set[float]:
        """收集允许用于策略过滤的明确价格数值。"""

        values: set[float] = set()
        if field_name == "max_price":
            if place_type == "hotel" and context.requirements.hotel_budget_per_night:
                values.add(float(context.requirements.hotel_budget_per_night))
            if (
                place_type == "restaurant"
                and context.requirements.meal_budget_per_person
            ):
                values.add(float(context.requirements.meal_budget_per_person))

        for constraint in context.explicit_hard_constraints:
            if self._constraint_matches_price_scope(constraint, place_type):
                try:
                    values.add(float(constraint.value))
                except (TypeError, ValueError):
                    continue
        return values

    @staticmethod
    def _constraint_matches_price_scope(
        constraint: HardConstraint,
        place_type: str,
    ) -> bool:
        """判断硬约束是否是指定资源类型的价格条件。"""

        field = constraint.field.lower()
        scope = constraint.scope.lower()
        price_keywords = {
            "price",
            "budget",
            "ticket",
            "cost",
            "费用",
            "价格",
            "预算",
            "门票",
            "人均",
        }
        scope_aliases = {
            place_type,
            "overall",
            "all",
            "全部",
            "整体",
        }
        if place_type == "restaurant":
            scope_aliases.update({"food", "meal", "餐饮", "餐厅"})
        if place_type == "hotel":
            scope_aliases.update({"住宿", "酒店"})
        if place_type == "attraction":
            scope_aliases.update({"景点", "门票"})
        return any(keyword in field for keyword in price_keywords) and scope in scope_aliases

    @staticmethod
    def _str_list(value: Any, field_name: str) -> list[str]:
        """读取字符串列表字段。"""

        if not isinstance(value, list):
            raise ModelDecisionError(f"大模型字段 {field_name} 必须是字符串列表")
        results: list[str] = []
        for item in value:
            if not isinstance(item, str) or not item.strip():
                raise ModelDecisionError(f"大模型字段 {field_name} 包含非法字符串")
            results.append(item.strip())
        return results

    @staticmethod
    def _required_str(data: dict[str, Any], field_name: str) -> str:
        """读取必填字符串字段。"""

        value = data.get(field_name)
        if not isinstance(value, str) or not value.strip():
            raise ModelDecisionError(f"大模型字段 {field_name} 必须是非空字符串")
        return value.strip()

    @staticmethod
    def _nullable_str(value: Any, field_name: str) -> str | None:
        """读取可空字符串字段。"""

        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            raise ModelDecisionError(f"大模型字段 {field_name} 必须是字符串或 null")
        return value.strip()

    @staticmethod
    def _nullable_float(value: Any, field_name: str) -> float | None:
        """读取可空数字字段。"""

        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ModelDecisionError(f"大模型字段 {field_name} 必须是数字或 null")
        return float(value)


__all__ = ["RecommendationPolicyAgent"]

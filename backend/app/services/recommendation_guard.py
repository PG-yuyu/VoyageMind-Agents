"""推荐结果硬约束校验服务。"""

from __future__ import annotations

from backend.app.schemas import (
    HardConstraint,
    Place,
    RecommendationContext,
    RecommendationResult,
    ValidationIssue,
)


class RecommendationGuard:
    """只校验客观事实和明确硬约束，不判断软偏好好坏。"""

    def validate_result(
        self,
        context: RecommendationContext,
        result: RecommendationResult,
        candidate_place_ids: set[str],
    ) -> list[ValidationIssue]:
        """校验模型选择结果是否满足硬性条件。"""

        issues: list[ValidationIssue] = []
        for place in [
            *result.attractions,
            *result.hotels,
            *result.restaurants,
        ]:
            issues.extend(self._validate_place(context, place, candidate_place_ids))
        return issues

    def _validate_place(
        self,
        context: RecommendationContext,
        place: Place,
        candidate_place_ids: set[str],
    ) -> list[ValidationIssue]:
        """校验单个地点的客观事实和明确约束。"""

        issues: list[ValidationIssue] = []
        if place.place_id not in candidate_place_ids:
            issues.append(self._issue("place_id", f"模型选择了候选池外地点：{place.place_id}"))
        if place.city != context.requirements.city:
            issues.append(self._issue("city", f"{place.name} 不属于目标城市"))
        if self._is_avoided_place(context, place):
            issues.append(self._issue("avoid_places", f"{place.name} 命中明确禁止地点"))
        if place.place_type == "hotel":
            issues.extend(self._validate_price_limit(
                place,
                context.requirements.hotel_budget_per_night,
                "hotel_budget_per_night",
            ))
        if place.place_type == "restaurant":
            issues.extend(self._validate_price_limit(
                place,
                context.requirements.meal_budget_per_person,
                "meal_budget_per_person",
            ))
            issues.extend(self._validate_food_avoidances(context, place))
        for constraint in context.explicit_hard_constraints:
            issues.extend(self._validate_explicit_constraint(place, constraint))
        return issues

    def _validate_explicit_constraint(
        self,
        place: Place,
        constraint: HardConstraint,
    ) -> list[ValidationIssue]:
        """校验当前支持的明确硬约束。"""

        if not self._constraint_scope_matches(place, constraint.scope):
            return []

        field = constraint.field.lower()
        operator = constraint.operator.lower()
        value = constraint.value
        if field in {"area", "district", "区域", "商圈"}:
            return self._validate_text_constraint(
                field="area",
                actual=place.area,
                expected=str(value),
                operator=operator,
                place=place,
            )
        if field in {"city", "城市"}:
            return self._validate_text_constraint(
                field="city",
                actual=place.city,
                expected=str(value),
                operator=operator,
                place=place,
            )
        if self._is_price_field(field):
            try:
                expected_price = float(value)
            except (TypeError, ValueError):
                return [self._issue("hard_constraint", "价格硬约束数值不合法")]
            return self._validate_numeric_constraint(
                field=field,
                actual=place.price,
                expected=expected_price,
                operator=operator,
                place=place,
            )
        return []

    def _validate_text_constraint(
        self,
        field: str,
        actual: str,
        expected: str,
        operator: str,
        place: Place,
    ) -> list[ValidationIssue]:
        """校验文本类硬约束。"""

        if operator in {"equals", "==", "=", "等于"} and actual != expected:
            return [self._issue(field, f"{place.name} 的 {field} 不等于 {expected}")]
        if operator in {"not_equals", "!=", "不等于"} and actual == expected:
            return [self._issue(field, f"{place.name} 的 {field} 命中禁止值 {expected}")]
        return []

    def _validate_numeric_constraint(
        self,
        field: str,
        actual: float | None,
        expected: float,
        operator: str,
        place: Place,
    ) -> list[ValidationIssue]:
        """校验数值类硬约束。"""

        if actual is None:
            return [self._issue(field, f"{place.name} 缺少价格事实，无法校验硬约束")]

        passed = True
        if operator in {"less_than_or_equal", "<=", "最多", "不超过"}:
            passed = actual <= expected
        elif operator in {"less_than", "<", "低于"}:
            passed = actual < expected
        elif operator in {"greater_than_or_equal", ">=", "至少"}:
            passed = actual >= expected
        elif operator in {"greater_than", ">", "高于"}:
            passed = actual > expected
        elif operator in {"equals", "==", "=", "等于"}:
            passed = actual == expected

        if passed:
            return []
        return [self._issue(field, f"{place.name} 的价格 {actual} 不满足硬约束 {operator} {expected}")]

    def _validate_price_limit(
        self,
        place: Place,
        limit: int | None,
        field: str,
    ) -> list[ValidationIssue]:
        """校验成员一结构化出的明确价格上限。"""

        if limit is None:
            return []
        if place.price is None:
            return [self._issue(field, f"{place.name} 缺少价格事实")]
        if place.price > limit:
            return [self._issue(field, f"{place.name} 价格超过明确上限 {limit}")]
        return []

    def _validate_food_avoidances(
        self,
        context: RecommendationContext,
        place: Place,
    ) -> list[ValidationIssue]:
        """校验明确饮食禁忌是否出现在餐厅事实中。"""

        text = " ".join([place.name, place.description, *place.tags])
        issues: list[ValidationIssue] = []
        for avoidance in context.requirements.food_avoidances:
            if avoidance and avoidance in text:
                issues.append(self._issue("food_avoidances", f"{place.name} 命中饮食禁忌：{avoidance}"))
        return issues

    @staticmethod
    def _constraint_scope_matches(place: Place, scope: str) -> bool:
        """判断硬约束作用范围是否覆盖当前地点。"""

        normalized_scope = scope.lower()
        aliases = {
            place.place_type,
            "overall",
            "all",
            "全部",
            "整体",
        }
        if place.place_type == "attraction":
            aliases.add("景点")
        if place.place_type == "hotel":
            aliases.update({"酒店", "住宿"})
        if place.place_type == "restaurant":
            aliases.update({"餐厅", "餐饮", "food", "meal"})
        return normalized_scope in aliases

    @staticmethod
    def _is_avoided_place(context: RecommendationContext, place: Place) -> bool:
        """判断地点是否命中明确禁止地点。"""

        avoided_names = {item.strip() for item in context.requirements.avoid_places}
        return place.name in avoided_names or place.place_id in avoided_names

    @staticmethod
    def _is_price_field(field: str) -> bool:
        """判断字段是否表达价格硬约束。"""

        return any(
            keyword in field
            for keyword in ["price", "budget", "ticket", "cost", "价格", "预算", "门票", "费用"]
        )

    @staticmethod
    def _issue(field: str, message: str) -> ValidationIssue:
        """构造错误级校验问题。"""

        return ValidationIssue(field=field, message=message, level="error")


__all__ = ["RecommendationGuard"]

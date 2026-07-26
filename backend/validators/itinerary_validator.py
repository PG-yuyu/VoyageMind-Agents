"""
行程确定性规则校验器（保留向后兼容）
====================================

⚠️  v2 重构后此模块委托给独立的子校验器，建议新代码直接使用：
    from backend.validators.hard_constraint_validator import validate_hard_constraints

独立校验器:
  - opening_time_validator      (PLACE_CLOSED, ARRIVAL_OUTSIDE_OPENING_HOURS)
  - route_time_validator        (TIME_CONFLICT, ROUTE_TIME_INSUFFICIENT, DAILY_END_TIME_EXCEEDED)
  - explicit_budget_validator   (BUDGET_EXCEEDED)
  - explicit_walking_validator  (WALKING_LIMIT_EXCEEDED)
  - food_safety_validator       (FOOD_AVOIDANCE_CONFLICT)
  - factual_consistency_validator (MUST_VISIT_MISSING, DUPLICATE_PLACE, INVALID_COORDINATE, UNVERIFIED_ROUTE)
  - hard_constraint_validator   (总调度)
"""

from __future__ import annotations

from backend.validators.hard_constraint_validator import (
    validate_hard_constraints,
    enrich_items_with_places,
)


def validate_itinerary(
    itinerary: dict | object,
    requirements: dict | object,
    places: list[dict] | None = None,
    routes: list[dict] | None = None,
) -> object:
    """向后兼容入口 —— 委托给 validate_hard_constraints。

    Args:
        itinerary: Itinerary 字典或对象
        requirements: TravelRequest 字典或对象
        places: Place 列表（可选，用于注入 _place 引用）
        routes: RouteResult 列表（可选，用于注入 _route 引用）

    Returns:
        HardConstraintEvaluation: 硬约束校验结果
    """
    it = _d(itinerary)
    if places:
        enrich_items_with_places(it, places)
    # 注入 route 引用
    if routes:
        _enrich_routes(it, routes)

    return validate_hard_constraints(it, requirements)


def _d(obj) -> dict:
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "dict"):
        return obj.dict()
    return {}


def _enrich_routes(itinerary: dict, routes: list[dict]) -> None:
    """注入 _route 引用。"""
    route_map: dict[str, dict] = {r.get("route_id", ""): r for r in routes}
    for day_data in itinerary.get("days", []):
        for item in day_data.get("items", []):
            rid = item.get("route_from_previous_id")
            if rid and rid in route_map:
                item["_route"] = route_map[rid]

"""
硬约束校验总调度
================

编排所有独立校验器，将结果汇总为 HardConstraintEvaluation。

校验流程:
  1. 遍历所有子校验器，收集 ValidationIssue
  2. 计算量化指标（budget_match_rate, interest_coverage_rate 等）
  3. 判断整体结果：无 error 级问题即 passed=True

执行的所有校验器:
  - opening_time_validator      (PLACE_CLOSED, ARRIVAL_OUTSIDE_OPENING_HOURS)
  - route_time_validator        (TIME_CONFLICT, ROUTE_TIME_INSUFFICIENT, DAILY_END_TIME_EXCEEDED)
  - explicit_budget_validator   (BUDGET_EXCEEDED)
  - explicit_walking_validator  (WALKING_LIMIT_EXCEEDED)
  - food_safety_validator       (FOOD_AVOIDANCE_CONFLICT)
  - factual_consistency_validator (MUST_VISIT_MISSING, DUPLICATE_PLACE, INVALID_COORDINATE, UNVERIFIED_ROUTE)
"""

from __future__ import annotations

from backend.schemas.evaluation import (
    EvaluationMetrics,
    HardConstraintEvaluation,
    Severity,
    ValidationCode,
)
from backend.schemas.itinerary import ItemType

from backend.validators.opening_time_validator import validate_opening_time
from backend.validators.route_time_validator import (
    validate_daily_end_time,
    validate_route_time,
    validate_time_conflict,
)
from backend.validators.explicit_budget_validator import validate_budget
from backend.validators.explicit_walking_validator import validate_walking
from backend.validators.food_safety_validator import validate_food_safety
from backend.validators.factual_consistency_validator import (
    validate_coordinate,
    validate_duplicate_place,
    validate_must_visit,
    validate_route_verified,
)


def validate_hard_constraints(
    itinerary: dict | object,
    requirements: dict | object,
) -> HardConstraintEvaluation:
    """对行程执行全部确定性规则校验（硬约束）。

    Args:
        itinerary: Itinerary 字典或 Pydantic 对象
        requirements: TravelRequest 字典或 Pydantic 对象

    Returns:
        HardConstraintEvaluation: 硬约束校验结果
    """
    it = _d(itinerary)
    req = _d(requirements)

    # 为每个 item 注入 _place 引用（便于校验器读取地点详情）
    _enrich_items(it)

    issues: list[ValidationIssue] = []

    # 执行所有子校验器
    issues += validate_opening_time(it)
    issues += validate_time_conflict(it)
    issues += validate_route_time(it)
    issues += validate_daily_end_time(it, req)
    issues += validate_budget(it, req)
    issues += validate_walking(it, req)
    issues += validate_food_safety(it, req)
    issues += validate_must_visit(it, req)
    issues += validate_duplicate_place(it)
    issues += validate_coordinate(it)
    issues += validate_route_verified(it)

    # 计算量化指标
    metrics = _compute_metrics(it, req, issues)

    # passed = 无 error 级别问题
    has_errors = any(i.severity == Severity.ERROR for i in issues)
    return HardConstraintEvaluation(
        passed=not has_errors,
        issues=issues,
        metrics=metrics,
    )


# ====================================================================
# 指标计算
# ====================================================================


def _compute_metrics(
    itinerary: dict,
    requirements: dict,
    issues: list[ValidationIssue],
) -> EvaluationMetrics:
    """根据校验结果计算量化指标。"""

    # 预算匹配率
    total_budget = requirements.get("total_budget", 0) or 0
    total_cost = itinerary.get("total_cost", 0) or 0
    budget_match = 1.0
    if total_budget > 0:
        ratio = total_cost / total_budget
        budget_match = max(0.0, min(1.0, 2.0 - ratio)) if ratio > 1 else ratio

    # 必去景点覆盖率
    must_visit: list = requirements.get("must_visit") or []
    scheduled: set[str] = set()
    for day_data in itinerary.get("days", []):
        for item in day_data.get("items", []):
            place = item.get("_place") or {}
            if place.get("name"):
                scheduled.add(place["name"])
            if item.get("place_id"):
                scheduled.add(item["place_id"])
    must_visit_hits = sum(1 for mv in must_visit if mv in scheduled)
    must_visit_rate = must_visit_hits / len(must_visit) if must_visit else 1.0

    # 兴趣覆盖率（景点中命中用户兴趣的比例）
    interests: list = requirements.get("interests") or []
    attraction_count = 0
    interest_hits = 0
    for day_data in itinerary.get("days", []):
        for item in day_data.get("items", []):
            if item.get("item_type") != ItemType.ATTRACTION.value:
                continue
            attraction_count += 1
            place = item.get("_place") or {}
            cats = place.get("categories", [])
            if any(interest in cats for interest in interests):
                interest_hits += 1
    interest_rate = interest_hits / attraction_count if attraction_count else 1.0

    # 时间有效
    time_codes = {ValidationCode.TIME_CONFLICT, ValidationCode.ARRIVAL_OUTSIDE_OPENING_HOURS}
    time_valid = not any(
        i.code in time_codes and i.severity == Severity.ERROR for i in issues
    )

    # 步行有效
    walking_valid = not any(
        i.code == ValidationCode.WALKING_LIMIT_EXCEEDED for i in issues
    )

    return EvaluationMetrics(
        budget_match_rate=round(budget_match, 2),
        interest_coverage_rate=round(interest_rate, 2),
        must_visit_coverage_rate=round(must_visit_rate, 2),
        time_valid=time_valid,
        walking_limit_valid=walking_valid,
    )


# ====================================================================
# 辅助
# ====================================================================


def _d(obj) -> dict:
    """对象/字典 → dict。"""
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "dict"):
        return obj.dict()
    return {}


def _enrich_items(itinerary: dict) -> None:
    """为每个 item 注入 _place 引用。

    注意：此函数为空壳。实际的 _place 注入由 enrich_items_with_places()
    完成（需要外部传入 places 列表）。调用方必须在 validate_hard_constraints()
    之前调用 enrich_items_with_places()，否则所有依赖 _place 的校验器将静默跳过。
    """
    import logging
    has_place = False
    for day_data in itinerary.get("days", []):
        for item in day_data.get("items", []):
            if item.get("_place"):
                has_place = True
                break
    if not has_place:
        logging.getLogger(__name__).debug(
            "行程 items 缺少 _place 引用。依赖 _place 的校验器将静默跳过。"
        )


def enrich_items_with_places(
    itinerary: dict,
    places: list[dict],
) -> None:
    """从外部 places 列表为行程 items 注入 _place 引用。

    Args:
        itinerary: 行程字典
        places: Place 字典列表
    """
    place_map: dict[str, dict] = {p.get("place_id", ""): p for p in places}
    for day_data in itinerary.get("days", []):
        for item in day_data.get("items", []):
            pid = item.get("place_id")
            if pid and pid in place_map:
                item["_place"] = place_map[pid]

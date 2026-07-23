"""
行程确定性规则校验器
====================

9 项（扩展为 10 项）规则全部由 Python 代码完成，不依赖大模型判断。

校验维度:
  1. PLACE_CLOSED              景点/餐厅在游览时段是否开放
  2. ARRIVAL_OUTSIDE_OPENING    到达时间是否在开放时间内
  3. TIME_CONFLICT             前后行程项时间是否冲突
  4. ROUTE_TIME_INSUFFICIENT   路线耗时是否超出相邻项间隔
  5. BUDGET_EXCEEDED           总费用是否超预算
  6. MUST_VISIT_MISSING        必去景点是否都已安排
  7. DUPLICATE_PLACE           同一天是否有重复地点
  8. WALKING_LIMIT_EXCEEDED    日步行距离是否超限
  9. FOOD_AVOIDANCE_CONFLICT   餐厅是否与饮食禁忌冲突
  10. DAILY_END_TIME_EXCEEDED  每日结束时间是否超限
"""

from __future__ import annotations

from datetime import datetime, timedelta

from schemas.evaluation import (
    EvaluationMetrics,
    HardConstraintEvaluation,
    Severity,
    ValidationCode,
    ValidationIssue,
)
from schemas.itinerary import ItemType


# ---------------------------------------------------------------------------
# 时间工具
# ---------------------------------------------------------------------------


def _parse_time(time_str: str | None) -> datetime | None:
    """将 HH:MM 转为今日 datetime，失败返回 None。"""
    if not time_str:
        return None
    try:
        h, m = map(int, time_str.split(":"))
        return datetime(2000, 1, 1, h, m)
    except (ValueError, AttributeError):
        return None


def _time_diff_minutes(earlier: str, later: str) -> int:
    """计算 later - earlier 的分钟差。"""
    t1 = _parse_time(earlier)
    t2 = _parse_time(later)
    if t1 is None or t2 is None:
        return 0
    return int((t2 - t1).total_seconds() / 60)


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


def validate_itinerary(
    itinerary: dict | object,
    requirements: dict | object,
    places: list[dict] | None = None,
    routes: list[dict] | None = None,
) -> HardConstraintEvaluation:
    """对行程执行全部确定性规则校验（硬约束）。

    Args:
        itinerary: Itinerary 字典或对象
        requirements: TravelRequest 字典或对象
        places: Place 列表（含 open_time / close_time / categories 等）
        routes: RouteResult 列表

    Returns:
        HardConstraintEvaluation: 硬约束校验结果，passed=True 表示无 error 级问题
    """

    it = _d(itinerary)
    req = _d(requirements)
    _places = places or []
    _routes = routes or []

    # 建立索引
    place_map: dict[str, dict] = {p.get("place_id", ""): p for p in _places}
    route_map: dict[str, dict] = {r.get("route_id", ""): r for r in _routes}

    # 补充 item 的 _place 和 _route 引用，方便各规则读取
    _enrich_items(it, place_map, route_map)

    issues: list[ValidationIssue] = []

    # 逐项执行所有规则
    issues += _check_place_closed(it)
    issues += _check_arrival_outside_opening(it)
    issues += _check_time_conflict(it)
    issues += _check_route_time_insufficient(it)
    issues += _check_budget_exceeded(it, req)
    issues += _check_must_visit_missing(it, req)
    issues += _check_duplicate_place(it)
    issues += _check_walking_limit(it, req)
    issues += _check_food_avoidance(it, req)
    issues += _check_daily_end_time(it, req)

    # 计算指标
    metrics = _compute_metrics(it, req, issues)

    # passed = 无 error 级别问题
    has_errors = any(i.severity == Severity.ERROR for i in issues)
    return HardConstraintEvaluation(passed=not has_errors, issues=issues, metrics=metrics)


# ====================================================================
# 规则 1: PLACE_CLOSED
# ====================================================================


def _check_place_closed(itinerary: dict) -> list[ValidationIssue]:
    """检查景点/餐厅在游览时段是否开放（考虑周几）。"""
    issues: list[ValidationIssue] = []
    for day_data in itinerary.get("days", []):
        day_num = day_data.get("day", 1)
        date_str = day_data.get("date", "")
        weekday = _get_weekday(date_str)

        for item in day_data.get("items", []):
            place = item.get("_place")
            if not place:
                continue
            open_weekdays = place.get("open_weekdays")
            if open_weekdays and weekday not in open_weekdays:
                issues.append(ValidationIssue(
                    code=ValidationCode.PLACE_CLOSED,
                    severity=Severity.ERROR,
                    day=day_num,
                    item_id=item.get("item_id"),
                    message=f"{place.get('name', '地点')} 周{weekday}不开放",
                    suggestion="替换为当日开放的地点",
                ))
    return issues


# ====================================================================
# 规则 2: ARRIVAL_OUTSIDE_OPENING_HOURS
# ====================================================================


def _check_arrival_outside_opening(itinerary: dict) -> list[ValidationIssue]:
    """检查到达时间是否在开放时间窗口内。"""
    issues: list[ValidationIssue] = []
    for day_data in itinerary.get("days", []):
        day_num = day_data.get("day", 1)
        for item in day_data.get("items", []):
            place = item.get("_place")
            if not place:
                continue
            open_t = place.get("open_time")
            close_t = place.get("close_time")
            if not open_t or not close_t:
                continue

            start = item.get("start_time", "")
            end = item.get("end_time", "")

            if start and start < open_t:
                issues.append(ValidationIssue(
                    code=ValidationCode.ARRIVAL_OUTSIDE_OPENING_HOURS,
                    severity=Severity.ERROR,
                    day=day_num,
                    item_id=item.get("item_id"),
                    message=(
                        f"{place.get('name', '地点')} {start} 到达，"
                        f"但开放时间为 {open_t}-{close_t}"
                    ),
                    suggestion=f"推迟至 {open_t} 之后",
                ))
            if end and end > close_t:
                issues.append(ValidationIssue(
                    code=ValidationCode.ARRIVAL_OUTSIDE_OPENING_HOURS,
                    severity=Severity.ERROR,
                    day=day_num,
                    item_id=item.get("item_id"),
                    message=(
                        f"{place.get('name', '地点')} {end} 离开，"
                        f"但关闭时间为 {close_t}"
                    ),
                    suggestion=f"提前结束或缩短游览时间",
                ))
    return issues


# ====================================================================
# 规则 3: TIME_CONFLICT
# ====================================================================


def _check_time_conflict(itinerary: dict) -> list[ValidationIssue]:
    """检查同一天内前后行程项时间是否重叠或顺序错误。"""
    issues: list[ValidationIssue] = []
    for day_data in itinerary.get("days", []):
        day_num = day_data.get("day", 1)
        items = day_data.get("items", [])
        for i in range(len(items) - 1):
            curr_end = items[i].get("end_time", "")
            next_start = items[i + 1].get("start_time", "")
            if curr_end and next_start and curr_end > next_start:
                issues.append(ValidationIssue(
                    code=ValidationCode.TIME_CONFLICT,
                    severity=Severity.ERROR,
                    day=day_num,
                    item_id=items[i + 1].get("item_id"),
                    message=(
                        f"「{items[i].get('item_id')}」{curr_end} 结束，"
                        f"但「{items[i+1].get('item_id')}」{next_start} 已开始"
                    ),
                    suggestion="调整前后项时间或顺序",
                ))
    return issues


# ====================================================================
# 规则 4: ROUTE_TIME_INSUFFICIENT
# ====================================================================


def _check_route_time_insufficient(itinerary: dict) -> list[ValidationIssue]:
    """检查路线耗时是否超出相邻两项之间的间隔时间。"""
    issues: list[ValidationIssue] = []
    for day_data in itinerary.get("days", []):
        day_num = day_data.get("day", 1)
        items = day_data.get("items", [])
        for i in range(len(items) - 1):
            prev_end = items[i].get("end_time", "")
            next_start = items[i + 1].get("start_time", "")
            gap_min = _time_diff_minutes(prev_end, next_start)

            route = items[i + 1].get("_route") or items[i + 1].get("route_from_previous_id")
            if isinstance(route, str):
                continue  # 仅有 ID 无详情，跳过
            route_duration = (route or {}).get("duration_minutes", 0)
            if isinstance(route_duration, int) and route_duration > gap_min:
                issues.append(ValidationIssue(
                    code=ValidationCode.ROUTE_TIME_INSUFFICIENT,
                    severity=Severity.ERROR,
                    day=day_num,
                    item_id=items[i + 1].get("item_id"),
                    message=(
                        f"路线耗时 {route_duration} 分钟 > "
                        f"间隔 {gap_min} 分钟，无法按时到达"
                    ),
                    suggestion="提前出发或更换交通方式",
                ))
    return issues


# ====================================================================
# 规则 5: BUDGET_EXCEEDED
# ====================================================================


def _check_budget_exceeded(itinerary: dict, requirements: dict) -> list[ValidationIssue]:
    """检查总费用是否超预算。"""
    issues: list[ValidationIssue] = []
    total_budget = requirements.get("total_budget", 0) or 0
    if total_budget == 0:
        return issues  # 不限预算模式，跳过

    total_cost = itinerary.get("total_cost", 0) or 0
    if total_cost > total_budget:
        issues.append(ValidationIssue(
            code=ValidationCode.BUDGET_EXCEEDED,
            severity=Severity.WARNING,
            day=None,
            item_id=None,
            message=f"总费用 ¥{total_cost} 超出预算 ¥{total_budget}",
            suggestion="替换高消费项目或放宽预算",
        ))
    return issues


# ====================================================================
# 规则 6: MUST_VISIT_MISSING
# ====================================================================


def _check_must_visit_missing(itinerary: dict, requirements: dict) -> list[ValidationIssue]:
    """检查必去景点是否全部安排。"""
    issues: list[ValidationIssue] = []
    must_visit: list[str] = requirements.get("must_visit") or []

    # 收集已安排的景点名称
    scheduled_names: set[str] = set()
    scheduled_place_ids: set[str] = set()
    for day_data in itinerary.get("days", []):
        for item in day_data.get("items", []):
            place = item.get("_place") or {}
            if place.get("name"):
                scheduled_names.add(place["name"])
            if item.get("place_id"):
                scheduled_place_ids.add(item["place_id"])

    for mv in must_visit:
        if mv not in scheduled_names and mv not in scheduled_place_ids:
            issues.append(ValidationIssue(
                code=ValidationCode.MUST_VISIT_MISSING,
                severity=Severity.ERROR,
                day=None,
                item_id=None,
                message=f"必去景点「{mv}」未在行程中安排",
                suggestion=f"将「{mv}」加入行程",
            ))
    return issues


# ====================================================================
# 规则 7: DUPLICATE_PLACE
# ====================================================================


def _check_duplicate_place(itinerary: dict) -> list[ValidationIssue]:
    """检查同一天是否有重复地点（排除 departure / return / hotel）。"""
    issues: list[ValidationIssue] = []
    for day_data in itinerary.get("days", []):
        day_num = day_data.get("day", 1)
        seen: dict[str, str] = {}  # place_id → first item_id
        for item in day_data.get("items", []):
            pid = item.get("place_id")
            if not pid:
                continue
            itype = item.get("item_type")
            if itype in (ItemType.DEPARTURE.value, ItemType.RETURN.value, ItemType.HOTEL.value):
                continue  # 出发/返回/酒店可重复
            if pid in seen:
                issues.append(ValidationIssue(
                    code=ValidationCode.DUPLICATE_PLACE,
                    severity=Severity.WARNING,
                    day=day_num,
                    item_id=item.get("item_id"),
                    message=f"地点 {pid} 在第{day_num}天重复出现",
                    suggestion="合并游览或替换其他地点",
                ))
            else:
                seen[pid] = item.get("item_id", "")
    return issues


# ====================================================================
# 规则 8: WALKING_LIMIT_EXCEEDED
# ====================================================================


def _check_walking_limit(itinerary: dict, requirements: dict) -> list[ValidationIssue]:
    """检查每日步行距离是否超限。"""
    issues: list[ValidationIssue] = []
    limit = requirements.get("walking_limit_m") or 999_999

    for day_data in itinerary.get("days", []):
        day_num = day_data.get("day", 1)
        walking = day_data.get("walking_distance_m", 0) or 0
        if walking > limit:
            issues.append(ValidationIssue(
                code=ValidationCode.WALKING_LIMIT_EXCEEDED,
                severity=Severity.WARNING,
                day=day_num,
                item_id=None,
                message=f"第{day_num}天步行 {walking} 米，超出限制 {limit} 米",
                suggestion="替换远距离景点或改用公交/驾车",
            ))
    return issues


# ====================================================================
# 规则 9: FOOD_AVOIDANCE_CONFLICT
# ====================================================================


def _check_food_avoidance(itinerary: dict, requirements: dict) -> list[ValidationIssue]:
    """检查餐厅是否与饮食禁忌冲突。"""
    issues: list[ValidationIssue] = []
    avoidances: list[str] = requirements.get("food_avoidances") or []

    if not avoidances:
        return issues

    for day_data in itinerary.get("days", []):
        day_num = day_data.get("day", 1)
        for item in day_data.get("items", []):
            itype = item.get("item_type")
            if itype not in (ItemType.LUNCH.value, ItemType.DINNER.value):
                continue
            place = item.get("_place") or {}
            categories = place.get("categories", [])
            # 检查餐厅分类是否命中用户回避项（简单关键词匹配）
            for av in avoidances:
                for cat in categories:
                    if av in cat or cat in av:
                        issues.append(ValidationIssue(
                            code=ValidationCode.FOOD_AVOIDANCE_CONFLICT,
                            severity=Severity.WARNING,
                            day=day_num,
                            item_id=item.get("item_id"),
                            message=f"餐厅「{place.get('name', '')}」分类含「{cat}」，与饮食禁忌「{av}」冲突",
                            suggestion="更换餐厅",
                        ))
    return issues


# ====================================================================
# 规则 10: DAILY_END_TIME_EXCEEDED
# ====================================================================


def _check_daily_end_time(itinerary: dict, requirements: dict) -> list[ValidationIssue]:
    """检查每日最后一项结束时间是否超出用户设定。"""
    issues: list[ValidationIssue] = []
    daily_end = requirements.get("daily_end_time", "18:00") or "18:00"

    for day_data in itinerary.get("days", []):
        day_num = day_data.get("day", 1)
        items = day_data.get("items", [])
        if not items:
            continue
        last_end = items[-1].get("end_time", "")
        if last_end and last_end > daily_end:
            issues.append(ValidationIssue(
                code=ValidationCode.DAILY_END_TIME_EXCEEDED,
                severity=Severity.WARNING,
                day=day_num,
                item_id=items[-1].get("item_id"),
                message=f"第{day_num}天 {last_end} 结束，超出设定 {daily_end}",
                suggestion="压缩行程或调整每日结束时间",
            ))
    return issues


# ====================================================================
# 指标计算
# ====================================================================


def _compute_metrics(
    itinerary: dict, requirements: dict, issues: list[ValidationIssue]
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

    # 兴趣覆盖率（简化：计算景点中命中兴趣的比例）
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


def _enrich_items(
    itinerary: dict, place_map: dict[str, dict], route_map: dict[str, dict]
) -> None:
    """为每个 item 注入 _place 和 _route 引用，方便校验时读取。"""
    for day_data in itinerary.get("days", []):
        for item in day_data.get("items", []):
            pid = item.get("place_id")
            if pid and pid in place_map:
                item["_place"] = place_map[pid]
            rid = item.get("route_from_previous_id")
            if rid and rid in route_map:
                item["_route"] = route_map[rid]


def _get_weekday(date_str: str) -> int:
    """从 YYYY-MM-DD 计算 ISO 周几（1=周一 … 7=周日）。"""
    if not date_str:
        return 0
    try:
        y, m, d = map(int, date_str.split("-"))
        dt = datetime(y, m, d)
        return dt.isoweekday()
    except (ValueError, AttributeError):
        return 0

"""
路线与时间校验器
================

检查:
  TIME_CONFLICT             前后行程项时间是否重叠或顺序错误
  ROUTE_TIME_INSUFFICIENT   路线耗时是否超出相邻项间隔
  DAILY_END_TIME_EXCEEDED   每日结束时间是否超限
"""

from __future__ import annotations

from datetime import datetime

from backend.schemas.evaluation import Severity, ValidationCode, ValidationIssue


def _parse_time(time_str: str | None) -> datetime | None:
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


# ====================================================================
# 规则 3: TIME_CONFLICT
# ====================================================================


def validate_time_conflict(itinerary: dict) -> list[ValidationIssue]:
    """检查同一天内前后行程项时间是否重叠或顺序错误。"""
    issues: list[ValidationIssue] = []
    for day_data in itinerary.get("days", []):
        day_num = day_data.get("day", 1)
        items = day_data.get("items", [])
        for i in range(len(items) - 1):
            curr_end = items[i].get("end_time", "")
            next_start = items[i + 1].get("start_time", "")
            if curr_end and next_start and curr_end > next_start:
                curr_name = items[i].get("item_id", f"第{i}项")
                next_name = items[i + 1].get("item_id", f"第{i+1}项")
                issues.append(ValidationIssue(
                    code=ValidationCode.TIME_CONFLICT,
                    severity=Severity.ERROR,
                    day=day_num,
                    item_id=items[i + 1].get("item_id"),
                    message=(
                        f"「{curr_name}」{curr_end} 结束，"
                        f"但「{next_name}」{next_start} 已开始"
                    ),
                    suggestion="调整前后项时间或顺序",
                ))
    return issues


# ====================================================================
# 规则 4: ROUTE_TIME_INSUFFICIENT
# ====================================================================


def validate_route_time(itinerary: dict) -> list[ValidationIssue]:
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
# 规则 10: DAILY_END_TIME_EXCEEDED
# ====================================================================


def validate_daily_end_time(itinerary: dict, requirements: dict) -> list[ValidationIssue]:
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

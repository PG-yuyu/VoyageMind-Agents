"""
开放时间校验器
==============

检查:
  PLACE_CLOSED              景点/餐厅在游览时段是否开放（考虑周几）
  ARRIVAL_OUTSIDE_OPENING   到达时间是否在开放时间窗口内
"""

from __future__ import annotations

from datetime import datetime

from backend.schemas.evaluation import Severity, ValidationCode, ValidationIssue


def _parse_time(time_str: str | None) -> datetime | None:
    """将 HH:MM 转为今日 datetime，失败返回 None。"""
    if not time_str:
        return None
    try:
        h, m = map(int, time_str.split(":"))
        return datetime(2000, 1, 1, h, m)
    except (ValueError, AttributeError):
        return None


def _get_weekday(date_str: str) -> int:
    """从 YYYY-MM-DD 计算 ISO 周几（1=周一 … 7=周日）。"""
    if not date_str:
        return 0
    try:
        y, m, d = map(int, date_str.split("-"))
        return datetime(y, m, d).isoweekday()
    except (ValueError, AttributeError):
        return 0


def _d(obj) -> dict:
    """对象/字典 → dict。"""
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "dict"):
        return obj.dict()
    return {}


def validate_opening_time(
    itinerary: dict,
) -> list[ValidationIssue]:
    """检查开放时间相关约束。

    Args:
        itinerary: Itinerary 字典（已通过 _enrich_items 注入 _place 引用）

    Returns:
        list[ValidationIssue]: 校验问题列表
    """
    issues: list[ValidationIssue] = []

    for day_data in itinerary.get("days", []):
        day_num = day_data.get("day", 1)
        date_str = day_data.get("date", "")
        weekday = _get_weekday(date_str)

        for item in day_data.get("items", []):
            place = item.get("_place")
            if not place:
                continue

            # ── PLACE_CLOSED：周几是否开放 ──────────────────────────────
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
                continue  # 已不开放，无需检查到达时间

            # ── ARRIVAL_OUTSIDE_OPENING_HOURS ──────────────────────────
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
                    suggestion="提前结束或缩短游览时间",
                ))

    return issues

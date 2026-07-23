"""
数据一致性校验器
================

检查:
  MUST_VISIT_MISSING   必去景点是否都已安排
  DUPLICATE_PLACE      同一天是否有重复地点（排除出发/返回/酒店）
  INVALID_COORDINATE   地点坐标是否合法
  UNVERIFIED_ROUTE     路线是否未经真实道路验证
"""

from __future__ import annotations

from schemas.evaluation import Severity, ValidationCode, ValidationIssue
from schemas.itinerary import ItemType


# ====================================================================
# 规则 6: MUST_VISIT_MISSING
# ====================================================================


def validate_must_visit(
    itinerary: dict,
    requirements: dict,
) -> list[ValidationIssue]:
    """检查必去景点是否全部安排。

    同时匹配 place.name 和 place_id 两种标识方式。
    """
    must_visit: list[str] = requirements.get("must_visit") or []
    if not must_visit:
        return []

    scheduled_names: set[str] = set()
    scheduled_place_ids: set[str] = set()
    for day_data in itinerary.get("days", []):
        for item in day_data.get("items", []):
            place = item.get("_place") or {}
            if place.get("name"):
                scheduled_names.add(place["name"])
            if item.get("place_id"):
                scheduled_place_ids.add(item["place_id"])

    issues: list[ValidationIssue] = []
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


def validate_duplicate_place(itinerary: dict) -> list[ValidationIssue]:
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
                continue
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
# 规则: INVALID_COORDINATE
# ====================================================================


def validate_coordinate(itinerary: dict) -> list[ValidationIssue]:
    """检查地点坐标是否合法（经度 ±180，纬度 ±90）。"""
    issues: list[ValidationIssue] = []
    for day_data in itinerary.get("days", []):
        day_num = day_data.get("day", 1)
        for item in day_data.get("items", []):
            place = item.get("_place") or {}
            lon = place.get("longitude")
            lat = place.get("latitude")
            if lon is None or lat is None:
                continue  # 无坐标信息的跳过（如出发项）
            if not (-180 <= lon <= 180) or not (-90 <= lat <= 90):
                issues.append(ValidationIssue(
                    code=ValidationCode.INVALID_COORDINATE,
                    severity=Severity.ERROR,
                    day=day_num,
                    item_id=item.get("item_id"),
                    message=f"地点「{place.get('name', '')}」坐标不合法 ({lon}, {lat})",
                    suggestion="通过高德 POI 查询更新坐标",
                ))
    return issues


# ====================================================================
# 规则: UNVERIFIED_ROUTE
# ====================================================================


def validate_route_verified(itinerary: dict) -> list[ValidationIssue]:
    """检查是否存在未经真实道路验证的路线（straight_line_estimation）。"""
    issues: list[ValidationIssue] = []
    for day_data in itinerary.get("days", []):
        day_num = day_data.get("day", 1)
        for item in day_data.get("items", []):
            route = item.get("_route") or {}
            source = route.get("source", "")
            if source == "straight_line_estimation":
                issues.append(ValidationIssue(
                    code=ValidationCode.UNVERIFIED_ROUTE,
                    severity=Severity.INFO,
                    day=day_num,
                    item_id=item.get("item_id"),
                    message="路线未经真实道路验证（直线距离估算）",
                    suggestion="检查高德 API 状态后重新规划路线",
                ))
    return issues

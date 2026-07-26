"""
步行上限校验器
==============

检查:
  WALKING_LIMIT_EXCEEDED  每日步行距离是否超出用户设定的明确上限
"""

from __future__ import annotations

from backend.schemas.evaluation import Severity, ValidationCode, ValidationIssue


def validate_walking(
    itinerary: dict,
    requirements: dict,
) -> list[ValidationIssue]:
    """检查每日步行距离是否超限。

    Args:
        itinerary: Itinerary 字典
        requirements: TravelRequest 字典（含 walking_limit_m）

    Returns:
        list[ValidationIssue]: 超限问题列表；上限=0 时使用默认值 999_999
    """
    limit = requirements.get("walking_limit_m") or 999_999
    if limit >= 999_999:
        return []  # 用户未设定步行上限，跳过

    issues: list[ValidationIssue] = []
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

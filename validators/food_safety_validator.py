"""
饮食安全校验器
==============

检查:
  FOOD_AVOIDANCE_CONFLICT  餐厅分类是否与用户明确饮食禁忌冲突
"""

from __future__ import annotations

from schemas.evaluation import Severity, ValidationCode, ValidationIssue
from schemas.itinerary import ItemType


def validate_food_safety(
    itinerary: dict,
    requirements: dict,
) -> list[ValidationIssue]:
    """检查餐厅是否与饮食禁忌冲突。

    使用类别关键词匹配（如 "辣" → 含"辣"的分类即视为冲突）。
    匹配逻辑：用户禁忌词 in 餐厅分类 or 餐厅分类 in 用户禁忌词。

    Args:
        itinerary: Itinerary 字典（已注入 _place 引用）
        requirements: TravelRequest 字典（含 food_avoidances）

    Returns:
        list[ValidationIssue]: 饮食冲突列表
    """
    avoidances: list[str] = requirements.get("food_avoidances") or []
    if not avoidances:
        return []

    issues: list[ValidationIssue] = []
    for day_data in itinerary.get("days", []):
        day_num = day_data.get("day", 1)
        for item in day_data.get("items", []):
            itype = item.get("item_type")
            if itype not in (ItemType.LUNCH.value, ItemType.DINNER.value):
                continue
            place = item.get("_place") or {}
            categories = place.get("categories", [])
            name = place.get("name", "")
            for av in avoidances:
                for cat in categories:
                    if av in cat or cat in av:
                        issues.append(ValidationIssue(
                            code=ValidationCode.FOOD_AVOIDANCE_CONFLICT,
                            severity=Severity.WARNING,
                            day=day_num,
                            item_id=item.get("item_id"),
                            message=(
                                f"餐厅「{name}」分类含「{cat}」，"
                                f"与饮食禁忌「{av}」冲突"
                            ),
                            suggestion="更换餐厅",
                        ))
    return issues

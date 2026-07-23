"""
预算上限校验器
==============

检查:
  BUDGET_EXCEEDED  总费用是否超出用户设定的明确预算上限
"""

from __future__ import annotations

from schemas.evaluation import Severity, ValidationCode, ValidationIssue


def validate_budget(
    itinerary: dict,
    requirements: dict,
) -> list[ValidationIssue]:
    """检查总费用是否超预算。

    Args:
        itinerary: Itinerary 字典
        requirements: TravelRequest 字典（含 total_budget）

    Returns:
        list[ValidationIssue]: 超预算问题列表；total_budget=0（不限）时返回空
    """
    total_budget = requirements.get("total_budget", 0) or 0
    if total_budget == 0:
        return []  # 不限预算模式，跳过

    total_cost = itinerary.get("total_cost", 0) or 0
    if total_cost > total_budget:
        return [
            ValidationIssue(
                code=ValidationCode.BUDGET_EXCEEDED,
                severity=Severity.WARNING,
                day=None,
                item_id=None,
                message=f"总费用 ¥{total_cost:.0f} 超出预算 ¥{total_budget:.0f}",
                suggestion="替换高消费项目或放宽预算",
            )
        ]
    return []

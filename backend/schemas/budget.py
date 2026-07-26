"""
预算明细模型 —— 成员三负责
============================

费用由 Python 确定性规则计算，不由大模型生成。

计算规则:
- 酒店 = 单价 × 入住晚数
- 门票 = 单价 × 人数
- 餐饮 = 人均 × 人数
- 交通 = 按路线或固定估算
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class BudgetSummary(BaseModel):
    """费用明细。"""

    hotel_cost: float = Field(0.0, ge=0, description="酒店总费用（元）")
    ticket_cost: float = Field(0.0, ge=0, description="门票总费用（元）")
    meal_cost: float = Field(0.0, ge=0, description="餐饮总费用（元）")
    transport_cost: float = Field(0.0, ge=0, description="交通总费用（元）")
    other_cost: float = Field(0.0, ge=0, description="其他费用（元）")
    total_cost: float = Field(0.0, ge=0, description="合计（元）")
    hotel_nights: int = Field(0, ge=0, description="入住晚数（统计 hotel item 数量）")
    total_budget: float = Field(0.0, ge=0, description="用户总预算（0=不限）")
    remaining_budget: float = Field(0.0, description="剩余预算（可为负）")
    over_budget: bool = Field(False, description="是否超预算")


# ── API 请求 ──────────────────────────────────────────────────────


class CalculateBudgetRequest(BaseModel):
    """预算核算请求。"""

    itinerary: dict[str, Any] = Field(..., description="Itinerary 字典")
    requirements: dict[str, Any] = Field(..., description="TravelRequest 字典")

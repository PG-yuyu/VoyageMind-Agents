"""
预算核算服务
============

由 Python 确定性规则计算，不依赖大模型。

计算规则:
- 酒店: 单价 × 入住晚数（天数 - 1）
- 门票: 单价 × 人数（仅 attraction 类型，按 per_person 计价）
- 餐饮: 人均 × 人数 × 餐数
- 交通: 按路线距离估算或实际费用累加
"""

from __future__ import annotations

from backend.schemas.budget import BudgetSummary
from backend.schemas.itinerary import ItemType


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 交通费用估算：每公里费用（元）
TRANSPORT_COST_PER_KM: dict[str, float] = {
    "walking": 0.0,
    "driving": 2.5,
    "transit": 3.0,
    "straight_line": 0.0,
}


def _safe_float(value, default: float = 0.0) -> float:
    """安全转 float，兼容 dict / 对象 两种输入。"""
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def _safe_int(value, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


# ---------------------------------------------------------------------------
# 核心计算
# ---------------------------------------------------------------------------


def calculate_budget(
    itinerary: dict | object,
    requirements: dict | object,
) -> BudgetSummary:
    """根据行程和需求计算完整预算。

    Args:
        itinerary: Itinerary 字典或 Pydantic 对象
        requirements: TravelRequest 字典或 Pydantic 对象

    Returns:
        BudgetSummary: 费用明细
    """

    # ── 归一化为 dict ──────────────────────────────────────────────
    it = _to_dict(itinerary)
    req = _to_dict(requirements)

    # ── 基础参数 ──────────────────────────────────────────────────
    days: int = _safe_int(req.get("days"), default=1)
    people: int = _safe_int(req.get("people"), default=1)
    total_budget: float = _safe_float(req.get("total_budget"), default=0.0)

    hotel_budget_per_night: float = _safe_float(
        req.get("hotel_budget_per_night"), default=0.0
    )
    meal_budget_per_person: float = _safe_float(
        req.get("meal_budget_per_person"), default=50.0
    )

    # ── 酒店费用 ──────────────────────────────────────────────────
    # 天数=N 则住 N-1 晚；若没指定酒店单价，按用户 hotel_budget_per_night 估算
    nights = max(days - 1, 1)
    hotel_price: float = _safe_float(
        (_get_place(it, "hotel") or {}).get("price"), default=0.0
    )
    if hotel_price == 0.0:
        hotel_price = hotel_budget_per_night
    hotel_cost = hotel_price * nights

    # ── 门票费用 ──────────────────────────────────────────────────
    ticket_cost = 0.0
    for day_data in it.get("days", []):
        for item in day_data.get("items", []):
            if item.get("item_type") == ItemType.ATTRACTION.value:
                ticket_cost += _safe_float(item.get("cost_per_person")) * people

    # ── 餐饮费用 ──────────────────────────────────────────────────
    meal_count = 0
    meal_total = 0.0
    for day_data in it.get("days", []):
        for item in day_data.get("items", []):
            itype = item.get("item_type")
            if itype in (ItemType.LUNCH.value, ItemType.DINNER.value):
                meal_count += 1
                meal_total += _safe_float(item.get("total_cost"))

    # 如果行程中还没有 item 级餐饮费用，按用户预算估算
    if meal_total == 0.0 and meal_count > 0:
        meal_total = meal_budget_per_person * people * meal_count
    meal_cost = meal_total

    # ── 交通费用 ──────────────────────────────────────────────────
    transport_cost = 0.0
    for day_data in it.get("days", []):
        for item in day_data.get("items", []):
            route = item.get("_route") or {}
            if route:
                mode = route.get("mode", "walking")
                distance_km = _safe_int(route.get("distance_m"), default=0) / 1000.0
                rate = TRANSPORT_COST_PER_KM.get(mode, 0.0)
                transport_cost += distance_km * rate * people

    # 若无路线数据，按步行 0 元默认
    if transport_cost == 0.0:
        transport_cost = 0.0  # 默认步行不计费

    # ── 汇总 ──────────────────────────────────────────────────────
    total = hotel_cost + ticket_cost + meal_cost + transport_cost
    remaining = total_budget - total

    return BudgetSummary(
        hotel_cost=round(hotel_cost, 2),
        ticket_cost=round(ticket_cost, 2),
        meal_cost=round(meal_cost, 2),
        transport_cost=round(transport_cost, 2),
        other_cost=0.0,
        total_cost=round(total, 2),
        total_budget=round(total_budget, 2),
        remaining_budget=round(remaining, 2),
        over_budget=remaining < 0 and total_budget > 0,
    )


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------


def _to_dict(obj) -> dict:
    """将 Pydantic 对象或 dict 统一转为 dict。"""
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "dict"):
        return obj.dict()
    return {}


def _get_place(itinerary: dict, place_type: str) -> dict | None:
    """从行程中提取指定类型的地点信息。"""
    for day_data in itinerary.get("days", []):
        for item in day_data.get("items", []):
            if item.get("item_type") == place_type:
                return item.get("_place") or {}
    return None

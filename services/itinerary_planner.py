"""
行程规划核心服务
================

将候选地点与路线编排为 1~3 日行程。

算法原则:
- 酒店作为每日出发和返回锚点
- 必去景点优先分配
- 上午 1~2 个景点 → 午餐 → 下午 1~2 个景点 → 返回酒店
- 餐饮在合适时段插入，优先选靠近当前景点的餐厅
- 路线耗时计入时间轴

注意: 本模块只做机械的时间槽编排。调整策略和自然语言解释由 Agent 层（planning_agent）负责。
"""

from __future__ import annotations

import copy
import uuid
from datetime import datetime, timedelta

from schemas.itinerary import (
    Itinerary,
    ItineraryDay,
    ItineraryItem,
    ItineraryStatus,
    ItemType,
)


# ── 时间常量 ────────────────────────────────────────────────────────
DEFAULT_START = "09:00"
DEFAULT_END = "18:00"
LUNCH_EARLIEST = "11:30"
LUNCH_LATEST = "13:30"
DINNER_EARLIEST = "17:30"
DINNER_LATEST = "19:30"
DEFAULT_MEAL_DURATION = 60  # 分钟
DEFAULT_ATTRACTION_DURATION = 120
BUFFER_MINUTES = 15  # 景点之间最小缓冲


def generate_itinerary(
    requirements: dict,
    hotel: dict | None,
    attractions: list[dict],
    restaurants: list[dict],
    route_mode_priority: list[str] | None = None,
    max_candidates_per_day: int = 5,
) -> Itinerary:
    """根据用户需求和候选地点生成初始行程。

    Args:
        requirements: TravelRequest 字典
        hotel: 酒店 Place 字典
        attractions: 景点列表（已按推荐度排序）
        restaurants: 餐厅列表
        route_mode_priority: 交通方式优先级，默认 ["walking", "transit"]
        max_candidates_per_day: 每天最多安排几个地点

    Returns:
        Itinerary: 完整行程（状态 draft，尚未挂载路线详情）
    """
    days_count: int = requirements.get("days", 1) or 1
    start_date: str = requirements.get("start_date", "") or _default_start_date()
    daily_start: str = requirements.get("daily_start_time", DEFAULT_START) or DEFAULT_START
    daily_end: str = requirements.get("daily_end_time", DEFAULT_END) or DEFAULT_END
    must_visit: list[str] = requirements.get("must_visit") or []
    people: int = requirements.get("people", 1) or 1

    mode_priority = route_mode_priority or ["walking", "transit"]

    # ── 1. 分类景点: 必去优先，其余按原始顺序 ────────────────────────
    must_attrs, normal_attrs = _partition_attractions(attractions, must_visit)

    # ── 2. 将景点分配到各天 ─────────────────────────────────────────
    daily_slots = _distribute_attractions(
        must_attrs, normal_attrs, days_count, max_candidates_per_day
    )

    # ── 3. 构建每天的 ItineraryDay ──────────────────────────────────
    hotel_place_id = (hotel or {}).get("place_id", "")
    itinerary_days: list[ItineraryDay] = []
    total_cost = 0.0

    for day_idx in range(days_count):
        day_num = day_idx + 1
        day_attrs = daily_slots[day_idx]
        day_date = _add_days(start_date, day_idx)

        items, day_cost, day_walking = _build_day_timeline(
            day_num=day_num,
            date=day_date,
            attractions=day_attrs,
            restaurants=restaurants,
            hotel=hotel,
            daily_start=daily_start,
            daily_end=daily_end,
            people=people,
        )

        daily_cost = sum(
            it.total_cost
            for it in items
            if it.item_type
            not in (ItemType.DEPARTURE, ItemType.RETURN, ItemType.HOTEL)
        )

        itinerary_days.append(ItineraryDay(
            day=day_num,
            date=day_date,
            items=items,
            daily_cost=round(daily_cost, 2),
            walking_distance_m=day_walking,
            start_time=items[0].start_time if items else daily_start,
            end_time=items[-1].end_time if items else daily_end,
        ))
        total_cost += daily_cost

    itinerary_id = f"trip_{uuid.uuid4().hex[:8]}"
    session_id = requirements.get("session_id", "unknown")

    return Itinerary(
        itinerary_id=itinerary_id,
        session_id=session_id,
        version=1,
        parent_version=None,
        requirements_snapshot=copy.deepcopy(requirements),
        days=itinerary_days,
        hotel_place_id=hotel_place_id or None,
        total_cost=round(total_cost, 2),
        status=ItineraryStatus.DRAFT,
    )


# ====================================================================
# 每日时间轴构建
# ====================================================================


def _build_day_timeline(
    day_num: int,
    date: str,
    attractions: list[dict],
    restaurants: list[dict],
    hotel: dict | None,
    daily_start: str,
    daily_end: str,
    people: int,
) -> tuple[list[ItineraryItem], float, int]:
    """为一天构建详细的行程时间轴。

    Returns:
        (items, daily_cost, walking_distance_m)
    """
    items: list[ItineraryItem] = []
    item_idx = 0
    hotel_place_id = (hotel or {}).get("place_id", "")
    current_time = daily_start
    current_place_id = hotel_place_id or None

    # ── 出发项 ──────────────────────────────────────────────────────
    items.append(_make_item(
        day_num=day_num, idx=item_idx, item_type=ItemType.DEPARTURE,
        place_id=hotel_place_id, start=current_time, end=current_time,
        duration=0, cost=0, people=people, locked=True,
        note=f"从{(hotel or {}).get('name', '酒店')}出发",
    ))
    item_idx += 1

    # ── 分配上午 / 下午景点 ──────────────────────────────────────────
    mid = max(1, len(attractions) // 2) if len(attractions) > 1 else len(attractions)
    morning_attrs = attractions[:mid]
    afternoon_attrs = attractions[mid:]

    walking_total = 0

    # ── 上午景点 ────────────────────────────────────────────────────
    for attr in morning_attrs:
        # 路线耗时（此时仅有估算值，后续 attach_routes 补充真实数据）
        route_dur = attr.get("_estimated_route_duration_minutes", 15)
        walking_total += attr.get("_estimated_route_distance_m", 500) or 0
        arrival = _add_minutes(current_time, route_dur)
        dur = attr.get("duration_minutes") or DEFAULT_ATTRACTION_DURATION
        end_time = _add_minutes(arrival, dur)

        price = attr.get("price", 0) or 0
        total = price * people

        items.append(_make_item(
            day_num=day_num, idx=item_idx, item_type=ItemType.ATTRACTION,
            place_id=attr.get("place_id", ""), start=arrival, end=end_time,
            duration=dur, cost_per_person=price, total=total, people=people,
            note=attr.get("recommendation_reason", ""),
        ))
        item_idx += 1
        current_time = _add_minutes(end_time, BUFFER_MINUTES)

    # ── 午餐 ────────────────────────────────────────────────────────
    lunch = _pick_restaurant(restaurants, "lunch", current_time, current_place_id)
    lunch_time = _clamp_time(current_time, LUNCH_EARLIEST, LUNCH_LATEST)
    lunch_end = _add_minutes(lunch_time, DEFAULT_MEAL_DURATION)
    lunch_cost = (lunch.get("price", 0) or 0) * people if lunch else 0

    items.append(_make_item(
        day_num=day_num, idx=item_idx, item_type=ItemType.LUNCH,
        place_id=lunch.get("place_id", "") if lunch else "",
        start=lunch_time, end=lunch_end,
        duration=DEFAULT_MEAL_DURATION, cost_per_person=lunch.get("price", 0) if lunch else 0,
        total=lunch_cost, people=people,
        note=lunch.get("name", "") if lunch else "午餐（未指定餐厅）",
    ))
    item_idx += 1
    current_time = lunch_end

    # ── 下午景点 ────────────────────────────────────────────────────
    for attr in afternoon_attrs:
        route_dur = attr.get("_estimated_route_duration_minutes", 15)
        walking_total += attr.get("_estimated_route_distance_m", 500) or 0
        arrival = _add_minutes(current_time, route_dur)
        dur = attr.get("duration_minutes") or DEFAULT_ATTRACTION_DURATION
        end_time = _add_minutes(arrival, dur)

        price = attr.get("price", 0) or 0
        total = price * people

        items.append(_make_item(
            day_num=day_num, idx=item_idx, item_type=ItemType.ATTRACTION,
            place_id=attr.get("place_id", ""), start=arrival, end=end_time,
            duration=dur, cost_per_person=price, total=total, people=people,
            note=attr.get("recommendation_reason", ""),
        ))
        item_idx += 1
        current_time = _add_minutes(end_time, BUFFER_MINUTES)

    # ── 返回酒店 ────────────────────────────────────────────────────
    return_time = min(current_time, daily_end) if current_time <= daily_end else current_time
    items.append(_make_item(
        day_num=day_num, idx=item_idx, item_type=ItemType.RETURN,
        place_id=hotel_place_id, start=return_time,
        end=_add_minutes(return_time, 15),
        duration=15, cost=0, people=people, locked=True,
        note="返回酒店",
    ))

    daily_cost = sum(it.total_cost for it in items)
    return items, daily_cost, walking_total


# ====================================================================
# 景点分配
# ====================================================================


def _partition_attractions(
    attractions: list[dict], must_visit: list[str]
) -> tuple[list[dict], list[dict]]:
    """将景点分为「必去」和「普通」两组，保持各自原始顺序。"""
    must: list[dict] = []
    normal: list[dict] = []
    must_set = set(must_visit)
    for a in attractions:
        name = a.get("name", "")
        pid = a.get("place_id", "")
        if name in must_set or pid in must_set:
            must.append(a)
        else:
            normal.append(a)
    return must, normal


def _distribute_attractions(
    must_attrs: list[dict],
    normal_attrs: list[dict],
    days_count: int,
    max_per_day: int,
) -> list[list[dict]]:
    """将景点分配到各天，必去优先，尽量均匀。"""
    slots: list[list[dict]] = [[] for _ in range(days_count)]

    # 先分配必去景点，轮询到每一天
    for i, attr in enumerate(must_attrs):
        day_idx = i % days_count
        if len(slots[day_idx]) < max_per_day:
            slots[day_idx].append(attr)

    # 再分配普通景点，从最少的一天开始填
    for attr in normal_attrs:
        # 找到当前景点数最少的天
        day_idx = min(range(days_count), key=lambda d: len(slots[d]))
        if len(slots[day_idx]) < max_per_day:
            slots[day_idx].append(attr)

    return slots


# ====================================================================
# 餐厅选择
# ====================================================================


def _pick_restaurant(
    restaurants: list[dict],
    meal_type: str,
    current_time: str,
    near_place_id: str | None,
) -> dict | None:
    """从餐厅列表中选一个适合当前时段和位置的。"""
    candidates = [r for r in restaurants if r.get("meal_type") == meal_type or True]
    if not candidates:
        return restaurants[0] if restaurants else None
    # 优先选靠近当前地点的
    for r in candidates:
        if r.get("near_place_id") == near_place_id:
            return r
    return candidates[0]


# ====================================================================
# 时间工具
# ====================================================================


def _parse_time(t: str) -> tuple[int, int]:
    try:
        h, m = map(int, t.split(":"))
        return h, m
    except (ValueError, AttributeError):
        return 0, 0


def _add_minutes(time_str: str, minutes: int) -> str:
    h, m = _parse_time(time_str)
    total = h * 60 + m + minutes
    h2, m2 = divmod(total % 1440, 60)
    return f"{h2:02d}:{m2:02d}"


def _clamp_time(time_str: str, earliest: str, latest: str) -> str:
    """将时间限制在 [earliest, latest] 范围内。"""
    if time_str < earliest:
        return earliest
    if time_str > latest:
        return latest
    return time_str


def _add_days(date_str: str, days: int) -> str:
    try:
        y, m, d = map(int, date_str.split("-"))
        dt = datetime(y, m, d) + timedelta(days=days)
        return dt.strftime("%Y-%m-%d")
    except (ValueError, AttributeError):
        return date_str


def _default_start_date() -> str:
    return datetime.now().strftime("%Y-%m-%d")


# ====================================================================
# Item 工厂
# ====================================================================


def _make_item(
    day_num: int,
    idx: int,
    item_type: ItemType,
    place_id: str | None,
    start: str,
    end: str,
    duration: int,
    cost_per_person: float = 0.0,
    total: float = 0.0,
    people: int = 1,
    locked: bool = False,
    note: str | None = None,
) -> ItineraryItem:
    return ItineraryItem(
        item_id=f"day{day_num}_item_{idx:03d}",
        day=day_num,
        item_type=item_type,
        place_id=place_id or None,
        start_time=start,
        end_time=end,
        duration_minutes=duration,
        route_from_previous_id=None,
        cost_per_person=round(cost_per_person, 2),
        total_cost=round(total, 2),
        locked=locked,
        note=note,
    )

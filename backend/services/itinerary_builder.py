"""
行程构建器
==========

从 LLM 简化输出（place_id + note + 顺序） + 推荐结果中的完整 place 数据，
确定性构建完整的每日行程结构（包含时间轴、费用、路线占位符）。

调用方: planing_agent._build_itinerary_dict() → build_complete_itinerary()
"""

from __future__ import annotations

import logging
import uuid
from datetime import date as date_type
from typing import Any

logger = logging.getLogger(__name__)


# ── 时间常量 ────────────────────────────────────────────────────────
DEFAULT_START = "09:00"
DEFAULT_END = "18:00"
DEFAULT_ATTRACTION_DURATION = 90  # 分钟
LUNCH_DURATION = 60
DINNER_DURATION = 60
RETURN_DURATION = 15


def build_complete_itinerary(
    decisions: dict[str, Any],
    places: list[dict[str, Any]],
    requirements: dict[str, Any],
) -> dict[str, Any]:
    """从 LLM 简化决策构建完整 Itinerary dict。

    Args:
        decisions: LLM 输出的简化结构，格式:
            {{
                "days": [
                    {{
                        "day": 1,
                        "attractions": [
                            {{"place_id": "...", "note": "推荐理由"}},
                            ...
                        ],
                        "lunch_place_id": "...",   # 可选
                        "dinner_place_id": "...",   # 可选
                    }}
                ]
            }}
        places: 推荐结果中的完整地点数据列表 (含 place_id, name, price,
                place_type, coordinate, duration_minutes, tags 等)
        requirements: TravelRequest 字典 (含 days, daily_start_time,
                     daily_end_time, people, session_id 等)

    Returns:
        完整的 Itinerary dict，与当前 Pydantic Itinerary.model_dump() 兼容
    """
    # ── 预处理 ──────────────────────────────────────────────────────
    req_days: int = requirements.get("days", 1) or 1
    daily_start: str = requirements.get("daily_start_time", DEFAULT_START) or DEFAULT_START
    daily_end: str = requirements.get("daily_end_time", DEFAULT_END) or DEFAULT_END
    people: int = requirements.get("people", 1) or 1
    start_date: str = (
        requirements.get("start_date")
        or date_type.today().isoformat()
    )

    # 建立 place_id → place 索引
    place_map: dict[str, dict] = {}
    for p in places:
        pid = p.get("place_id", "")
        if pid:
            place_map[pid] = p

    # 按类型分组
    hotel = next((p for p in places if p.get("place_type") == "hotel"), None)
    restaurants = [p for p in places if p.get("place_type") == "restaurant"]
    attractions_all = [p for p in places if p.get("place_type") == "attraction"]

    # 提取 LLM 决策
    raw_days = decisions.get("days") if isinstance(decisions.get("days"), list) else []
    llm_days: list[dict] = [d for d in raw_days if isinstance(d, dict)]

    # ── 兜底：LLM 完全没输出景点 → 从推荐列表均匀分配 ────────────
    if not llm_days or not any(
        isinstance(d.get("attractions"), list) and len(d.get("attractions", [])) > 0
        for d in llm_days
    ):
        logger.warning("LLM 未输出有效景点分配，使用推荐列表均匀分配")
        llm_days = _fallback_distribute(attractions_all, req_days)

    # ── 逐日构建 ────────────────────────────────────────────────────
    itinerary_days: list[dict] = []
    total_cost = 0.0
    seen_place_ids: set[str] = set()
    lunch_used_ids: set[str] = set()
    dinner_used_ids: set[str] = set()

    for day_idx in range(req_days):
        day_num = day_idx + 1
        llm_day = llm_days[day_idx] if day_idx < len(llm_days) else {}

        # 当天日期
        day_date = _add_days(start_date, day_idx)

        # 解析 LLM 选择的景点（按 place_id 查回完整数据）
        day_attrs: list[dict] = []
        llm_attractions = llm_day.get("attractions") if isinstance(llm_day.get("attractions"), list) else []
        for attr_decision in llm_attractions:
            if not isinstance(attr_decision, dict):
                continue
            pid = attr_decision.get("place_id", "")
            if not pid:
                continue
            # 去重：同一景点不出现在多天
            if pid in seen_place_ids:
                logger.warning("重复景点 %s 已在其他天出现，跳过", pid)
                continue
            place = place_map.get(pid)
            if not place:
                logger.warning("LLM 选了不在候选池的 place_id=%s，跳过", pid)
                continue
            seen_place_ids.add(pid)
            # 合并 LLM note + place 数据
            day_attrs.append({
                **place,
                "note": attr_decision.get("note") or place.get("recommendation_reason", ""),
            })

        # 上午/下午拆分: ceil(n/2) 上午, floor(n/2) 下午
        n = len(day_attrs)
        morning_count = (n + 1) // 2
        morning_attrs = day_attrs[:morning_count]
        afternoon_attrs = day_attrs[morning_count:]

        # 餐厅选择
        lunch = _resolve_restaurant(
            llm_day.get("lunch_place_id"), restaurants, place_map, lunch_used_ids
        )
        dinner = _resolve_restaurant(
            llm_day.get("dinner_place_id"), restaurants, place_map, dinner_used_ids
        )
        if lunch:
            lunch_used_ids.add(lunch.get("place_id", ""))
        if dinner:
            dinner_used_ids.add(dinner.get("place_id", ""))

        hotel_place_id = hotel.get("place_id", "") if hotel else ""

        # ── 构建每日 items（占位时间顺序累加，_resequence_times 会后修正） ──
        items: list[dict] = []
        item_idx = 0
        cur = daily_start  # 当前时间游标

        # 1. departure
        items.append(_make_item(
            day_num, item_idx, "departure", hotel_place_id,
            start=cur, end=cur, duration=0,
            note=f"从{(hotel or {}).get('name', '酒店')}出发",
            locked=True, people=people,
        ))
        item_idx += 1

        # 2. 上午景点
        for attr in morning_attrs:
            price = float(attr.get("price", 0) or 0)
            dur = attr.get("duration_minutes") or DEFAULT_ATTRACTION_DURATION
            end_t = _add_minutes_str(cur, dur)
            items.append(_make_item(
                day_num, item_idx, "attraction", attr.get("place_id", ""),
                start=cur, end=end_t, duration=dur,
                cost_per_person=price, people=people,
                note=attr.get("note") or attr.get("name", ""),
                _place=attr,
            ))
            item_idx += 1
            cur = _add_minutes_str(end_t, 15)  # 15 分钟缓冲

        # 3. lunch（当天有景点就加）
        if n > 0:
            lunch_price = float(lunch.get("price", 0) or 0) if lunch else 0
            lunch_end = _add_minutes_str(cur, LUNCH_DURATION)
            items.append(_make_item(
                day_num, item_idx, "lunch", lunch.get("place_id", "") if lunch else "",
                start=cur, end=lunch_end, duration=LUNCH_DURATION,
                cost_per_person=lunch_price, people=people,
                note=lunch.get("name", "") if lunch else "午餐（未指定餐厅）",
                _place=lunch,
            ))
            item_idx += 1
            cur = lunch_end

        # 4. 下午景点
        for attr in afternoon_attrs:
            price = float(attr.get("price", 0) or 0)
            dur = attr.get("duration_minutes") or DEFAULT_ATTRACTION_DURATION
            end_t = _add_minutes_str(cur, dur)
            items.append(_make_item(
                day_num, item_idx, "attraction", attr.get("place_id", ""),
                start=cur, end=end_t, duration=dur,
                cost_per_person=price, people=people,
                note=attr.get("note") or attr.get("name", ""),
                _place=attr,
            ))
            item_idx += 1
            cur = _add_minutes_str(end_t, 15)

        # 5. dinner（只有下午有景点时才加）
        if afternoon_attrs:
            dinner_price = float(dinner.get("price", 0) or 0) if dinner else 0
            dinner_end = _add_minutes_str(cur, DINNER_DURATION)
            items.append(_make_item(
                day_num, item_idx, "dinner", dinner.get("place_id", "") if dinner else "",
                start=cur, end=dinner_end, duration=DINNER_DURATION,
                cost_per_person=dinner_price, people=people,
                note=dinner.get("name", "") if dinner else "晚餐（未指定餐厅）",
                _place=dinner,
            ))
            item_idx += 1
            cur = dinner_end

        # 6. return
        ret_end = _add_minutes_str(cur, RETURN_DURATION)
        items.append(_make_item(
            day_num, item_idx, "return", hotel_place_id,
            start=cur, end=ret_end, duration=RETURN_DURATION,
            note="返回酒店",
            locked=True, people=people,
        ))

        # ── 汇总当天统计 ────────────────────────────────────────────
        daily_cost = round(sum(
            float(it.get("total_cost", 0) or 0) for it in items
        ), 2)
        # 步行距离暂时估算（_compute_itinerary_routes 会重算精确值）
        walking_estimate = len(day_attrs) * 800

        itinerary_days.append({
            "day": day_num,
            "date": day_date,
            "items": items,
            "daily_cost": daily_cost,
            "walking_distance_m": walking_estimate,
            "start_time": items[0]["start_time"] if items else daily_start,
            "end_time": items[-1]["end_time"] if items else daily_end,
        })
        total_cost += daily_cost

    # ── 构建顶层 ────────────────────────────────────────────────────
    itinerary_id = f"trip_{uuid.uuid4().hex[:8]}"
    session_id = requirements.get("session_id", "")

    return {
        "itinerary_id": itinerary_id,
        "session_id": session_id,
        "version": 1,
        "parent_version": None,
        "requirements_snapshot": requirements,
        "days": itinerary_days,
        "hotel_place_id": hotel.get("place_id") if hotel else None,
        "total_cost": round(total_cost, 2),
        "status": "draft",
    }


# ====================================================================
# 内部辅助
# ====================================================================


def _resolve_restaurant(
    place_id: str | None,
    restaurants: list[dict],
    place_map: dict[str, dict],
    used_ids: set[str],
) -> dict | None:
    """解析餐厅：优先用 LLM 选的，不可用则自动选一个未用过的。"""
    # 1. LLM 选了 → 验证有效
    if place_id:
        r = place_map.get(place_id)
        if r and r.get("place_type") == "restaurant":
            return r
        logger.warning("LLM 选的餐厅 place_id=%s 无效，自动分配", place_id)

    # 2. 自动选择一个未用过的
    unused = [r for r in restaurants if r.get("place_id", "") not in used_ids]
    if unused:
        return unused[0]
    # 3. 全用过 → 选第一个
    return restaurants[0] if restaurants else None


def _make_item(
    day_num: int,
    idx: int,
    item_type: str,
    place_id: str | None,
    start: str = "",
    end: str = "",
    duration: int = 0,
    cost_per_person: float = 0.0,
    people: int = 1,
    locked: bool = False,
    note: str | None = None,
    _place: dict | None = None,
) -> dict:
    """构建单个行程项 dict。"""
    price = round(float(cost_per_person or 0), 2)
    total = round(price * people, 2)
    item: dict[str, Any] = {
        "item_id": f"day{day_num}_item_{idx:03d}",
        "day": day_num,
        "item_type": item_type,
        "place_id": place_id or None,
        "start_time": start,
        "end_time": end,
        "duration_minutes": duration,
        "route_from_previous_id": None,
        "cost_per_person": price,
        "total_cost": total,
        "locked": locked,
        "note": note,
    }
    if _place:
        item["_place"] = _place
    return item


def _add_minutes_str(time_str: str, minutes: int) -> str:
    """时间字符串 + 分钟数 → 新时间字符串 (HH:MM)。"""
    try:
        h, m = map(int, time_str.split(":"))
        total = h * 60 + m + int(minutes)
        h2, m2 = divmod(total % 1440, 60)
        return f"{h2:02d}:{m2:02d}"
    except (ValueError, AttributeError):
        return time_str or "09:00"


def _fallback_distribute(
    attractions: list[dict],
    days_count: int,
) -> list[dict]:
    """LLM 完全无输出时的兜底：将推荐景点均匀分配到每天。"""
    if not attractions:
        return []
    result: list[dict] = []
    for day_num in range(1, days_count + 1):
        day_attrs = [
            a for i, a in enumerate(attractions)
            if i % days_count == day_num - 1
        ]
        result.append({
            "day": day_num,
            "attractions": [
                {"place_id": a.get("place_id", ""), "note": a.get("name", "")}
                for a in day_attrs
            ],
        })
    return result


def _add_days(date_str: str, days: int) -> str:
    """日期字符串 + N 天。"""
    try:
        from datetime import datetime, timedelta
        y, m, d = map(int, date_str.split("-"))
        dt = datetime(y, m, d) + timedelta(days=days)
        return dt.strftime("%Y-%m-%d")
    except (ValueError, AttributeError):
        return date_str

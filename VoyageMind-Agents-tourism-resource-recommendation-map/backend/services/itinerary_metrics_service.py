"""
行程指标计算服务
================

计算行程的各种量化指标，用于评价和对比。
这些指标可以支持 LLM 做更精确的软偏好判断。
"""

from __future__ import annotations

from typing import Any

from backend.schemas.itinerary import ItemType


def calculate_day_stats(
    itinerary: dict[str, Any],
) -> list[dict[str, Any]]:
    """计算每日统计指标。

    Returns:
        list[dict]: 每天的各种统计数据
    """
    stats = []
    for day in itinerary.get("days", []):
        day_num = day.get("day", 0)
        items = day.get("items", [])

        attraction_count = 0
        meal_count = 0
        total_duration = 0
        attraction_duration = 0
        transit_duration = 0
        rest_duration = 0

        for item in items:
            itype = item.get("item_type", "")
            dur = item.get("duration_minutes", 0) or 0
            total_duration += dur

            if itype == ItemType.ATTRACTION.value:
                attraction_count += 1
                attraction_duration += dur
            elif itype in (ItemType.LUNCH.value, ItemType.DINNER.value):
                meal_count += 1
            elif itype == ItemType.REST.value:
                rest_duration += dur
            elif itype == ItemType.TRANSPORT.value:
                transit_duration += dur

        walking = day.get("walking_distance_m", 0) or 0
        daily_cost = day.get("daily_cost", 0) or 0

        # 强度评分（基于景点数量 + 步行距离 + 总时长）
        intensity_score = _calc_intensity(
            attraction_count, walking, total_duration
        )

        stats.append({
            "day": day_num,
            "attraction_count": attraction_count,
            "meal_count": meal_count,
            "total_duration_minutes": total_duration,
            "attraction_duration_minutes": attraction_duration,
            "transit_duration_minutes": transit_duration,
            "rest_duration_minutes": rest_duration,
            "walking_distance_m": walking,
            "daily_cost": daily_cost,
            "intensity_score": intensity_score,
            "intensity_label": _intensity_label(intensity_score),
        })

    return stats


def calculate_overall_metrics(
    itinerary: dict[str, Any],
    requirements: dict[str, Any],
) -> dict[str, Any]:
    """计算整体行程指标。"""
    day_stats = calculate_day_stats(itinerary)

    total_attractions = sum(s["attraction_count"] for s in day_stats)
    total_days = len(itinerary.get("days", []))
    total_cost = itinerary.get("total_cost", 0) or 0

    # 平均每天景点数
    avg_attractions_per_day = (
        round(total_attractions / total_days, 1) if total_days else 0
    )

    # 节奏评估
    intensities = [s["intensity_score"] for s in day_stats]
    avg_intensity = sum(intensities) / len(intensities) if intensities else 0

    # 预算使用率
    budget = requirements.get("total_budget", 0) or 0
    budget_usage = round(total_cost / budget, 2) if budget > 0 else 0

    # 日间差异（判断是否某天特别累或特别松）
    day_variance = (
        max(intensities) - min(intensities) if len(intensities) > 1 else 0
    )

    return {
        "total_attractions": total_attractions,
        "avg_attractions_per_day": avg_attractions_per_day,
        "avg_intensity": round(avg_intensity, 1),
        "max_intensity": max(intensities) if intensities else 0,
        "min_intensity": min(intensities) if intensities else 0,
        "day_variance": round(day_variance, 1),
        "budget_usage_rate": budget_usage,
        "total_cost": total_cost,
        "day_stats": day_stats,
    }


def _calc_intensity(
    attraction_count: int,
    walking_m: int,
    total_duration_minutes: int,
) -> float:
    """计算单天强度评分（0-10）。

    考虑因素：
    - 景点数量（每个约 2 分）
    - 步行距离（每公里约 1 分）
    - 总时长（每小时约 0.5 分）
    """
    score = 0.0
    score += attraction_count * 2.0
    score += (walking_m / 1000) * 1.0
    score += (total_duration_minutes / 60) * 0.5
    return round(min(score, 10.0), 1)


def _intensity_label(score: float) -> str:
    if score <= 3:
        return "轻松"
    elif score <= 5:
        return "适中"
    elif score <= 7:
        return "较紧"
    else:
        return "紧凑"

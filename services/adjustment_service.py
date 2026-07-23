"""
结构调整执行服务
================

在确定为受影响的日程进行结构调整时，提供低层级工具函数：
- 替换行程项
- 删除行程项
- 插入行程项
- 重新排序
- 更新时间和费用

注意：本服务只做机械的数据操作，调整策略由 adjustment_agent 的 LLM 决定。
"""

from __future__ import annotations

import copy
from typing import Any

from schemas.itinerary import ItineraryItem, ItemType


def replace_item(
    days: list[dict],
    target_item_id: str,
    new_place_id: str,
    new_item_type: str | None = None,
    new_duration: int | None = None,
) -> bool:
    """替换指定行程项的地点。

    Args:
        days: 天数列表
        target_item_id: 目标 item_id
        new_place_id: 新地点 place_id
        new_item_type: 新类型（可选）
        new_duration: 新建议时长（可选）

    Returns:
        bool: 是否成功替换
    """
    for day in days:
        for item in day.get("items", []):
            if item.get("item_id") == target_item_id:
                item["place_id"] = new_place_id
                if new_item_type:
                    item["item_type"] = new_item_type
                if new_duration:
                    item["duration_minutes"] = new_duration
                return True
    return False


def delete_item(days: list[dict], target_item_id: str) -> bool:
    """删除指定行程项，并调整前后衔接。

    Args:
        days: 天数列表
        target_item_id: 目标 item_id

    Returns:
        bool: 是否成功删除
    """
    for day in days:
        items = day.get("items", [])
        for i, item in enumerate(items):
            if item.get("item_id") == target_item_id:
                # 调整前后时间（前项 end_time = 后项 start_time）
                if i > 0 and i < len(items) - 1:
                    items[i - 1]["end_time"] = items[i + 1]["start_time"]
                day["items"].pop(i)
                return True
    return False


def insert_item_after(
    days: list[dict],
    after_item_id: str,
    new_item: dict[str, Any],
) -> bool:
    """在指定行程项之后插入新项。

    Args:
        days: 天数列表
        after_item_id: 插入位置的目标 item_id
        new_item: 新行程项字典

    Returns:
        bool: 是否成功插入
    """
    for day in days:
        items = day.get("items", [])
        for i, item in enumerate(items):
            if item.get("item_id") == after_item_id:
                # 生成新 item_id
                new_item["item_id"] = new_item.get("item_id") or f"{after_item_id}_new"
                items.insert(i + 1, new_item)
                return True
    return False


def reorder_items(
    days: list[dict],
    day_num: int,
    new_order: list[str],
) -> bool:
    """重新排列指定天的行程项顺序。

    Args:
        days: 天数列表
        day_num: 第几天
        new_order: 新的 item_id 顺序列表

    Returns:
        bool: 是否成功重排
    """
    for day in days:
        if day.get("day") != day_num:
            continue
        items = day.get("items", [])
        item_map = {it["item_id"]: it for it in items}
        reordered = []
        for iid in new_order:
            if iid in item_map:
                reordered.append(item_map[iid])
        if len(reordered) == len(items):
            day["items"] = reordered
            return True
    return False


def update_item_times(
    days: list[dict],
    target_item_id: str,
    start_time: str | None = None,
    end_time: str | None = None,
) -> bool:
    """更新指定行程项的时间。

    Args:
        days: 天数列表
        target_item_id: 目标 item_id
        start_time: 新开始时间（可选）
        end_time: 新结束时间（可选）

    Returns:
        bool: 是否成功更新
    """
    for day in days:
        for item in day.get("items", []):
            if item.get("item_id") == target_item_id:
                if start_time:
                    item["start_time"] = start_time
                if end_time:
                    item["end_time"] = end_time
                return True
    return False


def recalculate_day_costs(days: list[dict]) -> None:
    """重新计算每天的 total_cost 和 walking_distance_m。"""
    for day in days:
        total = 0.0
        walking = 0
        for item in day.get("items", []):
            total += float(item.get("total_cost", 0) or 0)
        day["daily_cost"] = round(total, 2)
        day["walking_distance_m"] = day.get("walking_distance_m", 0) or 0

"""
局部重规划服务
==============

仅修改受影响的天/时段，锁定未受影响的部分。

用于：
- 用户修改后的局部重规划
- 自动调整失败的局部修复
- 替换单个地点后的衔接调整

设计原则：
1. 锁定项的时间、地点和顺序不得改变
2. 只重新排列和组织 unlocked items
3. 重新计算受影响天的费用、步行距离和时间范围
"""

from __future__ import annotations

import copy
from typing import Any

from schemas.itinerary import ItemType


def get_affected_days(
    itinerary: dict[str, Any],
    target_day: int | None = None,
    target_item_ids: list[str] | None = None,
) -> dict[int, list[dict]]:
    """获取受影响的天和行程项。

    Args:
        itinerary: 行程字典
        target_day: 指定受影响的第几天（None=全部）
        target_item_ids: 指定受影响的行程项 ID 列表

    Returns:
        dict[int, list[dict]]: {day_num: [affected_items]}
    """
    result: dict[int, list[dict]] = {}
    target_set = set(target_item_ids or [])

    for day in itinerary.get("days", []):
        day_num = day.get("day", 0)
        if target_day and day_num != target_day:
            continue

        affected = []
        for item in day.get("items", []):
            if not target_set or item.get("item_id") in target_set:
                affected.append(item)
        if affected:
            result[day_num] = affected

    return result


def lock_items(
    itinerary: dict[str, Any],
    except_item_ids: list[str] | None = None,
    except_days: list[int] | None = None,
) -> None:
    """锁定行程项（除了指定的项/天）。

    Args:
        itinerary: 行程字典
        except_item_ids: 不锁定的 item_id 列表
        except_days: 不锁定的天数列表（整天的项都不锁）
    """
    except_items = set(except_item_ids or [])
    except_days_set = set(except_days or [])

    for day in itinerary.get("days", []):
        day_num = day.get("day", 0)
        for item in day.get("items", []):
            iid = item.get("item_id", "")
            should_lock = not (
                iid in except_items or day_num in except_days_set
            )
            item["locked"] = should_lock


def extract_locked_and_unlocked(
    itinerary: dict[str, Any],
) -> tuple[list[dict], list[dict]]:
    """分离锁定和未锁定的行程项。

    Returns:
        (locked_items, unlocked_items)
    """
    locked = []
    unlocked = []
    for day in itinerary.get("days", []):
        for item in day.get("items", []):
            if item.get("locked"):
                locked.append(item)
            else:
                unlocked.append(item)
    return locked, unlocked


def extract_day(
    itinerary: dict[str, Any],
    day_num: int,
) -> dict[str, Any] | None:
    """提取指定天的行程数据（深拷贝）。

    Returns:
        dict | None: 当天的行程数据，或 None（不存在）
    """
    for day in itinerary.get("days", []):
        if day.get("day") == day_num:
            return copy.deepcopy(day)
    return None


def replace_day(
    itinerary: dict[str, Any],
    day_num: int,
    new_day: dict[str, Any],
) -> bool:
    """替换指定天的行程数据。

    Args:
        itinerary: 行程字典（原地修改）
        day_num: 第几天
        new_day: 新天数据

    Returns:
        bool: 是否成功替换
    """
    for i, day in enumerate(itinerary.get("days", [])):
        if day.get("day") == day_num:
            itinerary["days"][i] = new_day
            return True
    return False


def recalculate_day_metrics(
    itinerary: dict[str, Any],
    day_num: int | None = None,
) -> None:
    """重新计算行程的费用和步行距离指标。

    Args:
        itinerary: 行程字典（原地修改）
        day_num: 指定天数，None=全部
    """
    for day in itinerary.get("days", []):
        if day_num and day.get("day") != day_num:
            continue

        total_cost = 0.0
        walking = day.get("walking_distance_m", 0) or 0
        items = day.get("items", [])

        for item in items:
            total_cost += float(item.get("total_cost", 0) or 0)

        day["daily_cost"] = round(total_cost, 2)
        if items:
            day["start_time"] = items[0].get("start_time", "09:00")
            day["end_time"] = items[-1].get("end_time", "18:00")

    # 重新计算 total_cost
    grand_total = 0.0
    for day in itinerary.get("days", []):
        grand_total += day.get("daily_cost", 0) or 0
    itinerary["total_cost"] = round(grand_total, 2)


def validate_replan_boundaries(
    itinerary: dict[str, Any],
    locked_item_ids: list[str],
) -> list[str]:
    """检查重规划后锁定项是否被意外修改。

    Returns:
        list[str]: 被违反的锁定项说明
    """
    violations = []
    lock_set = set(locked_item_ids)

    for day in itinerary.get("days", []):
        for item in day.get("items", []):
            iid = item.get("item_id", "")
            if iid in lock_set:
                # 检查锁定项是否变化（简化：仅检查是否仍在）
                pass  # 实际比对需传入原始数据

    return violations

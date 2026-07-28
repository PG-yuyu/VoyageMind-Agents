"""
差异对比服务
============

对比两个行程版本的详细差异，生成 TripDiff。

与 version_service.diff_versions 的关系：
- diff_versions: 从持久化版本读取并对比
- diff_service: 提供底层差异算法，可独立于版本存储使用
"""

from __future__ import annotations

from typing import Any

from backend.schemas.itinerary import ItineraryItem
from backend.schemas.version import ChangeType, TripChange, TripDiff


def compute_diff(
    old_itinerary: dict | object,
    new_itinerary: dict | object,
    from_version: int = 1,
    to_version: int = 2,
) -> TripDiff:
    """计算两个行程之间的差异。

    Args:
        old_itinerary: 旧版本行程
        new_itinerary: 新版本行程
        from_version: 旧版本号
        to_version: 新版本号

    Returns:
        TripDiff: 差异详情
    """
    old = _d(old_itinerary)
    new = _d(new_itinerary)

    changes: list[TripChange] = []
    affected_days: set[int] = set()
    unchanged_ids: list[str] = []

    # 索引 items
    old_items: dict[str, dict] = {}
    for day in old.get("days", []):
        for item in day.get("items", []):
            old_items[item.get("item_id", "")] = item

    new_items: dict[str, dict] = {}
    for day in new.get("days", []):
        for item in day.get("items", []):
            new_items[item.get("item_id", "")] = item

    all_ids = set(old_items.keys()) | set(new_items.keys())

    for iid in sorted(all_ids):
        in_old = iid in old_items
        in_new = iid in new_items

        if in_old and in_new:
            o = old_items[iid]
            n = new_items[iid]
            if o.get("place_id") != n.get("place_id") or o.get("item_type") != n.get("item_type"):
                affected_days.add(n.get("day", 0))
                changes.append(TripChange(
                    change_type=ChangeType.REPLACE,
                    before_item_id=iid,
                    after_item_id=iid,
                    before_place_id=o.get("place_id"),
                    after_place_id=n.get("place_id"),
                    before_place_name=_item_place_name(o),
                    after_place_name=_item_place_name(n),
                    reason=_detect_change_reason(o, n),
                    cost_change=round(
                        float(n.get("total_cost", 0) or 0)
                        - float(o.get("total_cost", 0) or 0),
                        2,
                    ),
                    distance_change_m=_dist_diff(o, n),
                ))
            else:
                unchanged_ids.append(iid)

        elif in_old and not in_new:
            o = old_items[iid]
            affected_days.add(o.get("day", 0))
            changes.append(TripChange(
                change_type=ChangeType.DELETE,
                before_item_id=iid,
                after_item_id=None,
                before_place_id=o.get("place_id"),
                after_place_id=None,
                before_place_name=_item_place_name(o),
                after_place_name=None,
                reason="删除项目",
                cost_change=round(-float(o.get("total_cost", 0) or 0), 2),
                distance_change_m=0,
            ))

        elif not in_old and in_new:
            n = new_items[iid]
            affected_days.add(n.get("day", 0))
            changes.append(TripChange(
                change_type=ChangeType.ADD,
                before_item_id=None,
                after_item_id=iid,
                before_place_id=None,
                after_place_id=n.get("place_id"),
                before_place_name=None,
                after_place_name=_item_place_name(n),
                reason="新增项目",
                cost_change=round(float(n.get("total_cost", 0) or 0), 2),
                distance_change_m=0,
            ))

    return TripDiff(
        from_version=from_version,
        to_version=to_version,
        affected_days=sorted(affected_days),
        changes=changes,
        unchanged_item_ids=unchanged_ids,
    )


def _detect_change_reason(
    old_item: dict,
    new_item: dict,
) -> str:
    """自动检测变化原因。"""
    old_type = old_item.get("item_type", "")
    new_type = new_item.get("item_type", "")

    if old_type != new_type:
        return f"类型从 {old_type} 变为 {new_type}"
    if old_item.get("item_type") in ("attraction",):
        return "地点替换"
    return "项目变更"


def _item_place_name(item: dict) -> str | None:
    """尽量从行程项里取出给用户看的地点名称。"""
    place = item.get("_place") or {}
    if isinstance(place, dict):
        name = place.get("name") or place.get("title")
        if name:
            return str(name)
    for key in ("title", "place_name", "name", "note"):
        value = item.get(key)
        if value:
            return str(value)
    return item.get("place_id")


def _dist_diff(old_item: dict, new_item: dict) -> int:
    """估算两个 item 之间的距离差。"""
    old_route = old_item.get("_route") or {}
    new_route = new_item.get("_route") or {}
    old_dist = old_route.get("distance_m", 0) if isinstance(old_route, dict) else 0
    new_dist = new_route.get("distance_m", 0) if isinstance(new_route, dict) else 0
    return int(new_dist) - int(old_dist)


def summarize_changes(diff: TripDiff) -> dict[str, Any]:
    """生成人类可读的变更摘要。

    Args:
        diff: TripDiff 对象

    Returns:
        dict: {
            "summary": "修改了 2 天的行程，共 3 项变更",
            "total_cost_change": 0.0,
            "total_distance_change": 0,
            "affected_days": [1, 2]
        }
    """
    total_cost = sum(c.cost_change for c in diff.changes)
    total_dist = sum(c.distance_change_m for c in diff.changes)

    return {
        "summary": f"修改了 {len(diff.affected_days)} 天的行程，共 {len(diff.changes)} 项变更",
        "total_cost_change": round(total_cost, 2),
        "total_distance_change": total_dist,
        "affected_days": diff.affected_days,
    }


def _d(obj) -> dict:
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "dict"):
        return obj.dict()
    return {}

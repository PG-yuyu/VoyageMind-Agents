"""
行程版本管理服务
================

- 每次修改生成新版本，不覆盖旧版本
- 通过 parent_version 形成版本链
- 提供版本列表、指定版本查询、版本差异对比
"""

from __future__ import annotations

import copy
import uuid
from collections import OrderedDict
from datetime import datetime
from typing import Any

from schemas.version import ChangeType, TripChange, TripDiff
from schemas.itinerary import Itinerary, ItineraryItem, ItineraryStatus


# ============================================================================
# 内存存储（后续可替换为 SQLite / 文件）
# ============================================================================

# 多行程存储: itinerary_id → OrderedDict[version, Itinerary]
_store: dict[str, OrderedDict[int, Itinerary]] = {}


# ============================================================================
# 保存 / 读取
# ============================================================================


def save_version(itinerary: Itinerary) -> Itinerary:
    """保存一个新版本。

    - 首版 version=1, parent_version=None
    - 新版本自动递增 version 号并设置 parent_version
    """
    tid = itinerary.itinerary_id
    if tid not in _store:
        _store[tid] = OrderedDict()

    versions = _store[tid]

    if not versions:
        # 首版
        itinerary.version = 1
        itinerary.parent_version = None
    else:
        latest = max(versions.keys())
        itinerary.version = latest + 1
        itinerary.parent_version = latest

    itinerary.created_at = datetime.now()
    _store[tid][itinerary.version] = copy.deepcopy(itinerary)
    return itinerary


def get_itinerary(itinerary_id: str, version: int | None = None) -> Itinerary | None:
    """获取指定版本行程。version=None 则返回最新版本。"""
    versions = _store.get(itinerary_id)
    if not versions:
        return None
    if version is None:
        version = max(versions.keys())
    return versions.get(version)


def get_all_versions(itinerary_id: str) -> list[dict[str, Any]]:
    """获取行程的所有版本摘要列表。"""
    versions = _store.get(itinerary_id, {})
    return [
        {
            "itinerary_id": itinerary_id,
            "version": v,
            "parent_version": it.parent_version,
            "status": it.status.value,
            "total_cost": it.total_cost,
            "created_at": it.created_at.isoformat() if it.created_at else None,
        }
        for v, it in versions.items()
    ]


# ============================================================================
# 差异对比
# ============================================================================


def diff_versions(
    itinerary_id: str, from_version: int, to_version: int
) -> TripDiff | None:
    """对比两个版本的差异。

    Returns:
        TripDiff: 差异详情；版本不存在返回 None
    """
    old = get_itinerary(itinerary_id, from_version)
    new = get_itinerary(itinerary_id, to_version)
    if old is None or new is None:
        return None

    changes: list[TripChange] = []
    affected_days: set[int] = set()
    unchanged_ids: list[str] = []

    # 收集所有 item（按 item_id 索引）
    old_items: dict[str, ItineraryItem] = {}
    for day in old.days:
        for item in day.items:
            old_items[item.item_id] = item

    new_items: dict[str, ItineraryItem] = {}
    for day in new.days:
        for item in day.items:
            new_items[item.item_id] = item

    all_ids = set(old_items.keys()) | set(new_items.keys())

    for iid in sorted(all_ids):
        in_old = iid in old_items
        in_new = iid in new_items

        if in_old and in_new:
            o = old_items[iid]
            n = new_items[iid]
            if o.place_id != n.place_id:
                affected_days.add(n.day)
                changes.append(TripChange(
                    change_type=ChangeType.REPLACE,
                    before_item_id=iid,
                    after_item_id=iid,
                    before_place_id=o.place_id,
                    after_place_id=n.place_id,
                    reason="地点替换",
                    cost_change=round(n.total_cost - o.total_cost, 2),
                    distance_change_m=_dist_diff(o, n),
                ))
            else:
                unchanged_ids.append(iid)
        elif in_old and not in_new:
            o = old_items[iid]
            affected_days.add(o.day)
            changes.append(TripChange(
                change_type=ChangeType.DELETE,
                before_item_id=iid,
                after_item_id=None,
                before_place_id=o.place_id,
                after_place_id=None,
                reason="删除项目",
                cost_change=round(-o.total_cost, 2),
                distance_change_m=0,
            ))
        elif not in_old and in_new:
            n = new_items[iid]
            affected_days.add(n.day)
            changes.append(TripChange(
                change_type=ChangeType.ADD,
                before_item_id=None,
                after_item_id=iid,
                before_place_id=None,
                after_place_id=n.place_id,
                reason="新增项目",
                cost_change=round(n.total_cost, 2),
                distance_change_m=0,
            ))

    return TripDiff(
        from_version=from_version,
        to_version=to_version,
        affected_days=sorted(affected_days),
        changes=changes,
        unchanged_item_ids=unchanged_ids,
    )


# ============================================================================
# 实用方法
# ============================================================================


def clone_for_modification(
    itinerary: Itinerary,
    new_status: ItineraryStatus | None = None,
) -> Itinerary:
    """深拷贝行程，准备作为新版本修改。"""
    cloned = copy.deepcopy(itinerary)
    if new_status:
        cloned.status = new_status
    return cloned


def lock_all_items(itinerary: Itinerary, locked: bool = True) -> None:
    """批量锁定/解锁行程中的所有 item。"""
    for day in itinerary.days:
        for item in day.items:
            item.locked = locked


def unlock_items(itinerary: Itinerary, item_ids: list[str]) -> None:
    """解锁指定 item。"""
    ids = set(item_ids)
    for day in itinerary.days:
        for item in day.items:
            if item.item_id in ids:
                item.locked = False


def lock_items_except(itinerary: Itinerary, except_ids: list[str]) -> None:
    """锁定除了指定 item 以外的全部 item。"""
    keep = set(except_ids)
    for day in itinerary.days:
        for item in day.items:
            item.locked = item.item_id not in keep


# ============================================================================
# 内部辅助
# ============================================================================


def _dist_diff(old: ItineraryItem, new: ItineraryItem) -> int:
    """估算两个 item 之间的距离差（从 route 中提取）。"""
    old_dist = 0
    new_dist = 0
    # 从 route 引用中获取距离（需 item 上有 _route 扩展属性）
    old_route = getattr(old, "_route", None) or {}
    new_route = getattr(new, "_route", None) or {}
    if isinstance(old_route, dict):
        old_dist = old_route.get("distance_m", 0) or 0
    if isinstance(new_route, dict):
        new_dist = new_route.get("distance_m", 0) or 0
    return new_dist - old_dist

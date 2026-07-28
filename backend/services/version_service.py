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

from backend.schemas.version import ChangeType, TripChange, TripDiff
from backend.schemas.itinerary import Itinerary, ItineraryItem, ItineraryStatus


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


def get_itinerary(
    itinerary_id: str,
    version: int | None = None,
    *,
    enrich: bool = True,
) -> Itinerary | None:
    """获取指定版本行程。version=None 则返回最新版本。

    enrich=True 时自动从 PlaceRepository 补全 items 的 _place 引用，
    确保调用方始终能拿到带地点名称的完整数据。
    """
    versions = _store.get(itinerary_id)
    if not versions:
        return None
    if version is None:
        version = max(versions.keys())
    it = versions.get(version)
    if it is not None and enrich:
        _enrich_loaded_itinerary(it)
    return it


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
                    before_place_name=_item_place_name(o),
                    after_place_name=_item_place_name(n),
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
                before_place_name=_item_place_name(o),
                after_place_name=None,
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
                before_place_name=None,
                after_place_name=_item_place_name(n),
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


def _item_place_name(item: ItineraryItem) -> str | None:
    """尽量从行程项或地点仓库里取出可展示的中文地点名。"""
    place = getattr(item, "_place", None)
    if isinstance(place, dict):
        name = place.get("name") or place.get("title")
        if name:
            return str(name)

    note = getattr(item, "note", None)
    if note:
        return str(note)

    place_id = getattr(item, "place_id", None)
    if place_id:
        try:
            from backend.app.repositories import PlaceRepository
            repo = PlaceRepository()
            place_obj = repo.get_by_id(place_id)
            if place_obj:
                place_dict = place_obj.to_dict()
                name = place_dict.get("name") or place_dict.get("title")
                if name:
                    return str(name)
        except Exception:
            pass
    return place_id


# ============================================================================
# 行程加载后 _place 补全
# ============================================================================


def _enrich_loaded_itinerary(it: Itinerary) -> None:
    """为从存储加载的 Itinerary 的每个 item 补全 _place 引用。

    先 model_dump 为 dict → 注入 _place → 再重新解析为 Itinerary。
    这样 model_dump(mode="json") 之后的 dict 仍保留 _place。
    """
    try:
        from backend.app.repositories import PlaceRepository
        repo = PlaceRepository()
        pid_to_place: dict[str, dict] = {}
        for p in repo.list_attractions() + repo.list_hotels() + repo.list_restaurants():
            pd = p.to_dict()
            pid = pd.get("place_id", "")
            if pid:
                pid_to_place[pid] = pd

        # 先导出为 dict，注入 _place
        it_dict = it.model_dump(mode="json")
        for day_data in it_dict.get("days", []):
            for item in day_data.get("items", []):
                pid = item.get("place_id") or ""
                place = pid_to_place.get(pid)
                if place:
                    item["_place"] = place
                    if not item.get("note") or item["note"].startswith("已替换") or "alt_" in pid:
                        item["note"] = place.get("name", item.get("note") or "")

        # 重新解析（_place 依然在 dict 上，model_dump 保留它）
        # 但 Itinerary(**it_dict) 会丢弃 _place…所以不重新解析，
        # 直接用 _enriched_dict 在调用方手动合并。
        # 把 enriched items 写回原 Itinerary 对象
        from backend.schemas.itinerary import Itinerary
        new_it = Itinerary(**it_dict)
        it.itinerary_id = new_it.itinerary_id
        it.session_id = new_it.session_id
        it.version = new_it.version
        it.parent_version = new_it.parent_version
        it.days = new_it.days
        it.hotel_place_id = new_it.hotel_place_id
        it.total_cost = new_it.total_cost
        it.status = new_it.status
        # _place 已通过 model_dump(mode="json") 保留在 item dict 中
        # 但因为 ItineraryItem 重构丢失了，存到 _enriched_dict 上
        object.__setattr__(it, "_enriched_dict", it_dict)
    except Exception:
        pass


def model_dump_with_places(it: Itinerary) -> dict:
    """与 model_dump(mode="json") 相同，但包含 _place 引用。"""
    enriched = getattr(it, "_enriched_dict", None)
    if enriched:
        return enriched
    # 未 enrich 过，手动注入
    d = it.model_dump(mode="json")
    _inject_places_into_dict(d)
    return d


def _inject_places_into_dict(itinerary_dict: dict) -> None:
    """向行程 dict 的每个 item 注入 _place 引用。"""
    try:
        from backend.app.repositories import PlaceRepository
        repo = PlaceRepository()
        pid_to_place: dict[str, dict] = {}
        for p in repo.list_attractions() + repo.list_hotels() + repo.list_restaurants():
            pd = p.to_dict()
            pid = pd.get("place_id", "")
            if pid:
                pid_to_place[pid] = pd
        for day_data in itinerary_dict.get("days", []):
            for item in day_data.get("items", []):
                pid = item.get("place_id") or ""
                place = pid_to_place.get(pid)
                if place:
                    item["_place"] = place
                    if not item.get("note") or item["note"].startswith("已替换") or "alt_" in pid:
                        item["note"] = place.get("name", item.get("note") or "")
    except Exception:
        pass

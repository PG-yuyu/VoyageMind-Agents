"""
调整 API
========

- POST /api/v1/itineraries/modify          用户主动修改
- POST /api/v1/itineraries/local-replan    局部重规划
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from backend.schemas import ApiResponse
from backend.schemas.modification import ModificationRequest
from backend.agents.adjustment_agent import AdjustmentAgent
from backend.agents.coordinator_agent import (
    _normalize_item_types,
    _sync_replaced_places,
    _extract_places_from_itinerary,
    _enrich_itinerary_display,
    _compute_itinerary_routes,
)

router = APIRouter(prefix="/api/v1/itineraries", tags=["adjustment"])


def _make_alt_fetcher(session_id: str = "", itinerary_id: str = ""):
    """创建替代地点获取函数。

    优先从当前 session 缓存的推荐候选中筛选未被选中的，
    降级到 PlaceRepository 全量查询。
    不再调用成员二推荐（已有缓存，无需重复 LLM 调用）。
    """
    from backend.services.session_store import store as _store

    def fetcher(original_place_id, constraints=None, limit=5):
        constraints = constraints or {}
        indoor_only = constraints.get("indoor") or constraints.get("change_to_indoor")

        # ── 方案 A：从缓存的推荐候选中筛选未选中的 ──────────
        cached = _store.recommended_places.get(session_id, [])
        if cached:
            # 收集当前行程已用的 place_id
            used_ids: set[str] = set()
            if itinerary_id:
                try:
                    from backend.services.version_service import get_itinerary
                    current = get_itinerary(itinerary_id, enrich=False)
                    if current:
                        for day in current.days:
                            for item in day.items:
                                pid = item.place_id or ""
                                if pid:
                                    used_ids.add(pid)
                except Exception:
                    pass

            candidates = []
            for p in cached:
                pd = p if isinstance(p, dict) else {}
                pid = pd.get("place_id", "")
                # 跳过自身 + 已被行程使用的
                if pid == original_place_id or pid in used_ids:
                    continue
                # 类型过滤：景点对景点，餐厅对餐厅
                ptype = pd.get("place_type", "")
                if ptype not in ("attraction", "restaurant"):
                    continue
                # 室内约束
                if indoor_only:
                    tags = pd.get("tags", []) or []
                    if not any("室内" in (t or "") for t in tags if t):
                        continue
                candidates.append(pd)
            if candidates:
                return candidates[:limit]

        # ── 方案 B：PlaceRepository 全量查询 ──────────────
        try:
            from backend.app.repositories import PlaceRepository
            repo = PlaceRepository()
            orig = repo.get_by_id(original_place_id)
            target_type = getattr(orig, "place_type", None) if orig else None
            if target_type == "attraction":
                all_p = repo.list_attractions()
            elif target_type == "restaurant":
                all_p = repo.list_restaurants()
            else:
                all_p = repo.list_attractions() + repo.list_restaurants()
            candidates = []
            for p in all_p:
                pd = p.to_dict()
                if pd.get("place_id") == original_place_id:
                    continue
                if indoor_only:
                    tags = pd.get("tags", []) or []
                    if not any("室内" in (t or "") for t in tags if t):
                        continue
                candidates.append(pd)
            return candidates[:limit]
        except Exception:
            return []
    return fetcher


def _post_process_modified_itinerary(itinerary: dict) -> dict:
    """对修改后的行程做后处理：字段修正 + 名称补全 + 路线重算。"""
    if not itinerary or not itinerary.get("days"):
        return itinerary
    _normalize_item_types(itinerary)
    _sync_replaced_places(itinerary)
    _places = _extract_places_from_itinerary(itinerary)
    if _places:
        _enrich_itinerary_display(itinerary, _places)
        _compute_itinerary_routes(itinerary, _places)
    return itinerary


@router.post("/modify")
async def api_modify(request: ModificationRequest) -> ApiResponse:
    """用户主动修改行程。

    Agent 会自动解析 LLM（优先 DeepSeekLLM，Mock 兜底）。
    """
    try:
        agent = AdjustmentAgent(
            alternative_place_fetcher=_make_alt_fetcher(
                session_id=request.session_id,
                itinerary_id=request.itinerary_id,
            ),
        )
        result = agent.modify(request=request)
        # 后处理：修正字段 + 补全名称 + 重算路线
        if result.get("itinerary"):
            result["itinerary"] = _post_process_modified_itinerary(result["itinerary"])
        return ApiResponse(success=True, data=result)
    except Exception as exc:
        return ApiResponse(
            success=False,
            code="INTERNAL_ERROR",
            message=str(exc),
        )


@router.post("/local-replan")
async def api_local_replan(
    itinerary_id: str,
    base_version: int = 1,
    target_day: int | None = None,
    target_item_id: str | None = None,
    action: str = "replace",
    constraints: dict[str, Any] | None = None,
) -> ApiResponse:
    """仅对指定天/项进行局部重规划。"""
    try:
        request = ModificationRequest(
            session_id="",
            itinerary_id=itinerary_id,
            base_version=max(base_version, 1),
            action=action,
            target_day=target_day,
            target_item_id=target_item_id,
            new_constraints=constraints or {},
        )
        agent = AdjustmentAgent(
            alternative_place_fetcher=_make_alt_fetcher(
                session_id="",
                itinerary_id=itinerary_id,
            ),
        )
        result = agent.modify(request=request)
        if result.get("itinerary"):
            result["itinerary"] = _post_process_modified_itinerary(result["itinerary"])
        return ApiResponse(success=True, data=result)
    except Exception as exc:
        return ApiResponse(
            success=False,
            code="INTERNAL_ERROR",
            message=str(exc),
        )

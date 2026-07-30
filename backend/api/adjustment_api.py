"""
调整 API
========

- POST /api/v1/itineraries/modify          用户主动修改
- POST /api/v1/itineraries/local-replan    局部重规划
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.schemas import ApiResponse
from backend.schemas.modification import ModificationRequest
from backend.agents.adjustment_agent import AdjustmentAgent
from backend.services.chatbot_service import ChatbotService
from backend.agents.coordinator_agent import (
    _normalize_item_types,
    _normalize_itinerary,
    _sync_replaced_places,
    _extract_places_from_itinerary,
)

router = APIRouter(prefix="/api/v1/itineraries", tags=["adjustment"])


class AdjustmentPreviewRequest(BaseModel):
    """只生成修改建议，不直接改写行程。"""

    session_id: str = Field(default="demo_session")
    target_day: int | None = Field(default=None, ge=1)
    action: str = Field(default="replace_attraction")
    original_text: str = Field(default="")
    current_itinerary: dict[str, Any] = Field(default_factory=dict)


def _compact_preview_itinerary(itinerary: dict[str, Any], target_day: int | None) -> list[dict[str, Any]]:
    """压缩前端行程给 LLM，避免长 RAG 描述污染建议。"""
    days = itinerary.get("days") or []
    compact_days: list[dict[str, Any]] = []
    for day in days:
        day_no = day.get("day")
        if target_day and int(day_no or 0) != int(target_day):
            continue
        items = []
        for item in day.get("items") or []:
            items.append({
                "item_id": item.get("item_id") or "",
                "place_id": item.get("place_id") or "",
                "item_type": item.get("item_type") or "",
                "time": item.get("time") or item.get("start_time") or "",
                "title": item.get("title") or item.get("place_name") or item.get("note") or "",
                "tag": item.get("tag") or item.get("item_type") or "",
                "desc": item.get("desc") or item.get("note") or "",
                "route": item.get("route") or "",
                "cost": item.get("cost") if item.get("cost") is not None else item.get("total_cost", 0),
            })
        compact_days.append({
            "day": day_no,
            "title": day.get("title") or f"第 {day_no} 天",
            "walking": day.get("walking") or day.get("walking_distance_m") or "",
            "cost": day.get("cost") if day.get("cost") is not None else day.get("daily_cost", 0),
            "items": items,
        })
    return compact_days


def _clean_preview_changes(raw_changes: Any) -> list[dict[str, str]]:
    changes: list[dict[str, str]] = []
    seen_sources: set[str] = set()
    seen_pairs: set[tuple[str, str]] = set()
    if not isinstance(raw_changes, list):
        return changes
    for raw in raw_changes:
        if not isinstance(raw, dict):
            continue
        label = str(raw.get("label") or "调整建议").strip()
        from_text = str(raw.get("from") or "").strip()
        to_text = str(raw.get("to") or "").strip()
        why = str(raw.get("why") or raw.get("reason") or "").strip()
        if not from_text or not to_text:
            continue
        if from_text.replace(" ", "") == to_text.replace(" ", ""):
            continue
        source_key = _normalize_change_key(from_text)
        pair_key = (source_key, _normalize_change_key(to_text))
        if source_key in seen_sources or pair_key in seen_pairs:
            continue
        seen_sources.add(source_key)
        seen_pairs.add(pair_key)
        changes.append({
            "label": label[:18],
            "from": from_text[:42],
            "to": to_text[:52],
            "why": why[:90] or "根据你的输入和当前行程由智能体判断。",
        })
        if len(changes) >= 3:
            break
    return changes


def _normalize_change_key(value: str) -> str:
    text = "".join(str(value or "").split())
    for sep in ("(", "（", "->", "改为", "替换为"):
        if sep in text:
            text = text.split(sep, 1)[0]
    return text[:24]


def _make_alt_fetcher(session_id: str = "", itinerary_id: str = ""):
    """创建替代地点获取函数。

    优先从当前 session 缓存的推荐候选中筛选未被选中的，
    不再降级到 PlaceRepository 全量查询。
    调整只能使用系统已经推荐给用户的地点，避免 LLM 或数据库兜底生成演示中没有出现过的景点。
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

        return []
    return fetcher


def _post_process_modified_itinerary(itinerary: dict) -> dict:
    """对修改后的行程做后处理——与规划 Agent 使用相同的标准化逻辑。"""
    if not itinerary or not itinerary.get("days"):
        return itinerary
    _normalize_item_types(itinerary)
    _sync_replaced_places(itinerary)
    _places = _extract_places_from_itinerary(itinerary)
    if _places:
        _normalize_itinerary(itinerary, _places)
    return itinerary


@router.post("/adjustment-preview")
async def api_adjustment_preview(request: AdjustmentPreviewRequest) -> ApiResponse:
    """由 Chatbot 智能体生成修改建议预览。

    这个接口只分析用户想怎么改，不直接替换行程；前端点击“应用这些修改”
    后再调用 /modify 执行真正调整。
    """
    target_day = request.target_day
    compact_days = _compact_preview_itinerary(request.current_itinerary or {}, target_day)
    scope = f"第 {target_day} 天" if target_day else "当前行程"

    if not compact_days:
        return ApiResponse(data={
            "ready": False,
            "scope": scope,
            "summary": "当前没有可分析的行程数据，请先生成行程后再修改。",
            "changes": [],
        })

    fallback = {
        "ready": False,
        "scope": scope,
        "summary": "智能体暂未返回可应用的修改建议，请换一种说法或指定更明确的地点、时间段、预算或体力要求。",
        "changes": [],
    }

    chatbot = ChatbotService()
    if not chatbot.available:
        return ApiResponse(data={
            **fallback,
            "summary": f"智能体不可用，无法生成真实建议：{chatbot.error or '模型配置未就绪'}",
        })

    system_prompt = (
        "你是天津自由行系统的“行程智能调整 Agent”。"
        "你只负责根据用户修改请求和当前行程，产出最多 3 条可确认的修改建议。"
        "必须用当前行程里的真实地点作为 from；to 可以是更合理的新安排、压缩停留、调整交通或时间。"
        "不要把地点改成同一个地点；不要输出空泛建议；不要自动应用。"
        "如果用户说累、少走、近一点，应优先缩短半径、减少跨区、改交通或替换为同区域低强度点。"
        "如果用户说下雨/室内，应优先把露天安排换成室内场馆或商圈休整。"
        "如果用户说预算，应优先调整高消费餐饮、酒店或交通。"
        "只返回 JSON 对象，字段为 ready、scope、summary、changes。"
        "changes 每项字段为 label、from、to、why。"
        "只返回真正必要的修改，1 条、2 条或 3 条都可以，不要为了凑满 3 条生成重复建议。"
        "同一个原安排只能给 1 条最佳替代，不要连续输出多个替换同一地点的方案。"
    )
    user_payload = {
        "用户修改要求": request.original_text,
        "识别动作": request.action,
        "目标范围": scope,
        "当前行程": compact_days,
        "输出要求": "最多 3 条，可以只返回 1 或 2 条；不要为了凑满 3 条生成重复建议；同一个原安排只能给 1 条最佳替代；每条建议必须具体到原安排和新安排；不要 Markdown。",
    }
    result = chatbot.chat_json(
        system_prompt,
        json.dumps(user_payload, ensure_ascii=False),
        fallback,
    )
    changes = _clean_preview_changes(result.get("changes"))
    return ApiResponse(data={
        "ready": bool(changes),
        "scope": str(result.get("scope") or scope),
        "summary": str(result.get("summary") or (
            f"已由智能体生成 {len(changes)} 条建议，确认后再替换当前行程。"
            if changes else fallback["summary"]
        )),
        "changes": changes,
    })


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
            original_text=action,
            current_itinerary=None,
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

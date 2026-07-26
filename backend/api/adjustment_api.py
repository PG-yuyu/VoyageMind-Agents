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

router = APIRouter(prefix="/api/v1/itineraries", tags=["adjustment"])


@router.post("/modify")
async def api_modify(request: ModificationRequest) -> ApiResponse:
    """用户主动修改行程。

    Agent 会自动解析 LLM（优先 DeepSeekLLM，Mock 兜底）。
    """
    try:
        agent = AdjustmentAgent()
        result = agent.modify(request=request)
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
        agent = AdjustmentAgent()
        result = agent.modify(request=request)
        return ApiResponse(success=True, data=result)
    except Exception as exc:
        return ApiResponse(
            success=False,
            code="INTERNAL_ERROR",
            message=str(exc),
        )

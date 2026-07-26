"""
调整 API
========

- POST /api/v1/itineraries/auto-adjust     自动调整
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
    """用户主动修改行程。"""
    try:
        agent = AdjustmentAgent(llm_callable=_dummy_llm)
        result = agent.modify(request=request)
        return ApiResponse(success=True, data=result)
    except Exception as exc:
        return ApiResponse(
            success=False,
            code="INTERNAL_ERROR",
            message=str(exc),
        )


def _dummy_llm(prompt: str) -> str:
    """开发用占位 LLM 调用（后续替换为真实 LLM）。"""
    return '{"days": []}'

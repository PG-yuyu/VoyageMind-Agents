"""
行程 API
========

成员三负责的行程相关接口：
- POST /api/v1/itineraries/generate      生成初始行程
- GET  /api/v1/itineraries/{id}           获取行程
"""

from __future__ import annotations

from fastapi import APIRouter

from backend.schemas import ApiResponse
from backend.schemas.itinerary import GenerateRequest
from backend.services.itinerary_planner import generate_itinerary
from backend.services.version_service import get_itinerary

router = APIRouter(prefix="/api/v1/itineraries", tags=["itineraries"])


@router.post("/generate")
async def api_generate(request: GenerateRequest) -> ApiResponse:
    """生成初始行程。"""
    try:
        itinerary = generate_itinerary(
            requirements=request.requirements,
            hotel=request.hotel,
            attractions=request.attractions,
            restaurants=request.restaurants,
            route_mode_priority=request.route_mode_priority,
            max_candidates_per_day=request.max_candidates_per_day,
        )
        return ApiResponse(success=True, data=itinerary.model_dump())
    except Exception as exc:
        return ApiResponse(
            success=False,
            code="ITINERARY_GENERATION_FAILED",
            message=str(exc),
        )


@router.get("/{itinerary_id}")
async def api_get_itinerary(
    itinerary_id: str,
    version: int | None = None,
) -> ApiResponse:
    """获取指定行程（可指定版本）。"""
    try:
        itinerary = get_itinerary(itinerary_id, version)
        if itinerary is None:
            return ApiResponse(
                success=False,
                code="RESOURCE_NOT_FOUND",
                message=f"行程 {itinerary_id} 不存在",
            )
        return ApiResponse(success=True, data=itinerary.model_dump())
    except Exception as exc:
        return ApiResponse(
            success=False,
            code="INTERNAL_ERROR",
            message=str(exc),
        )


@router.post("/save-demo")
async def api_save_demo_itinerary(
    itinerary: dict,
) -> ApiResponse:
    """保存前端演示行程到后端版本存储（用于智能修改的前置条件）。

    前端生成的演示行程没有 itinerary_id, 先保存到后端，
    然后才能调用 /modify 进行修改。
    """
    try:
        from backend.schemas.itinerary import Itinerary
        from backend.services.version_service import save_version

        # 补全必填字段
        it = Itinerary(**itinerary)
        saved = save_version(it)
        return ApiResponse(
            success=True,
            data={
                "itinerary_id": saved.itinerary_id,
                "version": saved.version,
            },
        )
    except Exception as exc:
        return ApiResponse(
            success=False,
            code="SAVE_DEMO_FAILED",
            message=str(exc),
        )

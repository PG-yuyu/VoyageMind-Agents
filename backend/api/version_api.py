"""
版本 API
========

- GET  /api/v1/itineraries/{id}/versions          版本列表
- GET  /api/v1/itineraries/{id}/versions/{version} 指定版本
- GET  /api/v1/itineraries/{id}/diff               版本差异
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from backend.schemas import ApiResponse
from backend.services.version_service import (
    get_all_versions,
    get_itinerary,
    diff_versions,
)

router = APIRouter(prefix="/api/v1/itineraries", tags=["versions"])


@router.get("/{itinerary_id}/versions")
async def api_list_versions(itinerary_id: str) -> ApiResponse:
    """获取行程的所有版本列表。"""
    try:
        versions = get_all_versions(itinerary_id)
        return ApiResponse(success=True, data={"versions": versions})
    except Exception as exc:
        return ApiResponse(
            success=False,
            code="INTERNAL_ERROR",
            message=str(exc),
        )


@router.get("/{itinerary_id}/versions/{version}")
async def api_get_version(
    itinerary_id: str,
    version: int,
) -> ApiResponse:
    """获取指定版本行程。"""
    try:
        itinerary = get_itinerary(itinerary_id, version)
        if itinerary is None:
            return ApiResponse(
                success=False,
                code="RESOURCE_NOT_FOUND",
                message=f"版本 {version} 不存在",
            )
        return ApiResponse(success=True, data=itinerary.model_dump())
    except Exception as exc:
        return ApiResponse(
            success=False,
            code="INTERNAL_ERROR",
            message=str(exc),
        )


@router.get("/{itinerary_id}/diff")
async def api_diff_versions(
    itinerary_id: str,
    from_version: int = Query(1, ge=1),
    to_version: int = Query(2, ge=1),
) -> ApiResponse:
    """获取两个版本之间的差异。"""
    try:
        diff = diff_versions(itinerary_id, from_version, to_version)
        if diff is None:
            return ApiResponse(
                success=False,
                code="RESOURCE_NOT_FOUND",
                message="版本不存在",
            )
        return ApiResponse(success=True, data=diff.model_dump())
    except Exception as exc:
        return ApiResponse(
            success=False,
            code="INTERNAL_ERROR",
            message=str(exc),
        )

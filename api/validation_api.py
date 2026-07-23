"""
校验 API
========

- POST /api/v1/itineraries/calculate-budget  预算核算
- POST /api/v1/itineraries/validate          校验行程
"""

from __future__ import annotations

from fastapi import APIRouter

from schemas.budget import CalculateBudgetRequest
from schemas.evaluation import ValidateRequest
from schemas.common import ApiResponse
from services.budget_service import calculate_budget
from validators.hard_constraint_validator import (
    enrich_items_with_places,
    validate_hard_constraints,
)

router = APIRouter(prefix="/api/v1/itineraries", tags=["validation"])


@router.post("/calculate-budget")
async def api_calculate_budget(request: CalculateBudgetRequest) -> ApiResponse:
    """预算核算。"""
    try:
        budget = calculate_budget(request.itinerary, request.requirements)
        return ApiResponse(success=True, data=budget.model_dump())
    except Exception as exc:
        return ApiResponse(
            success=False,
            code="INTERNAL_ERROR",
            message=str(exc),
        )


@router.post("/validate")
async def api_validate(request: ValidateRequest) -> ApiResponse:
    """校验行程（硬约束检查）。"""
    try:
        it = request.itinerary
        if request.places:
            enrich_items_with_places(it, request.places)
        evaluation = validate_hard_constraints(it, request.requirements)
        return ApiResponse(success=True, data=evaluation.model_dump())
    except Exception as exc:
        return ApiResponse(
            success=False,
            code="ITINERARY_VALIDATION_FAILED",
            message=str(exc),
        )

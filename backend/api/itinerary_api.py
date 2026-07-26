"""
行程 API
========

成员三负责的行程相关接口：
- POST /api/v1/itineraries/generate      生成初始行程
- POST /api/v1/itineraries/attach-routes  补充路线到行程
- GET  /api/v1/itineraries/{id}           获取行程
- POST /api/v1/itineraries/evaluate       统一评价（硬约束 + 软偏好 + 综合评分）
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter

from backend.schemas import ApiResponse
from backend.schemas.itinerary import GenerateRequest
from backend.services.itinerary_planner import generate_itinerary
from backend.services.version_service import get_itinerary

logger = logging.getLogger(__name__)

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


@router.post("/evaluate")
async def api_evaluate(request: dict[str, Any]) -> ApiResponse:
    """统一评价接口 —— 执行硬约束 + 软偏好双轨评价。

    调用 EvaluationAgent，对行程进行完整评价：
    - 轨 1: HardConstraintValidator（Python 规则校验）
    - 轨 2: ItineraryPreferenceCritic（LLM 软偏好评价）
    - 综合评分（5 项客观量化指标）
    - 重规划指导指令（LLM 生成）

    Request body:
        itinerary: Itinerary 字典
        requirements: TravelRequest 字典
        places: (可选) 候选地点列表
        routes: (可选) 路线列表
        semantic_preferences: (可选) 隐含偏好列表
        generate_replan_directives: (可选) 是否生成重规划指令，默认 true
    """
    try:
        from backend.agents.evaluation_agent import EvaluationAgent
        from backend.clients.deepseek_llm import DeepSeekLLM

        llm = DeepSeekLLM()
        agent = EvaluationAgent(llm_callable=llm)

        result = agent.evaluate(
            itinerary=request.get("itinerary", {}),
            requirements=request.get("requirements", {}),
            places=request.get("places"),
            routes=request.get("routes"),
            semantic_preferences=request.get("semantic_preferences"),
            generate_replan_directives=request.get(
                "generate_replan_directives", True
            ),
        )

        return ApiResponse(
            success=True,
            data=result.model_dump(),
        )
    except (ImportError, ValueError) as exc:
        logger.warning("EvaluationAgent 或 DeepSeekLLM 不可用: %s", exc)
        # 降级：仅执行不需要 LLM 的硬约束校验
        return _fallback_evaluate(request)
    except Exception as exc:
        logger.exception("评价失败: %s", exc)
        # 也尝试降级
        try:
            return _fallback_evaluate(request)
        except Exception:
            return ApiResponse(
                success=False,
                code="EVALUATION_FAILED",
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


def _fallback_evaluate(request: dict[str, Any]) -> ApiResponse:
    """LLM 不可用时的降级评价：仅执行硬约束校验。"""
    from backend.validators.hard_constraint_validator import (
        enrich_items_with_places,
        validate_hard_constraints,
    )

    it = request.get("itinerary", {})
    places = request.get("places", [])
    if places:
        enrich_items_with_places(it, places)
    hard_result = validate_hard_constraints(
        it, request.get("requirements", {})
    )
    return ApiResponse(
        success=True,
        data={
            "passed": hard_result.passed,
            "soft_preference_passed": True,
            "overall_score": 0.5,
            "hard_issues": [
                i.model_dump() for i in hard_result.issues
            ],
            "soft_issues": [],
            "metrics": hard_result.metrics.model_dump(),
            "time_reasonableness_score": 0.5,
            "replan_directives": [],
            "note": "LLM 不可用，仅返回硬约束校验结果",
        },
    )

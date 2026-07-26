"""
校验模型 —— 成员三负责
============================

两类校验:
- HardConstraintEvaluation: Python 规则检查客观事实和明确硬约束
- SoftPreferenceEvaluation: LLM 判断隐含偏好满足度（见 preference_evaluation.py）
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from .common import Severity


class ValidationCode(str, Enum):
    """校验问题码 —— 确定性规则检查产出。"""

    PLACE_CLOSED = "PLACE_CLOSED"
    ARRIVAL_OUTSIDE_OPENING_HOURS = "ARRIVAL_OUTSIDE_OPENING_HOURS"
    TIME_CONFLICT = "TIME_CONFLICT"
    ROUTE_TIME_INSUFFICIENT = "ROUTE_TIME_INSUFFICIENT"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    MUST_VISIT_MISSING = "MUST_VISIT_MISSING"
    DUPLICATE_PLACE = "DUPLICATE_PLACE"
    WALKING_LIMIT_EXCEEDED = "WALKING_LIMIT_EXCEEDED"
    RESTAURANT_CLOSED = "RESTAURANT_CLOSED"
    FOOD_AVOIDANCE_CONFLICT = "FOOD_AVOIDANCE_CONFLICT"
    DAILY_END_TIME_EXCEEDED = "DAILY_END_TIME_EXCEEDED"
    INVALID_COORDINATE = "INVALID_COORDINATE"
    UNVERIFIED_ROUTE = "UNVERIFIED_ROUTE"


# ── 校验问题 ──────────────────────────────────────────────────────


class ValidationIssue(BaseModel):
    """单条校验问题。"""

    code: ValidationCode = Field(..., description="问题码")
    severity: Severity = Field(..., description="严重程度")
    day: int | None = Field(None, description="发生在第几天")
    item_id: str | None = Field(None, description="具体行程项 ID")
    message: str = Field(..., description="人类可读描述")
    suggestion: str | None = Field(None, description="修正建议")


# ── 量化指标 ──────────────────────────────────────────────────────


class EvaluationMetrics(BaseModel):
    """由 Python 规则计算的量化指标。"""

    budget_match_rate: float = Field(1.0, ge=0.0, le=1.0)
    interest_coverage_rate: float = Field(1.0, ge=0.0, le=1.0)
    must_visit_coverage_rate: float = Field(1.0, ge=0.0, le=1.0)
    time_valid: bool = True
    walking_limit_valid: bool = True


# ── 硬约束校验结果 ───────────────────────────────────────────────


class HardConstraintEvaluation(BaseModel):
    """确定性规则校验结果 —— Python 代码完成，不依赖大模型。"""

    passed: bool = Field(..., description="无 error 级问题即 true")
    issues: list[ValidationIssue] = Field(default_factory=list)
    metrics: EvaluationMetrics = Field(default_factory=EvaluationMetrics)


# ── API 请求 ──────────────────────────────────────────────────────


class ValidateRequest(BaseModel):
    """校验行程请求。"""

    itinerary: dict[str, Any] = Field(..., description="Itinerary 字典")
    requirements: dict[str, Any] = Field(..., description="TravelRequest 字典")
    places: list[dict[str, Any]] = Field(default_factory=list)
    routes: list[dict[str, Any]] = Field(default_factory=list)

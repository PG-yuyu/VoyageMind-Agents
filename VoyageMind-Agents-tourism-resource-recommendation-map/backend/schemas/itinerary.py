"""
行程核心模型 —— 成员三负责
============================

ItineraryItem  → 行程单项
ItineraryDay   → 单日行程
Itinerary      → 完整行程（含版本链）
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ── 枚举 ───────────────────────────────────────────────────────────


class ItemType(str, Enum):
    DEPARTURE = "departure"
    TRANSPORT = "transport"
    ATTRACTION = "attraction"
    LUNCH = "lunch"
    DINNER = "dinner"
    HOTEL = "hotel"
    REST = "rest"
    RETURN = "return"


class ItineraryStatus(str, Enum):
    DRAFT = "draft"
    ROUTING = "routing"
    VALIDATING = "validating"
    ADJUSTING = "adjusting"
    PASSED = "passed"
    FAILED = "failed"


# ── 5.12 行程项目 ─────────────────────────────────────────────────


class ItineraryItem(BaseModel):
    """行程中的单个项目（景点/餐饮/酒店/交通/休息）。"""

    item_id: str = Field(..., description="全局唯一 ID，如 day1_item_001")
    day: int = Field(..., ge=1)
    item_type: ItemType
    place_id: str | None = Field(None, description="关联地点 place_id")
    start_time: str = Field(..., pattern=r"^\d{2}:\d{2}$")
    end_time: str = Field(..., pattern=r"^\d{2}:\d{2}$")
    duration_minutes: int = Field(..., ge=0)
    route_from_previous_id: str | None = None
    cost_per_person: float = Field(0.0, ge=0, description="人均费用（元）")
    total_cost: float = Field(0.0, ge=0, description="该项总费用（元）")
    locked: bool = Field(False, description="锁定后局部重规划不会改动该项")
    note: str | None = None


# ── 5.13 每日行程 ─────────────────────────────────────────────────


class ItineraryDay(BaseModel):
    """单日行程。"""

    day: int = Field(..., ge=1)
    date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    items: list[ItineraryItem] = Field(default_factory=list)
    daily_cost: float = Field(0.0, ge=0, description="当日总费用（元）")
    walking_distance_m: int = Field(0, ge=0, description="当日步行距离（米）")
    start_time: str = Field(..., pattern=r"^\d{2}:\d{2}$")
    end_time: str = Field(..., pattern=r"^\d{2}:\d{2}$")


# ── 5.14 完整行程 ─────────────────────────────────────────────────


class Itinerary(BaseModel):
    """完整行程方案。"""

    itinerary_id: str = Field(..., description="行程 ID，全局唯一")
    session_id: str = Field(..., description="所属会话 ID")
    version: int = Field(..., ge=1, description="版本号，从 1 开始递增")
    parent_version: int | None = Field(None, description="父版本号")
    requirements_snapshot: dict[str, Any] = Field(default_factory=dict)
    days: list[ItineraryDay] = Field(default_factory=list)
    hotel_place_id: str | None = None
    total_cost: float = Field(0.0, ge=0, description="行程总费用（元）")
    status: ItineraryStatus = Field(ItineraryStatus.DRAFT)
    created_at: datetime = Field(default_factory=datetime.now)


# ── API 请求模型 ──────────────────────────────────────────────────


class GenerateRequest(BaseModel):
    """生成初始行程请求（成员一 workflow → 成员三）。"""

    requirements: dict[str, Any] = Field(..., description="TravelRequest 字典")
    hotel: dict[str, Any] | None = None
    attractions: list[dict[str, Any]] = Field(default_factory=list)
    restaurants: list[dict[str, Any]] = Field(default_factory=list)
    route_mode_priority: list[str] = Field(default_factory=lambda: ["walking", "transit"])
    max_candidates_per_day: int = Field(5, ge=1, le=10)


class AttachRoutesRequest(BaseModel):
    """将批量路线结果挂载到行程 items。"""

    routes: list[dict[str, Any]] = Field(default_factory=list)

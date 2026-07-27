"""
成员一原始模型（向后兼容）
========================

从原 backend/schemas.py 迁入，仅将 ApiResponse/now_iso/new_id 改为从 _base 导入。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.schemas._base import ApiResponse, new_id, now_iso

# ── 类型别名 ────────────────────────────────────────────────────

IntentType = Literal["create_trip", "modify_trip", "travel_qa"]
SessionStatus = Literal[
    "active", "waiting_for_user", "planning", "completed", "failed", "closed"
]

# ── 请求/响应模型 ────────────────────────────────────────────────


class CreateSessionRequest(BaseModel):
    user_id: str = "demo_user"


class AuthLoginRequest(BaseModel):
    username: str
    password: str


class AuthRegisterRequest(BaseModel):
    username: str
    password: str
    nickname: str | None = None


class AuthUser(BaseModel):
    user_id: str
    username: str
    nickname: str
    token: str


class Session(BaseModel):
    session_id: str
    user_id: str
    status: SessionStatus = "active"
    current_itinerary_id: str | None = None
    current_version: int = 0
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class ChatMessage(BaseModel):
    message_id: str
    session_id: str
    role: Literal["user", "assistant", "system", "tool"]
    content: str
    created_at: str = Field(default_factory=now_iso)


class IntentResult(BaseModel):
    intent: IntentType
    confidence: float
    sub_intent: str | None = None
    original_text: str


class TravelRequest(BaseModel):
    session_id: str
    city: str | None = None
    start_date: str | None = None
    days: int | None = None
    people: int = 2
    total_budget: int | None = None
    hotel_budget_per_night: int | None = None
    meal_budget_per_person: int | None = None
    interests: list[str] = Field(default_factory=list)
    must_visit: list[str] = Field(default_factory=list)
    avoid_places: list[str] = Field(default_factory=list)
    preferred_areas: list[str] = Field(default_factory=list)
    avoid_areas: list[str] = Field(default_factory=list)
    food_preferences: list[str] = Field(default_factory=list)
    food_avoidances: list[str] = Field(default_factory=list)
    transport_modes: list[str] = Field(default_factory=lambda: ["walking", "transit"])
    walking_limit_m: int = 8000
    daily_start_time: str = "09:00"
    daily_end_time: str = "18:00"
    travel_pace: Literal["relaxed", "normal", "compact"] = "normal"
    hotel_place_id: str | None = None
    start_place_id: str | None = None
    use_current_location: bool = False


class Assumption(BaseModel):
    field: str
    value: Any
    reason: str


class RequirementExtractionResult(BaseModel):
    requirements: TravelRequest
    missing_fields: list[str] = Field(default_factory=list)
    assumptions: list[Assumption] = Field(default_factory=list)
    need_follow_up: bool = False
    follow_up_question: str | None = None


class ChatRequest(BaseModel):
    session_id: str
    message: str


class ChatResponse(BaseModel):
    message_id: str
    intent: IntentResult
    reply: str
    workflow_status: str
    requirements: TravelRequest | None = None
    itinerary: dict | None = None
    recommendation_result: dict | None = None
    map_resources: dict | None = None
    routes: list[dict] | None = None
    agent_trace: dict | None = None


class IntentDetectRequest(BaseModel):
    session_id: str
    message: str


class RequirementExtractRequest(BaseModel):
    session_id: str
    message: str
    existing_requirements: TravelRequest | None = None


class WorkflowRequest(BaseModel):
    session_id: str
    requirements: TravelRequest


class AgentStep(BaseModel):
    step: int
    agent: str
    action: str
    summary: str
    status: Literal["success", "running", "failed", "skipped"] = "success"
    duration_ms: int = 0


class AgentTrace(BaseModel):
    trace_id: str
    session_id: str
    steps: list[AgentStep] = Field(default_factory=list)

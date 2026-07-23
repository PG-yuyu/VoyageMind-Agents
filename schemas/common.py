"""
公共基础模型 —— 全员共用，统一响应格式、分页、枚举。

规范（来自接口文档）：
- 时间 HH:MM / 日期 YYYY-MM-DD / 完整时间 ISO 8601
- 距离: 米 / 时长: 分钟 / 金额: 元
- 坐标: GCJ-02, [经度, 纬度]
- 缺失值: null
- 枚举: 英文小写下划线
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# 统一响应封装
# ---------------------------------------------------------------------------

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """所有接口统一使用此格式返回。"""

    success: bool
    code: str = "OK"
    message: str = "操作成功"
    data: T | None = None
    trace_id: str | None = None
    timestamp: datetime | None = None


class PaginatedResponse(BaseModel, Generic[T]):
    """分页响应。"""

    items: list[T] = Field(default_factory=list)
    page: int = 1
    page_size: int = 20
    total: int = 0
    has_more: bool = False


# ---------------------------------------------------------------------------
# 通用枚举
# ---------------------------------------------------------------------------

class SessionStatus(str):
    ACTIVE = "active"
    WAITING_FOR_USER = "waiting_for_user"
    PLANNING = "planning"
    COMPLETED = "completed"
    FAILED = "failed"
    CLOSED = "closed"


class MessageRole(str):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class Intent(str):
    CREATE_TRIP = "create_trip"
    MODIFY_TRIP = "modify_trip"
    TRAVEL_QA = "travel_qa"


class ModifySubIntent(str):
    REPLACE_ATTRACTION = "replace_attraction"
    DELETE_PLACE = "delete_place"
    REPLACE_RESTAURANT = "replace_restaurant"
    CHANGE_HOTEL = "change_hotel"
    CHANGE_BUDGET = "change_budget"
    CHANGE_TIME = "change_time"
    REDUCE_WALKING = "reduce_walking"
    CHANGE_TO_INDOOR = "change_to_indoor"


class PlaceType(str):
    ATTRACTION = "attraction"
    HOTEL = "hotel"
    RESTAURANT = "restaurant"
    CUSTOM_LOCATION = "custom_location"


class PriceType(str):
    FREE = "free"
    PER_PERSON = "per_person"
    PER_NIGHT = "per_night"
    AVERAGE_PER_PERSON = "average_per_person"
    TOTAL = "total"


class WalkingIntensity(str):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class DataSource(str):
    LOCAL_DATABASE = "local_database"
    AMAP = "amap"
    USER_INPUT = "user_input"
    ESTIMATED = "estimated"


class TransportMode(str):
    WALKING = "walking"
    DRIVING = "driving"
    TRANSIT = "transit"
    STRAIGHT_LINE = "straight_line"


class TravelPace(str):
    RELAXED = "relaxed"
    NORMAL = "normal"
    COMPACT = "compact"


class MealType(str):
    BREAKFAST = "breakfast"
    LUNCH = "lunch"
    DINNER = "dinner"


class WorkflowStatus(str):
    CREATED = "created"
    EXTRACTING_REQUIREMENTS = "extracting_requirements"
    WAITING_FOR_USER = "waiting_for_user"
    RECOMMENDING = "recommending"
    ROUTING = "routing"
    PLANNING = "planning"
    VALIDATING = "validating"
    ADJUSTING = "adjusting"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Severity(str):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"

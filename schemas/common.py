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

from __future__ import annotations

from datetime import datetime
from enum import Enum
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

class SessionStatus(str, Enum):
    ACTIVE = "active"
    WAITING_FOR_USER = "waiting_for_user"
    PLANNING = "planning"
    COMPLETED = "completed"
    FAILED = "failed"
    CLOSED = "closed"


class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class Intent(str, Enum):
    CREATE_TRIP = "create_trip"
    MODIFY_TRIP = "modify_trip"
    TRAVEL_QA = "travel_qa"


class ModifySubIntent(str, Enum):
    REPLACE_ATTRACTION = "replace_attraction"
    DELETE_PLACE = "delete_place"
    REPLACE_RESTAURANT = "replace_restaurant"
    CHANGE_HOTEL = "change_hotel"
    CHANGE_BUDGET = "change_budget"
    CHANGE_TIME = "change_time"
    REDUCE_WALKING = "reduce_walking"
    CHANGE_TO_INDOOR = "change_to_indoor"


class PlaceType(str, Enum):
    ATTRACTION = "attraction"
    HOTEL = "hotel"
    RESTAURANT = "restaurant"
    CUSTOM_LOCATION = "custom_location"


class PriceType(str, Enum):
    FREE = "free"
    PER_PERSON = "per_person"
    PER_NIGHT = "per_night"
    AVERAGE_PER_PERSON = "average_per_person"
    TOTAL = "total"


class WalkingIntensity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class DataSource(str, Enum):
    LOCAL_DATABASE = "local_database"
    AMAP = "amap"
    USER_INPUT = "user_input"
    ESTIMATED = "estimated"


class TransportMode(str, Enum):
    WALKING = "walking"
    DRIVING = "driving"
    TRANSIT = "transit"
    STRAIGHT_LINE = "straight_line"


class TravelPace(str, Enum):
    RELAXED = "relaxed"
    NORMAL = "normal"
    COMPACT = "compact"


class MealType(str, Enum):
    BREAKFAST = "breakfast"
    LUNCH = "lunch"
    DINNER = "dinner"


class WorkflowStatus(str, Enum):
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


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


# ---------------------------------------------------------------------------
# v2 新增: 硬约束与隐含偏好模型（成员一 → 成员三）
# ---------------------------------------------------------------------------


class ConstraintOperator(str, Enum):
    """硬约束比较运算符。"""

    LESS_THAN = "less_than"
    LESS_THAN_OR_EQUAL = "less_than_or_equal"
    GREATER_THAN = "greater_than"
    GREATER_THAN_OR_EQUAL = "greater_than_or_equal"
    EQUAL = "equal"
    NOT_EQUAL = "not_equal"
    IN = "in"
    NOT_IN = "not_in"


class ExplicitConstraint(BaseModel):
    """明确硬约束 —— 用户明确提出的、可由程序精确校验的条件。

    成员一负责提取，成员二负责资源层校验，成员三负责行程层校验。
    """

    field: str = Field(..., description="约束字段, 如 hotel_price / walking_distance_m")
    operator: ConstraintOperator = Field(..., description="比较运算符")
    value: Any = Field(..., description="约束值")
    scope: str = Field(default="overall", description="作用域: overall / hotel / attraction / restaurant")
    source_text: str = Field(default="", description="用户原话, 如 '酒店每晚不能超过500元'")


class SemanticPreference(BaseModel):
    """隐含偏好 —— 用户未给出精确数值、需要大模型理解的偏好。

    成员一负责保留原文，成员二和成员三各自用 LLM 解释。
    禁止用固定规则（如 if student: budget=300）解释隐含偏好。
    """

    text: str = Field(..., description="偏好原文, 如 '预算不要太高'")
    scope: str = Field(default="overall", description="作用域: overall / hotel / attraction / restaurant")
    source_text: str = Field(default="", description="用户原话")
    emphasis: str = Field(default="normal", description="强调程度: low / normal / high")

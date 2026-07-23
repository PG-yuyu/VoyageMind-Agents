"""
成员三 · 行程与预算数据模型
============================

负责: 行程规划、预算校验、规则检查、自动调整、局部重规划、版本对比

本文件定义:
- ItineraryItem     行程中的单项
- ItineraryDay      单日行程
- Itinerary         完整行程
- BudgetSummary     预算明细
- ValidationIssue   单条校验问题
- EvaluationMetrics 校验指标
- EvaluationResult  校验结果
- ModificationRequest 用户修改请求
- TripChange        单条变更
- TripDiff          版本差异

以及各 API 端点的请求/响应辅助模型。

规范约束（必须遵守）:
- 时间 HH:MM 字符串 / 时长 int 分钟 / 距离 int 米 / 金额 float 元
- 缺失值用 None，禁止 "" / "未知" / -1 等占位
- place_id 作为地点唯一标识，禁止用地名做主键
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ============================================================================
# 枚举
# ============================================================================


class ItemType(str, Enum):
    """行程项类型。"""

    DEPARTURE = "departure"
    TRANSPORT = "transport"
    ATTRACTION = "attraction"
    LUNCH = "lunch"
    DINNER = "dinner"
    HOTEL = "hotel"
    REST = "rest"
    RETURN = "return"


class ItineraryStatus(str, Enum):
    """行程整体状态。"""

    DRAFT = "draft"
    ROUTING = "routing"
    VALIDATING = "validating"
    ADJUSTING = "adjusting"
    PASSED = "passed"
    FAILED = "failed"


class Severity(str, Enum):
    """校验问题严重程度。"""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class ValidationCode(str, Enum):
    """校验问题码 —— 确定性规则检查的产出。"""

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


class ChangeType(str, Enum):
    """TripDiff 中的变更类型。"""

    REPLACE = "replace"
    DELETE = "delete"
    ADD = "add"
    REORDER = "reorder"


# ============================================================================
# 5.12  行程项目
# ============================================================================


class ItineraryItem(BaseModel):
    """行程中的单个项目（景点/餐饮/酒店/交通等）。"""

    item_id: str = Field(..., description="全局唯一 item ID，如 day1_item_001")
    day: int = Field(..., ge=1, description="所属第几天")
    item_type: ItemType = Field(..., description="项目类型")
    place_id: str | None = Field(None, description="关联地点 place_id，纯交通/休息可为空")
    start_time: str = Field(..., pattern=r"^\d{2}:\d{2}$", description="开始时间 HH:MM")
    end_time: str = Field(..., pattern=r"^\d{2}:\d{2}$", description="结束时间 HH:MM")
    duration_minutes: int = Field(..., ge=0, description="持续时长（分钟）")
    route_from_previous_id: str | None = Field(None, description="从前一项到本项的路线 ID")
    cost_per_person: float = Field(0.0, ge=0, description="人均费用（元）")
    total_cost: float = Field(0.0, ge=0, description="该项总费用（元）")
    locked: bool = Field(False, description="是否锁定，锁定后局部重规划不会改动该项")
    note: str | None = Field(None, description="备注提示")


# ============================================================================
# 5.13  每日行程
# ============================================================================


class ItineraryDay(BaseModel):
    """单日行程。"""

    day: int = Field(..., ge=1, description="第几天，从 1 开始")
    date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$", description="日期 YYYY-MM-DD")
    items: list[ItineraryItem] = Field(default_factory=list, description="当日行程项目列表")
    daily_cost: float = Field(0.0, ge=0, description="当日总费用（元）")
    walking_distance_m: int = Field(0, ge=0, description="当日步行距离（米）")
    start_time: str = Field(..., pattern=r"^\d{2}:\d{2}$", description="当日出发时间 HH:MM")
    end_time: str = Field(..., pattern=r"^\d{2}:\d{2}$", description="当日结束时间 HH:MM")


# ============================================================================
# 5.14  完整行程
# ============================================================================


class Itinerary(BaseModel):
    """完整行程方案。"""

    itinerary_id: str = Field(..., description="行程 ID，全局唯一")
    session_id: str = Field(..., description="所属会话 ID")
    version: int = Field(..., ge=1, description="版本号，从 1 开始递增")
    parent_version: int | None = Field(None, description="父版本号，首版为 null")
    requirements_snapshot: dict[str, Any] = Field(
        default_factory=dict, description="生成时的用户需求快照"
    )
    days: list[ItineraryDay] = Field(default_factory=list, description="每日行程")
    hotel_place_id: str | None = Field(None, description="入住酒店 place_id")
    total_cost: float = Field(0.0, ge=0, description="行程总费用（元）")
    status: ItineraryStatus = Field(ItineraryStatus.DRAFT, description="行程状态")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")


# ============================================================================
# 5.15  预算明细
# ============================================================================


class BudgetSummary(BaseModel):
    """费用明细 —— 由 Python 按规则计算，不由大模型生成。"""

    hotel_cost: float = Field(0.0, ge=0, description="酒店总费用 = 单价 × 晚数")
    ticket_cost: float = Field(0.0, ge=0, description="门票总费用 = 单价 × 人数")
    meal_cost: float = Field(0.0, ge=0, description="餐饮总费用 = 人均 × 人数")
    transport_cost: float = Field(0.0, ge=0, description="交通总费用")
    other_cost: float = Field(0.0, ge=0, description="其他费用")
    total_cost: float = Field(0.0, ge=0, description="合计")
    total_budget: float = Field(0.0, ge=0, description="用户总预算")
    remaining_budget: float = Field(0.0, description="剩余预算（可为负）")
    over_budget: bool = Field(False, description="是否超预算")


# ============================================================================
# 5.16  校验问题
# ============================================================================


class ValidationIssue(BaseModel):
    """单条校验问题。"""

    code: ValidationCode = Field(..., description="问题码")
    severity: Severity = Field(..., description="严重程度")
    day: int | None = Field(None, description="发生在第几天（全局问题为空）")
    item_id: str | None = Field(None, description="具体行程项 ID（全局问题为空）")
    message: str = Field(..., description="人类可读的问题描述")
    suggestion: str | None = Field(None, description="修正建议")


# ============================================================================
# 5.17  校验指标 & 校验结果
# ============================================================================


class EvaluationMetrics(BaseModel):
    """校验指标 —— 所有字段由 Python 规则计算。"""

    budget_match_rate: float = Field(
        1.0, ge=0.0, le=1.0, description="预算匹配率"
    )
    interest_coverage_rate: float = Field(
        1.0, ge=0.0, le=1.0, description="兴趣覆盖度"
    )
    must_visit_coverage_rate: float = Field(
        1.0, ge=0.0, le=1.0, description="必去景点覆盖度"
    )
    time_valid: bool = Field(True, description="时间是否有效")
    walking_limit_valid: bool = Field(True, description="步行限制是否满足")


class EvaluationResult(BaseModel):
    """确定性规则校验结果 —— 由 Python 完成，不依赖大模型评分。"""

    passed: bool = Field(..., description="全部 error 级问题通过即 true")
    issues: list[ValidationIssue] = Field(default_factory=list, description="问题列表")
    metrics: EvaluationMetrics = Field(default_factory=EvaluationMetrics, description="量化指标")


# ============================================================================
# 5.18  修改请求（成员一 → 成员三）
# ============================================================================


class ModificationRequest(BaseModel):
    """用户主动修改行程的请求。成员一解析意图后构造，交给成员三执行。"""

    session_id: str = Field(..., description="会话 ID")
    itinerary_id: str = Field(..., description="目标行程 ID")
    base_version: int = Field(..., ge=1, description="基于哪个版本修改")
    target_day: int | None = Field(None, ge=1, description="目标第几天")
    target_item_id: str | None = Field(None, description="目标行程项 ID")
    action: str = Field(..., description="修改动作, 如 change_to_indoor / replace_attraction")
    new_constraints: dict[str, Any] = Field(
        default_factory=dict, description="新约束, 如 {indoor: true, max_extra_cost: 0}"
    )
    original_text: str | None = Field(None, description="用户原始输入文本")


# ============================================================================
# 5.19  单条变更 & 版本差异
# ============================================================================


class TripChange(BaseModel):
    """单条变更记录。"""

    change_type: ChangeType = Field(..., description="变更类型")
    before_item_id: str | None = Field(None, description="修改前的 item_id")
    after_item_id: str | None = Field(None, description="修改后的 item_id")
    before_place_id: str | None = Field(None, description="修改前的地点")
    after_place_id: str | None = Field(None, description="修改后的地点")
    reason: str | None = Field(None, description="变更原因")
    cost_change: float = Field(0.0, description="费用变动（元），负=省钱")
    distance_change_m: int = Field(0, description="距离变动（米），负=缩短")


class TripDiff(BaseModel):
    """版本间差异对比，供修改前后展示。"""

    from_version: int = Field(..., ge=1, description="旧版本号")
    to_version: int = Field(..., ge=1, description="新版本号")
    affected_days: list[int] = Field(default_factory=list, description="受影响的日期")
    changes: list[TripChange] = Field(default_factory=list, description="变更明细")
    unchanged_item_ids: list[str] = Field(
        default_factory=list, description="未变动的 item_id 列表"
    )


# ============================================================================
# API 请求 / 响应辅助模型
# ============================================================================

# -- 9.1 POST /itineraries/generate -----------------------------------------


class GenerateRequest(BaseModel):
    """生成初始行程请求。由成员一的 workflow 调用，传入成员二的推荐结果。"""

    requirements: dict[str, Any] = Field(..., description="TravelRequest 字典")
    hotel: dict[str, Any] | None = Field(None, description="酒店 Place 字典")
    attractions: list[dict[str, Any]] = Field(default_factory=list, description="景点 Place 列表")
    restaurants: list[dict[str, Any]] = Field(default_factory=list, description="餐厅 Place 列表")
    route_mode_priority: list[str] = Field(
        default_factory=lambda: ["walking", "transit"], description="交通方式优先级"
    )
    max_candidates_per_day: int = Field(5, ge=1, le=10, description="每天最多安排几个地点")


# -- 9.2 POST /itineraries/{id}/attach-routes -------------------------------


class AttachRoutesRequest(BaseModel):
    """将批量路线结果挂载到行程 items 上。"""

    routes: list[dict[str, Any]] = Field(default_factory=list, description="RouteResult 列表")


# -- 9.3 POST /itineraries/calculate-budget ---------------------------------


class CalculateBudgetRequest(BaseModel):
    """预算核算请求。"""

    itinerary: dict[str, Any] = Field(..., description="Itinerary 字典")
    requirements: dict[str, Any] = Field(..., description="TravelRequest 字典")


# -- 9.4 POST /itineraries/validate -----------------------------------------


class ValidateRequest(BaseModel):
    """校验行程请求。"""

    itinerary: dict[str, Any] = Field(..., description="Itinerary 字典")
    requirements: dict[str, Any] = Field(..., description="TravelRequest 字典")
    places: list[dict[str, Any]] = Field(default_factory=list, description="Place 列表（含开放时间等）")
    routes: list[dict[str, Any]] = Field(default_factory=list, description="RouteResult 列表")


# -- 9.5 POST /itineraries/auto-adjust --------------------------------------


class AutoAdjustRequest(BaseModel):
    """自动调整请求。"""

    itinerary: dict[str, Any] = Field(..., description="Itinerary 字典")
    requirements: dict[str, Any] = Field(..., description="TravelRequest 字典")
    evaluation: dict[str, Any] = Field(..., description="EvaluationResult 字典")
    max_adjustments: int = Field(1, ge=1, le=3, description="最大调整次数，默认 1")


class AutoAdjustResponse(BaseModel):
    """自动调整响应。"""

    adjusted: bool = Field(..., description="是否执行了调整")
    adjustment_count: int = Field(0, ge=0, description="实际调整次数")
    itinerary: Itinerary | None = Field(None, description="调整后的行程")
    evaluation: EvaluationResult | None = Field(None, description="调整后的校验结果")
    diff: TripDiff | None = Field(None, description="调整前后差异")


# -- 9.6 POST /itineraries/modify -------------------------------------------


class ModifyResponse(BaseModel):
    """用户主动修改的响应。"""

    itinerary: Itinerary = Field(..., description="修改后的新版本行程")
    evaluation: EvaluationResult = Field(..., description="新版本的校验结果")
    diff: TripDiff = Field(..., description="修改前后差异")


# -- 9.7 POST /itineraries/local-replan -------------------------------------


class LocalReplanRequest(BaseModel):
    """局部重规划请求。只允许修改受影响日期/时段，其余必须锁定。"""

    itinerary: dict[str, Any] = Field(..., description="当前 Itinerary 字典")
    target_day: int = Field(..., ge=1, description="需要重规划的目标日期")
    target_item_ids: list[str] = Field(default_factory=list, description="待替换的 item_id 列表")
    locked_item_ids: list[str] = Field(
        default_factory=list, description="必须锁定的 item_id 列表（未受影响的行程项）"
    )
    new_constraints: dict[str, Any] = Field(
        default_factory=dict, description="新约束，如 {indoor: true}"
    )
    replacement_places: list[dict[str, Any]] = Field(
        default_factory=list, description="成员二提供的替代 Place 列表"
    )
    replacement_routes: list[dict[str, Any]] = Field(
        default_factory=list, description="成员二提供的替代 RouteResult 列表"
    )


# ============================================================================
# 聚合视图（供前端使用，见接口文档第 10 节）
# ============================================================================


class TripViewResponse(BaseModel):
    """GET /api/v1/trips/{id}/view —— 行程页面全量聚合数据。"""

    requirements: dict[str, Any] | None = None
    itinerary: Itinerary | None = None
    places: list[dict[str, Any]] = Field(default_factory=list)
    routes: list[dict[str, Any]] = Field(default_factory=list)
    budget: BudgetSummary | None = None
    evaluation: EvaluationResult | None = None
    diff: TripDiff | None = None
    agent_trace: dict[str, Any] | None = None


class DayMapResponse(BaseModel):
    """GET /api/v1/trips/{id}/days/{day}/map —— 单日地图数据。"""

    day: int
    markers: list[dict[str, Any]] = Field(default_factory=list)
    routes: list[dict[str, Any]] = Field(default_factory=list)


class TimelineResponse(BaseModel):
    """GET /api/v1/trips/{id}/timeline —— 时间轴数据。"""

    days: list[dict[str, Any]] = Field(default_factory=list)

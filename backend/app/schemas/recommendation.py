"""推荐模块输入输出数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .place import Place
from .route import RouteInfo


@dataclass(frozen=True)
class TravelRequest:
    """用户需求理解提取出的基础旅行需求"""

    city: str
    days: int
    people: int
    total_budget: float | None = None

    def __post_init__(self) -> None:
        """校验基础需求"""

        if not self.city.strip():
            raise ValueError("目标城市不能为空")
        if self.days <= 0:
            raise ValueError("旅行天数必须大于 0")
        if self.people <= 0:
            raise ValueError("出行人数必须大于 0")
        if self.total_budget is not None and self.total_budget < 0:
            raise ValueError("总预算不能为负数")


@dataclass(frozen=True)
class HardConstraint:
    """用户明确提出的可量化的、必须由程序精确执行的硬约束"""

    field: str
    operator: str
    value: Any
    scope: str
    source_text: str

    def __post_init__(self) -> None:
        """校验硬约束的来源和目标字段。"""

        if not self.field.strip():
            raise ValueError("硬约束字段不能为空")
        if not self.operator.strip():
            raise ValueError("硬约束操作符不能为空")
        if not self.scope.strip():
            raise ValueError("硬约束作用范围不能为空")
        if not self.source_text.strip():
            raise ValueError("硬约束必须保留用户原文")


@dataclass(frozen=True)
class SemanticPreference:
    """用户隐含偏好，由推荐Agent结合语境理解"""

    text: str
    scope: str
    emphasis: str = "normal"

    def __post_init__(self) -> None:
        """校验隐含偏好文本。"""

        if not self.text.strip():
            raise ValueError("隐含偏好文本不能为空")
        if not self.scope.strip():
            raise ValueError("隐含偏好作用范围不能为空")


@dataclass(frozen=True)
class Evidence:
    """推荐理由对应的知识来源。"""

    place_id: str
    summary: str
    source: str
    page: int | None = None

    def __post_init__(self) -> None:
        """校验推荐依据必须可追溯。"""

        if not self.place_id.strip():
            raise ValueError("推荐依据必须绑定地点编号")
        if not self.summary.strip():
            raise ValueError("推荐依据摘要不能为空")
        if not self.source.strip():
            raise ValueError("推荐依据来源不能为空")
        if self.page is not None and self.page <= 0:
            raise ValueError("页码必须大于 0")


@dataclass(frozen=True)
class ValidationIssue:
    """推荐结果校验出现的问题"""

    field: str
    message: str
    level: str = "error"

    def __post_init__(self) -> None:
        """校验问题描述格式。"""

        if not self.field.strip():
            raise ValueError("问题字段不能为空")
        if not self.message.strip():
            raise ValueError("问题说明不能为空")
        if self.level not in {"info", "warning", "error"}:
            raise ValueError("问题级别不合法")


@dataclass(frozen=True)
class RecommendationContext:
    """用户需求理解传入的的推荐上下文"""

    session_id: str
    requirements: TravelRequest
    original_text: str
    conversation_context: list[str] = field(default_factory=list)
    explicit_hard_constraints: list[HardConstraint] = field(default_factory=list)
    semantic_preferences: list[SemanticPreference] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    unresolved_fields: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        """校验推荐上下文是否保留必要语义"""

        if not self.session_id.strip():
            raise ValueError("会话编号不能为空")
        if not isinstance(self.requirements, TravelRequest):
            raise TypeError("明确的旅行需求必须使用TravelRequest数据模型")
        if not self.original_text.strip():
            raise ValueError("必须保留用户原始表达")


@dataclass(frozen=True)
class RecommendationResult:
    """输出到旅游具体路线规划的推荐结果"""
    policy_summary: str
    attractions: list[Place] = field(default_factory=list)
    hotels: list[Place] = field(default_factory=list)
    restaurants: list[Place] = field(default_factory=list)
    routes: list[RouteInfo] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    validation_issues: list[ValidationIssue] = field(default_factory=list)
    need_follow_up: bool = False
    follow_up_question: str | None = None
    agent_trace: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        """校验推荐结果的基础结构"""
        if not self.policy_summary.strip():
            raise ValueError("推荐策略说明不能为空")
        for place in self.attractions:
            self._validate_place_type(place, "attraction")
        for place in self.hotels:
            self._validate_place_type(place, "hotel")
        for place in self.restaurants:
            self._validate_place_type(place, "restaurant")
        if self.need_follow_up and not self.follow_up_question:
            raise ValueError("需要追问时必须提供追问问题")

    @staticmethod
    def _validate_place_type(place: Place, expected_type: str) -> None:
        """校验地点是否放在正确的推荐分类里"""
        if not isinstance(place, Place):
            raise TypeError("推荐地点必须使用Place数据模型")
        if place.place_type != expected_type:
            raise ValueError("推荐地点类型与列表分类不一致")


ExplicitConstraint = HardConstraint
KnowledgeSource = Evidence
RecommendationAgentResult = RecommendationResult

__all__ = [
    "Evidence",
    "ExplicitConstraint",
    "HardConstraint",
    "KnowledgeSource",
    "RecommendationAgentResult",
    "RecommendationContext",
    "RecommendationResult",
    "SemanticPreference",
    "TravelRequest",
    "ValidationIssue",
]

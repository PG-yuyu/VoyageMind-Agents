"""
统一 Schema 包
=============

向上一级提供统一命名空间，同时兼容旧有 from backend.schemas import XXX 用法。
"""

# ── 统一基类 ─────────────────────────────────────────────────────
from backend.schemas._base import ApiResponse, PaginatedResponse, now_iso, new_id

# ── 成员一原始模型（向后兼容） ─────────────────────────────────────
from backend.schemas._member1 import (
    IntentType,
    SessionStatus,
    CreateSessionRequest,
    AuthLoginRequest,
    AuthRegisterRequest,
    AuthUser,
    Session,
    ChatMessage,
    IntentResult,
    TravelRequest,
    Assumption,
    RequirementExtractionResult,
    ChatRequest,
    ChatResponse,
    IntentDetectRequest,
    RequirementExtractRequest,
    WorkflowRequest,
    AgentStep,
    AgentTrace,
)

# ── 成员三通用枚举与模型 ──────────────────────────────────────────
from backend.schemas.common import (
    MessageRole,
    Intent,
    ModifySubIntent,
    PlaceType,
    PriceType,
    WalkingIntensity,
    DataSource,
    TransportMode,
    TravelPace,
    MealType,
    WorkflowStatus,
    Severity,
    ConstraintOperator,
    ExplicitConstraint,
    SemanticPreference,
)

# ── 成员三领域模型 ────────────────────────────────────────────────
from backend.schemas.itinerary import (
    ItemType,
    ItineraryItem,
    ItineraryDay,
    ItineraryStatus,
    Itinerary,
    GenerateRequest,
)
from backend.schemas.budget import BudgetSummary, CalculateBudgetRequest
from backend.schemas.evaluation import (
    ValidationCode,
    ValidationIssue,
    EvaluationMetrics,
    HardConstraintEvaluation,
    ValidateRequest,
)
from backend.schemas.evaluation_agent import (
    OverallEvaluationResult,
    ReplanDirective,
    ReplanActionType,
)
from backend.schemas.planning_policy import ItineraryPlanningPolicy
from backend.schemas.preference_evaluation import (
    SoftPreferenceIssue,
    SoftPreferenceEvaluation,
)
from backend.schemas.modification import ModificationRequest
from backend.schemas.version import ChangeType, TripChange, TripDiff

__all__ = [
    # _base
    "ApiResponse",
    "PaginatedResponse",
    "now_iso",
    "new_id",
    # _member1
    "IntentType",
    "SessionStatus",
    "CreateSessionRequest",
    "AuthLoginRequest",
    "AuthRegisterRequest",
    "AuthUser",
    "Session",
    "ChatMessage",
    "IntentResult",
    "TravelRequest",
    "Assumption",
    "RequirementExtractionResult",
    "ChatRequest",
    "ChatResponse",
    "IntentDetectRequest",
    "RequirementExtractRequest",
    "WorkflowRequest",
    "AgentStep",
    "AgentTrace",
    # common
    "MessageRole",
    "Intent",
    "ModifySubIntent",
    "PlaceType",
    "PriceType",
    "WalkingIntensity",
    "DataSource",
    "TransportMode",
    "TravelPace",
    "MealType",
    "WorkflowStatus",
    "Severity",
    "ConstraintOperator",
    "ExplicitConstraint",
    "SemanticPreference",
    # itinerary
    "ItemType",
    "ItineraryItem",
    "ItineraryDay",
    "ItineraryStatus",
    "Itinerary",
    "GenerateRequest",
    # budget
    "BudgetSummary",
    "CalculateBudgetRequest",
    # evaluation
    "ValidationCode",
    "ValidationIssue",
    "EvaluationMetrics",
    "HardConstraintEvaluation",
    "ValidateRequest",
    # evaluation_agent
    "OverallEvaluationResult",
    "ReplanDirective",
    "ReplanActionType",
    # planning_policy
    "ItineraryPlanningPolicy",
    # preference_evaluation
    "SoftPreferenceIssue",
    "SoftPreferenceEvaluation",
    # modification
    "ModificationRequest",
    # version
    "ChangeType",
    "TripChange",
    "TripDiff",
]

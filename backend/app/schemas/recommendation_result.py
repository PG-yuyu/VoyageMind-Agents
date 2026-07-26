"""推荐结果模型兼容导入入口。"""

from .recommendation import (
    Evidence,
    KnowledgeSource,
    RecommendationAgentResult,
    RecommendationResult,
    ValidationIssue,
)

__all__ = [
    "Evidence",
    "KnowledgeSource",
    "RecommendationAgentResult",
    "RecommendationResult",
    "ValidationIssue",
]

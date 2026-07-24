"""推荐策略数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RecommendationPolicy:
    """资源推荐策略摘要"""
    focus: list[str] = field(default_factory=list)
    filters: list[str] = field(default_factory=list)
    preference_notes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        """校验推荐策略至少包含一个推荐重点"""
        if not self.focus:
            raise ValueError("推荐策略至少需要一个推荐重点")
__all__ = ["RecommendationPolicy"]

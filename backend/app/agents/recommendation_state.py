"""推荐工作流执行状态。"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.app.schemas import (
    Place,
    RecommendationContext,
    RecommendationPolicy,
    RecommendationResult,
)


@dataclass
class RecommendationState:
    """记录第六步推荐工作流的中间状态和执行轨迹。"""

    context: RecommendationContext
    policy: RecommendationPolicy | None = None
    attraction_candidates: list[Place] = field(default_factory=list)
    hotel_candidates: list[Place] = field(default_factory=list)
    restaurant_candidates: list[Place] = field(default_factory=list)
    result: RecommendationResult | None = None
    trace: list[str] = field(default_factory=list)

    def add_trace(self, message: str) -> None:
        """追加一条中文执行轨迹。"""

        if not message.strip():
            raise ValueError("执行轨迹不能为空")
        self.trace.append(message)

    def record_candidates(
        self,
        attractions: list[Place],
        hotels: list[Place],
        restaurants: list[Place],
    ) -> None:
        """记录三类候选资源。"""

        self.attraction_candidates = list(attractions)
        self.hotel_candidates = list(hotels)
        self.restaurant_candidates = list(restaurants)

    def record_result(self, result: RecommendationResult) -> None:
        """记录最终推荐结果。"""

        if not isinstance(result, RecommendationResult):
            raise TypeError("推荐状态只能记录 RecommendationResult")
        self.result = result


__all__ = ["RecommendationState"]

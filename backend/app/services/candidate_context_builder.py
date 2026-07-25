"""推荐 Agent 候选资源上下文构建服务。"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.app.schemas import (
    Place,
    RecommendationPolicy,
    ResourceFilterPolicy,
)

from .place_search_service import PlaceSearchQuery, PlaceSearchService


@dataclass(frozen=True)
class CandidateResourceContext:
    """第六步推荐结果组装前的三类候选资源集合。"""

    attractions: list[Place] = field(default_factory=list)
    hotels: list[Place] = field(default_factory=list)
    restaurants: list[Place] = field(default_factory=list)

    def by_type(self, place_type: str) -> list[Place]:
        """按资源类型返回对应候选列表。"""

        if place_type == "attraction":
            return self.attractions
        if place_type == "hotel":
            return self.hotels
        if place_type == "restaurant":
            return self.restaurants
        raise ValueError("候选资源类型必须是景点、酒店或餐厅之一")


class CandidateContextBuilder:
    """把推荐策略转换为可供结果 Agent 使用的候选资源上下文。"""

    RESOURCE_TYPES = ("attraction", "hotel", "restaurant")

    def __init__(self, search_service: PlaceSearchService | None = None) -> None:
        """注入资源查询服务，默认使用本地样例数据查询服务。"""

        self.search_service = search_service or PlaceSearchService()

    def build(
        self,
        policy: RecommendationPolicy,
        city: str | None,
        per_type_limit: int | dict[str, int] = 2,
    ) -> CandidateResourceContext:
        """按策略查询每类候选资源，并返回统一上下文。"""

        if not isinstance(policy, RecommendationPolicy):
            raise TypeError("候选上下文只能根据 RecommendationPolicy 构建")
        self._validate_limits(per_type_limit)

        return CandidateResourceContext(
            attractions=self._search_by_type(
                policy,
                city,
                "attraction",
                self._limit_for_type(per_type_limit, "attraction"),
            ),
            hotels=self._search_by_type(
                policy,
                city,
                "hotel",
                self._limit_for_type(per_type_limit, "hotel"),
            ),
            restaurants=self._search_by_type(
                policy,
                city,
                "restaurant",
                self._limit_for_type(per_type_limit, "restaurant"),
            ),
        )

    def _search_by_type(
        self,
        policy: RecommendationPolicy,
        city: str | None,
        place_type: str,
        limit: int,
    ) -> list[Place]:
        """查询单类资源，先使用完整策略，必要时放宽标签条件。"""

        filter_policy = self._find_filter(policy, place_type)
        strict_query = self._build_query(city, place_type, filter_policy)
        results = self.search_service.search(strict_query)

        if not results and filter_policy and filter_policy.tags:
            relaxed_query = self._build_query(
                city=city,
                place_type=place_type,
                filter_policy=ResourceFilterPolicy(
                    place_type=filter_policy.place_type,
                    area=filter_policy.area,
                    min_price=filter_policy.min_price,
                    max_price=filter_policy.max_price,
                ),
            )
            results = self.search_service.search(relaxed_query)

        ranked_results = self._rank_results(results, filter_policy, policy)
        return ranked_results[:limit]

    def _build_query(
        self,
        city: str | None,
        place_type: str,
        filter_policy: ResourceFilterPolicy | None,
    ) -> PlaceSearchQuery:
        """把单类过滤策略转换成资源查询服务请求。"""

        if filter_policy is None:
            return PlaceSearchQuery(city=city, place_type=place_type)

        return PlaceSearchQuery(
            city=city,
            place_type=place_type,
            area=filter_policy.area,
            tags=filter_policy.tags,
            min_price=filter_policy.min_price,
            max_price=filter_policy.max_price,
        )

    @staticmethod
    def _find_filter(
        policy: RecommendationPolicy, place_type: str
    ) -> ResourceFilterPolicy | None:
        """从策略中过滤出指定资源类型的查询方向。"""

        for filter_policy in policy.filters:
            if filter_policy.place_type == place_type:
                return filter_policy
        return None

    def _rank_results(
        self,
        places: list[Place],
        filter_policy: ResourceFilterPolicy | None,
        policy: RecommendationPolicy,
    ) -> list[Place]:
        """根据标签、人群和预算倾向做轻量排序。"""

        return sorted(
            places,
            key=lambda place: self._sort_key(place, filter_policy, policy),
        )

    def _sort_key(
        self,
        place: Place,
        filter_policy: ResourceFilterPolicy | None,
        policy: RecommendationPolicy,
    ) -> tuple[int, float, str]:
        """生成确定性排序键，分数高的资源排在前面。"""

        tag_score = self._match_count(place.tags, filter_policy.tags if filter_policy else [])
        people_score = self._match_count(place.suitable_for, policy.people_direction)
        score = tag_score * 3 + people_score

        if policy.budget_direction == "预算友好":
            price_key = place.price if place.price is not None else float("inf")
        else:
            price_key = 0.0

        return (-score, price_key, place.name)

    @staticmethod
    def _match_count(source: list[str], targets: list[str]) -> int:
        """统计两个标签集合中完全命中的数量。"""

        return len(set(source).intersection(set(targets)))

    @classmethod
    def _validate_limits(cls, limits: int | dict[str, int]) -> None:
        """校验每类候选资源数量限制。"""

        if isinstance(limits, int):
            if limits <= 0:
                raise ValueError("每类候选资源数量必须大于 0")
            return

        for place_type, limit in limits.items():
            if place_type not in cls.RESOURCE_TYPES:
                raise ValueError("候选资源类型必须是景点、酒店或餐厅之一")
            if limit <= 0:
                raise ValueError("每类候选资源数量必须大于 0")

    @staticmethod
    def _limit_for_type(limits: int | dict[str, int], place_type: str) -> int:
        """读取指定资源类型的候选数量限制。"""

        if isinstance(limits, int):
            return limits
        return limits[place_type]


__all__ = ["CandidateContextBuilder", "CandidateResourceContext"]

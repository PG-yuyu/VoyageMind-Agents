"""推荐 Agent 候选资源上下文构建服务。"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.app.schemas import (
    Place,
    RecommendationContext,
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
    """把大模型策略转换为候选资源查询，不做推荐排序决策。"""

    RESOURCE_TYPES = ("attraction", "hotel", "restaurant")

    def __init__(self, search_service: PlaceSearchService | None = None) -> None:
        """注入资源查询服务，默认使用本地样例数据查询服务。"""

        self.search_service = search_service or PlaceSearchService()

    def build(
        self,
        policy: RecommendationPolicy,
        city: str | None,
        per_type_limit: int | dict[str, int | None] | None = None,
        context: RecommendationContext | None = None,
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
                context,
            ),
            hotels=self._search_by_type(
                policy,
                city,
                "hotel",
                self._limit_for_type(per_type_limit, "hotel"),
                context,
            ),
            restaurants=self._search_by_type(
                policy,
                city,
                "restaurant",
                self._limit_for_type(per_type_limit, "restaurant"),
                context,
            ),
        )

    def _search_by_type(
        self,
        policy: RecommendationPolicy,
        city: str | None,
        place_type: str,
        limit: int | None,
        context: RecommendationContext | None,
    ) -> list[Place]:
        """查询单类候选资源，只执行模型策略和硬性事实过滤。"""

        filter_policy = self._find_filter(policy, place_type)
        query = self._build_query(city, place_type, filter_policy, limit, context)
        return self.search_service.search(query)

    def _build_query(
        self,
        city: str | None,
        place_type: str,
        filter_policy: ResourceFilterPolicy | None,
        limit: int | None,
        context: RecommendationContext | None,
    ) -> PlaceSearchQuery:
        """把单类过滤策略转换成资源查询服务请求。"""

        if filter_policy is None:
            return PlaceSearchQuery(city=city, place_type=place_type, limit=limit)

        return PlaceSearchQuery(
            city=city,
            place_type=place_type,
            area=self._area_for_query(filter_policy, place_type, context),
            min_price=filter_policy.min_price,
            max_price=filter_policy.max_price,
            limit=limit,
        )

    def _area_for_query(
        self,
        filter_policy: ResourceFilterPolicy,
        place_type: str,
        context: RecommendationContext | None,
    ) -> str | None:
        """判断 LLM 策略中的 area 是否可作为查询硬过滤。

        允许 area 透传的条件（满足任一即可）：
        1. 有成员一传入的明确区域硬约束支持（原有逻辑）
        2. area 名称或其核心关键词出现在用户原文或语义偏好中
           —— 确保 LLM 是从用户输入推断的，而非凭空编造
        """

        if filter_policy.area is None or context is None:
            return None

        # 条件 1：明确硬约束支持
        if self._area_supported_by_explicit_constraint(
            context,
            place_type,
            filter_policy.area,
        ):
            return filter_policy.area

        # 条件 2：area 关键词在用户输入中出现过
        if self._area_mentioned_in_user_input(context, filter_policy.area):
            return filter_policy.area

        return None

    @staticmethod
    def _area_supported_by_explicit_constraint(
        context: RecommendationContext,
        place_type: str,
        area: str,
    ) -> bool:
        """判断区域过滤是否来自成员一传入的明确硬约束。"""

        scope_aliases = {place_type, "overall", "all", "全部", "整体"}
        if place_type == "attraction":
            scope_aliases.add("景点")
        if place_type == "hotel":
            scope_aliases.update({"hotel", "酒店", "住宿"})
        if place_type == "restaurant":
            scope_aliases.update({"restaurant", "餐厅", "餐饮", "food", "meal"})

        for constraint in context.explicit_hard_constraints:
            field = constraint.field.lower()
            scope = constraint.scope.lower()
            if field in {"area", "district", "区域", "商圈"}:
                if scope in scope_aliases and str(constraint.value) == area:
                    return True
        return False

    @staticmethod
    def _area_mentioned_in_user_input(
        context: RecommendationContext,
        area: str,
    ) -> bool:
        """检查 area 名称或其核心关键词是否在用户输入中出现过。

        支持模糊匹配：如 area="滨海新区"，用户说"滨海部分"即可命中。
        提取 area 的核心地名（去掉"区""新区"等后缀）与用户输入做子串匹配。
        """

        # 去掉常见行政区后缀，提取核心地名
        core_name = area
        for suffix in ["新区", "区", "县", "镇", "街道"]:
            if core_name.endswith(suffix):
                core_name = core_name[: -len(suffix)]
                break

        # 搜索源：用户原文 + 语义偏好
        sources = [context.original_text or ""]
        for pref in context.semantic_preferences:
            sources.append(pref.text or "")

        combined = " ".join(sources)
        return core_name in combined or area in combined

    @staticmethod
    def _find_filter(
        policy: RecommendationPolicy, place_type: str
    ) -> ResourceFilterPolicy | None:
        """从策略中过滤出指定资源类型的查询方向。"""

        for filter_policy in policy.filters:
            if filter_policy.place_type == place_type:
                return filter_policy
        return None

    @classmethod
    def _validate_limits(cls, limits: int | dict[str, int | None] | None) -> None:
        """校验每类候选资源数量限制。"""

        if limits is None:
            return
        if isinstance(limits, int):
            if limits <= 0:
                raise ValueError("每类候选资源数量必须大于 0")
            return

        for place_type, limit in limits.items():
            if place_type not in cls.RESOURCE_TYPES:
                raise ValueError("候选资源类型必须是景点、酒店或餐厅之一")
            if limit is not None and limit <= 0:
                raise ValueError("每类候选资源数量必须大于 0")

    @staticmethod
    def _limit_for_type(
        limits: int | dict[str, int | None] | None,
        place_type: str,
    ) -> int | None:
        """读取指定资源类型的候选数量限制。"""

        if limits is None:
            return None
        if isinstance(limits, int):
            return limits
        return limits.get(place_type)


__all__ = ["CandidateContextBuilder", "CandidateResourceContext"]

"""旅游资源查询服务。"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..repositories.place_repository import PlaceQuery, PlaceRepository
from ..schemas import Place


@dataclass(frozen=True)
class PlaceSearchQuery:
    """服务层旅游资源查询请求。"""

    city: str | None = None
    place_type: str | None = None
    area: str | None = None
    tags: list[str] = field(default_factory=list)
    min_price: float | None = None
    max_price: float | None = None
    suitable_for: list[str] = field(default_factory=list)
    limit: int | None = None

    def __post_init__(self) -> None:
        """校验查询请求的基础条件。"""

        if self.min_price is not None and self.min_price < 0:
            raise ValueError("最低价格不能为负数")
        if self.max_price is not None and self.max_price < 0:
            raise ValueError("最高价格不能为负数")
        if self.limit is not None and self.limit <= 0:
            raise ValueError("返回数量限制必须大于 0")
        if (
            self.min_price is not None
            and self.max_price is not None
            and self.min_price > self.max_price
        ):
            raise ValueError("最低价格不能大于最高价格")


class PlaceSearchService:
    """面向推荐流程的候选资源查询服务。"""

    def __init__(self, repository: PlaceRepository | None = None) -> None:
        """注入资源仓库，默认读取本地样例数据。"""

        self.repository = repository or PlaceRepository()

    def search(self, query: PlaceSearchQuery) -> list[Place]:
        """按请求条件返回候选资源事实。"""

        repository_query = PlaceQuery(
            city=query.city,
            place_type=query.place_type,
            tags=query.tags,
            area=query.area,
            min_price=query.min_price,
            max_price=query.max_price,
        )
        results = self.repository.search(repository_query)
        if query.suitable_for:
            results = [
                place
                for place in results
                if set(query.suitable_for).intersection(set(place.suitable_for))
            ]
        if query.limit is not None:
            results = results[: query.limit]
        return results

    def search_by_city_and_type(self, city: str, place_type: str) -> list[Place]:
        """按城市和资源类型查询候选资源。"""

        query = PlaceSearchQuery(city=city, place_type=place_type)
        return self.search(query)

    def search_attractions(
        self,
        city: str | None = None,
        tags: list[str] | None = None,
        limit: int | None = None,
    ) -> list[Place]:
        """查询景点候选资源。"""

        return self.search(
            PlaceSearchQuery(
                city=city,
                place_type="attraction",
                tags=tags or [],
                limit=limit,
            )
        )

    def search_hotels(
        self,
        city: str | None = None,
        max_price: float | None = None,
        limit: int | None = None,
    ) -> list[Place]:
        """查询酒店候选资源。"""

        return self.search(
            PlaceSearchQuery(
                city=city,
                place_type="hotel",
                max_price=max_price,
                limit=limit,
            )
        )

    def search_restaurants(
        self,
        city: str | None = None,
        tags: list[str] | None = None,
        max_price: float | None = None,
        limit: int | None = None,
    ) -> list[Place]:
        """查询餐厅候选资源。"""

        return self.search(
            PlaceSearchQuery(
                city=city,
                place_type="restaurant",
                tags=tags or [],
                max_price=max_price,
                limit=limit,
            )
        )


PlaceSearchRequest = PlaceSearchQuery

__all__ = ["PlaceSearchQuery", "PlaceSearchRequest", "PlaceSearchService"]

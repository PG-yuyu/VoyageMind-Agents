"""候选资源统一查询工具。"""

from __future__ import annotations

from ..schemas import Place
from ..services import PlaceSearchQuery, PlaceSearchService


def search_candidates(
    city: str | None = None,
    place_type: str | None = None,
    area: str | None = None,
    tags: list[str] | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    suitable_for: list[str] | None = None,
    limit: int | None = None,
) -> list[Place]:
    """查询满足条件的候选旅游资源。"""

    query = PlaceSearchQuery(
        city=city,
        place_type=place_type,
        area=area,
        tags=tags or [],
        min_price=min_price,
        max_price=max_price,
        suitable_for=suitable_for or [],
        limit=limit,
    )
    return PlaceSearchService().search(query)


__all__ = ["search_candidates"]

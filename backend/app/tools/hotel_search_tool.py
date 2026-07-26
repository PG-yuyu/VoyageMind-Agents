"""酒店候选资源查询工具。"""

from __future__ import annotations

from ..schemas import Place
from ..services import PlaceSearchService


def search_hotels(
    city: str | None = None,
    max_price: float | None = None,
    limit: int | None = None,
) -> list[Place]:
    """查询酒店候选资源。"""

    return PlaceSearchService().search_hotels(
        city=city,
        max_price=max_price,
        limit=limit,
    )


__all__ = ["search_hotels"]

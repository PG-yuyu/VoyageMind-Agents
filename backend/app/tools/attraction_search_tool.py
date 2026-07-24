"""景点候选资源查询工具。"""

from __future__ import annotations

from ..schemas import Place
from ..services import PlaceSearchService


def search_attractions(
    city: str | None = None,
    tags: list[str] | None = None,
    limit: int | None = None,
) -> list[Place]:
    """查询景点候选资源。"""

    return PlaceSearchService().search_attractions(
        city=city,
        tags=tags,
        limit=limit,
    )


__all__ = ["search_attractions"]

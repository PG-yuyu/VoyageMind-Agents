"""单条路线规划工具。"""

from __future__ import annotations

from backend.app.schemas import RouteInfo
from backend.app.services import RouteService


def plan_route(
    origin_place_id: str,
    destination_place_id: str,
    travel_mode: str = "walking",
) -> RouteInfo:
    """按起终点地点编号规划一条路线。"""

    return RouteService().plan_route_by_ids(
        origin_place_id=origin_place_id,
        destination_place_id=destination_place_id,
        travel_mode=travel_mode,
    )


__all__ = ["plan_route"]

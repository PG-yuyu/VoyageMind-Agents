"""批量路线规划工具。"""

from __future__ import annotations

from backend.app.schemas import RouteInfo, RouteRequest
from backend.app.services import RouteService


def plan_routes(
    requests: list[RouteRequest] | list[dict[str, str]],
) -> list[RouteInfo]:
    """批量规划路线。"""

    route_requests = [
        request if isinstance(request, RouteRequest) else RouteRequest(**request)
        for request in requests
    ]
    return RouteService().plan_batch(route_requests)


__all__ = ["plan_routes"]

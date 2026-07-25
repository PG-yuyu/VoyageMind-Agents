"""路线规划 API 入口。"""

from __future__ import annotations

from backend.app.schemas import RouteRequest
from backend.app.services import RouteService

try:
    from fastapi import APIRouter
except ModuleNotFoundError:
    APIRouter = None


route_service = RouteService()
router = (
    APIRouter(prefix="/api/v1/member2/routes", tags=["member2-routes"])
    if APIRouter
    else None
)


def plan_route_payload(payload: dict) -> dict:
    """处理单条路线规划请求。"""

    request = RouteRequest(**payload)
    return route_service.plan_route(request).to_dict()


def plan_batch_routes_payload(payload: dict) -> dict:
    """处理批量路线规划请求。"""

    requests = [RouteRequest(**item) for item in payload.get("routes", [])]
    routes = route_service.plan_batch(requests)
    return {"routes": [route.to_dict() for route in routes]}


if router is not None:

    @router.post("/plan")
    def plan_route_api(payload: dict) -> dict:
        """规划单条路线。"""

        return plan_route_payload(payload)

    @router.post("/batch-plan")
    def plan_batch_routes_api(payload: dict) -> dict:
        """批量规划路线。"""

        return plan_batch_routes_payload(payload)


__all__ = ["plan_batch_routes_payload", "plan_route_payload", "router"]

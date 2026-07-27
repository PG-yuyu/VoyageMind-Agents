"""路线规划服务。"""

from __future__ import annotations

from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from math import atan2, cos, radians, sin, sqrt
from typing import Protocol

from backend.app.clients import AmapClient
from backend.app.repositories import PlaceRepository
from backend.app.schemas import Place, RecommendationResult, RouteInfo, RouteRequest

from .route_cache_service import RouteCacheService


SUPPORTED_TRAVEL_MODES = {"walking", "transit", "driving"}
MODE_SPEED_METERS_PER_MINUTE = {
    "walking": 80.0,
    "transit": 250.0,
    "driving": 420.0,
}
EARTH_RADIUS_METERS = 6371000.0
STRAIGHT_LINE_WARNING = "路线未经真实道路验证，仅基于经纬度直线距离估算。"


class RouteClientLike(Protocol):
    """路线客户端需要提供的最小接口。"""

    def plan_route(
        self,
        origin: Place,
        destination: Place,
        travel_mode: str,
    ) -> RouteInfo | None:
        """查询两个地点之间的路线。"""


class RouteService:
    """查询或估算两个地点之间的路线事实。"""

    def __init__(
        self,
        place_repository: PlaceRepository | None = None,
        cache_service: RouteCacheService | None = None,
        amap_client: RouteClientLike | None = None,
    ) -> None:
        """注入地点仓库、路线缓存和高德客户端。"""

        self.place_repository = place_repository or PlaceRepository()
        self.cache_service = cache_service or RouteCacheService()
        self.amap_client = amap_client or AmapClient()

    def plan_route(self, request: RouteRequest) -> RouteInfo:
        """按地点编号规划单条路线。"""

        self._validate_travel_mode(request.travel_mode)
        cached_route = self.cache_service.get(request)
        if cached_route is not None:
            return cached_route

        origin = self._get_place_or_raise(request.origin_place_id, "起点")
        destination = self._get_place_or_raise(request.destination_place_id, "终点")
        route = self._plan_with_client_or_estimate(
            origin=origin,
            destination=destination,
            travel_mode=request.travel_mode,
        )
        self.cache_service.set(request, route)
        return route

    def plan_route_by_ids(
        self,
        origin_place_id: str,
        destination_place_id: str,
        travel_mode: str = "walking",
    ) -> RouteInfo:
        """使用地点编号规划路线。"""

        return self.plan_route(
            RouteRequest(
                origin_place_id=origin_place_id,
                destination_place_id=destination_place_id,
                travel_mode=travel_mode,
            )
        )

    def plan_between_places(
        self,
        origin: Place,
        destination: Place,
        travel_mode: str = "walking",
    ) -> RouteInfo:
        """使用两个地点模型规划路线。"""

        self._validate_place(origin, "起点")
        self._validate_place(destination, "终点")
        self._validate_travel_mode(travel_mode)
        return self._plan_with_client_or_estimate(origin, destination, travel_mode)

    def plan_batch(self, requests: Iterable[RouteRequest]) -> list[RouteInfo]:
        """批量规划路线。"""

        request_list = list(requests)
        if not request_list:
            return []
        if len(request_list) == 1:
            return [self.plan_route(request_list[0])]

        max_workers = min(8, len(request_list))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            return list(executor.map(self.plan_route, request_list))

    def plan_recommendation_routes(
        self,
        result: RecommendationResult,
        travel_mode: str = "walking",
    ) -> RecommendationResult:
        """为推荐结果补充从首个酒店到推荐资源的路线事实。"""

        if not isinstance(result, RecommendationResult):
            raise TypeError("路线规划只能处理 RecommendationResult")
        self._validate_travel_mode(travel_mode)
        if not result.hotels:
            return result

        base_hotel = result.hotels[0]
        route_requests = [
            RouteRequest(
                origin_place_id=base_hotel.place_id,
                destination_place_id=place.place_id,
                travel_mode=travel_mode,
            )
            for place in [*result.attractions, *result.restaurants]
            if place.place_id != base_hotel.place_id
        ]
        routes = self.plan_batch(route_requests)
        return RecommendationResult(
            policy_summary=result.policy_summary,
            attractions=result.attractions,
            hotels=result.hotels,
            restaurants=result.restaurants,
            routes=routes,
            evidence=result.evidence,
            validation_issues=result.validation_issues,
            need_follow_up=result.need_follow_up,
            follow_up_question=result.follow_up_question,
            agent_trace=[
                *result.agent_trace,
                f"补充路线事实 {len(routes)} 条，不生成每日行程",
            ],
        )

    def _plan_with_client_or_estimate(
        self,
        origin: Place,
        destination: Place,
        travel_mode: str,
    ) -> RouteInfo:
        """优先使用高德客户端，失败时返回未验证的直线估算。"""

        try:
            route = self.amap_client.plan_route(origin, destination, travel_mode)
        except Exception:
            route = None
        if route is not None:
            return route
        return self._estimate_straight_line_route(origin, destination, travel_mode)

    def _estimate_straight_line_route(
        self,
        origin: Place,
        destination: Place,
        travel_mode: str,
    ) -> RouteInfo:
        """根据坐标生成直线距离和估算耗时。"""

        distance = self._estimate_distance_meters(origin, destination)
        duration = self._estimate_duration_minutes(distance, travel_mode)
        return RouteInfo(
            origin_place_id=origin.place_id,
            destination_place_id=destination.place_id,
            distance_meters=round(distance, 2),
            duration_minutes=round(duration, 2),
            source="straight_line_estimation",
            verified=False,
            polyline=[
                (origin.coordinate.longitude, origin.coordinate.latitude),
                (destination.coordinate.longitude, destination.coordinate.latitude),
            ],
            warning=STRAIGHT_LINE_WARNING,
        )

    def _get_place_or_raise(self, place_id: str, label: str) -> Place:
        """按地点编号读取地点，不存在时抛出明确错误。"""

        place = self.place_repository.get_by_id(place_id)
        if place is None:
            raise ValueError(f"{label}地点不存在：{place_id}")
        return place

    @staticmethod
    def _validate_place(place: Place, label: str) -> None:
        """校验路线端点必须是地点模型。"""

        if not isinstance(place, Place):
            raise TypeError(f"{label}必须使用 Place 数据模型")

    @staticmethod
    def _validate_travel_mode(travel_mode: str) -> None:
        """校验出行方式是否被路线服务支持。"""

        if travel_mode not in SUPPORTED_TRAVEL_MODES:
            raise ValueError("出行方式必须是 walking、transit 或 driving")

    @staticmethod
    def _estimate_distance_meters(origin: Place, destination: Place) -> float:
        """使用 Haversine 公式估算两点直线距离。"""

        origin_lat = radians(origin.coordinate.latitude)
        destination_lat = radians(destination.coordinate.latitude)
        delta_lat = radians(destination.coordinate.latitude - origin.coordinate.latitude)
        delta_lng = radians(destination.coordinate.longitude - origin.coordinate.longitude)
        haversine_value = (
            sin(delta_lat / 2) ** 2
            + cos(origin_lat) * cos(destination_lat) * sin(delta_lng / 2) ** 2
        )
        central_angle = 2 * atan2(sqrt(haversine_value), sqrt(1 - haversine_value))
        return EARTH_RADIUS_METERS * central_angle

    @staticmethod
    def _estimate_duration_minutes(distance_meters: float, travel_mode: str) -> float:
        """按出行方式估算耗时。"""

        return distance_meters / MODE_SPEED_METERS_PER_MINUTE[travel_mode]


RoutePlanService = RouteService

__all__ = [
    "MODE_SPEED_METERS_PER_MINUTE",
    "RoutePlanService",
    "RouteService",
    "SUPPORTED_TRAVEL_MODES",
]

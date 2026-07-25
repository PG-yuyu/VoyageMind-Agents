"""路线缓存仓库。"""

from __future__ import annotations

from backend.app.schemas import RouteInfo, RouteRequest


class RouteRepository:
    """保存路线结果的内存仓库。"""

    def __init__(self) -> None:
        """初始化空路线缓存。"""

        self._routes: dict[tuple[str, str, str], RouteInfo] = {}

    def get(self, request: RouteRequest) -> RouteInfo | None:
        """按路线请求读取缓存结果。"""

        return self._routes.get(self._cache_key(request))

    def save(self, request: RouteRequest, route: RouteInfo) -> None:
        """保存路线结果。"""

        self._routes[self._cache_key(request)] = route

    def clear(self) -> None:
        """清空缓存，供测试和重新计算使用。"""

        self._routes.clear()

    def size(self) -> int:
        """返回缓存中的路线数量。"""

        return len(self._routes)

    @staticmethod
    def _cache_key(request: RouteRequest) -> tuple[str, str, str]:
        """生成稳定的路线缓存键。"""

        return (
            request.origin_place_id,
            request.destination_place_id,
            request.travel_mode,
        )


__all__ = ["RouteRepository"]

"""路线结果缓存服务。"""

from __future__ import annotations

from backend.app.repositories import RouteRepository
from backend.app.schemas import RouteInfo, RouteRequest


class RouteCacheService:
    """使用内存仓库缓存路线结果。"""

    def __init__(self, repository: RouteRepository | None = None) -> None:
        """注入路线仓库。"""

        self.repository = repository or RouteRepository()

    def get(self, request: RouteRequest) -> RouteInfo | None:
        """读取路线缓存。"""

        return self.repository.get(request)

    def set(self, request: RouteRequest, route: RouteInfo) -> None:
        """写入路线缓存。"""

        self.repository.save(request, route)

    def clear(self) -> None:
        """清空路线缓存。"""

        self.repository.clear()

    def size(self) -> int:
        """返回缓存数量。"""

        return self.repository.size()


__all__ = ["RouteCacheService"]

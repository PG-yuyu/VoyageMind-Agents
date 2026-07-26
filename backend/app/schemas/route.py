"""路线数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

VALID_ROUTE_SOURCES = {"amap", "manual", "straight_line_estimation"}


@dataclass(frozen=True)
class RouteRequest:
    """路线查询请求。"""

    origin_place_id: str
    destination_place_id: str
    travel_mode: str = "walking"

    def __post_init__(self) -> None:
        """校验路线请求的必要字段。"""
        if not self.origin_place_id.strip():
            raise ValueError("起点地点编号不能为空")
        if not self.destination_place_id.strip():
            raise ValueError("终点地点编号不能为空")
        if not self.travel_mode.strip():
            raise ValueError("出行方式不能为空")


@dataclass(frozen=True)
class RouteInfo:
    """两个地点之间的路线信息。"""

    origin_place_id: str
    destination_place_id: str
    distance_meters: float
    duration_minutes: float
    source: str
    verified: bool
    polyline: list[tuple[float, float]] = field(default_factory=list)
    warning: str | None = None

    def __post_init__(self) -> None:
        """校验路线来源、距离、耗时和验证状态"""
        if not self.origin_place_id.strip():
            raise ValueError("起点地点编号不能为空")
        if not self.destination_place_id.strip():
            raise ValueError("终点地点编号不能为空")
        if self.distance_meters < 0:
            raise ValueError("路线距离不能为负数")
        if self.duration_minutes < 0:
            raise ValueError("路线耗时不能为负数")
        if self.source not in VALID_ROUTE_SOURCES:
            raise ValueError("路线来源不合法")
        if self.source == "straight_line_estimation" and self.verified:
            raise ValueError("直线估算路线不能标记为已验证")
        if not self.verified and not self.warning:
            raise ValueError("未验证路线必须提供提示信息")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RouteInfo":
        """从字典构造路线模型"""
        return cls(
            origin_place_id=str(data["origin_place_id"]),
            destination_place_id=str(data["destination_place_id"]),
            distance_meters=float(data["distance_meters"]),
            duration_minutes=float(data["duration_minutes"]),
            source=str(data["source"]),
            verified=bool(data["verified"]),
            polyline=[tuple(point) for point in data.get("polyline", [])],
            warning=data.get("warning"),
        )

    def to_dict(self) -> dict[str, Any]:
        """转换为接口可直接返回的字典"""
        return {
            "origin_place_id": self.origin_place_id,
            "destination_place_id": self.destination_place_id,
            "distance_meters": self.distance_meters,
            "duration_minutes": self.duration_minutes,
            "source": self.source,
            "verified": self.verified,
            "polyline": [list(point) for point in self.polyline],
            "warning": self.warning,
        }


RouteResult = RouteInfo

__all__ = [
    "RouteInfo",
    "RouteRequest",
    "RouteResult",
]

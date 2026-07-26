"""旅游资源地点数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

VALID_PLACE_TYPES = {"attraction", "hotel", "restaurant"}


@dataclass(frozen=True)
class Coordinate:
    """地点经纬度坐标"""

    longitude: float
    latitude: float

    def __post_init__(self) -> None:
        """校验经纬度是否在合理范围内"""

        if not -180 <= self.longitude <= 180:
            raise ValueError("经度必须在 -180 到 180 之间")
        if not -90 <= self.latitude <= 90:
            raise ValueError("纬度必须在 -90 到 90 之间")

    def to_dict(self) -> dict[str, float]:
        """转换为接口可直接返回的字典。"""

        return {
            "longitude": self.longitude,
            "latitude": self.latitude,
        }


@dataclass(frozen=True)
class Place:
    """景点、酒店、餐厅等旅游资源统一格式"""

    place_id: str
    name: str
    place_type: str
    city: str
    area: str
    coordinate: Coordinate
    tags: list[str] = field(default_factory=list)
    price: float | None = None
    open_time: str | None = None
    description: str = ""
    suitable_for: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        """校验地点的必要字段和基础事实格式。"""
        if not self.place_id.strip():
            raise ValueError("地点编号不能为空")
        if not self.name.strip():
            raise ValueError("地点名称不能为空")
        if self.place_type not in VALID_PLACE_TYPES:
            raise ValueError("地点类型必须是景点、酒店或餐厅之一")
        if not self.city.strip():
            raise ValueError("城市不能为空")
        if not self.area.strip():
            raise ValueError("区域不能为空")
        if self.price is not None and self.price < 0:
            raise ValueError("价格不能为负数")
        if not isinstance(self.coordinate, Coordinate):
            raise TypeError("坐标必须使用 Coordinate 模型")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Place":
        """从字典构造地点模型。"""
        coordinate_data = data.get("coordinate", {})
        coordinate = Coordinate(
            longitude=float(coordinate_data["longitude"]),
            latitude=float(coordinate_data["latitude"]),
        )
        return cls(
            place_id=str(data["place_id"]),
            name=str(data["name"]),
            place_type=str(data["place_type"]),
            city=str(data["city"]),
            area=str(data["area"]),
            coordinate=coordinate,
            tags=list(data.get("tags", [])),
            price=data.get("price"),
            open_time=data.get("open_time"),
            description=str(data.get("description", "")),
            suitable_for=list(data.get("suitable_for", [])),
        )

    def to_dict(self) -> dict[str, Any]:
        """转换为接口和测试都能复用的字典"""
        return {
            "place_id": self.place_id,
            "name": self.name,
            "place_type": self.place_type,
            "city": self.city,
            "area": self.area,
            "coordinate": self.coordinate.to_dict(),
            "tags": list(self.tags),
            "price": self.price,
            "open_time": self.open_time,
            "description": self.description,
            "suitable_for": list(self.suitable_for),
        }

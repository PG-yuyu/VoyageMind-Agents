"""兴趣点匹配数据模型。"""

from __future__ import annotations

from dataclasses import dataclass

from .place import Coordinate


@dataclass(frozen=True)
class POICandidate:
    """地图服务返回的候选"""

    poi_id: str
    name: str
    city: str
    address: str
    coordinate: Coordinate
    verified: bool = False

    def __post_init__(self) -> None:
        """校验兴趣点候选的必要字段"""
        if not self.poi_id.strip():
            raise ValueError("POI编号不能为空")
        if not self.name.strip():
            raise ValueError("POI名称不能为空")
        if not self.city.strip():
            raise ValueError("POI城市不能为空")
        if not self.address.strip():
            raise ValueError("POI地址不能为空")


__all__ = ["POICandidate"]

"""旅游资源数据仓库。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..database.seed_loader import DEFAULT_DATA_DIR, load_all_resources
from ..schemas import Place


@dataclass(frozen=True)
class PlaceQuery:
    """旅游资源查询条件。"""

    city: str | None = None
    place_type: str | None = None
    tags: list[str] | None = None
    area: str | None = None
    min_price: float | None = None
    max_price: float | None = None


VALID_PLACE_TYPES = {"attraction", "hotel", "restaurant"}


class PlaceRepository:
    """从本地样例数据中读取并筛选旅游资源。"""

    def __init__(self, data_dir: Path = DEFAULT_DATA_DIR) -> None:
        """初始化数据目录。"""

        self.data_dir = data_dir

    def list_all(self) -> list[Place]:
        """返回全部景点、酒店和餐厅资源。"""

        resources = load_all_resources(self.data_dir)
        all_places: list[Place] = []
        for items in resources.values():
            all_places.extend(items)
        return all_places

    def list_attractions(self) -> list[Place]:
        """返回全部景点资源。"""

        return load_all_resources(self.data_dir)["景点"]

    def list_hotels(self) -> list[Place]:
        """返回全部酒店资源。"""

        return load_all_resources(self.data_dir)["酒店"]

    def list_restaurants(self) -> list[Place]:
        """返回全部餐厅资源。"""

        return load_all_resources(self.data_dir)["餐厅"]

    def list_by_type(self, place_type: str) -> list[Place]:
        """按资源类型返回对应候选资源。"""

        if place_type not in VALID_PLACE_TYPES:
            raise ValueError("资源类型必须是景点、酒店或餐厅之一")

        if place_type == "attraction":
            return self.list_attractions()
        if place_type == "hotel":
            return self.list_hotels()
        return self.list_restaurants()

    def get_by_id(self, place_id: str) -> Place | None:
        """按地点编号查找资源，找不到时返回 None。"""

        for place in self.list_all():
            if place.place_id == place_id:
                return place
        return None

    def search(self, query: PlaceQuery) -> list[Place]:
        """按城市、类型、标签、区域和价格范围筛选候选资源。"""

        places = (
            self.list_by_type(query.place_type) if query.place_type else self.list_all()
        )
        return [place for place in places if self._matches(place, query)]

    def _matches(self, place: Place, query: PlaceQuery) -> bool:
        """判断单个地点是否满足查询条件。"""

        if query.city and place.city != query.city:
            return False
        if query.place_type and place.place_type != query.place_type:
            return False
        if query.area and place.area != query.area:
            return False
        if query.tags and not set(query.tags).intersection(set(place.tags)):
            return False
        if query.min_price is not None and (
            place.price is None or place.price < query.min_price
        ):
            return False
        if query.max_price is not None and (
            place.price is None or place.price > query.max_price
        ):
            return False
        return True


__all__ = ["PlaceQuery", "PlaceRepository"]

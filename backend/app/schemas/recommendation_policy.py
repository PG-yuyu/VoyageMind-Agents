"""推荐策略数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field


VALID_POLICY_PLACE_TYPES = {"attraction", "hotel", "restaurant"}


@dataclass(frozen=True)
class ResourceFilterPolicy:
    """单类旅游资源的过滤方向。"""

    place_type: str
    tags: list[str] = field(default_factory=list)
    area: str | None = None
    min_price: float | None = None
    max_price: float | None = None

    def __post_init__(self) -> None:
        """校验过滤方向能被后续资源查询服务理解。"""

        if self.place_type not in VALID_POLICY_PLACE_TYPES:
            raise ValueError("策略资源类型必须是景点、酒店或餐厅之一")
        if self.area is not None and not self.area.strip():
            raise ValueError("区域过滤条件不能为空字符串")
        if self.min_price is not None and self.min_price < 0:
            raise ValueError("最低价格不能为负数")
        if self.max_price is not None and self.max_price < 0:
            raise ValueError("最高价格不能为负数")
        if (
            self.min_price is not None
            and self.max_price is not None
            and self.min_price > self.max_price
        ):
            raise ValueError("最低价格不能大于最高价格")
        for tag in self.tags:
            if not tag.strip():
                raise ValueError("标签过滤条件不能为空字符串")


@dataclass(frozen=True)
class RecommendationPolicy:
    """推荐策略摘要，只描述筛选方向，不包含最终资源结果。"""

    focus: list[str] = field(default_factory=list)
    filters: list[ResourceFilterPolicy] = field(default_factory=list)
    preference_notes: list[str] = field(default_factory=list)
    budget_direction: str = "均衡预算"
    people_direction: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        """校验推荐策略至少包含一个推荐重点。"""

        if not self.focus:
            raise ValueError("推荐策略至少需要一个推荐重点")
        for item in self.focus:
            if not item.strip():
                raise ValueError("推荐重点不能为空字符串")
        for item in self.filters:
            if not isinstance(item, ResourceFilterPolicy):
                raise TypeError("过滤条件必须使用 ResourceFilterPolicy 模型")
        for note in self.preference_notes:
            if not note.strip():
                raise ValueError("偏好说明不能为空字符串")
        if not self.budget_direction.strip():
            raise ValueError("预算倾向不能为空")
        for item in self.people_direction:
            if not item.strip():
                raise ValueError("人群偏好不能为空字符串")


__all__ = [
    "RecommendationPolicy",
    "ResourceFilterPolicy",
    "VALID_POLICY_PLACE_TYPES",
]

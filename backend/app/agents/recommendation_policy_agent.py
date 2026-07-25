"""推荐策略 Agent。"""

from __future__ import annotations

from typing import Iterable

from backend.app.schemas import (
    RecommendationContext,
    RecommendationPolicy,
    ResourceFilterPolicy,
)


ATTRACTION_TAG_KEYWORDS = [
    "历史文化",
    "博物馆",
    "园林",
    "胡同",
    "城市漫步",
    "本地生活",
    "经典景点",
]
HOTEL_TAG_KEYWORDS = ["交通方便", "经济型", "中等预算", "靠近景点", "适合学生"]
RESTAURANT_TAG_KEYWORDS = ["本地风味", "小吃", "老字号", "家常菜", "经济型"]
BUDGET_FRIENDLY_WORDS = ["预算不要太高", "不要太高", "便宜", "经济", "省钱", "学生"]


class RecommendationPolicyAgent:
    """把推荐上下文转换为可执行的资源推荐策略。"""

    def generate_policy(self, context: RecommendationContext) -> RecommendationPolicy:
        """生成推荐策略，不查询候选资源，也不返回最终推荐结果。"""

        if not isinstance(context, RecommendationContext):
            raise TypeError("策略 Agent 只能处理 RecommendationContext")

        return RecommendationPolicy(
            focus=self._build_focus(context),
            filters=self._build_filters(context),
            preference_notes=self._build_preference_notes(context),
            budget_direction=self._infer_budget_direction(context),
            people_direction=self._infer_people_direction(context),
        )

    def _build_focus(self, context: RecommendationContext) -> list[str]:
        """根据城市、天数、兴趣和语义偏好生成推荐重点。"""

        requirements = context.requirements
        focus = [
            f"{requirements.city}{requirements.days}日游资源策略",
            "覆盖景点、酒店、餐厅三类候选资源",
        ]
        for interest in requirements.interests:
            focus.append(f"优先围绕{interest}资源")
        for place_name in requirements.must_visit:
            focus.append(f"保留必去地点线索：{place_name}")
        for preference in context.semantic_preferences:
            focus.append(f"响应用户偏好：{preference.text}")
        if "毕业" in context.original_text:
            focus.append("兼顾毕业旅行的纪念感和同行体验")
        if "学生" in context.original_text:
            focus.append("优先考虑学生群体的预算和便利性")
        return self._unique(focus)

    def _build_filters(self, context: RecommendationContext) -> list[ResourceFilterPolicy]:
        """为景点、酒店、餐厅分别生成过滤方向。"""

        requirements = context.requirements
        attraction_tags = self._unique(
            [
                *requirements.interests,
                *self._keywords_from_text(context.original_text, ATTRACTION_TAG_KEYWORDS),
                *self._scoped_preference_keywords(
                    context,
                    {"attraction", "景点", "overall", "all"},
                    ATTRACTION_TAG_KEYWORDS,
                ),
            ]
        )
        hotel_tags = self._unique(
            [
                *self._keywords_from_text(context.original_text, HOTEL_TAG_KEYWORDS),
                *self._scoped_preference_keywords(
                    context,
                    {"hotel", "酒店", "overall", "all"},
                    HOTEL_TAG_KEYWORDS,
                ),
            ]
        )
        restaurant_tags = self._unique(
            [
                *requirements.food_preferences,
                *self._keywords_from_text(context.original_text, RESTAURANT_TAG_KEYWORDS),
                *self._scoped_preference_keywords(
                    context,
                    {"restaurant", "餐厅", "food", "餐饮", "overall", "all"},
                    RESTAURANT_TAG_KEYWORDS,
                ),
            ]
        )

        if self._is_budget_friendly(context):
            hotel_tags = self._unique([*hotel_tags, "经济型", "交通方便"])
            restaurant_tags = self._unique([*restaurant_tags, "经济型"])

        return [
            ResourceFilterPolicy(
                place_type="attraction",
                tags=attraction_tags,
                area=self._infer_area(context, "attraction"),
            ),
            ResourceFilterPolicy(
                place_type="hotel",
                tags=hotel_tags,
                area=self._infer_area(context, "hotel"),
                max_price=self._infer_hotel_max_price(context),
            ),
            ResourceFilterPolicy(
                place_type="restaurant",
                tags=restaurant_tags,
                area=self._infer_area(context, "restaurant"),
                max_price=context.requirements.meal_budget_per_person,
            ),
        ]

    def _build_preference_notes(self, context: RecommendationContext) -> list[str]:
        """整理后续推荐流程需要保留的用户偏好说明。"""

        requirements = context.requirements
        notes = [
            f"目标城市：{requirements.city}",
            f"旅行天数：{requirements.days}天",
            f"出行人数：{requirements.people}人",
        ]
        if requirements.total_budget is not None:
            notes.append(f"总预算约束：{requirements.total_budget}元")
        if requirements.food_preferences:
            notes.append(f"餐饮偏好：{'、'.join(requirements.food_preferences)}")
        if requirements.food_avoidances:
            notes.append(f"餐饮禁忌：{'、'.join(requirements.food_avoidances)}")
        if requirements.avoid_places:
            notes.append(f"需要避开：{'、'.join(requirements.avoid_places)}")
        for constraint in context.explicit_hard_constraints:
            notes.append(f"硬约束：{constraint.source_text}")
        for preference in context.semantic_preferences:
            notes.append(f"{preference.scope}偏好：{preference.text}")
        if self._is_budget_friendly(context):
            notes.append("预算控制优先，避免过高消费资源")
        if "毕业" in context.original_text:
            notes.append("毕业旅行需要兼顾纪念感、轻松度和同行体验")
        return self._unique(notes)

    def _infer_budget_direction(self, context: RecommendationContext) -> str:
        """根据预算字段和原文判断预算倾向。"""

        requirements = context.requirements
        if self._is_budget_friendly(context):
            return "预算友好"
        if requirements.total_budget is None:
            return "均衡预算"

        people = max(requirements.people, 1)
        days = max(requirements.days or 1, 1)
        daily_budget = requirements.total_budget / people / days
        if daily_budget <= 250:
            return "预算友好"
        if daily_budget <= 800:
            return "均衡预算"
        return "舒适优先"

    def _infer_people_direction(self, context: RecommendationContext) -> list[str]:
        """根据人数和原文判断适合人群方向。"""

        requirements = context.requirements
        directions: list[str] = []
        if requirements.people == 1:
            directions.append("单人出行")
        elif requirements.people >= 4:
            directions.append("多人同行")
        else:
            directions.append("双人或小团体")

        text = context.original_text
        keyword_map = {
            "学生": "学生",
            "毕业": "毕业旅行",
            "家庭": "家庭游客",
            "亲子": "亲子游客",
            "朋友": "朋友出游",
            "情侣": "情侣出游",
        }
        for keyword, direction in keyword_map.items():
            if keyword in text:
                directions.append(direction)
        return self._unique(directions)

    def _infer_hotel_max_price(self, context: RecommendationContext) -> float | None:
        """只在用户明确给出酒店每晚预算时生成酒店价格上限。"""

        requirements = context.requirements
        if requirements.hotel_budget_per_night is not None:
            return float(requirements.hotel_budget_per_night)
        return None

    def _infer_area(self, context: RecommendationContext, place_type: str) -> str | None:
        """从硬约束中提取区域过滤条件。"""

        for constraint in context.explicit_hard_constraints:
            field = constraint.field.lower()
            scope = constraint.scope.lower()
            if field in {"area", "district", "区域", "商圈"} and scope in {
                place_type,
                "overall",
                "all",
            }:
                return str(constraint.value)
        return None

    def _is_budget_friendly(self, context: RecommendationContext) -> bool:
        """判断用户是否表达了预算友好倾向。"""

        text_parts = [
            context.original_text,
            *context.conversation_context,
            *(preference.text for preference in context.semantic_preferences),
            *(constraint.source_text for constraint in context.explicit_hard_constraints),
        ]
        text = " ".join(text_parts)
        return any(word in text for word in BUDGET_FRIENDLY_WORDS)

    def _scoped_preference_keywords(
        self,
        context: RecommendationContext,
        scopes: set[str],
        keywords: list[str],
    ) -> list[str]:
        """提取指定作用范围内的偏好关键词。"""

        results: list[str] = []
        for preference in context.semantic_preferences:
            if preference.scope in scopes:
                results.extend(self._keywords_from_text(preference.text, keywords))
        return results

    @staticmethod
    def _keywords_from_text(text: str, keywords: list[str]) -> list[str]:
        """从文本中提取已知标签关键词。"""

        return [keyword for keyword in keywords if keyword in text]

    @staticmethod
    def _unique(items: Iterable[str]) -> list[str]:
        """按出现顺序去重并丢弃空字符串。"""

        results: list[str] = []
        seen: set[str] = set()
        for item in items:
            normalized = item.strip()
            if normalized and normalized not in seen:
                results.append(normalized)
                seen.add(normalized)
        return results


__all__ = ["RecommendationPolicyAgent"]

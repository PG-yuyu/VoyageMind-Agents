import re

from backend.schemas import Assumption, RequirementExtractionResult, TravelRequest

CITY_NAMES = ["天津"]
INTEREST_WORDS = [
    "近代建筑",
    "博物馆",
    "美食",
    "购物",
    "亲子",
    "夜景",
    "海河",
    "老街",
    "民俗",
    "滨海",
]
FOOD_WORDS = ["天津菜", "清淡", "素食", "煎饼果子", "锅巴菜", "熟梨糕", "八珍豆腐"]

# 区域关键词 → 标准化区域名映射
# 用户口语化区域词会映射到 places.json 中的 area 字段值
AREA_KEYWORD_MAP = {
    "滨海": "滨海新区",
    "滨海新区": "滨海新区",
    "塘沽": "滨海新区",
    "市中心": "和平区",
    "市区": "和平区",
    "和平": "和平区",
    "河西": "河西区",
    "南开": "南开区",
    "河北": "河北区",
    "河东": "河东区",
    "红桥": "红桥区",
    "西青": "西青区",
    "津南": "津南区",
    "东丽": "东丽区",
    "北辰": "北辰区",
    "武清": "武清区",
    "宝坻": "宝坻区",
    "静海": "静海区",
    "宁河": "宁河区",
    "蓟州": "蓟州区",
}

# "不想在市中心" → 需要排除的市中心各区
CITY_CENTER_AREAS = ["和平区", "河西区", "南开区", "河北区", "河东区", "红桥区"]


class RequirementService:
    def extract(
        self,
        session_id: str,
        message: str,
        existing: TravelRequest | None = None,
    ) -> RequirementExtractionResult:
        request = (
            existing.model_copy(deep=True)
            if existing
            else TravelRequest(session_id=session_id)
        )
        request.session_id = session_id

        city = next((name for name in CITY_NAMES if name in message), None)
        if city:
            request.city = city
        elif not request.city:
            request.city = "天津"

        day_match = re.search(r"(\d+)\s*[天日]", message)
        chinese_days = {"一": 1, "两": 2, "二": 2, "三": 3}
        if day_match:
            request.days = int(day_match.group(1))
        else:
            for word, value in chinese_days.items():
                if f"{word}日" in message or f"{word}天" in message:
                    request.days = value

        people_match = re.search(r"(\d+)\s*(个人|人)", message)
        if people_match:
            request.people = int(people_match.group(1))

        budget_match = re.search(r"预算\s*(\d+)|(\d+)\s*元", message)
        if budget_match:
            request.total_budget = int(
                next(group for group in budget_match.groups() if group)
            )

        interests = [word for word in INTEREST_WORDS if word in message]
        if interests:
            request.interests = sorted(set(request.interests + interests))

        foods = [word for word in FOOD_WORDS if word in message]
        if foods:
            request.food_preferences = sorted(set(request.food_preferences + foods))

        must_visit = []
        for name in [
            "五大道",
            "五大道文化旅游区",
            "天津之眼",
            "古文化街",
            "瓷房子",
            "意式风情区",
            "天津博物馆",
            "海河",
        ]:
            if name in message and any(
                prefix in message for prefix in ["必去", "一定去", "想去", "喜欢"]
            ):
                must_visit.append("五大道文化旅游区" if name == "五大道" else name)
        if must_visit:
            request.must_visit = sorted(set(request.must_visit + must_visit))

        # ── 区域偏好提取 ──────────────────────────────────
        # "在XX部分" / "在XX区" / "想去XX区" → preferred_areas
        preferred_areas = self._extract_preferred_areas(message)
        if preferred_areas:
            request.preferred_areas = sorted(
                set(request.preferred_areas + preferred_areas)
            )

        # ── 区域回避提取 ──────────────────────────────────
        # "不想在XX" / "不在XX" / "不去XX区" → avoid_areas
        avoid_areas = self._extract_avoid_areas(message)
        if avoid_areas:
            request.avoid_areas = sorted(set(request.avoid_areas + avoid_areas))

        # 同时把区域回避加入 avoid_places 以保证下游可见
        if avoid_areas:
            request.avoid_places = sorted(set(request.avoid_places + avoid_areas))

        walk_match = re.search(
            r"步行.*?(\d+)\s*(公里|km|千米)", message, re.IGNORECASE
        )
        if walk_match:
            request.walking_limit_m = int(walk_match.group(1)) * 1000

        assumptions = [
            Assumption(
                field="transport_modes",
                value=request.transport_modes,
                reason="用户未指定交通方式，默认步行加公共交通",
            ),
            Assumption(
                field="daily_start_time",
                value=request.daily_start_time,
                reason="用户未指定每日出发时间，使用默认 09:00",
            ),
        ]

        missing_fields = []
        if not request.days:
            missing_fields.append("days")

        follow_up = None
        if "days" in missing_fields:
            follow_up = "计划玩几天？"

        return RequirementExtractionResult(
            requirements=request,
            missing_fields=missing_fields,
            assumptions=assumptions,
            need_follow_up=bool(missing_fields),
            follow_up_question=follow_up,
        )

    @staticmethod
    def _extract_preferred_areas(message: str) -> list[str]:
        """从用户输入中提取偏好的区域。

        匹配模式：
        - "在XX部分" → 如"在滨海部分" → 滨海新区
        - "在XX区" / "想去XX区"
        - 直接提及区域关键词
        """
        areas: list[str] = []

        # 模式 1："在XX部分" / "XX部分"
        part_match = re.findall(r"在?\s*(\S+?)部分", message)
        for keyword in part_match:
            mapped = AREA_KEYWORD_MAP.get(keyword)
            if mapped and mapped not in areas:
                areas.append(mapped)

        # 模式 2：直接匹配区域关键词
        for keyword, mapped in AREA_KEYWORD_MAP.items():
            if keyword in message and mapped not in areas:
                # 排除否定语境："不想在XX" / "不在XX"
                if not re.search(
                    rf"(?:不想在|不在|不去|不选|避开|排除)\s*{keyword}", message
                ):
                    areas.append(mapped)

        return areas

    @staticmethod
    def _extract_avoid_areas(message: str) -> list[str]:
        """从用户输入中提取需要回避的区域。

        匹配模式：
        - "不想在XX" / "不在XX" / "不去XX"
        - "避开XX" / "排除XX"
        - "市中心" → 映射到全部中心城区
        """
        areas: list[str] = []

        # 模式 1："不想在XX" / "不在XX" / "不去XX"
        avoid_match = re.findall(
            r"(?:不想在|不在|不去|不选|避开|排除)\s*(\S+?)(?:[，。,\.\s]|$)", message
        )
        for keyword in avoid_match:
            keyword_clean = keyword.strip()
            if keyword_clean == "市中心" or keyword_clean == "市区":
                # "不想在市中心" → 排除所有中心城区
                for area in CITY_CENTER_AREAS:
                    if area not in areas:
                        areas.append(area)
            else:
                mapped = AREA_KEYWORD_MAP.get(keyword_clean)
                if mapped and mapped not in areas:
                    areas.append(mapped)

        return areas

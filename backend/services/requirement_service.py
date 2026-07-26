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

        walk_match = re.search(r"步行.*?(\d+)\s*(公里|km|千米)", message, re.IGNORECASE)
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

from backend.schemas import RequirementExtractionResult, TravelRequest
from backend.services.chatbot_service import ChatbotService
from backend.services.requirement_service import RequirementService


class RequirementAdapter:
    """需求提取适配器。

    新分工下，成员一核心交付是 CoordinatorAgent 和 IntentAgent。
    需求提取作为总控工作流需要调用的公共能力保留，方便向成员二、成员三输出
    TravelRequest，但不再作为成员一负责的独立 Agent 展示。
    """

    def __init__(self, chatbot_service: ChatbotService | None = None) -> None:
        """初始化需求适配器。

        RequirementService 负责规则抽取，ChatbotService 负责补充自然语言里的隐含字段。
        两者组合后向后续推荐、规划模块输出统一的 TravelRequest。
        """
        self.requirement_service = RequirementService()
        self.chatbot_service = chatbot_service or ChatbotService()

    def extract(
        self,
        session_id: str,
        message: str,
        existing_requirements: TravelRequest | None = None,
    ) -> RequirementExtractionResult:
        """从用户消息中抽取或补全旅行需求。

        先调用规则抽取器得到稳定结果，再让 Chatbot 尝试识别天数、预算、人数、
        兴趣、区域偏好和步行限制等字段；最后合并两份结果并判断是否还缺少关键字段。
        返回值会告诉总控是否需要追问，以及追问哪一个问题。
        """
        rule_result = self.requirement_service.extract(
            session_id, message, existing_requirements
        )
        ai_payload = self.chatbot_service.chat_json(
            system_prompt=(
                "你是天津自由行智能规划系统的需求抽取器，只处理天津旅行。"
                "请从用户自然语言中抽取 TravelRequest 字段，只输出 JSON。"
                "能明确推断的隐藏含义也要抽取，例如“天津2天游，预算1800元”"
                "应输出 days=2、total_budget=1800、city=天津。"
                "不要编造用户没说的硬约束。"
            ),
            user_prompt=(
                "返回 JSON 格式："
                '{"city":null或"天津","days":整数或null,"people":整数或null,'
                '"total_budget":整数或null,"interests":[],"must_visit":[],'
                '"avoid_places":[],"preferred_areas":[],"avoid_areas":[],'
                '"food_preferences":[],"food_avoidances":[],"transport_modes":[],'
                '"walking_limit_m":整数或null,"daily_start_time":null或"HH:MM",'
                '"daily_end_time":null或"HH:MM","travel_pace":null或'
                '\\"relaxed|normal|compact\\"}\n'
                "注意：preferred_areas 是用户想去的区域（如滨海新区），"
                "avoid_areas 是用户不想去的区域（如和平区=市中心），"
                "avoid_places 是用户明确不去的具体地点。"
                "如果用户说\"不想在市中心\"，avoid_areas 应包含市中心对应的区。\n"
                f"用户输入：{message}"
            ),

            fallback={},
        )
        requirements = self._merge_ai_payload(rule_result.requirements, ai_payload)
        missing_fields = self._missing_fields(requirements)
        return RequirementExtractionResult(
            requirements=requirements,
            missing_fields=missing_fields,
            assumptions=rule_result.assumptions,
            need_follow_up=bool(missing_fields),
            follow_up_question=self._follow_up_question(missing_fields),
        )

    def _merge_ai_payload(
        self, request: TravelRequest, payload: dict
    ) -> TravelRequest:
        """把模型抽取结果合并到规则抽取出的 TravelRequest。

        只接受 TravelRequest 支持的字段，并对数字、字符串和列表做基础类型转换。
        城市字段限定为天津相关输入，travel_pace 限定为 relaxed/normal/compact，
        避免模型把无关城市或非法枚举写入主流程。
        """
        if not payload:
            return request

        nested_requirements = payload.get("requirements")
        data = nested_requirements if isinstance(nested_requirements, dict) else payload
        if not isinstance(data, dict):
            return request
        merged = request.model_copy(deep=True)
        scalar_fields = {
            "city": str,
            "start_date": str,
            "days": int,
            "people": int,
            "total_budget": int,
            "hotel_budget_per_night": int,
            "meal_budget_per_person": int,
            "walking_limit_m": int,
            "daily_start_time": str,
            "daily_end_time": str,
            "travel_pace": str,
        }
        aliases = {
            "days": ["days", "travel_days", "duration_days", "day_count"],
            "total_budget": ["total_budget", "budget", "budget_yuan", "total_cost"],
            "people": ["people", "traveler_count", "participants"],
            "walking_limit_m": ["walking_limit_m", "walk_limit_m", "max_walking_m"],
        }

        for field, caster in scalar_fields.items():
            value = self._first_value(data, aliases.get(field, [field]))
            if value in (None, "", []):
                continue
            try:
                normalized = caster(value)
            except (TypeError, ValueError):
                continue
            if field == "city" and "天津" not in normalized:
                continue
            if field == "travel_pace" and normalized not in {"relaxed", "normal", "compact"}:
                continue
            setattr(merged, field, normalized)

        for field in [
            "interests",
            "must_visit",
            "avoid_places",
            "preferred_areas",
            "avoid_areas",
            "food_preferences",
            "food_avoidances",
            "transport_modes",
        ]:
            values = self._list_value(data.get(field))
            if values:
                setattr(merged, field, sorted(set(getattr(merged, field) + values)))

        if not merged.city:
            merged.city = "天津"
        return merged

    @staticmethod
    def _first_value(data: dict, keys: list[str]):
        """按别名顺序读取第一个存在的字段值。

        模型可能返回 days、travel_days、duration_days 等不同字段名，
        这个方法把这些同义字段统一映射到 TravelRequest 的标准字段。
        """
        for key in keys:
            if key in data:
                return data[key]
        return None

    @staticmethod
    def _list_value(value) -> list[str]:
        """把模型输出归一化成字符串列表。

        支持模型返回 list 或单个字符串；空字符串、空列表和无法表达偏好的值会被过滤掉。
        """
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return []

    @staticmethod
    def _missing_fields(request: TravelRequest) -> list[str]:
        """检查当前规划必须补齐的关键字段。

        目前规划流程至少需要天数和总预算；缺失字段会用于决定是否继续追问用户。
        """
        missing_fields = []
        if not request.days:
            missing_fields.append("days")
        if not request.total_budget:
            missing_fields.append("total_budget")
        return missing_fields

    @staticmethod
    def _follow_up_question(missing_fields: list[str]) -> str | None:
        """根据缺失字段生成一句面向用户的追问。

        只缺一个字段时精准追问；天数和预算都缺时合并成一个问题，减少对话轮次。
        字段完整时返回 None，表示可以进入推荐和规划阶段。
        """
        if missing_fields == ["days"]:
            return "计划玩几天？"
        if missing_fields == ["total_budget"]:
            return "这次天津旅行的大概预算是多少？"
        if missing_fields:
            return "计划玩几天？大概预算是多少？"
        return None

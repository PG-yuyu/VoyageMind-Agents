from backend.schemas import IntentResult
from backend.services.chatbot_service import ChatbotService
from backend.services.intent_service import IntentService


class IntentAgent:
    """三类一级意图识别 Agent。

    输出严格对齐接口文档中的 IntentResult：
    create_trip / modify_trip / travel_qa。

    优先通过改进封装后的 Chatbot 判断意图；Chatbot 不可用或返回非法结构时，
    才使用规则兜底，保证联调阶段稳定。
    """

    def __init__(self, chatbot_service: ChatbotService | None = None) -> None:
        self.intent_service = IntentService()
        self.chatbot_service = chatbot_service or ChatbotService()

    def run(self, message: str) -> IntentResult:
        fallback = self.intent_service.detect(message)
        if self._is_smalltalk(message):
            return fallback
        result = self.chatbot_service.chat_json(
            system_prompt=(
                "你是天津自由行智能规划系统的意图识别 Agent，本项目只处理天津旅游。"
                "你只能输出 JSON，不要解释。一级意图只能是 create_trip、modify_trip、travel_qa。"
                "修改子意图只能是 replace_attraction、delete_place、replace_restaurant、"
                "change_hotel、change_budget、change_time、reduce_walking、change_to_indoor 或 null。"
            ),
            user_prompt=(
                "请识别用户输入的旅行意图，返回 JSON："
                '{"intent":"create_trip|modify_trip|travel_qa",'
                '"confidence":0.0到1.0,'
                '"sub_intent":null或修改子意图,'
                '"original_text":"原文"}\n'
                f"用户输入：{message}"
            ),
            fallback=fallback.model_dump(),
        )
        return self._normalize_result(result, fallback, message)

    def _normalize_result(
        self, result: dict, fallback: IntentResult, message: str
    ) -> IntentResult:
        valid_intents = {"create_trip", "modify_trip", "travel_qa"}
        valid_sub_intents = {
            "replace_attraction",
            "delete_place",
            "replace_restaurant",
            "change_hotel",
            "change_budget",
            "change_time",
            "reduce_walking",
            "change_to_indoor",
            None,
        }
        try:
            confidence = float(result.get("confidence", fallback.confidence))
        except (TypeError, ValueError):
            confidence = fallback.confidence
        intent = result.get("intent")
        sub_intent = result.get("sub_intent")
        if intent not in valid_intents or sub_intent not in valid_sub_intents:
            return fallback
        if confidence < 0.6 and fallback.confidence >= confidence:
            return fallback
        return IntentResult(
            intent=intent,
            confidence=max(0.0, min(confidence, 1.0)),
            sub_intent=sub_intent,
            original_text=result.get("original_text") or message,
        )

    def _is_smalltalk(self, message: str) -> bool:
        text = message.strip().lower()
        return text in {"你好", "您好", "hi", "hello", "嗨", "你猜"} or len(text) <= 2

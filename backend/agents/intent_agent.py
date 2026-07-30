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
        """初始化意图识别 Agent。

        创建规则意图识别服务作为稳定兜底，同时接收可注入的 ChatbotService，
        方便测试或总控工作流复用同一个模型封装，避免重复加载模型配置。
        """
        self.intent_service = IntentService()
        self.chatbot_service = chatbot_service or ChatbotService()

    def run(self, message: str) -> IntentResult:
        """识别用户消息的一二级意图。

        先用规则服务得到 fallback，保证模型不可用时也能分流；短寒暄直接返回规则结果。
        其他输入交给 Chatbot 输出 JSON，再通过 _normalize_result 做合法性校验，
        最终返回 create_trip / modify_trip / travel_qa 之一。
        """
        fallback = self.intent_service.detect(message)
        if self._is_smalltalk(message):
            return fallback
        # 先让模型处理自然语言里的隐含意图；规则结果作为稳定兜底，避免模型异常影响主流程分发。
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
        """校验并归一化模型返回的意图 JSON。

        只接受白名单内的一级意图和修改子意图；置信度无法转换或过低时使用规则结果。
        这样可以防止模型输出拼写错误、未知标签或低置信度判断污染后续工作流。
        """
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
        # 低置信度时优先保留规则判断，减少把问答误分到规划或修改流程的情况。
        if confidence < 0.6 and fallback.confidence >= confidence:
            return fallback
        return IntentResult(
            intent=intent,
            confidence=max(0.0, min(confidence, 1.0)),
            sub_intent=sub_intent,
            original_text=result.get("original_text") or message,
        )

    def _is_smalltalk(self, message: str) -> bool:
        """判断输入是否只是寒暄或过短文本。

        这类文本信息量不足，不值得调用大模型识别旅行意图，直接走规则兜底即可。
        """
        text = message.strip().lower()
        return text in {"你好", "您好", "hi", "hello", "嗨", "你猜"} or len(text) <= 2

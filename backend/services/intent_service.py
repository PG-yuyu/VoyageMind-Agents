from backend.schemas import IntentResult


class IntentService:
    modification_words = {
        "减少步行": "reduce_walking",
        "室内": "change_to_indoor",
        "餐厅": "replace_restaurant",
        "酒店": "change_hotel",
        "预算": "change_budget",
        "降低": "change_budget",
        "提高": "change_budget",
        "删除": "delete_place",
        "换": "replace_attraction",
        "改": "change_time",
        "调整": "change_budget",
    }

    qa_words = ["有哪些", "注意事项", "为什么", "介绍", "历史", "来源", "依据", "怎么去", "开放时间"]
    create_words = ["规划", "安排", "生成", "旅游", "行程", "几日游", "自由行"]

    def detect(self, message: str) -> IntentResult:
        text = message.strip()
        sub_intent = None

        if "删除" in text:
            return IntentResult(
                intent="modify_trip",
                confidence=0.9,
                sub_intent="delete_place",
                original_text=text,
            )

        if "预算" in text and any(word in text for word in ["改", "调整", "降低", "提高", "降到", "改成"]):
            return IntentResult(
                intent="modify_trip",
                confidence=0.9,
                sub_intent="change_budget",
                original_text=text,
            )

        has_create_signal = any(word in text for word in self.create_words)
        has_change_signal = any(word in text for word in ["换", "改", "调整", "降低", "提高", "降到", "删除", "减少"])

        for keyword, value in self.modification_words.items():
            if keyword in text and has_change_signal and not (has_create_signal and "改" not in text):
                sub_intent = value
                return IntentResult(
                    intent="modify_trip",
                    confidence=0.88,
                    sub_intent=sub_intent,
                    original_text=text,
                )

        if any(word in text for word in self.qa_words) and not any(word in text for word in ["规划", "生成"]):
            return IntentResult(intent="travel_qa", confidence=0.84, original_text=text)

        if any(word in text for word in self.create_words):
            return IntentResult(intent="create_trip", confidence=0.9, original_text=text)

        return IntentResult(intent="travel_qa", confidence=0.58, original_text=text)

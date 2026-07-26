from backend.agents.intent_agent import IntentAgent
from backend.services.requirement_adapter import RequirementAdapter
from backend.services.intent_service import IntentService


class FakeLowConfidenceChatbot:
    available = True
    engine = object()

    def chat_json(self, system_prompt: str, user_prompt: str, fallback: dict):
        return {
            "intent": "travel_qa",
            "confidence": 0.1,
            "sub_intent": None,
            "original_text": "天津2天游，预算1800元",
        }


class FakeRequirementChatbot:
    available = True
    engine = object()

    def chat_json(self, system_prompt: str, user_prompt: str, fallback: dict):
        return {
            "city": "天津",
            "travel_days": "2",
            "budget": "1800",
            "interests": ["海河夜景"],
        }


def test_rule_intent_detects_tianjin_days_trip_as_create_trip() -> None:
    result = IntentService().detect("天津2天游，预算1800元")

    assert result.intent == "create_trip"


def test_intent_agent_keeps_rule_result_when_ai_confidence_is_low() -> None:
    result = IntentAgent(FakeLowConfidenceChatbot()).run("天津2天游，预算1800元")

    assert result.intent == "create_trip"
    assert result.confidence == 0.9


def test_requirement_adapter_extracts_days_and_budget_with_ai_aliases() -> None:
    result = RequirementAdapter(FakeRequirementChatbot()).extract(
        session_id="session_test",
        message="天津2天游，预算1800元",
    )

    assert result.requirements.city == "天津"
    assert result.requirements.days == 2
    assert result.requirements.total_budget == 1800
    assert result.requirements.interests == ["海河夜景"]
    assert result.missing_fields == []
    assert result.need_follow_up is False

from __future__ import annotations

from fastapi import APIRouter, File, Form, UploadFile

from backend.schemas import ApiResponse
from backend.services.chatbot_service import ChatbotService

router = APIRouter(prefix="/api/v1/voice", tags=["voice"])

SCENE_LABELS = {
    "plan": "Tianjin itinerary planning",
    "qa": "Tianjin travel Q&A",
    "guide": "map AI tour guide",
    "adjustment": "itinerary adjustment",
}


def ok(data=None, message: str = "\u64cd\u4f5c\u6210\u529f") -> ApiResponse:
    return ApiResponse(data=data, message=message)


@router.post("/understand")
async def understand_voice(
    session_id: str = Form("demo_session"),
    scene: str = Form("plan"),
    client_hint: str = Form(""),
    audio: UploadFile = File(...),
) -> ApiResponse:
    """Unified voice input endpoint.

    The frontend uploads the real recording so the user can play it back.
    This lightweight version uses a hidden browser recognition hint plus the
    project Chatbot to correct noisy text. A real ASR provider can replace
    _understand_with_chatbot later without changing the frontend contract.
    """

    raw_hint = client_hint.strip()
    understood_text = _understand_with_chatbot(raw_hint, scene) if raw_hint else ""
    return ok(
        {
            "session_id": session_id,
            "scene": scene,
            "audio_filename": audio.filename,
            "audio_content_type": audio.content_type,
            "understood_text": understood_text,
            "display_text": _display_text(scene),
            "recognized": bool(understood_text),
            "recognition_mode": "browser_hint_plus_chatbot" if raw_hint else "fallback",
        }
    )


def _understand_with_chatbot(raw_hint: str, scene: str) -> str:
    fallback = _normalize_locally(raw_hint, scene)
    try:
        chatbot = ChatbotService()
        system_prompt = (
            "You are the voice-understanding corrector for a Tianjin travel app. "
            "The browser produced a possibly noisy Chinese speech recognition hint. "
            "Correct typos, normalize spoken numbers and keep travel constraints. "
            "Return one natural Chinese user request that can be sent to downstream agents. "
            "Return only the request, no explanation, no Markdown."
        )
        user_prompt = (
            f"Scene: {SCENE_LABELS.get(scene, scene)}\n"
            f"Noisy recognition hint: {raw_hint}\n"
            "If this is planning, preserve days, budget, people, interests and walking limits. "
            "If this is Q&A or tour guide, rewrite it as a natural question."
        )
        result = chatbot.chat(system_prompt, user_prompt).strip()
        return result or fallback
    except Exception:
        return fallback


def _normalize_locally(text: str, scene: str) -> str:
    cleaned = " ".join(text.split())
    replacements = {
        "\u4e8c\u5929": "\u4e24\u5929",
        "2\u5929\u6e38": "\u4e24\u65e5\u6e38",
        "\u4e8c\u65e5": "\u4e24\u65e5",
        "\u4e00\u5343\u516b": "1800\u5143",
        "\u4e09\u5343": "3000\u5143",
    }
    for old, new in replacements.items():
        cleaned = cleaned.replace(old, new)
    if scene == "plan" and "\u5929\u6d25" in cleaned and not cleaned.startswith("\u5e2e\u6211"):
        return f"\u5e2e\u6211\u89c4\u5212{cleaned}"
    return cleaned or _fallback_text(scene)


def _fallback_text(scene: str) -> str:
    if scene == "qa":
        return "\u5929\u6d25\u6709\u54ea\u4e9b\u9002\u5408\u7b2c\u4e00\u6b21\u53bb\u7684\u666f\u70b9\uff1f"
    if scene == "guide":
        return "\u8fd9\u91cc\u6700\u503c\u5f97\u770b\u7684\u5730\u65b9\u662f\u4ec0\u4e48\uff1f"
    if scene == "adjustment":
        return "\u4eca\u5929\u4e0b\u5348\u4e0b\u96e8\u4e86\uff0c\u5e2e\u6211\u628a\u9732\u5929\u666f\u70b9\u6539\u6210\u5ba4\u5185\u5b89\u6392"
    return "\u5e2e\u6211\u89c4\u5212\u5929\u6d25\u4e24\u65e5\u6e38\uff0c\u9884\u7b971800\u5143\uff0c\u559c\u6b22\u8fd1\u4ee3\u5efa\u7b51\u548c\u6d77\u6cb3\u591c\u666f\uff0c\u6b65\u884c\u4e0d\u8981\u8d85\u8fc77\u516c\u91cc\u3002"


def _display_text(scene: str) -> str:
    if scene == "qa":
        return "\u5df2\u53d1\u9001\u4e00\u6761\u8bed\u97f3\u95ee\u9898"
    if scene == "guide":
        return "\u5df2\u53d1\u9001\u4e00\u6761\u8bed\u97f3\u5bfc\u6e38\u95ee\u9898"
    if scene == "adjustment":
        return "\u5df2\u53d1\u9001\u4e00\u6761\u8bed\u97f3\u4fee\u6539\u9700\u6c42"
    return "\u5df2\u53d1\u9001\u4e00\u6761\u8bed\u97f3\u89c4\u5212\u9700\u6c42"

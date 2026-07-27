from __future__ import annotations

from fastapi import APIRouter, File, Form, UploadFile

from backend.schemas import ApiResponse

router = APIRouter(prefix="/api/v1/voice", tags=["voice"])


def ok(data=None, message: str = "操作成功") -> ApiResponse:
    return ApiResponse(data=data, message=message)


@router.post("/understand")
async def understand_voice(
    session_id: str = Form("demo_session"),
    scene: str = Form("plan"),
    client_hint: str = Form(""),
    audio: UploadFile = File(...),
) -> ApiResponse:
    """语音输入入口。

    当前版本先完成“前端上传语音 -> 后端统一入口 -> 进入现有 Agent 流程”的闭环。
    client_hint 是浏览器端隐式识别出的语义线索，前端不会展示给用户。
    后续接入 Whisper、SenseVoice 或多模态模型时，只需要替换这里的 understood_text。
    """

    understood_text = client_hint.strip() or _fallback_text(scene)
    return ok(
        {
            "session_id": session_id,
            "scene": scene,
            "audio_filename": audio.filename,
            "audio_content_type": audio.content_type,
            "understood_text": understood_text,
            "display_text": _display_text(scene),
        }
    )


def _fallback_text(scene: str) -> str:
    if scene == "qa":
        return "天津有哪些适合第一次去的景点？"
    if scene == "guide":
        return "这里最值得看的地方是什么？"
    if scene == "adjustment":
        return "今天下午下雨了，帮我把露天景点改成室内安排"
    return "帮我规划天津两日游，预算1800元，喜欢近代建筑和海河夜景，步行不要超过7公里。"


def _display_text(scene: str) -> str:
    if scene == "qa":
        return "已发送一条语音问题"
    if scene == "guide":
        return "已发送一条语音导游问题"
    if scene == "adjustment":
        return "已发送一条语音修改需求"
    return "已发送一条语音规划需求"

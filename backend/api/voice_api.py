from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import re
import subprocess
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

from dotenv import load_dotenv
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
    The backend uses an AI ASR service to transcribe audio, then uses the
    project Chatbot to correct noisy text before sending it to downstream agents.
    """

    audio_bytes = await audio.read()
    raw_transcript, asr_error = await _transcribe_audio(audio_bytes, audio.filename or "voice.webm")
    raw_hint = raw_transcript.strip() or client_hint.strip()
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
            "raw_transcript": raw_transcript,
            "asr_error": asr_error,
            "recognition_mode": "server_asr_plus_chatbot" if raw_transcript else "server_asr_failed",
        }
    )


async def _transcribe_audio(audio_bytes: bytes, filename: str) -> tuple[str, str]:
    if not audio_bytes:
        return "", "empty_audio"

    return await asyncio.to_thread(_transcribe_audio_sync, audio_bytes, filename)


def _transcribe_audio_sync(audio_bytes: bytes, filename: str) -> tuple[str, str]:
    load_dotenv(override=False, encoding="utf-8-sig")
    provider = os.environ.get("ASR_PROVIDER", "baidu").strip().lower()

    if provider in {"baidu", "baidu-cloud"}:
        return _transcribe_with_baidu(audio_bytes, filename)

    if provider in {"sensevoice", "funasr"}:
        return _transcribe_with_sensevoice(audio_bytes, filename)

    if provider in {"openai", "whisper", "openai-compatible"}:
        return _transcribe_with_openai_compatible(audio_bytes, filename)

    return "", f"Unsupported ASR_PROVIDER: {provider}"


def _transcribe_with_baidu(audio_bytes: bytes, filename: str) -> tuple[str, str]:
    api_key = os.environ.get("BAIDU_ASR_API_KEY") or os.environ.get("BAIDU_APP_KEY")
    secret_key = os.environ.get("BAIDU_ASR_SECRET_KEY") or os.environ.get("BAIDU_SECRET_KEY")
    cuid = os.environ.get("BAIDU_ASR_CUID") or os.environ.get("BAIDU_APP_ID") or "voyagemind-member1"
    dev_pid = int(os.environ.get("BAIDU_ASR_DEV_PID", "1537"))

    if not api_key or not secret_key:
        return "", "BAIDU_ASR_API_KEY and BAIDU_ASR_SECRET_KEY are not configured"

    wav_bytes, convert_error = _convert_audio_to_wav_16k(audio_bytes, filename)
    if convert_error:
        return "", convert_error

    token, token_error = _get_baidu_access_token(api_key, secret_key)
    if token_error:
        return "", token_error

    payload = {
        "format": "wav",
        "rate": 16000,
        "channel": 1,
        "cuid": str(cuid),
        "token": token,
        "dev_pid": dev_pid,
        "speech": base64.b64encode(wav_bytes).decode("ascii"),
        "len": len(wav_bytes),
    }
    try:
        request = urllib.request.Request(
            "https://vop.baidu.com/server_api",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        return "", f"Baidu ASR request failed: {exc}"

    if result.get("err_no") != 0:
        return "", f"Baidu ASR failed: {result.get('err_msg') or result}"

    return "".join(result.get("result") or []).strip(), ""


def _get_baidu_access_token(api_key: str, secret_key: str) -> tuple[str, str]:
    query = urllib.parse.urlencode(
        {
            "grant_type": "client_credentials",
            "client_id": api_key,
            "client_secret": secret_key,
        }
    )
    try:
        with urllib.request.urlopen(
            f"https://aip.baidubce.com/oauth/2.0/token?{query}",
            timeout=20,
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        return "", f"Baidu token request failed: {exc}"

    token = payload.get("access_token")
    if not token:
        return "", f"Baidu token response missing access_token: {payload}"
    return token, ""


def _convert_audio_to_wav_16k(audio_bytes: bytes, filename: str) -> tuple[bytes, str]:
    suffix = Path(filename).suffix or ".webm"
    input_path = ""
    output_path = ""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as input_file:
            input_file.write(audio_bytes)
            input_path = input_file.name
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as output_file:
            output_path = output_file.name

        command = [
            os.environ.get("FFMPEG_BINARY", "ffmpeg"),
            "-y",
            "-i",
            input_path,
            "-ac",
            "1",
            "-ar",
            "16000",
            "-f",
            "wav",
            output_path,
        ]
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if completed.returncode != 0:
            stderr = completed.stderr.decode("utf-8", errors="ignore").strip()
            return "", f"ffmpeg audio conversion failed: {stderr or 'unknown error'}"

        return Path(output_path).read_bytes(), ""
    except FileNotFoundError:
        return "", "ffmpeg is required to convert browser audio before Baidu ASR"
    except Exception as exc:
        return "", f"audio conversion failed: {exc}"
    finally:
        for path in (input_path, output_path):
            if path:
                try:
                    Path(path).unlink()
                except OSError:
                    pass


def _transcribe_with_sensevoice(audio_bytes: bytes, filename: str) -> tuple[str, str]:
    model_name = os.environ.get("ASR_MODEL", "iic/SenseVoiceSmall")
    suffix = Path(filename).suffix or ".webm"
    temp_path = ""

    try:
        from funasr import AutoModel
    except Exception as exc:
        return "", f"SenseVoice requires funasr. Please install backend requirements first: {exc}"

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            temp_file.write(audio_bytes)
            temp_path = temp_file.name

        model = AutoModel(
            model=model_name,
            trust_remote_code=True,
            vad_model=os.environ.get("ASR_VAD_MODEL", "fsmn-vad"),
            vad_kwargs={"max_single_segment_time": 30000},
            device=os.environ.get("ASR_DEVICE", "cpu"),
        )
        result = model.generate(
            input=temp_path,
            cache={},
            language=os.environ.get("ASR_LANGUAGE", "zh"),
            use_itn=True,
            batch_size_s=60,
        )
        return _extract_sensevoice_text(result), ""
    except Exception as exc:
        return "", str(exc)
    finally:
        if temp_path:
            try:
                Path(temp_path).unlink()
            except OSError:
                pass


def _extract_sensevoice_text(result) -> str:
    if isinstance(result, list) and result:
        text = " ".join(str(item.get("text", "")) for item in result if isinstance(item, dict))
    elif isinstance(result, dict):
        text = str(result.get("text", ""))
    else:
        text = str(result or "")
    return re.sub(r"<\|.*?\|>", "", text).strip()


def _transcribe_with_openai_compatible(audio_bytes: bytes, filename: str) -> tuple[str, str]:
    api_key = os.environ.get("ASR_API_KEY") or os.environ.get("OPENAI_API_KEY")
    base_url = os.environ.get("ASR_BASE_URL") or None
    model = os.environ.get("ASR_MODEL", "whisper-1")

    if not api_key:
        return "", "ASR_API_KEY is not configured"

    try:
        from openai import OpenAI
    except Exception as exc:
        return "", f"openai package is unavailable: {exc}"

    try:
        client = OpenAI(api_key=api_key, base_url=base_url)
        audio_file = io.BytesIO(audio_bytes)
        audio_file.name = filename
        result = client.audio.transcriptions.create(
            model=model,
            file=audio_file,
            language="zh",
        )
        return (getattr(result, "text", "") or "").strip(), ""
    except Exception as exc:
        return "", str(exc)


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

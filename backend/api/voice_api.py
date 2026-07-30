from __future__ import annotations

import asyncio
import base64
import importlib
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
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from backend.schemas import ApiResponse
from backend.services.chatbot_service import ChatbotService
from backend.services.tts_script_service import GuideTtsScriptService
from backend.services.tts_service import DashScopeTtsService

router = APIRouter(prefix="/api/v1/voice", tags=["voice"])

SCENE_LABELS = {
    "plan": "Tianjin itinerary planning",
    "qa": "Tianjin travel Q&A",
    "guide": "map AI tour guide",
    "adjustment": "itinerary adjustment",
}

# TTS 链路拆成两层服务：
# 1. GuideTtsScriptService 只负责 LLM 改写和 SSML 停顿包装。
# 2. DashScopeTtsService 只负责调用阿里 TTS、下载并缓存音频文件。
tts_script_service = GuideTtsScriptService()
tts_service = DashScopeTtsService()


def _env_default(name: str, fallback: str) -> str:
    """读取环境变量默认值。

    用于 Pydantic 字段的 default_factory，让 TTS 模型、音色和格式可以通过 .env 调整；
    如果环境变量未配置，则返回代码内置的 fallback。
    """
    # Pydantic 的 default_factory 在请求建模时读取环境变量，便于 .env 调整默认音色。
    return os.environ.get(name, fallback)


class GuideTtsRequest(BaseModel):
    """导游讲解 TTS 请求体。

    前端只需要传 text；target_type 和 target_title 用来帮助 LLM 改写得更贴合场景。
    model、voice、format 可以由前端覆盖，也可以直接走 .env 默认值。
    """

    # 保留 session_id，便于后续按会话做音频历史或缓存清理。
    session_id: str = "demo_session"

    # text 是导游回答原文，先经 LLM 改写，再进入 TTS。
    text: str = Field(..., min_length=1, max_length=3000)

    # target_type 例如 place、route、food，用于提示讲解对象类型。
    target_type: str = "place"

    # target_title 例如“五大道”，用于让讲解稿开头更自然。
    target_title: str = ""

    # 默认模型从 .env 读取，未配置时使用 CosyVoice v3 flash。
    model: str = Field(
        default_factory=lambda: _env_default("TTS_MODEL", "cosyvoice-v3-flash")
    )

    # 默认音色从 .env 读取，方便联调时统一替换声音。
    voice: str = Field(
        default_factory=lambda: _env_default("TTS_VOICE", "longanhuan_v3")
    )

    # 默认输出 mp3，前端 audio 标签兼容性最好。
    format: str = Field(default_factory=lambda: _env_default("TTS_FORMAT", "mp3"))


def ok(data=None, message: str = "\u64cd\u4f5c\u6210\u529f") -> ApiResponse:
    """构造统一成功响应。

    voice_api 内部所有成功接口都返回 ApiResponse，便于前端用同一套 data/message 结构处理结果。
    """
    return ApiResponse(data=data, message=message)


@router.post("/understand")
async def understand_voice(
    session_id: str = Form("demo_session"),
    scene: str = Form("plan"),
    client_hint: str = Form(""),
    audio: UploadFile = File(...),
) -> ApiResponse:
    """接收浏览器录音并转换成下游 Agent 可处理的文本。

    前端上传真实音频文件、场景和可选识别提示；后端先调用 ASR 得到原始转写，
    再用 Chatbot 按场景纠错和规范化，例如修正数字、预算、景点名和步行限制。
    返回 understood_text 给规划、问答、导游或调整流程继续使用，同时保留 raw_transcript 和错误信息便于调试。
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


@router.post("/synthesize")
async def synthesize_voice(body: GuideTtsRequest) -> ApiResponse:
    """生成导游讲解音频。

    流程是：原始文本 -> LLM 讲解稿 -> 后端规则 SSML -> 阿里 TTS -> 本地 mp3 URL。
    """

    try:
        # 第一步：只让 LLM 生成纯中文讲解稿，不让它直接输出 SSML 标签。
        script = tts_script_service.build_script(
            body.text,
            body.target_type,
            body.target_title,
        )

        # 第二步：后端按标点统一插入停顿，保证 SSML 结构稳定可控。
        ssml = tts_script_service.build_ssml(script)

        # 第三步：TTS 合成和音频下载是阻塞 I/O，放到线程池避免卡住事件循环。
        audio_path = await asyncio.to_thread(
            tts_service.synthesize_to_file,
            ssml,
            body.model,
            body.voice,
            body.format,
        )

        # 只返回后端可访问的相对 URL，不暴露阿里返回的临时音频地址。
        return ok(
            {
                "audio_url": f"/api/v1/voice/tts/{audio_path.name}",
                "audio_type": _audio_media_type(audio_path.suffix),
                "speech_script": script,
            }
        )
    except Exception as exc:
        # 保留具体错误信息，联调时能看到是 LLM、SSML、TTS 请求还是下载失败。
        raise HTTPException(status_code=500, detail=f"语音讲解生成失败：{exc}") from exc


@router.get("/tts/{filename}")
def get_tts_file(filename: str):
    """读取本地缓存音频文件，供前端 audio 标签播放。"""

    # 只允许纯文件名，拒绝 ../ 这类路径穿越输入。
    safe_name = Path(filename).name
    if safe_name != filename:
        raise HTTPException(status_code=400, detail="非法文件名")

    # 音频必须位于 DashScopeTtsService 固定生成目录下。
    path = tts_service.tts_dir / safe_name
    if not path.exists():
        raise HTTPException(status_code=404, detail="音频不存在")

    # 根据真实后缀返回媒体类型，避免前端播放器识别错误。
    return FileResponse(path, media_type=_audio_media_type(path.suffix))


def _audio_media_type(suffix: str) -> str:
    """把文件后缀映射成 HTTP Content-Type。"""

    return {
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".opus": "audio/ogg",
        ".pcm": "application/octet-stream",
    }.get(suffix.lower(), "application/octet-stream")


async def _transcribe_audio(audio_bytes: bytes, filename: str) -> tuple[str, str]:
    """异步封装 ASR 转写入口。

    FastAPI 接口运行在事件循环中，真实 ASR、ffmpeg 和网络请求都是阻塞操作；
    因此这里先处理空音频，再把同步转写逻辑放到线程池执行，避免阻塞其他请求。
    """
    if not audio_bytes:
        return "", "empty_audio"

    return await asyncio.to_thread(_transcribe_audio_sync, audio_bytes, filename)


def _transcribe_audio_sync(audio_bytes: bytes, filename: str) -> tuple[str, str]:
    """根据 ASR_PROVIDER 环境变量选择具体语音识别后端。

    支持 baidu、sensevoice/funasr 和 openai-compatible 三类 provider。
    返回值统一为 (识别文本, 错误信息)，成功时错误信息为空，失败时文本为空。
    """
    load_dotenv(override=False, encoding="utf-8-sig")
    provider = os.environ.get("ASR_PROVIDER", "baidu").strip().lower()

    # ASR 服务通过环境变量切换，接口层保持不变，前端始终只调用 /voice/understand。
    if provider in {"baidu", "baidu-cloud"}:
        return _transcribe_with_baidu(audio_bytes, filename)

    if provider in {"sensevoice", "funasr"}:
        return _transcribe_with_sensevoice(audio_bytes, filename)

    if provider in {"openai", "whisper", "openai-compatible"}:
        return _transcribe_with_openai_compatible(audio_bytes, filename)

    return "", f"Unsupported ASR_PROVIDER: {provider}"


def _transcribe_with_baidu(audio_bytes: bytes, filename: str) -> tuple[str, str]:
    """使用百度短语音识别接口转写浏览器录音。

    函数先读取百度 API Key、Secret、CUID 和 dev_pid，再调用 ffmpeg 把浏览器音频转成
    16k 单声道 wav，最后请求百度 server_api。任何配置、转码或接口错误都会以字符串返回。
    """
    api_key = os.environ.get("BAIDU_ASR_API_KEY") or os.environ.get("BAIDU_APP_KEY")
    secret_key = os.environ.get("BAIDU_ASR_SECRET_KEY") or os.environ.get("BAIDU_SECRET_KEY")
    cuid = os.environ.get("BAIDU_ASR_CUID") or os.environ.get("BAIDU_APP_ID") or "voyagemind-member1"
    dev_pid = int(os.environ.get("BAIDU_ASR_DEV_PID", "1537"))

    if not api_key or not secret_key:
        return "", "BAIDU_ASR_API_KEY and BAIDU_ASR_SECRET_KEY are not configured"

    # 浏览器录音通常是 webm/opus，百度短语音接口更稳定的输入是 16k 单声道 wav。
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
    """向百度 OAuth 接口申请 ASR access_token。

    百度语音识别接口需要先用 API Key 和 Secret 换取 token。
    成功返回 (token, "")，失败返回 ("", 错误信息)，调用方据此决定是否继续识别。
    """
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
    """调用 ffmpeg 把浏览器音频转为百度 ASR 需要的 16k 单声道 wav。

    浏览器通常上传 webm/opus，百度短语音接口对 wav 更稳定。
    这里会创建临时输入和输出文件，执行 ffmpeg 转码，读取 wav 字节后清理临时文件。
    如果本机没有安装 ffmpeg 或转码失败，会返回空字节和错误信息。
    """
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
        # ffmpeg 放在子进程中执行，避免把浏览器音频格式兼容问题扩散到 ASR 调用处。
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if completed.returncode != 0:
            stderr = completed.stderr.decode("utf-8", errors="ignore").strip()
            return b"", f"ffmpeg audio conversion failed: {stderr or 'unknown error'}"

        return Path(output_path).read_bytes(), ""
    except FileNotFoundError:
        return b"", "ffmpeg is required to convert browser audio before Baidu ASR"
    except Exception as exc:
        return b"", f"audio conversion failed: {exc}"
    finally:
        for path in (input_path, output_path):
            if path:
                try:
                    Path(path).unlink()
                except OSError:
                    pass


def _transcribe_with_sensevoice(audio_bytes: bytes, filename: str) -> tuple[str, str]:
    """使用本地 FunASR/SenseVoice 模型进行语音识别。

    该分支适合离线或本地模型部署场景：先动态导入 funasr.AutoModel，
    再把上传音频写入临时文件并调用 model.generate，最后提取纯文本并清理临时文件。
    """
    model_name = os.environ.get("ASR_MODEL", "iic/SenseVoiceSmall")
    suffix = Path(filename).suffix or ".webm"
    temp_path = ""

    try:
        AutoModel = importlib.import_module("funasr").AutoModel
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
    """从 SenseVoice/FunASR 返回结果中提取干净文本。

    FunASR 可能返回 list、dict 或其他对象，并常带有 <|zh|> 这类标签。
    该函数统一拼接 text 字段，并移除模型标签，得到可展示和可纠错的中文文本。
    """
    if isinstance(result, list) and result:
        text = " ".join(str(item.get("text", "")) for item in result if isinstance(item, dict))
    elif isinstance(result, dict):
        text = str(result.get("text", ""))
    else:
        text = str(result or "")
    return re.sub(r"<\|.*?\|>", "", text).strip()


def _transcribe_with_openai_compatible(audio_bytes: bytes, filename: str) -> tuple[str, str]:
    """使用 OpenAI 或兼容 OpenAI 接口的 Whisper ASR 服务识别音频。

    从 ASR_API_KEY/OPENAI_API_KEY、ASR_BASE_URL 和 ASR_MODEL 读取配置，
    把上传的音频字节包装成文件对象后调用 audio.transcriptions.create。
    适合接入官方 Whisper 或第三方兼容服务。
    """
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
    """用 Chatbot 修正 ASR 原始文本。

    ASR 容易把口语数字、预算金额、景点名和约束词识别错；
    这里先准备本地兜底文本，再让 Chatbot 根据当前场景把原始识别结果改写成自然中文请求。
    模型不可用时直接返回本地规范化结果。
    """
    fallback = _normalize_locally(raw_hint, scene)
    try:
        chatbot = ChatbotService()
        # ASR 结果可能把数字、预算或景点名识别错；这里统一修正成下游 Agent 可直接处理的中文请求。
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
    """不依赖模型的本地语音文本规范化。

    主要做空白压缩和少量常见中文数字替换；规划场景下，如果文本包含天津但没有
    “帮我”开头，会补成更像用户请求的句子，方便下游意图识别。
    """
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
    """根据语音使用场景返回默认文本。

    当 ASR 没有识别结果且前端也没有 hint 时，用这个默认文本保证接口仍能返回可演示内容。
    不同场景分别对应问答、导游、行程调整和行程规划。
    """
    if scene == "qa":
        return "\u5929\u6d25\u6709\u54ea\u4e9b\u9002\u5408\u7b2c\u4e00\u6b21\u53bb\u7684\u666f\u70b9\uff1f"
    if scene == "guide":
        return "\u8fd9\u91cc\u6700\u503c\u5f97\u770b\u7684\u5730\u65b9\u662f\u4ec0\u4e48\uff1f"
    if scene == "adjustment":
        return "\u4eca\u5929\u4e0b\u5348\u4e0b\u96e8\u4e86\uff0c\u5e2e\u6211\u628a\u9732\u5929\u666f\u70b9\u6539\u6210\u5ba4\u5185\u5b89\u6392"
    return "\u5e2e\u6211\u89c4\u5212\u5929\u6d25\u4e24\u65e5\u6e38\uff0c\u9884\u7b971800\u5143\uff0c\u559c\u6b22\u8fd1\u4ee3\u5efa\u7b51\u548c\u6d77\u6cb3\u591c\u666f\uff0c\u6b65\u884c\u4e0d\u8981\u8d85\u8fc77\u516c\u91cc\u3002"


def _display_text(scene: str) -> str:
    """生成前端语音气泡里展示的简短状态文案。

    display_text 不等于真实识别文本，只用于告诉用户“已经发送了哪类语音请求”。
    这样前端可以隐藏冗长 ASR 过程，同时保持交互反馈清晰。
    """
    if scene == "qa":
        return "\u5df2\u53d1\u9001\u4e00\u6761\u8bed\u97f3\u95ee\u9898"
    if scene == "guide":
        return "\u5df2\u53d1\u9001\u4e00\u6761\u8bed\u97f3\u5bfc\u6e38\u95ee\u9898"
    if scene == "adjustment":
        return "\u5df2\u53d1\u9001\u4e00\u6761\u8bed\u97f3\u4fee\u6539\u9700\u6c42"
    return "\u5df2\u53d1\u9001\u4e00\u6761\u8bed\u97f3\u89c4\u5212\u9700\u6c42"

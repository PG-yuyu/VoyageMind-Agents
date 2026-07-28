from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import load_dotenv


# 只允许后端明确支持的音频格式，避免用户传入奇怪后缀影响文件保存。
SUPPORTED_AUDIO_FORMATS = {"mp3", "wav", "pcm", "opus"}


class DashScopeTtsService:
    """负责调用阿里百炼 TTS，并把临时音频下载成本地文件。"""

    def __init__(self) -> None:
        # 服务文件位于 backend/services，因此 parents[2] 是项目根目录。
        project_root = Path(__file__).resolve().parents[2]

        # 后端启动时读取 .env；override=False 避免覆盖已存在的系统环境变量。
        load_dotenv(project_root / ".env", override=False, encoding="utf-8-sig")

        # 生成的音频统一放在 backend/generated/tts，便于后续 FileResponse 读取。
        self.tts_dir = Path(__file__).resolve().parents[1] / "generated" / "tts"
        self.tts_dir.mkdir(parents=True, exist_ok=True)

    def synthesize_to_file(
        self,
        ssml: str,
        model: str,
        voice: str,
        audio_format: str = "mp3",
    ) -> Path:
        """提交 SSML 到阿里 TTS，下载音频，并返回本地文件路径。"""

        # API Key 是强依赖；缺失时直接暴露清晰错误，方便联调定位。
        api_key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("DASHSCOPE_API_KEY is not configured")

        # 标准化并校验格式，后面会用它生成文件名和 Content-Type。
        audio_format = self._normalize_format(audio_format)

        # 配置了 WorkspaceId 时使用百炼工作空间域名；否则退回 DashScope 默认域名。
        workspace_id = os.environ.get("DASHSCOPE_WORKSPACE_ID", "").strip()
        base_url = (
            f"https://{workspace_id}.cn-beijing.maas.aliyuncs.com/api/v1"
            if workspace_id
            else "https://dashscope.aliyuncs.com/api/v1"
        )
        endpoint = f"{base_url}/services/audio/tts/SpeechSynthesizer"

        # 相同模型、音色、格式、SSML 直接复用文件，减少重复计费和等待时间。
        cache_key = hashlib.sha1(
            f"{model}|{voice}|{audio_format}|{ssml}".encode("utf-8")
        ).hexdigest()[:24]
        output_path = self.tts_dir / f"guide-{cache_key}.{audio_format}"
        if output_path.exists():
            return output_path

        # enable_ssml 必须为 True，否则 <break> 会被当成普通文本处理。
        payload = {
            "model": model,
            "input": {
                "text": ssml,
                "voice": voice,
                "format": audio_format,
                "sample_rate": int(os.environ.get("TTS_SAMPLE_RATE", "24000")),
                "rate": float(os.environ.get("TTS_RATE", "0.92")),
                "pitch": float(os.environ.get("TTS_PITCH", "1.0")),
                "language_hints": ["zh"],
                "enable_ssml": True,
            },
        }
        instruction = os.environ.get("TTS_INSTRUCTION", "").strip()
        if instruction:
            payload["input"]["instruction"] = instruction

        # 阿里非流式接口先返回一个临时音频 URL，真正文件需要再下载一次。
        result = self._post_json(endpoint, payload, api_key)
        audio_url = result.get("output", {}).get("audio", {}).get("url")
        if not audio_url:
            raise RuntimeError(f"TTS response missing audio url: {result}")

        self._download_audio(audio_url, output_path)
        return output_path

    def _normalize_format(self, audio_format: str) -> str:
        """校验请求中的音频格式，防止异常文件名或不支持的格式进入流程。"""

        normalized = (audio_format or "mp3").strip().lower()

        # 后缀只允许字母数字，避免路径穿越或带点号的伪装后缀。
        if not re.fullmatch(r"[a-z0-9]+", normalized):
            raise ValueError("Invalid audio format")

        # 限定为当前接口明确知道如何保存和返回的格式。
        if normalized not in SUPPORTED_AUDIO_FORMATS:
            raise ValueError(
                f"Unsupported audio format: {normalized}. "
                f"Use one of {sorted(SUPPORTED_AUDIO_FORMATS)}."
            )
        return normalized

    def _post_json(self, endpoint: str, payload: dict, api_key: str) -> dict:
        """发送 TTS 合成请求，并把 JSON 响应解析成字典。"""

        # 使用标准库发请求，避免额外安装 SDK；ensure_ascii=False 保留中文原文。
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            # 读取错误响应体，便于在 FastAPI 500 detail 中看到阿里侧具体原因。
            body = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"TTS request failed with HTTP {exc.code}: {body}") from exc

    def _download_audio(self, audio_url: str, output_path: Path) -> None:
        """下载阿里返回的临时音频，并写入本地缓存文件。"""

        try:
            with urllib.request.urlopen(audio_url, timeout=90) as audio_response:
                output_path.write_bytes(audio_response.read())
        except urllib.error.HTTPError as exc:
            # 下载失败通常是临时 URL 过期、鉴权失败或网络问题，需要保留响应体。
            body = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(
                f"TTS audio download failed with HTTP {exc.code}: {body}"
            ) from exc

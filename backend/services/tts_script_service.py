from __future__ import annotations

import html
import re

from backend.services.chatbot_service import ChatbotService


class GuideTtsScriptService:
    """负责“文本改写”和“SSML 包装”的服务层。

    这一层只处理播报文案质量，不直接调用 TTS。这样可以把 LLM 输出和
    音频合成解耦，后续更换语音厂商时也不影响导游讲解稿生成规则。
    """

    def __init__(self) -> None:
        # 复用项目已有 ChatbotService，避免为了语音讲解再引入一套 LLM SDK。
        self.chatbot = ChatbotService()

    def build_script(
        self,
        text: str,
        target_type: str = "place",
        target_title: str = "",
    ) -> str:
        """把导游回答改写成适合中文语音播报的短讲解稿。"""

        # fallback 保证 LLM 不可用、超时、返回异常时，接口仍能产出可播报文本。
        fallback = {"script": self._fallback_script(text)}

        # 系统提示只要求模型写“纯讲解稿”，不要让模型写 SSML 标签。
        # SSML 后面由规则生成，可避免模型乱写 XML 导致 TTS 报错。
        system = (
            "你是天津自由行系统的 AI 导游语音讲解撰稿人。"
            "把导游回答改写成适合中文语音播报的讲解稿。"
            "只保留原文事实，不新增票价、开放时间、历史细节。"
            "语气亲切自然，短句为主，不要 Markdown，不要标题，不要项目符号。"
            "控制在120到260个汉字。只返回 JSON：{\"script\":\"...\"}"
        )

        # 目标类型和标题只作为改写上下文，不能让模型据此编造新事实。
        user = (
            f"导游对象类型：{target_type}\n"
            f"导游对象：{target_title}\n"
            f"原始回答：\n{text}"
        )

        # chat_json 内部已有 JSON 解析和一次格式重试，这里直接取 script 字段。
        result = self.chatbot.chat_json(system, user, fallback)
        return self._clean_script(str(result.get("script") or fallback["script"]))

    def build_ssml(self, script: str) -> str:
        """把纯中文讲解稿包装为阿里 TTS 可识别的 SSML。"""

        # 先转义 XML 特殊字符，防止文本中的符号破坏 <speak> 结构。
        escaped = html.escape(self._clean_script(script))

        # 句末停顿最长，帮助语音听起来像自然讲解，而不是连续念稿。
        escaped = re.sub(r"([。！？])", r'\1<break time="600ms"/>', escaped)

        # 分号通常表示半句转折，停顿略短于句号。
        escaped = re.sub(r"(；|;)", r'\1<break time="450ms"/>', escaped)

        # 逗号和顿号只做轻微停顿，保留中文口语节奏。
        escaped = re.sub(r"(，|、)", r'\1<break time="220ms"/>', escaped)

        # 阿里 HTTP TTS 开启 enable_ssml 后，会按 speak 根节点解析停顿标签。
        return f'<speak version="1.0" xml:lang="zh-CN">{escaped}</speak>'

    def _fallback_script(self, text: str) -> str:
        """本地兜底改写：去掉 Markdown 痕迹，并把换行压成短句。"""

        # 删除常见 Markdown 符号，避免语音把符号读出来。
        clean = re.sub(r"[*#>`\-•]+", "", text or "")

        # 多段文本在语音里需要自然断开，统一替换为中文句号。
        clean = re.sub(r"\s+", "。", clean)
        return self._clean_script(clean)

    def _clean_script(self, text: str) -> str:
        """统一清理播报文本，限制长度，保护 TTS 请求体大小。"""

        # 去掉所有空白，避免生成多余停顿；真正停顿由 build_ssml 负责。
        clean = re.sub(r"\s+", "", text or "")

        # 给兜底和模型输出都加硬上限，避免超长讲解影响响应速度。
        return clean[:320]

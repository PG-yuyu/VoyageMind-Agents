"""自定义 JSON 格式日志 Formatter。

将日志记录格式化为每行一个 JSON 对象，方便机器解析和日志采集系统消费。
对应需求 G2（JSON 格式日志）。

每行格式示例：
    {"time": "2026-07-15 10:30:45", "level": "INFO", "module": "chat_engine", "message": "模型切换: qwen3.6-flash"}

敏感信息脱敏：对 message 中的 API Key 模式（sk-xxx）进行脱敏处理（5.2）。
"""

import json
import logging
import re
from datetime import datetime

# 匹配 API Key 的正则（sk- 开头，后跟至少 10 个字符）
_API_KEY_PATTERN = re.compile(r"sk-[A-Za-z0-9]{10,}")


def mask_api_key(text: str) -> str:
    """对文本中的 API Key 进行脱敏（只显示前 8 位）。

    示例：sk-abcdef1234567890 → sk-abcdef1...
    """
    return _API_KEY_PATTERN.sub(lambda m: m.group()[:8] + "...", text)


class JsonFormatter(logging.Formatter):
    """JSON 格式日志 Formatter。

    将每条日志格式化为 JSON 对象，包含：
        - time: 时间戳
        - level: 日志级别
        - module: 模块名（logger 名）
        - message: 日志消息（已脱敏）
    """

    def format(self, record: logging.LogRecord) -> str:
        # 构建日志字典
        log_dict = {
            "time": datetime.fromtimestamp(record.created).strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            "level": record.levelname,
            "module": record.name,
            "message": mask_api_key(str(record.msg)),
        }
        return json.dumps(log_dict, ensure_ascii=False)

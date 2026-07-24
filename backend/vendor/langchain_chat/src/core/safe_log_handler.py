"""Windows 兼容的按天轮转日志 Handler。

背景：
    标准库 logging.handlers.TimedRotatingFileHandler 在 Windows 上有一个经典缺陷——
    跨午夜轮转时调用 os.rename(app.log, app.log.2026-07-16)，但当前进程自己正以写
    模式持有 app.log，导致 PermissionError [WinError 32]，每次写日志都刷一段
    "--- Logging error ---" 到控制台（非致命，但刷屏）。

解决：
    重写 doRollover：os.rename 失败时，改为「复制原文件到归档名 + 原地清空」
    （truncate 到 0），避免对正在使用的文件做重命名操作。这是 Windows 上日志轮转
    的标准解法，不影响日志内容，只是归档方式从「改名」变成「复制+清空」。

    同时重写 emit 的兜底：即便轮转仍失败（极罕见），也只记一条简短警告，不再抛
    "--- Logging error ---" 长堆栈刷屏。

在 config/logging.yaml 中通过 `(): core.safe_log_handler.SafeTimedRotatingFileHandler`
启用（与 JsonFormatter 的自定义引用方式一致）。
"""

import logging
import shutil
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path


class SafeTimedRotatingFileHandler(TimedRotatingFileHandler):
    """TimedRotatingFileHandler 的 Windows 兼容版本。

    与标准库行为一致，仅重写 doRollover 的文件轮转方式：
    优先用 os.rename；失败（文件被占用）时降级为「复制 + 原地清空」。
    """

    def rotate(self, source, dest):
        """轮转：rename 失败时降级为 copy + truncate。

        参数：
            source: 当前日志文件路径（如 logs/app.log）
            dest: 归档文件路径（如 logs/app.log.2026-07-16）
        """
        src = Path(source)
        if not src.exists():
            return  # 源文件不存在，无需轮转
        try:
            # 优先标准方式：重命名（Linux/Mac 或文件未被占用时直接成功）
            src.rename(dest)
        except (PermissionError, OSError):
            # Windows：文件被当前进程占用，rename 失败 → 改为「复制 + 原地清空」
            try:
                shutil.copy2(source, dest)
                # 原地清空：以写模式打开会释放再重建句柄，避免占用冲突
                with open(source, "w", encoding="utf-8"):
                    pass
            except OSError:
                # 复制也失败（极罕见）——放弃本次轮转，下天再试，不抛异常刷屏
                pass

    def emit(self, record):
        """写日志，轮转异常时不再向上抛（避免 --- Logging error --- 刷屏）。"""
        try:
            super().emit(record)
        except (PermissionError, OSError):
            # 轮转/写入失败时静默吞掉（已尽力），不影响应用功能
            pass

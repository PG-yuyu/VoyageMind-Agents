"""会话历史存储 —— 简单的线程安全内存存储。

存储对话消息用于：
- QueryRewriter 的上下文
- AnswerGenerator 的多轮对话
"""

import logging
import threading

logger = logging.getLogger("rag.session_store")


class SessionStore:
    """线程安全的内存会话存储。"""

    def __init__(self):
        self._sessions: dict[str, list[dict]] = {}
        self._lock = threading.Lock()

    def get_history(
        self,
        session_id: str,
        max_messages: int = 10,
    ) -> list[dict]:
        """获取会话的最近 N 条消息。

        Returns:
            list[dict]: 消息列表 [{"role": "user"|"assistant", "content": ...}]
        """
        with self._lock:
            messages = self._sessions.get(session_id, [])
            return messages[-max_messages:] if len(messages) > max_messages else list(messages)

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
    ) -> None:
        """添加一条消息到会话历史。"""
        if not session_id or not content:
            return

        with self._lock:
            if session_id not in self._sessions:
                self._sessions[session_id] = []
            self._sessions[session_id].append({
                "role": role,
                "content": content,
            })
            logger.debug("Session %s: added %s message (total: %d)",
                         session_id, role, len(self._sessions[session_id]))

    def clear_session(self, session_id: str) -> bool:
        """清除指定会话的历史。"""
        with self._lock:
            existed = session_id in self._sessions
            self._sessions.pop(session_id, None)
            if existed:
                logger.info("Session %s cleared", session_id)
            return existed

    def clear_all(self) -> None:
        """清除所有会话。"""
        with self._lock:
            count = len(self._sessions)
            self._sessions.clear()
            logger.info("All %d sessions cleared", count)

    @property
    def session_count(self) -> int:
        """当前会话数量。"""
        with self._lock:
            return len(self._sessions)

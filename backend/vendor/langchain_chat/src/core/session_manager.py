"""会话管理业务层。

封装会话相关的业务逻辑：新建会话、保存消息、加载历史、生成标题。
对应需求文档 C1（新建会话）、C6（自动保存）、C7（标题生成）。

设计说明：
    - SessionManager 通过依赖注入接收 StorageBackend，不直接操作数据库。
    - 消息加载时，把数据库的 Message 转成 LangChain 的 BaseMessage（供 ChatEngine 使用）。
    - 标题生成用 ChatEngine（LLM 摘要），失败时兜底截取前 30 字符。
"""
import logging
logger = logging.getLogger(__name__)
from typing import Optional

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from core.config_manager import AppConfig
from models.schemas import Message, Session
from storage.base import StorageBackend


class SessionManager:
    """会话管理器。

    通过传入的 StorageBackend 实例操作数据。
    使用方式：
        mgr = SessionManager(backend, config)
        session = await mgr.create_session(user_id=1, model_name="deepseek-chat")
    """

    def __init__(self, backend: StorageBackend, config: AppConfig):
        self.backend = backend
        self.config = config

    async def create_session(
        self,
        user_id: int,
        model_name: str,
        preset_id: Optional[int] = None,
        title: str = "新会话",
    ) -> Session:
        """新建会话（C1）。

        参数：
            user_id: 所属用户 ID
            model_name: 使用的模型名
            preset_id: 使用的预设 ID（可选）
            title: 会话标题（默认「新会话」，后续自动生成或手动修改）
        返回：
            创建后的 Session（含分配的 id）
        """
        session = Session(
            id=0,
            user_id=user_id,
            title=title,
            model_name=model_name,
            preset_id=preset_id,
        )
        logger.info("创建会话: 用户=%d, 模型=%s", user_id, model_name)
        return await self.backend.create_session(session)

    async def add_message(
        self,
        session: Session,
        role: str,
        content: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
    ) -> Message:
        """保存一条消息并更新会话的 Token 统计（C6 自动保存）。

        参数：
            session: 所属会话（会被更新 Token 统计）
            role: 消息角色（human / ai / system）
            content: 消息内容
            prompt_tokens: 本条输入 token 数
            completion_tokens: 本条输出 token 数
        返回：
            创建后的 Message（含分配的 id）
        """
        message = Message(
            id=0,
            session_id=session.id,
            role=role,
            content=content,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
        message = await self.backend.add_message(message)

        # 更新会话的 Token 统计
        session.total_prompt_tokens += prompt_tokens
        session.total_completion_tokens += completion_tokens
        await self.backend.update_session(session)

        return message

    async def load_messages_as_langchain(self, session_id: int) -> list[BaseMessage]:
        """加载会话的历史消息，转成 LangChain 消息列表。

        用于加载历史会话时，把数据库里的消息恢复成内存历史（供 ChatEngine 使用）。
        """
        messages = await self.backend.list_messages(session_id)
        return [self._to_langchain_message(m) for m in messages]

    async def generate_title(self, first_user_input: str, engine) -> str:
        """用 LLM 生成会话标题（C7）。

        参数：
            first_user_input: 用户的第一轮输入
            engine: ChatEngine 实例（用于调用 LLM）
        返回：
            生成的标题（10-20 字）。如果 LLM 调用失败，兜底截取前 30 字符。
        """
        title_prompt = [
            SystemMessage(
                content="请用 10-20 个字概括以下用户意图，作为对话标题。只输出标题，不要引号、不要其他内容。"
            ),
            HumanMessage(content=first_user_input),
        ]
        try:
            title, _ = engine.chat(title_prompt)
            # 清理：去掉可能的引号和换行
            title = title.strip().strip('"\'「」""').strip()
            # 限制长度
            if len(title) > 30:
                title = title[:30]
            return title if title else self._fallback_title(first_user_input)
        except Exception:
            # LLM 调用失败，兜底截取
            return self._fallback_title(first_user_input)

    def _fallback_title(self, text: str) -> str:
        """兜底标题：截取前 30 字符。"""
        max_len = self.config.title_max_length
        return text[:max_len] + ("..." if len(text) > max_len else "")

    async def update_title(self, session: Session, new_title: str) -> None:
        """修改会话标题（C4，对话中的 /rename 命令使用）。"""
        session.title = new_title.strip()
        await self.backend.update_session(session)

    async def update_session_model(self, session: Session, model_name: str) -> None:
        """更新会话使用的模型名（A5 会话内模型切换时使用）。

        参数：
            session: 要更新的会话
            model_name: 新模型名
        """
        session.model_name = model_name
        await self.backend.update_session(session)

    @staticmethod
    def _to_langchain_message(message: Message) -> BaseMessage:
        """把数据库的 Message 转成 LangChain 的消息类型。"""
        if message.role == "human":
            return HumanMessage(content=message.content)
        elif message.role == "ai":
            return AIMessage(content=message.content)
        else:  # system
            return SystemMessage(content=message.content)

    # ── 会话管理（Step 8 新增）──────────────────────────────────────────

    async def list_sessions(self, user_id: int, limit: int = 0, offset: int = 0) -> list[Session]:
        """列出指定用户的会话（C3 会话列表，支持分页）。

        按更新时间倒序排列（最近更新的在最前面）。

        参数：
            user_id: 用户 ID
            limit: 返回数量上限（0=不限制）
            offset: 跳过前 N 条（默认 0）
        返回：
            该用户的会话列表（按 id 倒序，最新的在前）
        """
        return await self.backend.list_sessions(user_id, limit=limit, offset=offset)

    async def get_session(self, session_id: int) -> Optional[Session]:
        """按 ID 查询单个会话（C2 加载历史会话）。

        参数：
            session_id: 会话 ID
        返回：
            Session 对象，或 None（不存在）
        """
        return await self.backend.get_session(session_id)

    async def rename_session(self, session_id: int, new_title: str) -> None:
        """重命名会话（C4 会话重命名）。

        参数：
            session_id: 会话 ID
            new_title: 新标题

        异常：
            ValueError: 标题为空 或 会话不存在
        """
        if not new_title or not new_title.strip():
            raise ValueError("标题不能为空")
        new_title = new_title.strip()

        session = await self.backend.get_session(session_id)
        if session is None:
            raise ValueError(f"会话 id={session_id} 不存在")

        session.title = new_title
        await self.backend.update_session(session)

    async def delete_session(self, session_id: int) -> None:
        """删除会话及其所有消息（C5 删除会话）。

        关联的消息靠数据库的 ON DELETE CASCADE 自动清理。

        参数：
            session_id: 会话 ID

        异常：
            ValueError: 会话不存在
        """
        session = await self.backend.get_session(session_id)
        if session is None:
            raise ValueError(f"会话 id={session_id} 不存在")

        await self.backend.delete_session(session_id)

    async def delete_all_sessions(self, user_id: int) -> int:
        """删除指定用户的全部会话及其所有消息。

        参数：
            user_id: 用户 ID
        返回：
            删除的会话数量
        """
        sessions = await self.backend.list_sessions(user_id)
        count = len(sessions)
        if count == 0:
            return 0
        await self.backend.delete_sessions_by_user(user_id)
        logger.info("删除用户 %d 的全部会话: %d 个", user_id, count)
        return count

    # ── 搜索与记录查看（Step 9 新增）─────────────────────────────────────

    async def search_messages(self, user_id: int, keyword: str) -> list[Message]:
        """在指定用户的所有会话中按关键词搜索消息（E1 对话搜索）。

        参数：
            user_id: 用户 ID（只搜该用户的消息，用户隔离）
            keyword: 搜索关键词
        返回：
            匹配的 Message 列表（按 id 正序，即时间正序）
        """
        if not keyword or not keyword.strip():
            return []
        keyword = keyword.strip()
        return await self.backend.search_messages(user_id, keyword)

    async def get_session_messages(self, session_id: int) -> list[Message]:
        """获取指定会话的全部消息（用于查看会话记录）。

        参数：
            session_id: 会话 ID
        返回：
            该会话的全部 Message 列表（按 id 正序，即时间正序）
        """
        return await self.backend.list_messages(session_id)

    # ── 导出（Step 10 新增）─────────────────────────────────────────────

    async def export_to_markdown(self, session_id: int, username: str) -> str:
        """把指定会话导出为 Markdown 文件（F1/F2）。

        参数：
            session_id: 要导出的会话 ID
            username: 当前用户名（用于构建导出路径）
        返回：
            导出文件的路径
        异常：
            ValueError: 会话不存在
        """
        from datetime import datetime
        from pathlib import Path

        session = await self.backend.get_session(session_id)
        if session is None:
            raise ValueError(f"会话 id={session_id} 不存在")

        messages = await self.backend.list_messages(session_id)

        # 构建 Markdown 内容
        lines = []
        lines.append(f"# {session.title}\n")
        lines.append(f"> 模型: {session.model_name} | 导出时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
        lines.append("---\n")

        for msg in messages:
            if msg.role == "human":
                lines.append(f"**用户**: {msg.content}\n")
            elif msg.role == "ai":
                lines.append(f"**AI**: {msg.content}\n")
            else:
                lines.append(f"**系统**: {msg.content}\n")

        lines.append("---\n")
        total_tokens = session.total_prompt_tokens + session.total_completion_tokens
        lines.append(f"> 共 {len(messages)} 条消息 | Token: 输入 {session.total_prompt_tokens}，输出 {session.total_completion_tokens}，总计 {total_tokens}\n")

        content = "\n".join(lines)

        # 构建导出路径：data/users/{username}/exports/{title}_{date}.md
        safe_title = "".join(c for c in session.title if c not in r'\/:*?"<>|')[:30]
        date_str = datetime.now().strftime("%Y%m%d")
        export_dir = Path("data/users") / username / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        file_path = export_dir / f"{safe_title}_{date_str}.md"

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)

        return str(file_path)
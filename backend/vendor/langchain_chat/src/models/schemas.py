"""数据模型定义（Pydantic BaseModel）。

本模块定义项目的核心数据结构，对应需求文档第四部分「数据实体设计」。
所有层（core / storage / ui）共用这些模型，保证数据形状全局一致。

模型清单：
    - User       用户
    - Session    会话
    - Message    消息（单轮对话内容）
    - Preset     预设角色
    - UserConfig 用户配置（键值对）
"""

from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────────────────────────────
# 辅助函数：生成当前 UTC 时间（统一时间源，便于将来多环境对齐）
# ─────────────────────────────────────────────────────────────────────────────
def _now() -> datetime:
    """返回带时区的当前 UTC 时间。

    使用 UTC 而非本地时间，原因：
        1. 多环境（dev/test/prod）可能跨时区，UTC 是唯一无歧义的基准。
        2. 数据库存储统一用 UTC，显示时再按用户时区转换。
    """
    return datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────────────────────
# 用户模型（对应 users 表）
# ─────────────────────────────────────────────────────────────────────────────
class User(BaseModel):
    """用户实体。

    对应需求文档 B1 至 B4（用户管理）与第四章 users 表。
    """

    id: int  # 主键
    username: str  # 用户名（唯一）
    default_model: Optional[str] = None  # 默认模型（可选）
    default_preset_id: Optional[int] = None  # 默认预设 ID（可选，外键）
    created_at: datetime = Field(default_factory=_now)  # 创建时间（自动）
    updated_at: datetime = Field(default_factory=_now)  # 更新时间（自动）


# ─────────────────────────────────────────────────────────────────────────────
# 会话模型（对应 sessions 表）
# ─────────────────────────────────────────────────────────────────────────────
class Session(BaseModel):
    """会话实体。

    对应需求文档 C1 至 C7（会话管理）与第四章 sessions 表。
    一个会话代表一次连续的多轮对话。
    """

    id: int  # 主键
    user_id: int  # 所属用户 ID（外键）
    title: str  # 会话标题
    model_name: str  # 使用的模型名
    preset_id: Optional[int] = None  # 使用的预设 ID（可选，外键）
    total_prompt_tokens: int = 0  # 累计输入 token
    total_completion_tokens: int = 0  # 累计输出 token
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


# ─────────────────────────────────────────────────────────────────────────────
# 消息模型（对应 messages 表）
# ─────────────────────────────────────────────────────────────────────────────
# 角色类型：限定为三种合法取值，防止写入非法角色
# 特别说明：此处不涉及 tool_message，因为当前项目无需用到工具调用
MessageRole = Literal["human", "ai", "system"]


class Message(BaseModel):
    """单条消息实体。

    对应需求文档第四章 messages 表。
    一轮对话产生两条消息：一条 human（用户说的），一条 ai（模型回复的）。
    """

    id: int  # 主键
    session_id: int  # 所属会话 ID（外键）
    role: MessageRole  # 角色：human/ai/system
    content: str  # 消息内容
    prompt_tokens: int = 0  # 本条输入 token 数
    completion_tokens: int = 0  # 本条输出 token 数
    created_at: datetime = Field(default_factory=_now)


# ─────────────────────────────────────────────────────────────────────────────
# 预设模型（对应 presets 表）
# ─────────────────────────────────────────────────────────────────────────────
class Preset(BaseModel):
    """预设角色实体。

    对应需求文档 D1 至 D4（预设 Prompt 管理）与第四章 presets 表。
    user_id 为 None 表示系统内置预设（所有用户共享）。
    """

    id: int  # 主键
    user_id: Optional[int] = None  # 所属用户 ID（None=系统内置）
    name: str  # 预设名称
    description: str = ""  # 一句话描述
    system_prompt: str  # 系统提示词（定义 AI 角色）
    is_builtin: bool = False  # 是否系统内置
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


# ─────────────────────────────────────────────────────────────────────────────
# 用户配置模型（对应 user_configs 表）
# ─────────────────────────────────────────────────────────────────────────────
class UserConfig(BaseModel):
    """用户配置键值对实体。

    对应需求文档第四章 user_configs 表。
    用于存储用户个性化偏好（如主题、快捷键等），以键值对形式灵活扩展。
    """

    id: int  # 主键
    user_id: int  # 所属用户 ID（外键）
    key: str  # 配置键
    value: str  # 配置值
    updated_at: datetime = Field(default_factory=_now)

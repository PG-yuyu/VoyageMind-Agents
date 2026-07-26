"""配置管理 —— 所有配置通过环境变量读取，避免硬编码。"""

import os
from dataclasses import dataclass, field
from pathlib import Path


def _load_dotenv() -> None:
    """Load a local .env file without adding another runtime dependency."""
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().lstrip("\ufeff")
        value = value.strip().strip('"').strip("'")
        os.environ[key] = value


@dataclass
class Settings:
    """全局配置，从环境变量加载。"""

    # ── LLM Provider (DeepSeek / OpenAI 兼容 API) ──
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-chat"
    llm_temperature: float = 0.3
    llm_max_tokens: int = 4096
    llm_timeout: int = 60

    # ── Document Chunking ──
    chunk_size: int = 500
    chunk_overlap: int = 50

    # ── Retrieval Defaults ──
    default_top_k: int = 10
    default_max_hops: int = 2

    # ── Reranking ──
    rerank_top_k: int = 10

    # ── Logging ──
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "Settings":
        """从环境变量构建 Settings 实例。"""
        _load_dotenv()
        return cls(
            llm_api_key=os.getenv("LLM_API_KEY", ""),
            llm_base_url=os.getenv("LLM_BASE_URL", "https://api.deepseek.com"),
            llm_model=os.getenv("LLM_MODEL", "deepseek-chat"),
            llm_temperature=float(os.getenv("LLM_TEMPERATURE", "0.3")),
            llm_max_tokens=int(os.getenv("LLM_MAX_TOKENS", "4096")),
            llm_timeout=int(os.getenv("LLM_TIMEOUT", "60")),
            chunk_size=int(os.getenv("RAG_CHUNK_SIZE", "500")),
            chunk_overlap=int(os.getenv("RAG_CHUNK_OVERLAP", "50")),
            default_top_k=int(os.getenv("RAG_TOP_K", "10")),
            default_max_hops=int(os.getenv("RAG_DEFAULT_MAX_HOPS", "2")),
            rerank_top_k=int(os.getenv("RAG_RERANK_TOP_K", "10")),
            log_level=os.getenv("RAG_LOG_LEVEL", "INFO"),
        )


# 模块级单例（工厂函数也可传入自定义 Settings）
_default_settings: Settings | None = None


def get_settings() -> Settings:
    """获取全局 Settings 单例。"""
    global _default_settings
    if _default_settings is None:
        _default_settings = Settings.from_env()
    return _default_settings

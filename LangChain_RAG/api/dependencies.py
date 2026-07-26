"""FastAPI 依赖注入 —— 构建并缓存 BackendService 单例。"""

import logging
from functools import lru_cache

from rag import create_backend_service
from rag.config import Settings, get_settings

logger = logging.getLogger("api.dependencies")


@lru_cache(maxsize=1)
def _cached_backend_service():
    """创建并缓存 BackendService 实例（只初始化一次）。"""
    logger.info("Initializing BackendService singleton...")
    return create_backend_service()


def get_backend_service():
    """FastAPI 依赖：获取 BackendService 实例。"""
    return _cached_backend_service()


def get_app_settings() -> Settings:
    """FastAPI 依赖：获取应用配置。"""
    return get_settings()

"""配置加载与管理。

本模块负责读取并合并多个配置源：
    1. .env 文件：各服务商的 API Key、默认模型名。
    2. config.yaml 文件：基础业务配置（所有环境共享）。
    3. config.{APP_ENV}.yaml 文件：环境覆盖配置（Step 15 多环境区分）。

合并规则（Step 15）：
    最终配置 = config.yaml（基础） + config.{APP_ENV}.yaml（环境覆盖）
    环境覆盖文件只写「与基础配置不同的字段」，合并时深度覆盖。

Step 10 重构：从单一服务商改为多服务商分组（providers 结构）。
Step 15 新增：多环境区分（dev/test/prod）。
"""

import copy
import os
from pathlib import Path
from typing import Any, Optional

import yaml
from dotenv import load_dotenv


def _load_env():
    """加载 .env 文件到环境变量。

    Step 15 多环境：根据 APP_ENV 加载对应的 .env 文件。
    执行顺序：
        1. 先加载基础 .env（含 APP_ENV 的设置）
        2. 再从环境变量读 APP_ENV（此时 .env 的值已生效）
        3. 加载环境特定 .env.{APP_ENV}
    """
    # 第 1 步：先加载基础 .env（此时 .env 里的 APP_ENV 会被加载到环境变量）
    env_path = Path(".env")
    if env_path.exists():
        load_dotenv(env_path, override=True)

    # 第 2 步：读 APP_ENV（优先级：命令行 > .env）
    app_env = os.environ.get("APP_ENV", "dev")

    # 第 3 步：加载环境特定 .env（如果存在，覆盖基础）
    env_specific = Path(f".env.{app_env}")
    if env_specific.exists():
        load_dotenv(env_specific, override=True)


_load_env()


def get_config_value(env_key: str, default: str = "") -> str:
    """从环境变量读取配置值。"""
    return os.environ.get(env_key, default)


def _deep_merge(base: dict, override: dict) -> dict:
    """深度合并两个字典。override 的值覆盖 base 的同名键。

    对于嵌套字典，递归合并（而非整体替换）。
    对于非字典值，override 直接覆盖 base。

    示例：
        base = {"storage": {"type": "sqlite", "path": "a.db"}}
        override = {"storage": {"type": "mysql"}}
        结果 = {"storage": {"type": "mysql", "path": "a.db"}}
    """
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


class AppConfig:
    """应用配置（单例）。

    封装 .env（敏感配置）与 config.yaml + config.{APP_ENV}.yaml（业务配置）。
    通过 get_config() 全局访问。
    """

    def __init__(self) -> None:
        # 当前环境（Step 15）
        self.app_env: str = os.environ.get("APP_ENV", "dev")

        # 加载基础配置（config.yaml）
        base_config = self._load_yaml("config.yaml")

        # 加载环境覆盖配置（config.{APP_ENV}.yaml），合并
        env_config_file = f"config.{self.app_env}.yaml"
        env_config = self._load_yaml(env_config_file)

        # 深度合并：环境覆盖 > 基础
        self._yaml_config: dict[str, Any] = _deep_merge(base_config, env_config)

    def _load_yaml(self, filename: str) -> dict[str, Any]:
        """读取 YAML 配置文件，返回字典。"""
        path = Path(filename)
        if not path.exists():
            return {}
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else {}

    # ── 敏感配置（从 .env 读取）─────────────────────────────────────────

    @property
    def default_model(self) -> str:
        """默认模型名（从 .env 的 DEFAULT_MODEL 读取）。"""
        return get_config_value("DEFAULT_MODEL", "qwen3.6-flash")

    def get_api_key(self, env_key: str) -> str:
        """按变量名从 .env 读取 API Key。"""
        return get_config_value(env_key, "")

    # ── 服务商配置（从 config.yaml 的 providers 读取）────────────────────

    @property
    def providers(self) -> list[dict]:
        """所有服务商配置列表。"""
        return self._yaml_config.get("providers", [])

    def get_all_models(self) -> list[dict[str, str]]:
        """获取所有服务商下的全部模型（扁平化列表）。

        返回格式: [{"name": "显示名", "value": "模型标识", "provider": "服务商名"}, ...]
        """
        result = []
        for provider in self.providers:
            for model in provider.get("models", []):
                result.append(
                    {
                        "name": model.get("name", model.get("value", "")),
                        "value": model.get("value", ""),
                        "provider": provider.get("name", ""),
                    }
                )
        return result

    def find_provider_by_model(self, model_value: str) -> Optional[dict]:
        """按模型标识查找所属服务商配置。

        参数：
            model_value: 模型标识（如 qwen3.6-flash）
        返回：
            服务商配置字典，或 None（模型不存在）
        """
        for provider in self.providers:
            for model in provider.get("models", []):
                if model.get("value") == model_value:
                    return provider
        return None

    # ── 生成参数（从 config.yaml 顶层读取）──────────────────────────────

    @property
    def temperature(self) -> float:
        """生成温度（范围 0 到 2。0=最确定，2=最随机，本项目默认 0.7）。"""
        return self._yaml_config.get("temperature", 0.7)

    @property
    def max_tokens(self) -> int:
        """单次回复最大 token 数。"""
        return self._yaml_config.get("max_tokens", 2048)

    # ── 其他配置 ────────────────────────────────────────────────────────

    @property
    def current_step(self) -> str:
        """当前开发步骤（横幅显示用）。"""
        return self._yaml_config.get("app", {}).get("current_step", "开发中")

    @property
    def storage_type(self) -> str:
        """存储后端类型。"""
        return self._yaml_config.get("storage", {}).get("type", "sqlite")

    @property
    def llm_timeout(self) -> int:
        """LLM 调用超时（秒）。"""
        return self._yaml_config.get("llm", {}).get("timeout", 30)

    @property
    def llm_max_retries(self) -> int:
        """LLM 最大重试次数。"""
        return self._yaml_config.get("llm", {}).get("max_retries", 3)

    @property
    def title_max_length(self) -> int:
        """会话标题自动截断长度。"""
        return self._yaml_config.get("session", {}).get("title_max_length", 30)

    # ── 安全配置（Step 16 新增）─────────────────────────────────────────

    @property
    def max_input_length(self) -> int:
        """用户单次输入最大字符数。"""
        return self._yaml_config.get("security", {}).get("max_input_length", 5000)

    @property
    def context_max_tokens(self) -> int:
        """发送给 LLM 的上下文最大 Token 数（滑动窗口 + Token 计数）。"""
        return self._yaml_config.get("security", {}).get("context_max_tokens", 4000)

    def get(self, *keys: str, default: Any = None) -> Any:
        """按层级键路径读取业务配置。"""
        value: Any = self._yaml_config
        for key in keys:
            if not isinstance(value, dict):
                return default
            value = value.get(key)
            if value is None:
                return default
        return value


# ── 全局单例 ────────────────────────────────────────────────────────────
_config_instance: Optional[AppConfig] = None


def get_config() -> AppConfig:
    """获取全局配置实例（单例）。"""
    global _config_instance
    if _config_instance is None:
        _config_instance = AppConfig()
    return _config_instance

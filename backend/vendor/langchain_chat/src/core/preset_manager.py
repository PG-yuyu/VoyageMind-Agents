"""预设管理业务层。

封装预设相关的业务逻辑：加载内置预设、查看、新增、编辑、删除。
对应需求文档 D1 至 D4（预设 Prompt 管理）。

设计说明：
    - 系统内置预设（is_builtin=True）从 config/presets.yaml 导入，只读，所有用户共享。
    - 用户自定义预设（is_builtin=False）可增删改，归属当前用户。
    - 列出预设时，合并显示内置预设和当前用户的自定义预设。
"""

from pathlib import Path
from typing import Optional

import yaml

from models.schemas import Preset
from storage.base import StorageBackend


class PresetManager:
    """预设管理器。

    通过传入的 StorageBackend 实例操作数据。
    使用方式：
        mgr = PresetManager(backend)
        await mgr.load_builtin_presets()   # 启动时导入内置预设
        presets = await mgr.list_presets(user_id)
    """

    # 内置预设 YAML 文件路径（相对于运行目录）
    BUILTIN_PRESETS_FILE = "config/presets.yaml"

    def __init__(self, backend: StorageBackend):
        self.backend = backend

    # ── 内置预设加载 ──────────────────────────────────────────────────────

    async def load_builtin_presets(self) -> int:
        """从 config/presets.yaml 导入系统内置预设。

        幂等：基于 name 去重，已存在的同名内置预设不重复导入。
        返回：本次新导入的预设数量。
        """
        # 1. 读取 YAML 文件
        path = Path(self.BUILTIN_PRESETS_FILE)
        if not path.exists():
            print(f"[预设] 内置预设文件 {self.BUILTIN_PRESETS_FILE} 不存在，跳过导入")
            return 0

        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if not data or "presets" not in data:
            print(f"[预设] 内置预设文件格式异常，无 presets 字段")
            return 0

        # 2. 查询已存在的内置预设名（用于去重）
        existing_builtin = await self._get_builtin_preset_names()

        # 3. 逐个导入（跳过已存在的）
        imported = 0
        for item in data["presets"]:
            name = item.get("name", "").strip()
            if not name or name in existing_builtin:
                continue    # 名字为空或已存在，跳过

            preset = Preset(
                id=0,
                user_id=None,                     # None 表示系统内置
                name=name,
                description=item.get("description", ""),
                system_prompt=item.get("system_prompt", ""),
                is_builtin=True,
            )
            await self.backend.save_preset(preset)
            imported += 1

        return imported

    async def _get_builtin_preset_names(self) -> set[str]:
        """获取已存在的内置预设名集合（用于去重）。

        内置预设 user_id 为 None，不属于任何用户。
        这里传 user_id=0（不存在的用户），list_presets 会返回所有内置预设。
        """
        all_presets = await self.backend.list_presets(user_id=0)
        return {p.name for p in all_presets if p.is_builtin}

    # ── 查询 ──────────────────────────────────────────────────────────────

    async def list_presets(self, user_id: int) -> list[Preset]:
        """列出内置预设 + 指定用户的自定义预设。"""
        return await self.backend.list_presets(user_id)

    async def get_preset(self, preset_id: int) -> Optional[Preset]:
        """按 ID 查询单个预设（含内置和所有用户的自定义）。不存在返回 None。"""
        return await self.backend.get_preset_by_id(preset_id)

    # ── 用户自定义预设的增删改 ────────────────────────────────────────────

    async def create_preset(
        self, user_id: int, name: str, description: str, system_prompt: str
    ) -> Preset:
        """创建用户自定义预设（D2）。

        异常：
            ValueError: 名字为空 / system_prompt 为空 / 名字与内置预设冲突
        """
        if not name or not name.strip():
            raise ValueError("预设名不能为空")
        name = name.strip()

        if not system_prompt or not system_prompt.strip():
            raise ValueError("系统提示词不能为空")

        # 检查名字是否与内置预设冲突
        builtin_names = await self._get_builtin_preset_names()
        if name in builtin_names:
            raise ValueError(f"预设名 '{name}' 与内置预设冲突，请换个名字")

        preset = Preset(
            id=0,
            user_id=user_id,
            name=name,
            description=description.strip(),
            system_prompt=system_prompt.strip(),
            is_builtin=False,
        )
        return await self.backend.save_preset(preset)

    async def update_preset(
        self, preset: Preset, name: str, description: str, system_prompt: str
    ) -> Preset:
        """更新自定义预设。preset 必须是已有的自定义预设。

        异常：
            ValueError: 试图修改内置预设 / 名字为空 / system_prompt 为空
        """
        if preset.is_builtin:
            raise ValueError("内置预设不允许修改")

        if not name or not name.strip():
            raise ValueError("预设名不能为空")
        if not system_prompt or not system_prompt.strip():
            raise ValueError("系统提示词不能为空")

        preset.name = name.strip()
        preset.description = description.strip()
        preset.system_prompt = system_prompt.strip()
        return await self.backend.save_preset(preset)

    async def delete_preset(self, preset_id: int) -> None:
        """删除自定义预设（仅允许删除非内置的）。

        异常：
            ValueError: 试图删除内置预设
        """
        preset = await self.get_preset(preset_id)
        if preset is None:
            raise ValueError("预设不存在")

        if preset.is_builtin:
            raise ValueError("内置预设不允许删除")

        await self.backend.delete_preset(preset_id)
"""UI 协议（接口定义）。

定义 UI 层必须实现的接口规范，让业务层与 UI 层解耦。
对应需求文档 H1（WebUI 接口预留）：TUI 与 WebUI 通过实现同一接口对接业务层。

设计说明：
    - AbstractUI 定义了 UI 必须实现的方法。
    - TUI（本步骤）和未来 WebUI 都继承这个接口。
    - 业务层（core）只依赖 AbstractUI，不依赖具体的 TUI 或 WebUI。
"""

from abc import ABC, abstractmethod
from typing import Optional


class AbstractUI(ABC):
    """UI 抽象基类。

    所有 UI 实现（TUIApp、未来 WebUIApp）必须继承本类并实现所有方法。
    这样业务层可以面向 AbstractUI 编程，不关心具体是 TUI 还是 WebUI。
    """

    @abstractmethod
    async def display_message(self, role: str, content: str) -> None:
        """显示一条消息（用户的或 AI 的）。

        参数：
            role: 消息角色（human / ai / system）
            content: 消息内容
        """
        ...

    @abstractmethod
    async def get_user_input(self, prompt_text: str = "") -> str:
        """获取用户输入。

        参数：
            prompt_text: 输入提示文字
        返回：
            用户输入的文本
        """
        ...

    @abstractmethod
    async def display_menu(self, title: str, options: list[str]) -> int:
        """显示菜单并获取用户选择。

        参数：
            title: 菜单标题
            options: 选项列表
        返回：
            用户选择的序号（从 0 开始）
        """
        ...

    @abstractmethod
    async def display_error(self, message: str) -> None:
        """显示错误信息（以醒目方式）。"""
        ...

    @abstractmethod
    async def display_info(self, message: str) -> None:
        """显示普通提示信息。"""
        ...

    @abstractmethod
    async def run(self) -> None:
        """启动 UI 主循环。"""
        ...
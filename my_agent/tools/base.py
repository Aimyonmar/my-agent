"""工具基类与注册表：把普通 Python 能力包装成模型可调用的「函数」。"""

from __future__ import annotations

from abc import ABC, abstractmethod


class Tool(ABC):
    """一个可被模型调用的工具。

    子类需要声明：
      name        工具名（模型用它发起调用，全局唯一）
      description 告诉模型这个工具能干什么、什么时候用
      parameters  参数的 JSON Schema
    并实现 execute()，返回值是喂回给模型的纯文本。
    """

    name: str = ""
    description: str = ""
    parameters: dict = {}

    @abstractmethod
    async def execute(self, **kwargs) -> str:
        """执行工具。任何异常都不该从这里抛出——
        把错误信息拼成文本返回，让模型自己决定怎么修正。"""

    def to_spec(self) -> dict:
        """转成 OpenAI 协议要求的工具定义格式。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"工具重名：{tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def specs(self) -> list[dict]:
        return [t.to_spec() for t in self._tools.values()]

    def __iter__(self):
        return iter(self._tools.values())

    def __len__(self) -> int:
        return len(self._tools)

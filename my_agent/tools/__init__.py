"""内置工具集：注册即用。"""

from __future__ import annotations

from pathlib import Path

from .base import Tool, ToolRegistry
from .calc import CalculateTool
from .files import ListDirTool, ReadFileTool, WriteFileTool
from .shell import ShellTool


def build_registry(workspace: Path) -> ToolRegistry:
    """创建注册表并装入基础三件套（共 5 个工具）。"""
    registry = ToolRegistry()
    for tool in (
        CalculateTool(),
        ListDirTool(workspace),
        ReadFileTool(workspace),
        WriteFileTool(workspace),
        ShellTool(workspace),
    ):
        registry.register(tool)
    return registry


__all__ = ["Tool", "ToolRegistry", "build_registry"]

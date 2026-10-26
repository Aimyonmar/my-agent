"""内置工具集：注册即用。

main 分支 = 基础五件套（空壳核心）；
feat/business-tools 分支 = 追加业务四件套（sql_exec / excel 读写 / webhook / http_fetch）。
"""

from __future__ import annotations

from pathlib import Path

from .base import Tool, ToolRegistry, WorkspaceTool
from .calc import CalculateTool
from .db import SqlExecTool
from .excel import ExcelReadTool, ExcelWriteTool
from .fetch import HttpFetchTool
from .files import ListDirTool, ReadFileTool, WriteFileTool
from .shell import ShellTool
from .webhook import WebhookNotifyTool


def build_registry(workspace: Path) -> ToolRegistry:
    """创建注册表并装入全部工具（基础五件套 + 业务四件套，共 10 个）。"""
    registry = ToolRegistry()
    for tool in (
        # ---- 基础五件套（main 分支即有）----
        CalculateTool(),
        ListDirTool(workspace),
        ReadFileTool(workspace),
        WriteFileTool(workspace),
        ShellTool(workspace),
        # ---- 业务四件套（feat/business-tools 分支新增）----
        SqlExecTool(workspace),
        ExcelReadTool(workspace),
        ExcelWriteTool(workspace),
        WebhookNotifyTool(),
        HttpFetchTool(),
    ):
        registry.register(tool)
    return registry


__all__ = ["Tool", "ToolRegistry", "WorkspaceTool", "build_registry"]

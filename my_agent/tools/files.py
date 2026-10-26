"""文件三件套：list_dir / read_file / write_file。

所有路径都被限制在 workspace 目录内，
目录穿越（如 ../../etc/passwd、绝对路径）会被直接拒绝。
"""

from __future__ import annotations

from pathlib import Path

from .base import Tool

_MAX_READ_CHARS = 20_000      # 读取内容上限，防止把模型上下文撑爆
_MAX_WRITE_CHARS = 50_000
_MAX_LIST_ENTRIES = 200


class _WorkspaceTool(Tool):
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()

    def resolve_in_workspace(self, path: str) -> Path:
        """把用户/模型给的路径规范化到 workspace 内，越界即拒绝。"""
        p = (self.workspace / path).resolve()
        if p != self.workspace and self.workspace not in p.parents:
            raise ValueError(f"路径越界，只允许访问 {self.workspace} 内的文件：{path!r}")
        return p


class ListDirTool(_WorkspaceTool):
    name = "list_dir"
    description = "列出某个目录下的文件和子目录。path 省略时列出工作区根目录。"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "相对工作区根目录的路径，默认 '.'"},
        },
    }

    async def execute(self, path: str = ".") -> str:
        try:
            target = self.resolve_in_workspace(path)
            if not target.is_dir():
                return f"ERROR: 不是目录或不存在：{path!r}"
            entries = sorted(
                target.iterdir(), key=lambda p: (p.is_file(), p.name.lower())
            )
            lines = []
            for i, entry in enumerate(entries):
                if i >= _MAX_LIST_ENTRIES:
                    lines.append(f"…（已截断，共 {len(entries)} 项）")
                    break
                if entry.is_dir():
                    lines.append(f"[dir]  {entry.name}/")
                else:
                    lines.append(f"[file] {entry.name}  ({_human_size(entry.stat().st_size)})")
            return "\n".join(lines) or "(空目录)"
        except (ValueError, OSError) as exc:
            return f"ERROR: {exc}"


class ReadFileTool(_WorkspaceTool):
    name = "read_file"
    description = "读取一个文本文件的内容（二进制文件不支持）。"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "相对工作区根目录的文件路径"},
        },
        "required": ["path"],
    }

    async def execute(self, path: str) -> str:
        try:
            target = self.resolve_in_workspace(path)
            if not target.exists():
                return f"ERROR: 文件不存在：{path!r}"
            if target.is_dir():
                return f"ERROR: {path!r} 是目录，请用 list_dir"
            if b"\x00" in target.read_bytes()[:1024]:
                return f"ERROR: {path!r} 疑似二进制文件，不支持读取"
            text = target.read_text(encoding="utf-8", errors="replace")
            if len(text) > _MAX_READ_CHARS:
                return text[:_MAX_READ_CHARS] + f"\n…（内容过长，已截断，全文 {len(text)} 字符）"
            return text or "(空文件)"
        except (ValueError, OSError) as exc:
            return f"ERROR: {exc}"


class WriteFileTool(_WorkspaceTool):
    name = "write_file"
    description = "把文本内容写入文件（覆盖写入，父目录不存在会自动创建）。"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "相对工作区根目录的文件路径"},
            "content": {"type": "string", "description": "要写入的完整文本内容"},
        },
        "required": ["path", "content"],
    }

    async def execute(self, path: str, content: str) -> str:
        try:
            if len(content) > _MAX_WRITE_CHARS:
                return f"ERROR: 内容过长（{len(content)} 字符，上限 {_MAX_WRITE_CHARS}）"
            target = self.resolve_in_workspace(path)
            if target == self.workspace:
                return "ERROR: 不能把整个工作区当作文件写入"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            rel = target.relative_to(self.workspace)
            return f"OK: 已写入 {len(content)} 字符 -> {rel}"
        except (ValueError, OSError) as exc:
            return f"ERROR: {exc}"


def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"

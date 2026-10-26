"""run_shell：执行系统命令（Windows 下经 cmd.exe）。

注意：黑名单只是防呆，不是沙箱。
这个工具天生有风险，只应在自己信任的环境里运行。
"""

from __future__ import annotations

import asyncio
import locale
import re
from pathlib import Path

from .base import Tool

# 粗粒度危险命令黑名单（防手滑，不防恶意模型）
_DENY_PATTERNS = [
    r"rm\s+(-\w+\s+)*-{0,1}\w*r\w*f",   # rm -rf / rm -fr
    r"\bformat\s+[a-z]:",               # format c:
    r"\bshutdown\b",
    r"\breboot\b",
    r"\bmkfs\b",
    r"\brd\s+/s",
    r"\bdel\s+/[fqs]",
    r"\bdiskpart\b",
    r"reg\s+(delete|add)\b",
    r"remove-item\b[^|;&]*-recurse[^|;&]*-force",
    r":\(\)\s*\{[^}]*\}",               # fork bomb 雏形 :(){ ... };
    r">\s*/dev/sd",
]
_DENY_RE = [re.compile(p, re.IGNORECASE) for p in _DENY_PATTERNS]

_MAX_OUTPUT_CHARS = 8_000
_DEFAULT_TIMEOUT = 30.0
_MAX_TIMEOUT = 120.0


class ShellTool(Tool):
    name = "run_shell"
    description = (
        "在系统 shell 中执行一条命令（Windows 为 cmd）并返回输出。"
        "适合：查看目录、git 操作、跑 python 脚本等。"
        "命令会在工作区目录下执行，默认 30 秒超时。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "要执行的命令"},
            "timeout": {"type": "number", "description": "超时秒数，默认 30，最大 120"},
        },
        "required": ["command"],
    }

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()

    async def execute(self, command: str, timeout: float = _DEFAULT_TIMEOUT) -> str:
        command = command.strip()
        if not command:
            return "ERROR: 命令为空"
        for pattern in _DENY_RE:
            if pattern.search(command):
                return f"ERROR: 命令命中安全黑名单，已拒绝执行：{command!r}"
        try:
            timeout = max(1.0, min(float(timeout), _MAX_TIMEOUT))
        except (TypeError, ValueError):
            timeout = _DEFAULT_TIMEOUT

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                cwd=str(self.workspace),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except OSError as exc:
            return f"ERROR: 无法启动子进程：{exc}"

        try:
            raw, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return f"ERROR: 命令超过 {timeout:.0f}s 未完成，已终止。"

        encoding = locale.getpreferredencoding(False) or "utf-8"
        out = (raw or b"").decode(encoding, errors="replace").strip()
        if len(out) > _MAX_OUTPUT_CHARS:
            out = out[:_MAX_OUTPUT_CHARS] + f"\n…（输出过长，已截断，全文 {len(out)} 字符）"
        return f"[exit code {proc.returncode}]\n{out or '(无输出)'}"

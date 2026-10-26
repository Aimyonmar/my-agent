"""CLI 交互式 REPL：只负责交互与展示，不含业务逻辑。"""

from __future__ import annotations

import asyncio
import json

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from . import __version__
from .agent import Agent
from .config import Config
from .llm import LLMError, ToolCall

_TOOL_RESULT_PREVIEW = 600


class Repl:
    def __init__(
        self, agent: Agent, config: Config, console: Console | None = None
    ) -> None:
        self.agent = agent
        self.config = config
        self.console = console or Console()

    # ---- 生命周期 -------------------------------------------------------

    def run(self) -> None:
        asyncio.run(self.run_async())

    async def run_async(self) -> None:
        self._print_banner()
        while True:
            try:
                line = self.console.input("\n[bold green]你 ›[/bold green] ")
            except (EOFError, KeyboardInterrupt):
                self.console.print("再见。")
                return
            line = line.strip()
            if not line:
                continue
            if line.startswith("/"):
                if self._command(line):
                    return
                continue
            await self._turn(line)

    # ---- 一轮对话 ---------------------------------------------------------

    async def _turn(self, text: str) -> None:
        self.console.print("[bold cyan]agent ›[/bold cyan]")
        try:
            answer = await self.agent.run(
                text,
                on_text=self._on_text,
                on_tool_start=self._on_tool_start,
                on_tool_end=self._on_tool_end,
            )
        except LLMError as exc:
            self.agent.rollback()
            self.console.print(
                Panel(Text(str(exc)), title="模型调用失败", border_style="red")
            )
            self.console.print(
                "[dim]本轮已回滚。请检查 .env 中 API Key / base_url 是否配置正确"
                "（模板见 .env.example）。[/dim]"
            )
            return
        except KeyboardInterrupt:
            self.agent.rollback()
            self.console.print("\n[yellow]已中断，本轮对话已回滚。[/yellow]")
            return
        if not answer:
            self.console.print("[dim](模型没有返回文本内容)[/dim]")
        self.console.print()

    # ---- 流式与工具事件回调 ---------------------------------------------

    def _on_text(self, delta: str) -> None:
        self.console.print(
            delta, end="", markup=False, highlight=False, soft_wrap=True
        )

    def _on_tool_start(self, call: ToolCall) -> None:
        self.console.print(
            Panel(
                Syntax(
                    _pretty_json(call.arguments), "json",
                    theme="ansi_dark", word_wrap=True,
                ),
                title=f"调用工具  {call.name}",
                border_style="cyan",
                padding=(0, 1),
            )
        )

    def _on_tool_end(self, call: ToolCall, output: str) -> None:
        preview = (
            output
            if len(output) <= _TOOL_RESULT_PREVIEW
            else output[:_TOOL_RESULT_PREVIEW] + " …"
        )
        self.console.print(
            Panel(
                Text(preview),
                title=f"工具结果  {call.name}",
                border_style="dim",
                padding=(0, 1),
            )
        )

    # ---- 斜杠命令 -----------------------------------------------------------

    def _command(self, line: str) -> bool:
        """处理 / 命令；返回 True 表示退出 REPL。"""
        cmd = line.split(maxsplit=1)[0].lower()
        if cmd in ("/quit", "/exit", "/q"):
            self.console.print("再见。")
            return True
        if cmd == "/help":
            self.console.print(
                "[bold]/help[/bold]    显示本帮助\n"
                "[bold]/tools[/bold]   查看内置工具\n"
                "[bold]/model[/bold]   查看当前模型配置\n"
                "[bold]/history[/bold] 查看下一轮将发给模型的完整 messages\n"
                "[bold]/clear[/bold]   清空对话历史\n"
                "[bold]/quit[/bold]    退出"
            )
        elif cmd == "/history":
            if not self.agent.history:
                self.console.print("对话历史为空，先聊两句再来。")
            else:
                msgs = [
                    {"role": "system", "content": self.agent.system_prompt},
                    *self.agent.history,
                ]
                self.console.print(
                    Panel(
                        Syntax(
                            json.dumps(msgs, ensure_ascii=False, indent=2),
                            "json",
                            theme="ansi_dark",
                            word_wrap=True,
                        ),
                        title=f"下一轮请求将携带的完整 messages（{len(msgs)} 条）",
                        border_style="dim",
                        padding=(0, 1),
                    )
                )
        elif cmd == "/tools":
            table = Table(title=f"内置工具（{len(self.agent.tools)} 个）")
            table.add_column("工具", style="cyan", no_wrap=True)
            table.add_column("参数", style="dim")
            table.add_column("说明", overflow="fold")
            for tool in self.agent.tools:
                params = "、".join(tool.parameters.get("properties", {})) or "-"
                table.add_row(tool.name, params, tool.description)
            self.console.print(table)
        elif cmd == "/model":
            self.console.print(
                Panel(self.config.describe(), title="当前配置", padding=(0, 1))
            )
        elif cmd == "/clear":
            self.agent.reset()
            self.console.print("已清空对话历史。")
        else:
            self.console.print(f"未知命令 {cmd}，输入 [bold]/help[/bold] 查看可用命令。")
        return False

    # ---- 启动横幅 -------------------------------------------------------------

    def _print_banner(self) -> None:
        tool_names = "、".join(t.name for t in self.agent.tools)
        self.console.print(
            Panel(
                f"[bold]my-agent[/bold] v{__version__} —— 手搓 Agent 实验场\n\n"
                f"接入：{self.config.provider} / {self.config.model}\n"
                f"工具：{tool_names}\n\n"
                f"直接输入问题开始对话；输入 [bold]/help[/bold] 查看命令。",
                border_style="cyan",
                padding=(0, 1),
            )
        )
        if not self.config.key_ready:
            self.console.print(
                "[yellow]注意：API Key 未配置。"
                "请复制 .env.example 为 .env 并填入密钥。[/yellow]"
            )


def _pretty_json(raw: str) -> str:
    try:
        return json.dumps(json.loads(raw or "{}"), ensure_ascii=False, indent=2)
    except json.JSONDecodeError:
        return raw or "{}"

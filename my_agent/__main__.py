"""入口：python -m my_agent [--check]"""

from __future__ import annotations

import argparse
import asyncio

from rich.console import Console

from . import __version__
from .config import WORKSPACE_DIR, load_config


def main() -> int:
    parser = argparse.ArgumentParser(prog="my_agent", description="手搓 CLI Agent")
    parser.add_argument(
        "--check", action="store_true", help="离线自检：验证配置与工具，不调用模型"
    )
    parser.add_argument("--version", action="version", version=f"my-agent {__version__}")
    args = parser.parse_args()

    console = Console()

    if args.check:
        try:
            return asyncio.run(_self_check(console))
        except KeyboardInterrupt:
            return 130

    try:
        config = load_config()
    except ValueError as exc:
        console.print(f"[red]配置错误：{exc}[/red]")
        return 1

    from .agent import Agent
    from .llm import LLMClient
    from .repl import Repl
    from .tools import build_registry

    llm = LLMClient(config)
    agent = Agent(llm, build_registry(WORKSPACE_DIR), config)

    async def _amain() -> None:
        try:
            await Repl(agent, config, console).run_async()
        finally:
            await llm.aclose()

    try:
        asyncio.run(_amain())
    except KeyboardInterrupt:
        pass
    return 0


async def _self_check(console: Console) -> int:
    """离线自检：验证配置加载与全部工具的行为，不发起任何网络请求。"""
    from .tools import build_registry

    try:
        config = load_config()
    except ValueError as exc:
        console.print(f"FAIL 配置加载：{exc}")
        return 1

    key_state = "已配置" if config.key_ready else "未配置（正式对话前需在 .env 填入）"
    console.print(
        f"PASS 配置加载：provider={config.provider}  "
        f"model={config.model}  key={key_state}"
    )

    registry = build_registry(WORKSPACE_DIR)
    cases = [
        ("calculate", {"expression": "(1+2)*3.5"}, "10.5"),
        ("calculate", {"expression": "2**10"}, "1024"),
        ("calculate", {"expression": "__import__('os').system('dir')"}, "ERROR"),
        ("read_file", {"path": "../outside.txt"}, "ERROR"),
        ("write_file", {"path": "tmp_selfcheck.txt", "content": "hello agent"}, "OK"),
        ("read_file", {"path": "tmp_selfcheck.txt"}, "hello agent"),
        ("list_dir", {"path": "."}, None),
        ("run_shell", {"command": "echo agent-shell-ok"}, "agent-shell-ok"),
        ("sql_exec", {"sql": "CREATE TABLE t(id INTEGER, name TEXT)", "db": "tmp_selfcheck.db"}, "OK"),
        ("sql_exec", {"sql": "INSERT INTO t(id, name) VALUES (1, 'agent-db')", "db": "tmp_selfcheck.db"}, "OK"),
        ("sql_exec", {"sql": "SELECT * FROM t", "db": "tmp_selfcheck.db"}, "agent-db"),
        ("sql_exec", {"sql": "SELEC bad syntax", "db": "tmp_selfcheck.db"}, "ERROR"),
        ("excel_write", {"path": "tmp_selfcheck.xlsx", "rows": [["name", "score"], ["agent", 100]]}, "OK"),
        ("excel_read", {"path": "tmp_selfcheck.xlsx"}, "agent"),
        ("excel_read", {"path": "no_such.xlsx"}, "ERROR"),
        ("webhook_notify", {"text": "hi"}, "ERROR"),  # 未配置 WEBHOOK_URL，离线可测
        ("http_fetch", {"url": "not-a-url"}, "ERROR"),
    ]
    failed = 0
    for name, kwargs, expect in cases:
        tool = registry.get(name)
        output = await tool.execute(**kwargs)
        if expect == "ERROR":
            ok = output.startswith("ERROR")
        else:
            ok = not output.startswith("ERROR")
            if expect is not None:
                ok = ok and expect in output
        if ok:
            hint = (
                kwargs.get("expression")
                or kwargs.get("path")
                or kwargs.get("command")
                or kwargs.get("sql")
                or kwargs.get("text")
                or ""
            )
            console.print(f"PASS {name}  {hint}")
        else:
            failed += 1
            console.print(f"FAIL {name}  {kwargs} -> {output[:160]}")

    for tmp in ("tmp_selfcheck.txt", "tmp_selfcheck.xlsx", "tmp_selfcheck.db"):
        (WORKSPACE_DIR / tmp).unlink(missing_ok=True)

    if failed:
        console.print(f"[red]自检未通过：{failed} 项失败[/red]")
        return 1
    console.print(
        "[green]自检全部通过。下一步：复制 .env.example 为 .env，"
        "填入 API Key 后运行 python -m my_agent[/green]"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

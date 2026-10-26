"""sql_exec：在 workspace 内的 SQLite 数据库上执行 SQL。

「连接数据库」的基础设施：让 Agent 能把结构化业务数据落库、
去重、统计——比如客户信息入库、案例编号唯一化。
库文件被限制在 workspace 内（默认 agent.db），一次只执行一条语句。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .base import WorkspaceTool

_MAX_ROWS = 50           # 查询最多返回的行数，防止刷屏撑爆上下文
_MAX_TEXT_CHARS = 4_000   # 结果文本上限


class SqlExecTool(WorkspaceTool):
    name = "sql_exec"
    description = (
        "在 SQLite 数据库上执行一条 SQL（CREATE / INSERT / UPDATE / DELETE / SELECT 均可），"
        "查询返回表格文本，其他语句返回受影响行数。库文件固定存放在工作区内，默认 agent.db。"
        "适合把结构化业务数据落库、去重、统计。一次只执行一条语句。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "sql": {"type": "string", "description": "一条 SQL 语句，如 SELECT * FROM customers"},
            "db": {"type": "string", "description": "数据库文件名（相对工作区根目录），默认 agent.db"},
        },
        "required": ["sql"],
    }

    async def execute(self, sql: str, db: str = "agent.db") -> str:
        sql = sql.strip().rstrip(";").strip()
        if not sql:
            return "ERROR: SQL 为空"
        try:
            db_path = self.resolve_in_workspace(db)
        except ValueError as exc:
            return f"ERROR: {exc}"
        if db_path.is_dir():
            return f"ERROR: {db!r} 是目录，不能作为数据库文件"

        try:
            conn = sqlite3.connect(db_path, timeout=5.0)
        except sqlite3.Error as exc:
            return f"ERROR: 无法打开数据库：{exc}"
        try:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(sql)
            if cur.description is None:  # 非查询语句
                conn.commit()
                return f"OK: 已执行，受影响 {cur.rowcount} 行"
            rows = cur.fetchmany(_MAX_ROWS + 1)  # 多取一行用于判断是否截断
            return self._format_rows(cur.description, rows)
        except sqlite3.Error as exc:
            return f"ERROR: SQL 执行失败：{exc}"
        finally:
            conn.close()

    def _format_rows(self, description, rows) -> str:
        cols = [d[0] for d in description]
        if not rows:
            return f"OK: 查询无结果（{len(cols)} 列）"
        truncated = len(rows) > _MAX_ROWS
        if truncated:
            rows = rows[:_MAX_ROWS]
        lines = [" | ".join(cols)]
        lines += [
            " | ".join("" if v is None else str(v) for v in row) for row in rows
        ]
        text = "\n".join(lines)
        if len(text) > _MAX_TEXT_CHARS:
            text = text[:_MAX_TEXT_CHARS] + "\n…（结果过长，已截断）"
        note = f"（{len(rows)} 行）"
        if truncated:
            note += "…（超过 50 行已截断，建议加 WHERE / LIMIT）"
        return f"{text}\n{note}"

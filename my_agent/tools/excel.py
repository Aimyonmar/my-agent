"""excel_read / excel_write：业务表格读写（openpyxl）。

「连接表格」的基础设施：把结构化结果写成 .xlsx 交给业务同事，
或把现有表格读进来交给模型加工——业务自动化的最后一公里。
"""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook, load_workbook

from .base import WorkspaceTool

_MAX_WRITE_ROWS = 500      # 单次写入行数上限（含表头）
_MAX_WRITE_COLS = 50
_MAX_READ_ROWS = 20        # 默认读取行数（模型可调，上限 200）
_MAX_READ_ROWS_HARD = 200
_MAX_TEXT_CHARS = 4_000


class ExcelWriteTool(WorkspaceTool):
    name = "excel_write"
    description = (
        "把二维数组写入 .xlsx 文件（覆盖写入），rows 的第一行默认作为表头。"
        "单元格只接受文本/数字/布尔值。适合把结构化结果（如客户信息表）导出成表格。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "目标文件路径，必须以 .xlsx 结尾（相对工作区根目录）"},
            "rows": {
                "type": "array",
                "description": "二维数组，如 [[\"姓名\",\"电话\"],[\"张三\",\"138xx\"]]",
                "items": {"type": "array"},
            },
            "sheet": {"type": "string", "description": "工作表名，默认 Sheet1"},
        },
        "required": ["path", "rows"],
    }

    async def execute(self, path: str, rows: list, sheet: str = "Sheet1") -> str:
        try:
            target = self.resolve_in_workspace(path)
        except ValueError as exc:
            return f"ERROR: {exc}"
        if target.suffix.lower() != ".xlsx":
            return f"ERROR: 仅支持 .xlsx 文件：{path!r}"
        if not isinstance(rows, list) or not rows:
            return "ERROR: rows 必须是非空二维数组"
        if len(rows) > _MAX_WRITE_ROWS:
            return f"ERROR: 行数超限（{len(rows)} 行，上限 {_MAX_WRITE_ROWS}）"

        wb = Workbook()
        ws = wb.active
        ws.title = str(sheet)[:31] or "Sheet1"  # Excel 工作表名上限 31 字符
        for i, row in enumerate(rows, start=1):
            if not isinstance(row, list):
                return f"ERROR: 第 {i} 行不是数组：{row!r}"
            if len(row) > _MAX_WRITE_COLS:
                return f"ERROR: 第 {i} 行列数超限（上限 {_MAX_WRITE_COLS}）"
            for j, cell in enumerate(row, start=1):
                if cell is not None and not isinstance(cell, (str, int, float, bool)):
                    return (
                        f"ERROR: 第 {i} 行第 {j} 列不是标量（{type(cell).__name__}），"
                        "请先拆成文本或数字再写入"
                    )
            ws.append(row)

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            wb.save(target)
        except OSError as exc:
            return f"ERROR: 写入失败：{exc}"
        rel = target.relative_to(self.workspace)
        return f"OK: 已写入 {len(rows)} 行 x {max(len(r) for r in rows)} 列 -> {rel}"


class ExcelReadTool(WorkspaceTool):
    name = "excel_read"
    description = (
        "读取 .xlsx 文件内容并返回表格文本（默认前 20 行）。"
        "适合把业务同事给的表格读进来做整理、清洗或加工。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件路径（相对工作区根目录）"},
            "sheet": {"type": "string", "description": "工作表名，默认第一张表"},
            "max_rows": {"type": "integer", "description": "最多读取的行数，默认 20，上限 200"},
        },
        "required": ["path"],
    }

    async def execute(self, path: str, sheet: str = "", max_rows: int = _MAX_READ_ROWS) -> str:
        try:
            target = self.resolve_in_workspace(path)
        except ValueError as exc:
            return f"ERROR: {exc}"
        if not target.exists():
            return f"ERROR: 文件不存在：{path!r}"
        max_rows = max(1, min(int(max_rows), _MAX_READ_ROWS_HARD))

        try:
            wb = load_workbook(target, read_only=True, data_only=True)
        except Exception as exc:  # openpyxl 异常类型较杂（坏文件/非 xlsx 等）
            return f"ERROR: 无法读取 Excel 文件：{exc}"
        try:
            ws = wb[str(sheet)] if sheet else wb.active
            total = ws.max_row or 0
            rows = []
            for i, row in enumerate(ws.iter_rows(values_only=True), start=1):
                if i > max_rows:
                    rows.append(("__TRUNCATED__",))
                    break
                rows.append(row)
        except KeyError:
            available = "、".join(wb.sheetnames)
            return f"ERROR: 工作表不存在：{sheet!r}。可用工作表：{available}"
        except Exception as exc:
            return f"ERROR: 读取失败：{exc}"
        finally:
            wb.close()
        lines = []
        for row in rows:
            if row and row[0] == "__TRUNCATED__":
                lines.append(f"…（已截断，共 {total} 行，可调大 max_rows 或加条件筛选）")
                break
            lines.append(" | ".join("" if v is None else str(v) for v in row))
        text = "\n".join(lines) or "(空表格)"
        if len(text) > _MAX_TEXT_CHARS:
            text = text[:_MAX_TEXT_CHARS] + "\n…（内容过长，已截断）"
        return text

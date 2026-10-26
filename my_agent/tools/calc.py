"""calculate：安全的算术工具。

不使用 eval()，而是把表达式解析成 AST 后在白名单节点上求值，
从根源上杜绝 __import__ / os.system 之类的注入。
"""

from __future__ import annotations

import ast
import math
import operator

from .base import Tool

_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCS = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sqrt": math.sqrt,
    "pow": pow,
    "log": math.log,
    "log2": math.log2,
    "log10": math.log10,
    "exp": math.exp,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
}
_CONSTS = {"pi": math.pi, "e": math.e, "tau": math.tau}

_MAX_EXPR_LEN = 300      # 防止超长表达式拖垮解析
_MAX_EXPONENT = 10_000   # 防止 2**99999999 这类天文数字运算卡死


def safe_eval(expr: str) -> float:
    """在白名单 AST 节点范围内求值，任何越界节点都会抛 ValueError。"""
    expr = expr.strip()
    if not expr or len(expr) > _MAX_EXPR_LEN:
        raise ValueError(f"表达式为空或过长（>{_MAX_EXPR_LEN} 字符）")
    tree = ast.parse(expr, mode="eval")
    return _eval_node(tree.body)


def _eval_node(node: ast.AST) -> float:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        raise ValueError(f"不支持的常量：{node.value!r}")
    if isinstance(node, ast.BinOp):
        op = _BIN_OPS.get(type(node.op))
        if op is None:
            raise ValueError(f"不支持的运算符：{type(node.op).__name__}")
        left, right = _eval_node(node.left), _eval_node(node.right)
        if op is operator.pow and abs(right) > _MAX_EXPONENT:
            raise ValueError(f"指数绝对值不能超过 {_MAX_EXPONENT}")
        return op(left, right)
    if isinstance(node, ast.UnaryOp):
        op = _UNARY_OPS.get(type(node.op))
        if op is None:
            raise ValueError(f"不支持的一元运算符：{type(node.op).__name__}")
        return op(_eval_node(node.operand))
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCS:
            raise ValueError("只允许调用白名单内的数学函数")
        if node.keywords:
            raise ValueError("不支持关键字参数")
        return _FUNCS[node.func.id](*[_eval_node(a) for a in node.args])
    if isinstance(node, ast.Name):
        if node.id in _CONSTS:
            return _CONSTS[node.id]
        raise ValueError(f"未知标识符：{node.id}")
    raise ValueError(f"不支持的语法节点：{type(node).__name__}")


class CalculateTool(Tool):
    name = "calculate"
    description = (
        "精确计算数学表达式。支持 + - * / // % **、括号，"
        "以及 abs/round/min/max/sqrt/pow/log/log2/log10/exp/sin/cos/tan "
        "和常量 pi/e/tau。例：(1+2)*3.5、sqrt(2)**2、log(100, 10)。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "expression": {"type": "string", "description": "要计算的表达式"},
        },
        "required": ["expression"],
    }

    async def execute(self, expression: str) -> str:
        try:
            value = safe_eval(expression)
        except (ValueError, SyntaxError, ZeroDivisionError, OverflowError) as exc:
            return f"ERROR: 无法计算 {expression!r}：{exc}"
        return repr(value) if isinstance(value, float) else str(value)

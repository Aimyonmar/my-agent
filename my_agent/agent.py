"""Agent 核心循环——整个项目的心脏。

一轮对话的完整流程（ReAct 思想的最小实现）：

    用户输入
        │
        ▼
    ┌─ 携带全部历史消息请求模型 ─┐
    │   (messages + tools 声明) │
    └──────────┬───────────────┘
               ▼
      模型返回的是文本吗？
        ├── 是 → 输出给用户，本轮结束
        └── 否（是 tool_calls）
                ├── 依次执行工具，结果以 role=tool 追加进历史
                └── 回到顶部继续请求模型（最多 max_iterations 轮）
"""

from __future__ import annotations

import json
from typing import Callable

from .config import Config
from .llm import ChatResult, LLMClient, ToolCall
from .tools import ToolRegistry

DEFAULT_SYSTEM_PROMPT = """\
You are a CLI assistant agent running on the user's local machine. You can accomplish real tasks by calling tools.

Rules:
1. For casual chat, greetings, or general knowledge questions: answer directly in text. Do NOT call any tool.
2. For precise calculations, file operations, or command execution: call the corresponding tool. Never fabricate results.
3. Only make necessary calls per turn. After receiving tool results, decide whether they are sufficient to answer or whether more calls are needed.
4. When a tool returns ERROR, read the reason, fix the arguments, and retry. If the same tool fails 3 times in a row, stop and explain to the user.
5. Before risky operations (deleting files, overwriting, changing system settings), state in one sentence what you are about to do.
6. Only call tools that are declared in the tools section. Never invent tool names, and never write tool calls as plain text.
7. Always write your final answer in Simplified Chinese, concise and direct. Keep interim explanations to one or two sentences.\
"""


def _extract_text_tool_call(content: str) -> dict | None:
    """识别弱模型把工具调用写成正文的情况。

    支持两种形态：整段内容就是工具调用 JSON；或正文里夹着
    {"name": ..., "parameters"/"arguments": ...} 对象（正文 + 调用的混合体）。
    要求对象同时带 name 和 parameters/arguments 键，尽量避免误伤正常回答。
    返回 {"name", "arguments"} 或 None。
    """
    text = content.strip()
    if "{" not in text or "name" not in text:
        return None
    decoder = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(text, i)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        name = obj.get("name")
        if not isinstance(name, str) or not name:
            continue
        if "parameters" not in obj and "arguments" not in obj:
            continue
        args = obj.get("parameters", obj.get("arguments")) or {}
        if isinstance(args, dict):
            args = json.dumps(args, ensure_ascii=False)
        if not isinstance(args, str):
            continue
        return {"name": name, "arguments": args}
    return None


class Agent:
    def __init__(
        self,
        llm: LLMClient,
        tools: ToolRegistry,
        config: Config,
        system_prompt: str | None = None,
    ) -> None:
        self.llm = llm
        self.tools = tools
        self.config = config
        self.system_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT
        self.history: list[dict] = []
        self._turn_base = 0  # 当前这轮对话在 history 中的起点，用于异常时回滚

    # ---- 对外主流程 ---------------------------------------------------

    async def run(
        self,
        user_text: str,
        on_text: Callable[[str], None] | None = None,
        on_tool_start: Callable[[ToolCall], None] | None = None,
        on_tool_end: Callable[[ToolCall, str], None] | None = None,
    ) -> str:
        """处理一轮用户输入：内部最多循环 max_iterations 次「请求模型-执行工具」。"""
        self._turn_base = len(self.history)
        self.history.append({"role": "user", "content": user_text})

        last_content = ""
        for _ in range(self.config.max_iterations):
            result = await self.llm.chat(
                self._build_messages(), self.tools.specs(), on_text=on_text
            )
            self._record_assistant(result)

            if not result.tool_calls:
                # 弱模型回收：有些模型会把工具调用写成正文文本（如
                # '{"name":"x","parameters":{...}}'）。识别后把它还原成
                # 规范的 tool_calls 走一遍，让模型在协议层面得到纠错反馈。
                text_call = _extract_text_tool_call(result.content)
                if text_call:
                    call = ToolCall(
                        id=f"call_text_{len(self.history)}",
                        name=text_call["name"],
                        arguments=text_call["arguments"],
                    )
                    self.history.append(
                        {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": call.id,
                                    "type": "function",
                                    "function": {
                                        "name": call.name,
                                        "arguments": call.arguments,
                                    },
                                }
                            ],
                        }
                    )
                    if on_tool_start:
                        on_tool_start(call)
                    output = await self._dispatch(call)
                    if on_tool_end:
                        on_tool_end(call, output)
                    self.history.append(
                        {"role": "tool", "tool_call_id": call.id, "content": output}
                    )
                    continue
                self._turn_base = len(self.history)
                return result.content  # 纯文本回答 → 本轮结束

            for call in result.tool_calls:  # 依次执行工具，结果回填历史
                if on_tool_start:
                    on_tool_start(call)
                output = await self._dispatch(call)
                if on_tool_end:
                    on_tool_end(call, output)
                self.history.append(
                    {"role": "tool", "tool_call_id": call.id, "content": output}
                )
            last_content = result.content

        # 工具循环达到上限仍未收敛，强制收尾
        hint = "（已达最大工具循环次数，先停在这里）"
        self._turn_base = len(self.history)
        return (last_content + "\n" + hint).strip() or hint

    def rollback(self) -> None:
        """回滚当前这轮对话（中断/失败时调用），保证历史消息序列的一致性。"""
        del self.history[self._turn_base :]
        self._turn_base = len(self.history)

    def reset(self) -> None:
        """清空全部对话历史。"""
        self.history.clear()
        self._turn_base = 0

    # ---- 内部实现 ------------------------------------------------------

    def _build_messages(self) -> list[dict]:
        return [{"role": "system", "content": self.system_prompt}, *self.history]

    def _record_assistant(self, result: ChatResult) -> None:
        """把模型这一步的输出写进历史；含 tool_calls 时必须原样保留，
        因为协议要求后续的 tool 消息与其一一对应。"""
        if not result.tool_calls:
            self.history.append({"role": "assistant", "content": result.content})
            return
        self.history.append(
            {
                "role": "assistant",
                "content": result.content or "",
                "tool_calls": [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.name,
                            "arguments": call.arguments,
                        },
                    }
                    for call in result.tool_calls
                ],
            }
        )

    async def _dispatch(self, call: ToolCall) -> str:
        """执行一次工具调用。任何失败都转成文本喂回模型，而不是抛异常——
        让模型看到错误并自行修正是 Agent 的关键设计。"""
        tool = self.tools.get(call.name)
        if tool is None:
            available = "、".join(t.name for t in self.tools)
            return f"ERROR: 不存在名为 {call.name!r} 的工具。可用工具：{available}"
        try:
            args = json.loads(call.arguments or "{}")
        except json.JSONDecodeError as exc:
            return f"ERROR: 工具参数不是合法 JSON：{exc}\n原始参数：{call.arguments[:200]}"
        if not isinstance(args, dict):
            return "ERROR: 工具参数必须是 JSON 对象"
        try:
            return await tool.execute(**args)
        except TypeError as exc:
            return f"ERROR: 调用参数不匹配：{exc}"
        except Exception as exc:  # noqa: BLE001 —— 工具异常也要反馈给模型
            return f"ERROR: 工具执行失败 {type(exc).__name__}: {exc}"

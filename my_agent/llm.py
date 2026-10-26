"""极简 OpenAI 兼容 Chat Completions 客户端。

不依赖任何官方 SDK，用 httpx 手写流式请求，
能直观看到 Agent 与模型服务之间的原始协议交互：

    POST {base_url}/chat/completions
    请求体: model / messages / tools / stream
    响应:   SSE 流，每个 "data: {...}" 行是一个增量 chunk
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable

import httpx

from .config import Config


class LLMError(RuntimeError):
    """调用模型服务失败（网络、鉴权、限流、协议不兼容等）。"""


@dataclass
class ToolCall:
    """模型决定发起的一次工具调用。arguments 保持原始 JSON 字符串。"""

    id: str
    name: str
    arguments: str


@dataclass
class ChatResult:
    """一轮对话的完整结果：文本 + 可能的工具调用。"""

    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = ""


class LLMClient:
    def __init__(self, config: Config) -> None:
        self._config = config
        # 空 key 时干脆不发 Authorization 头（本地 Ollama 等无需鉴权的场景），
        # 否则 "Bearer " 空值会被 httpx 判为非法头，在发送前直接抛错
        headers = (
            {"Authorization": f"Bearer {config.api_key}"} if config.api_key else {}
        )
        self._client = httpx.AsyncClient(
            base_url=config.base_url,
            headers=headers,
            timeout=httpx.Timeout(config.request_timeout, connect=15.0),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        on_text: Callable[[str], None] | None = None,
    ) -> ChatResult:
        """发起一次流式对话。

        on_text: 每收到一段文本增量就回调一次（REPL 用它实现打字机效果）。
        返回聚合后的完整结果；工具调用的 arguments 由多个 chunk 拼接而成。
        """
        # 前置校验：与其让空 key 变成晦涩的协议层报错，不如直接说清楚怎么配
        if not self._config.key_ready:
            raise LLMError(
                f"当前接入方式（{self._config.provider}）需要 API Key："
                f"请复制 .env.example 为 .env，填入 {self._config.key_env} 后重试"
            )
        payload: dict = {
            "model": self._config.model,
            "messages": messages,
            "stream": True,
            # 低温采样：Agent 要的是稳定执行指令而不是发散创作；
            # 高温是小模型语言漂移（中英韩混杂）的放大器
            "temperature": self._config.temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        result = ChatResult()
        # 工具调用缓冲：index -> {"id", "name", "arguments"}
        tool_buf: dict[int, dict] = {}

        try:
            async with self._client.stream(
                "POST", "/chat/completions", json=payload
            ) as resp:
                if resp.status_code != 200:
                    body = (await resp.aread()).decode("utf-8", errors="replace")
                    raise LLMError(
                        f"模型服务返回 HTTP {resp.status_code}：{_brief(body)}"
                    )
                async for line in resp.aiter_lines():
                    # SSE 格式：每行 "data: {...}"；以 ":" 开头的是服务端注释
                    if not line.startswith("data:"):
                        continue
                    data = line[len("data:"):].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue  # 容忍个别服务插入的非 JSON 行
                    _absorb_chunk(chunk, result, tool_buf, on_text)
        except httpx.HTTPError as exc:
            raise LLMError(f"网络请求失败：{exc}") from exc

        for idx in sorted(tool_buf):
            slot = tool_buf[idx]
            result.tool_calls.append(
                ToolCall(
                    id=slot["id"] or f"call_{idx}",
                    name=slot["name"],
                    arguments=slot["arguments"],
                )
            )
        return result


def _absorb_chunk(
    chunk: dict,
    result: ChatResult,
    tool_buf: dict[int, dict],
    on_text: Callable[[str], None] | None,
) -> None:
    """把一个流式 chunk 的增量合并进 result。"""
    choices = chunk.get("choices") or []
    if not choices:
        return
    choice = choices[0]
    if choice.get("finish_reason"):
        result.finish_reason = choice["finish_reason"]
    delta = choice.get("delta") or {}

    text = delta.get("content")
    if text:
        result.content += text
        if on_text:
            on_text(text)

    # 注：思考型模型的 delta.reasoning_content 在 v1 中被忽略，只聚合正文与工具调用
    for tc in delta.get("tool_calls") or []:
        idx = tc.get("index", 0) or 0
        slot = tool_buf.setdefault(idx, {"id": "", "name": "", "arguments": ""})
        if tc.get("id"):
            slot["id"] = tc["id"]
        fn = tc.get("function") or {}
        if fn.get("name"):
            slot["name"] += fn["name"]  # 个别服务会分片发送函数名
        if fn.get("arguments"):
            slot["arguments"] += fn["arguments"]  # 参数 JSON 一定是分片拼接的


def _brief(body: str, limit: int = 400) -> str:
    body = " ".join(body.split())
    return body[:limit] + ("…" if len(body) > limit else "")

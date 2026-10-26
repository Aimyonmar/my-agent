"""http_fetch：抓取网页/接口内容并转成纯文本（只读 GET）。

联网获取素材的基础设施：抓一页产品介绍、拉一份公告原文，
交给模型做整理。「下载上限 + 输出截断」双闸门，防止把上下文撑爆。
仅支持 http/https，不做任何写操作，不带任何鉴权头。
"""

from __future__ import annotations

import html as html_lib
import re

import httpx

from .base import Tool

_TIMEOUT = 15.0
_MAX_RAW_BYTES = 2_000_000    # 下载字节上限，防止拉超大文件
_MAX_TEXT_CHARS = 4_000        # 回传给模型的文本上限

# 块级标签结束的位置换成换行，保住 HTML 转文本后的可读结构
_BREAK_TAGS = re.compile(r"(?i)<br\s*/?>|</p>|</div>|</li>|</h[1-6]>|</tr>|</table>")
_TAG = re.compile(r"<[^>]+>")
_SCRIPT_STYLE = re.compile(r"(?is)<(script|style|noscript)\b[^>]*>.*?</\1\s*>")
_BLANK_LINE = re.compile(r"\n\s*\n+")

_ALLOWED_CONTENT_TYPES = ("text/html", "text/plain", "application/json", "text/json", "application/xml", "text/xml", "text/markdown")


class HttpFetchTool(Tool):
    name = "http_fetch"
    description = (
        "抓取一个网页或 JSON 接口的内容，返回纯文本（HTML 会自动去掉标签，保留结构）。"
        "只读 GET，输出默认截断到 4000 字符。适合联网取素材后做整理。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "目标地址，必须以 http(s):// 开头"},
            "max_chars": {"type": "integer", "description": "返回文本的字符上限，默认 4000，最大 20000"},
        },
        "required": ["url"],
    }

    async def execute(self, url: str, max_chars: int = _MAX_TEXT_CHARS) -> str:
        url = (url or "").strip()
        if not url.lower().startswith(("http://", "https://")):
            return f"ERROR: URL 必须以 http(s):// 开头：{url[:100]!r}"
        try:
            max_chars = max(200, min(int(max_chars), 20_000))
        except (TypeError, ValueError):
            max_chars = _MAX_TEXT_CHARS

        try:
            async with httpx.AsyncClient(
                timeout=_TIMEOUT, follow_redirects=True
            ) as client:
                raw, content_type = await self._download(client, url)
        except httpx.HTTPError as exc:
            return f"ERROR: 抓取失败（{type(exc).__name__}）：{exc}"

        if raw is None:
            return f"ERROR: 目标返回非文本内容（Content-Type: {content_type}），无法整理"

        text = self._decode(raw, content_type)
        if "html" in (content_type or "").lower():
            text = self._html_to_text(text)
        text = text.strip() or "(空内容)"
        if len(text) > max_chars:
            text = text[:max_chars] + f"\n…（已截断，全文 {len(text)} 字符，可调大 max_chars）"
        return text

    async def _download(self, client: httpx.AsyncClient, url: str) -> tuple[bytes | None, str]:
        """流式下载，超过上限即停止；返回 (字节, Content-Type)。非文本类返回 (None, 类型)。"""
        async with client.stream("GET", url) as resp:
            content_type = resp.headers.get("content-type", "")
            if resp.status_code != 200:
                snippet = (await resp.aread())[:200].decode("utf-8", errors="replace")
                raise httpx.HTTPStatusError(
                    f"HTTP {resp.status_code} {snippet}", request=resp.request, response=resp
                )
            if content_type and not content_type.split(";")[0].strip().lower().startswith(_ALLOWED_CONTENT_TYPES):
                return None, content_type
            chunks: list[bytes] = []
            received = 0
            async for chunk in resp.aiter_bytes():
                chunks.append(chunk)
                received += len(chunk)
                if received >= _MAX_RAW_BYTES:
                    break
            return b"".join(chunks)[:_MAX_RAW_BYTES], content_type

    def _decode(self, raw: bytes, content_type: str) -> str:
        """按 Content-Type 里的 charset 解码，缺省 utf-8 容错。"""
        m = re.search(r"charset=([\w\-]+)", content_type or "", re.IGNORECASE)
        encoding = m.group(1) if m else "utf-8"
        try:
            return raw.decode(encoding, errors="replace")
        except LookupError:  # 未知编码名
            return raw.decode("utf-8", errors="replace")

    def _html_to_text(self, html: str) -> str:
        """极简 HTML 转文本：去 script/style、块级标签换行、去标签、反转义、压空行。"""
        text = _SCRIPT_STYLE.sub(" ", html)
        text = _BREAK_TAGS.sub("\n", text)
        text = _TAG.sub(" ", text)
        text = html_lib.unescape(text)
        lines = [ln.strip() for ln in text.splitlines()]
        return _BLANK_LINE.sub("\n", "\n".join(lines))

"""webhook_notify：向 .env 配置的 Webhook 地址推送文本消息（企微/钉钉/飞书群机器人等）。

「任务完成自动通知」链路的出口：Agent 跑完整理/生成任务后
主动推送结果摘要，业务同事不用守着终端看。

安全设计：地址只能来自 .env 里人工配置的 WEBHOOK_URL，
不接受模型/用户在参数里临时指定——模型无法把数据发往任意地址，
从源头堵住「提示注入 -> 数据外送」的通路。
按域名自动适配企业微信 / 钉钉 / 飞书的报文格式，其余地址发通用 JSON。
"""

from __future__ import annotations

import os

import httpx

from .base import Tool

_TIMEOUT = 10.0
_MAX_TEXT_CHARS = 2_000     # 单条消息长度上限（各平台普遍在 2000~4000）
_MAX_BODY_CHARS = 300       # 回显响应体的上限，够模型判断成败即可


def _payload_for(url: str, text: str) -> dict:
    """按平台域名适配报文格式，未识别的地址发通用 JSON。"""
    host = url.lower()
    if "qyapi.weixin.qq.com" in host:  # 企业微信机器人
        return {"msgtype": "text", "text": {"content": text}}
    if "oapi.dingtalk.com" in host:     # 钉钉机器人
        return {"msgtype": "text", "text": {"content": text}}
    if "open.feishu.cn" in host:       # 飞书机器人
        return {"msg_type": "text", "content": {"text": text}}
    return {"text": text}


class WebhookNotifyTool(Tool):
    name = "webhook_notify"
    description = (
        "向 .env 中配置的 WEBHOOK_URL 推送一条文本消息（任务完成通知）。"
        "自动适配企业微信/钉钉/飞书群机器人格式。若未配置 WEBHOOK_URL 会返回配置指引。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "要推送的消息文本"},
        },
        "required": ["text"],
    }

    async def execute(self, text: str) -> str:
        text = (text or "").strip()
        if not text:
            return "ERROR: 消息内容为空"
        url = os.getenv("WEBHOOK_URL", "").strip()
        if not url:
            return (
                "ERROR: .env 中未配置 WEBHOOK_URL。"
                "请引导用户在 .env 写入 WEBHOOK_URL=机器人地址 后重试"
            )
        if not url.lower().startswith(("http://", "https://")):
            return f"ERROR: WEBHOOK_URL 必须以 http(s):// 开头，请检查 .env 配置"
        if len(text) > _MAX_TEXT_CHARS:
            text = text[:_MAX_TEXT_CHARS] + "…（已截断）"

        payload = _payload_for(url, text)
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(url, json=payload)
        except httpx.HTTPError as exc:
            return f"ERROR: 推送失败（{type(exc).__name__}）：{exc}"

        body = resp.text[:_MAX_BODY_CHARS]
        if resp.status_code != 200:
            return f"ERROR: 平台返回 HTTP {resp.status_code}：{body}"
        return f"OK: 已推送（HTTP 200）。平台响应：{body or '(空)'}"

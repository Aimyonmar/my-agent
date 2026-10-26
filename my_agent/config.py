"""配置加载：从 .env / 环境变量读取，支持 glm / ollama / openai 三种接入方式。

三种接入最终都走 OpenAI 兼容的 /chat/completions 协议，
只是 base_url、默认模型和鉴权方式不同。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# 项目根目录（my_agent 包的上一级），也是文件工具的活动边界
ROOT_DIR = Path(__file__).resolve().parent.parent
WORKSPACE_DIR = ROOT_DIR

load_dotenv(ROOT_DIR / ".env")

# 各接入方式的预设值。key_env 指向存放 API Key 的环境变量名。
PROVIDER_PRESETS: dict[str, dict] = {
    "glm": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4-flash",
        "key_env": "GLM_API_KEY",
        "need_key": True,
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "model": "qwen2.5:7b",
        "key_env": "OLLAMA_API_KEY",
        "need_key": False,  # 本地服务，占位即可
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "key_env": "OPENAI_API_KEY",
        "need_key": True,
    },
}


@dataclass
class Config:
    provider: str
    base_url: str
    api_key: str
    model: str
    max_iterations: int = 15
    request_timeout: float = 120.0
    key_env: str = ""  # 该接入方式存放 API Key 的环境变量名，用于报错提示
    temperature: float = 0.4  # 低温：Agent 要的是稳定执行指令，高温是语言漂移的放大器

    @property
    def key_ready(self) -> bool:
        """当前接入方式是否已具备可用的鉴权信息。"""
        return bool(self.api_key) or not PROVIDER_PRESETS[self.provider]["need_key"]

    def describe(self) -> str:
        key_state = "已配置" if self.key_ready else "[red]缺失[/red]"
        return (
            f"provider : {self.provider}\n"
            f"base_url : {self.base_url}\n"
            f"model    : {self.model}\n"
            f"api key  : {key_state}\n"
            f"max loop : {self.max_iterations} 轮"
        )


def load_config() -> Config:
    """读取并校验配置。环境变量优先级高于 .env 文件。"""
    provider = os.getenv("AGENT_PROVIDER", "glm").strip().lower()
    if provider not in PROVIDER_PRESETS:
        raise ValueError(
            f"未知的 AGENT_PROVIDER={provider!r}，可选值：{' / '.join(PROVIDER_PRESETS)}"
        )
    preset = PROVIDER_PRESETS[provider]
    prefix = provider.upper()

    base_url = os.getenv(f"{prefix}_BASE_URL", preset["base_url"]).strip().rstrip("/")
    model = os.getenv(f"{prefix}_MODEL", preset["model"]).strip()
    api_key = os.getenv(preset["key_env"], "").strip()

    try:
        max_iterations = int(os.getenv("AGENT_MAX_ITERATIONS", "15"))
    except ValueError:
        max_iterations = 15
    max_iterations = max(1, min(max_iterations, 50))

    try:
        temperature = float(os.getenv("AGENT_TEMPERATURE", "0.4"))
    except ValueError:
        temperature = 0.4
    temperature = max(0.0, min(temperature, 2.0))

    return Config(
        provider=provider,
        base_url=base_url,
        model=model,
        api_key=api_key,
        max_iterations=max_iterations,
        key_env=preset["key_env"],
        temperature=temperature,
    )

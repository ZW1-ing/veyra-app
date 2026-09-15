"""模型层的抽象：上层代码只认这些协议，不认具体厂商。

这就是 Veyra 里 `compat.ts` 的思路搬到 Python：一套 OpenAI 兼容实现
同时支撑 DeepSeek、豆包方舟、本地 Ollama 和任意兼容服务。
"""

import math
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ChatMessage:
    role: str  # system | user | assistant | tool
    content: str


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass
class ChatChunk:
    """流式返回的最小单位：一段增量文本，可选附带用量。"""

    delta: str = ""
    usage: Usage | None = None


class LLMProvider(Protocol):
    name: str
    model: str

    def stream(self, messages: Sequence[ChatMessage]) -> AsyncIterator[ChatChunk]:
        """流式对话：逐段吐出增量文本。"""
        ...

    async def complete(self, messages: Sequence[ChatMessage]) -> tuple[str, Usage]:
        """一次性对话：返回完整文本与用量。"""
        ...


def estimate_tokens(text: str) -> int:
    """没有真实用量时的粗略估算：按字符数折半。

    真实计费以厂商返回的 usage 为准，这里只用于本地模型（Ollama 等）
    或服务端未返回用量时的兜底，避免统计直接空掉。
    """
    if not text:
        return 0
    return max(1, math.ceil(len(text) / 2))

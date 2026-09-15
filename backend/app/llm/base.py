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
    # 原生工具调用：assistant 消息可以携带 tool_calls，tool 消息要带上对应的 tool_call_id
    tool_calls: list["ToolCall"] | None = None
    tool_call_id: str | None = None


@dataclass(frozen=True)
class ToolCall:
    """模型请求调用某个工具。arguments 是 JSON 字符串，与 OpenAI 协议保持一致。"""

    id: str
    name: str
    arguments: str = "{}"


@dataclass(frozen=True)
class ToolSpec:
    """给模型看的工具说明（JSON Schema 形式）。"""

    name: str
    description: str
    parameters: dict

    def to_openai(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


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
    # 原生工具调用：流结束时一次性给出（流式增量里的 tool_calls 会在 provider 内聚合）
    tool_calls: list[ToolCall] | None = None


class LLMProvider(Protocol):
    name: str
    model: str
    # 是否支持原生 function calling。不支持时上层回退到 JSON 协议。
    supports_native_tools: bool

    def stream(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolSpec] | None = None,
    ) -> AsyncIterator[ChatChunk]:
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

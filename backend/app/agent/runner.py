"""Agent 对外入口：把图的执行过程翻译成前端能消费的事件流。"""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from ..llm.base import Usage
from .graph import build_agent_graph
from .tools import ToolRegistry


@dataclass
class AgentRun:
    text: str = ""
    steps: int = 0
    usage: Usage = field(default_factory=Usage)
    tool_calls: list[str] = field(default_factory=list)


async def stream_agent(
    provider,
    registry: ToolRegistry,
    history: list[dict[str, str]],
    max_steps: int = 8,
    timeout_seconds: float = 120.0,
    system_prompt: str | None = None,
    checkpointer=None,
) -> AsyncIterator[dict]:
    """逐步产出事件：token / action / tool / final。

    调用方（FastAPI 路由）只负责把这些事件变成 SSE，不关心内部怎么编排。
    """
    graph = build_agent_graph(
        provider,
        registry,
        max_steps=max_steps,
        timeout_seconds=timeout_seconds,
        persona=system_prompt,
        checkpointer=checkpointer,
    )
    state = {
        "messages": history,
        "steps": 0,
        "pending_calls": [],
        "final": "",
        "usage": {"prompt_tokens": 0, "completion_tokens": 0},
        "max_steps": max_steps,
    }

    last_values: dict = {}
    async for mode, payload in graph.astream(state, stream_mode=["custom", "values"]):
        if mode == "custom":
            yield payload
        elif mode == "values":
            last_values = payload

    usage_raw = last_values.get("usage", {}) if isinstance(last_values, dict) else {}
    yield {
        "type": "final",
        "text": last_values.get("final", "") if isinstance(last_values, dict) else "",
        "steps": last_values.get("steps", 0) if isinstance(last_values, dict) else 0,
        "usage": {
            "prompt_tokens": int(usage_raw.get("prompt_tokens", 0)),
            "completion_tokens": int(usage_raw.get("completion_tokens", 0)),
        },
    }

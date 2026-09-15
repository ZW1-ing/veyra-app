"""选择用哪种编排：单智能体（带工具）还是多智能体（规划 + 分工 + 汇总）。"""

from collections.abc import AsyncIterator

from ..agent.runner import stream_agent
from ..agent.swarm import stream_swarm
from ..agent.tools import ToolRegistry
from ..core.config import Settings


def stream_dialogue(
    *,
    mode: str,
    provider,
    registry: ToolRegistry,
    context: list[dict[str, str]],
    question: str,
    knowledge: str,
    max_steps: int,
    settings: Settings,
    system_prompt: str | None = None,
) -> AsyncIterator[dict]:
    if mode == "swarm":
        return stream_swarm(provider, question, knowledge, settings, system_prompt)
    return stream_agent(
        provider,
        registry,
        context,
        max_steps=max_steps,
        timeout_seconds=settings.agent_timeout_seconds,
        system_prompt=system_prompt,
    )

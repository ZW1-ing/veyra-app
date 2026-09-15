"""LangGraph 编排：agent 节点负责思考与流式输出，tools 节点负责执行工具。

整个图长这样：

    START -> agent -> (有工具调用?) -> tools -> agent -> ... -> END

用图而不是 while 循环的好处：每一步状态都是显式的，
以后要加「人工确认」「并行分支」「断点续跑」只需要加节点和边，
不用把循环改成一团 if。
"""

from __future__ import annotations

import asyncio
from typing import Any, TypedDict

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph

from ..llm.base import ChatMessage, Usage
from .prompts import build_system_prompt, extract_action
from .tools import ToolRegistry


class AgentState(TypedDict, total=False):
    messages: list[dict[str, str]]
    steps: int
    tool_name: str | None
    tool_args: dict[str, Any]
    final: str
    usage: dict[str, int]
    max_steps: int


def build_agent_graph(
    provider,
    registry: ToolRegistry,
    max_steps: int = 8,
    timeout_seconds: float = 120.0,
    persona: str | None = None,
    checkpointer=None,
):
    """编译一张可执行的图。

    checkpointer 传入后即可支持断点续跑（本切片先支持内存版 InMemorySaver）。
    """

    async def agent_node(state: AgentState) -> AgentState:
        step_limit = state.get("max_steps", max_steps)
        system_prompt = build_system_prompt(registry.specs_text(), step_limit, persona)
        messages = [ChatMessage(role="system", content=system_prompt)]
        messages += [ChatMessage(role=m["role"], content=m["content"]) for m in state["messages"]]

        writer = get_stream_writer()
        collected: list[str] = []
        usage = Usage(
            prompt_tokens=state.get("usage", {}).get("prompt_tokens", 0),
            completion_tokens=state.get("usage", {}).get("completion_tokens", 0),
        )

        timed_out = False
        try:
            async with asyncio.timeout(timeout_seconds):
                async for chunk in provider.stream(messages):
                    if chunk.delta:
                        collected.append(chunk.delta)
                        writer({"type": "token", "text": chunk.delta})
                    if chunk.usage:
                        usage.prompt_tokens = max(usage.prompt_tokens, chunk.usage.prompt_tokens)
                        usage.completion_tokens += chunk.usage.completion_tokens
        except TimeoutError:
            # 模型卡住时不能把请求无限挂着：保留已经吐出来的部分，明确告诉调用方发生了什么
            timed_out = True
            note = f"\n\n[已到达 {timeout_seconds:.0f} 秒超时上限，本轮中止]"
            collected.append(note)
            writer({"type": "token", "text": note})
            writer({"type": "timeout", "seconds": timeout_seconds})

        text = "".join(collected)
        if timed_out:
            return {
                "messages": state["messages"],
                "final": text,
                "tool_name": None,
                "usage": {
                    "prompt_tokens": usage.prompt_tokens,
                    "completion_tokens": usage.completion_tokens,
                },
            }

        action = extract_action(text)
        new_messages = list(state["messages"])
        if action:
            new_messages.append({"role": "assistant", "content": text})
            writer({"type": "action", "tool": action["tool"], "args": action["args"]})
            return {
                "messages": new_messages,
                "tool_name": action["tool"],
                "tool_args": action["args"],
                "usage": {
                    "prompt_tokens": usage.prompt_tokens,
                    "completion_tokens": usage.completion_tokens,
                },
            }

        return {
            "messages": state["messages"],
            "final": text,
            "tool_name": None,
            "usage": {
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
            },
        }

    def tools_node(state: AgentState) -> AgentState:
        name = state.get("tool_name") or ""
        args = state.get("tool_args") or {}
        ok, result = registry.run(name, args)
        writer = get_stream_writer()
        writer({"type": "tool", "tool": name, "ok": ok, "result": result[:500]})

        messages = list(state["messages"])
        messages.append(
            {
                "role": "tool",
                "content": f"工具 {name} 返回：{result}",
            }
        )
        return {
            "messages": messages,
            "steps": state.get("steps", 0) + 1,
            "final": "",
            "usage": state.get("usage", {}),
        }

    def route(state: AgentState) -> str:
        if state.get("tool_name"):
            if state.get("steps", 0) >= state.get("max_steps", max_steps):
                return "finish"
            return "tools"
        return "finish"

    def finish_node(state: AgentState) -> AgentState:
        """步数用尽时的兜底：把观察到的信息交回模型做一次收尾。"""
        if state.get("final"):
            return state
        return {
            "messages": state["messages"],
            "final": "已达到工具调用步数上限，请基于当前信息作答。",
            "tool_name": None,
            "usage": state.get("usage", {}),
        }

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tools_node)
    graph.add_node("finish", finish_node)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", route, {"tools": "tools", "finish": "finish"})
    graph.add_edge("tools", "agent")
    graph.add_edge("finish", END)

    return graph.compile(checkpointer=checkpointer)

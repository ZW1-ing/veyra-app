"""LangGraph 编排：agent 节点负责思考与流式输出，tools 节点负责执行工具。

整个图长这样：

    START -> agent -> (有工具调用?) -> tools -> agent -> ... -> END

用图而不是 while 循环的好处：每一步状态都是显式的，
以后要加「人工确认」「并行分支」「断点续跑」只需要加节点和边，
不用把循环改成一团 if。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, TypedDict

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph

from ..llm.base import ChatMessage, ToolCall, Usage
from .prompts import build_system_prompt, extract_action
from .tools import ToolRegistry


class AgentState(TypedDict, total=False):
    messages: list[dict[str, str]]
    steps: int
    # 待执行的工具调用：原生 function calling 与 JSON 协议都归一到这个形状
    pending_calls: list[dict[str, Any]]
    final: str
    usage: dict[str, int]
    max_steps: int


def _to_chat_messages(messages: list[dict[str, Any]]) -> list[ChatMessage]:
    """把图状态里的消息转成模型层消息（携带原生工具调用需要的字段）。"""
    converted: list[ChatMessage] = []
    for message in messages:
        raw_calls = message.get("tool_calls")
        converted.append(
            ChatMessage(
                role=str(message.get("role", "user")),
                content=str(message.get("content") or ""),
                tool_calls=(
                    [
                        ToolCall(
                            id=str(call.get("id") or ""),
                            name=str(call.get("name") or ""),
                            arguments=str(call.get("arguments") or "{}"),
                        )
                        for call in raw_calls
                    ]
                    if raw_calls
                    else None
                ),
                tool_call_id=message.get("tool_call_id"),
            )
        )
    return converted


def _parse_args(raw: Any) -> dict[str, Any]:
    """原生工具调用的参数是 JSON 字符串；解析不出来就返回空字典，让工具自己报参数错误。"""
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        parsed = json.loads(str(raw))
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


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
        # 支持原生工具调用的后端就走 tools 参数；否则继续用 JSON 协议（兼容性更好）
        supports_native = bool(getattr(provider, "supports_native_tools", False))
        system_prompt = build_system_prompt(
            registry.specs_text(), step_limit, persona, native_tools=supports_native
        )
        messages = [ChatMessage(role="system", content=system_prompt)]
        messages += _to_chat_messages(state["messages"])

        tools = registry.tool_specs() if supports_native else None

        writer = get_stream_writer()
        collected: list[str] = []
        native_calls: list[ToolCall] = []
        usage = Usage(
            prompt_tokens=state.get("usage", {}).get("prompt_tokens", 0),
            completion_tokens=state.get("usage", {}).get("completion_tokens", 0),
        )

        timed_out = False
        try:
            async with asyncio.timeout(timeout_seconds):
                async for chunk in provider.stream(messages, tools=tools):
                    if chunk.delta:
                        collected.append(chunk.delta)
                        writer({"type": "token", "text": chunk.delta})
                    if chunk.tool_calls:
                        native_calls.extend(chunk.tool_calls)
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
                "pending_calls": [],
                "usage": {
                    "prompt_tokens": usage.prompt_tokens,
                    "completion_tokens": usage.completion_tokens,
                },
            }

        # 原生工具调用优先；后端不支持时回退到 JSON 协议
        calls: list[dict[str, Any]] = []
        if native_calls:
            calls = [
                {"id": call.id, "name": call.name, "arguments": call.arguments}
                for call in native_calls
            ]
        else:
            action = extract_action(text)
            if action:
                calls = [
                    {
                        "id": f"call_{len(state.get('messages', []))}",
                        "name": action["tool"],
                        "arguments": json.dumps(action["args"], ensure_ascii=False),
                    }
                ]

        new_messages = list(state["messages"])
        if calls:
            assistant_message: dict[str, Any] = {"role": "assistant", "content": text}
            if native_calls:
                # 原生协议要求把 tool_calls 原样带回对话历史
                assistant_message["tool_calls"] = calls
            new_messages.append(assistant_message)
            for call in calls:
                writer(
                    {
                        "type": "action",
                        "tool": call["name"],
                        "args": _parse_args(call["arguments"]),
                    }
                )
            return {
                "messages": new_messages,
                "pending_calls": calls,
                "usage": {
                    "prompt_tokens": usage.prompt_tokens,
                    "completion_tokens": usage.completion_tokens,
                },
            }

        return {
            "messages": state["messages"],
            "final": text,
            "pending_calls": [],
            "usage": {
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
            },
        }

    def tools_node(state: AgentState) -> AgentState:
        writer = get_stream_writer()
        messages = list(state["messages"])
        for call in state.get("pending_calls") or []:
            name = str(call.get("name") or "")
            args = _parse_args(call.get("arguments"))
            ok, result = registry.run(name, args)
            writer({"type": "tool", "tool": name, "ok": ok, "result": result[:500]})
            messages.append(
                {
                    "role": "tool",
                    "content": result,
                    "tool_call_id": call.get("id"),
                }
            )

        return {
            "messages": messages,
            "steps": state.get("steps", 0) + 1,
            "pending_calls": [],
            "final": "",
            "usage": state.get("usage", {}),
        }

    def route(state: AgentState) -> str:
        if state.get("pending_calls"):
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
            "pending_calls": [],
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

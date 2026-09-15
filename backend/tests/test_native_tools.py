"""原生 function calling：支持 tools 参数的后端走原生协议，不支持的走 JSON 协议。"""

from collections.abc import Sequence

from app.agent.runner import stream_agent
from app.agent.tools import build_default_registry
from app.llm.base import ChatChunk, ChatMessage, ToolCall, Usage


class NativeToolProvider:
    """支持原生工具调用的假模型：第一轮要求调 calc，第二轮给出结论。"""

    name = "native"
    model = "native-model"
    supports_native_tools = True

    def __init__(self) -> None:
        self.requests: list[list[ChatMessage]] = []
        self.tool_schemas: list[list] = []

    async def stream(self, messages: Sequence[ChatMessage], tools=None):
        self.requests.append(list(messages))
        self.tool_schemas.append(list(tools or []))

        if len(self.requests) == 1:
            yield ChatChunk(
                tool_calls=[
                    ToolCall(id="call_1", name="calc", arguments='{"expression": "23*47"}')
                ]
            )
        else:
            yield ChatChunk(delta="23 × 47 = 1081")
        yield ChatChunk(usage=Usage(10, 5))

    async def complete(self, messages: Sequence[ChatMessage]) -> tuple[str, Usage]:
        return "", Usage()


async def _collect(events):
    return [event async for event in events]


async def test_native_tool_call_round_trip():
    provider = NativeToolProvider()

    events = await _collect(
        stream_agent(
            provider,
            build_default_registry(),
            [{"role": "user", "content": "23 乘 47 等于多少"}],
        )
    )

    # 工具真的被执行了
    tool_events = [e for e in events if e["type"] == "tool"]
    assert tool_events and tool_events[0]["tool"] == "calc"
    assert tool_events[0]["ok"] is True
    assert "1081" in tool_events[0]["result"]

    final = next(e for e in events if e["type"] == "final")
    assert "1081" in final["text"]
    assert final["steps"] == 1

    # 原生协议要求把工具声明发给模型
    assert provider.tool_schemas[0], "第一轮应当带上工具声明"
    assert provider.tool_schemas[0][0].name == "now"

    # 第二轮请求里应有：带 tool_calls 的 assistant 消息 + 带 tool_call_id 的 tool 消息
    second = provider.requests[1]
    assert any(m.tool_calls for m in second), "assistant 消息要带 tool_calls"
    tool_message = next(m for m in second if m.role == "tool")
    assert tool_message.tool_call_id == "call_1"
    assert "1081" in tool_message.content


async def test_provider_without_native_support_does_not_receive_tool_schemas():
    """不支持原生工具调用的后端（如内置 mock）不应该收到 tools 参数。"""

    class LegacyProvider:
        name = "legacy"
        model = "legacy"
        supports_native_tools = False

        def __init__(self) -> None:
            self.received_tools: list = []

        async def stream(self, messages: Sequence[ChatMessage], tools=None):
            self.received_tools.append(tools)
            yield ChatChunk(delta="普通回答")
            yield ChatChunk(usage=Usage(1, 1))

        async def complete(self, messages: Sequence[ChatMessage]) -> tuple[str, Usage]:
            return "", Usage()

    provider = LegacyProvider()
    events = await _collect(
        stream_agent(provider, build_default_registry(), [{"role": "user", "content": "你好"}])
    )

    assert provider.received_tools == [None]
    assert next(e for e in events if e["type"] == "final")["text"] == "普通回答"

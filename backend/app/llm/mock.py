"""离线可跑的假模型：让测试和演示完全不依赖网络与密钥。"""

from collections.abc import AsyncIterator, Sequence

from .base import ChatChunk, ChatMessage, Usage, estimate_tokens


class MockProvider:
    """按脚本回复的假模型。

    replies 为空时进入「回声模式」：把最后一条用户消息复述一遍，
    主要用于健康检查和最简联调。
    """

    name = "mock"
    # 假模型不走原生工具调用，让上层用 JSON 协议——这样离线也能覆盖那条分支
    supports_native_tools = False

    def __init__(self, replies: Sequence[str] | None = None, model: str = "mock-assistant"):
        self.model = model
        self._replies = list(replies or [])
        self.calls: list[list[ChatMessage]] = []

    def _next_reply(self, messages: Sequence[ChatMessage]) -> str:
        if self._replies:
            return self._replies.pop(0)
        last_user = next((m for m in reversed(messages) if m.role == "user"), None)
        return f"[mock] 收到：{last_user.content if last_user else ''}"

    async def stream(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[object] | None = None,
    ) -> AsyncIterator[ChatChunk]:
        self.calls.append(list(messages))
        reply = self._next_reply(messages)
        # 每 8 个字符切一段，模拟真实的流式分片
        for start in range(0, len(reply), 8):
            yield ChatChunk(delta=reply[start : start + 8])
        prompt_tokens = sum(estimate_tokens(m.content) for m in messages)
        yield ChatChunk(usage=Usage(prompt_tokens, estimate_tokens(reply)))

    async def complete(self, messages: Sequence[ChatMessage]) -> tuple[str, Usage]:
        self.calls.append(list(messages))
        reply = self._next_reply(messages)
        prompt_tokens = sum(estimate_tokens(m.content) for m in messages)
        return reply, Usage(prompt_tokens, estimate_tokens(reply))

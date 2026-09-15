"""OpenAI 兼容后端：DeepSeek / 豆包方舟 / Ollama / 任意兼容服务共用这一份实现。"""

import json
from collections.abc import AsyncIterator, Sequence

import httpx

from .base import ChatChunk, ChatMessage, ToolCall, ToolSpec, Usage, estimate_tokens


class OpenAICompatProvider:
    name = "openai_compat"
    # OpenAI 兼容协议支持原生 function calling（Ollama / DeepSeek / 豆包方舟都实现了 tools 参数）
    supports_native_tools = True

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "",
        timeout: float = 60.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _payload(
        self,
        messages: Sequence[ChatMessage],
        stream: bool,
        tools: Sequence[ToolSpec] | None = None,
    ) -> dict:
        payload: dict = {
            "model": self.model,
            "messages": [self._serialize_message(m) for m in messages],
            "stream": stream,
        }
        if tools:
            payload["tools"] = [spec.to_openai() for spec in tools]
            payload["tool_choice"] = "auto"
        return payload

    @staticmethod
    def _serialize_message(message: ChatMessage) -> dict:
        """按 OpenAI 协议序列化消息：带工具调用要带 tool_calls，工具结果要带 tool_call_id。"""
        payload: dict = {"role": message.role, "content": message.content}
        if message.tool_calls:
            payload["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": call.arguments},
                }
                for call in message.tool_calls
            ]
        if message.tool_call_id:
            payload["tool_call_id"] = message.tool_call_id
        return payload

    async def stream(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolSpec] | None = None,
    ) -> AsyncIterator[ChatChunk]:
        prompt_estimate = sum(estimate_tokens(m.content) for m in messages)
        collected: list[str] = []
        usage: Usage | None = None
        # 流式返回的 tool_calls 是分片的（按 index 增量拼接），这里先聚合再一次性给出
        pending_calls: dict[int, dict[str, str]] = {}

        async with httpx.AsyncClient(timeout=self.timeout) as client, client.stream(
            "POST",
            f"{self.base_url}/chat/completions",
            headers=self._headers(),
            json=self._payload(messages, stream=True, tools=tools),
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    event = json.loads(data)
                except json.JSONDecodeError:
                    continue

                if isinstance(event.get("usage"), dict):
                    u = event["usage"]
                    usage = Usage(
                        int(u.get("prompt_tokens") or 0),
                        int(u.get("completion_tokens") or 0),
                    )

                choices = event.get("choices") or []
                if not choices:
                    continue
                choice_delta = choices[0].get("delta") or {}

                for raw_call in choice_delta.get("tool_calls") or []:
                    index = int(raw_call.get("index") or 0)
                    slot = pending_calls.setdefault(index, {"id": "", "name": "", "arguments": ""})
                    if raw_call.get("id"):
                        slot["id"] = str(raw_call["id"])
                    function = raw_call.get("function") or {}
                    if function.get("name"):
                        slot["name"] = str(function["name"])
                    if function.get("arguments"):
                        slot["arguments"] += str(function["arguments"])

                delta = choice_delta.get("content") or ""
                if delta:
                    collected.append(delta)
                    yield ChatChunk(delta=delta)

        if pending_calls:
            calls = [
                ToolCall(
                    id=slot["id"] or f"call_{index}",
                    name=slot["name"],
                    arguments=slot["arguments"] or "{}",
                )
                for index, slot in sorted(pending_calls.items())
                if slot["name"]
            ]
            if calls:
                yield ChatChunk(tool_calls=calls)

        if usage is None:
            usage = Usage(prompt_estimate, estimate_tokens("".join(collected)))
        yield ChatChunk(usage=usage)

    async def complete(self, messages: Sequence[ChatMessage]) -> tuple[str, Usage]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
            json=self._payload(messages, stream=False),
            )
            response.raise_for_status()
            data = response.json()

        text = data["choices"][0]["message"].get("content") or ""
        raw_usage = data.get("usage") or {}
        usage = Usage(
            int(raw_usage.get("prompt_tokens") or estimate_tokens("".join(m.content for m in messages))),
            int(raw_usage.get("completion_tokens") or estimate_tokens(text)),
        )
        return text, usage

"""OpenAI 兼容后端：DeepSeek / 豆包方舟 / Ollama / 任意兼容服务共用这一份实现。"""

import json
from collections.abc import AsyncIterator, Sequence

import httpx

from .base import ChatChunk, ChatMessage, Usage, estimate_tokens


class OpenAICompatProvider:
    name = "openai_compat"

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

    def _payload(self, messages: Sequence[ChatMessage], stream: bool) -> dict:
        return {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": stream,
        }

    async def stream(self, messages: Sequence[ChatMessage]) -> AsyncIterator[ChatChunk]:
        prompt_estimate = sum(estimate_tokens(m.content) for m in messages)
        collected: list[str] = []
        usage: Usage | None = None

        async with httpx.AsyncClient(timeout=self.timeout) as client, client.stream(
            "POST",
            f"{self.base_url}/chat/completions",
            headers=self._headers(),
            json=self._payload(messages, stream=True),
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
                delta = (choices[0].get("delta") or {}).get("content") or ""
                if delta:
                    collected.append(delta)
                    yield ChatChunk(delta=delta)

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

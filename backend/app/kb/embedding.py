"""向量化：开发用确定性哈希向量，生产可切到 OpenAI 兼容的嵌入接口。"""

import hashlib
import math
import re
from collections.abc import Sequence
from typing import Protocol

import httpx

_TOKEN_RE = re.compile(r"[a-z0-9_]+|[\u3400-\u9fff]")


def _tokens(text: str) -> list[str]:
    lowered = text.lower()
    latin = re.findall(r"[a-z0-9][a-z0-9._-]*", lowered)
    cjk = _TOKEN_RE.findall(lowered)
    cjk = [t for t in cjk if "\u3400" <= t <= "\u9fff"]
    bigrams = [f"{cjk[i]}{cjk[i + 1]}" for i in range(len(cjk) - 1)]
    return latin + cjk + bigrams


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vector))
    if norm == 0:
        return vector
    return [v / norm for v in vector]


class EmbeddingProvider(Protocol):
    dim: int

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        ...


class HashEmbedding:
    """把词哈希进固定维度并做 L2 归一化。

    它没有语义泛化能力（「电脑」不会命中「计算机」），但足够稳定、离线、
    免费，适合开发与测试；接真实业务时换成 EmbeddingAPI。
    """

    def __init__(self, dim: int = 256):
        self.dim = dim
        self.name = "hash"
        self.model = f"hash-{dim}"

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        for token in _tokens(text):
            digest = hashlib.md5(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dim
            vector[index] += 1.0
        return _normalize(vector)


class OpenAICompatEmbedding:
    """调用 /embeddings 接口，Base URL 与聊天接口一致。"""

    name = "openai_compat"

    def __init__(self, base_url: str, model: str, api_key: str = "", dim: int = 1536, timeout: float = 60.0):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.dim = dim
        self.timeout = timeout

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/embeddings",
                headers=headers,
                json={"model": self.model, "input": list(texts)},
            )
            response.raise_for_status()
            data = response.json()
        return [item["embedding"] for item in data["data"]]


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    # 前面已经校验过维度一致，这里用 strict=True 让维度问题尽早暴露
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)

"""上下文预算与超时保护。"""

import asyncio
from collections.abc import Sequence

from app.agent.runner import stream_agent
from app.agent.tools import build_default_registry
from app.llm.base import ChatChunk, ChatMessage, Usage, estimate_tokens


class SlowProvider:
    """先吐一个字，然后卡住不动，用来触发超时。"""

    name = "slow"
    model = "slow-model"

    async def stream(self, messages: Sequence[ChatMessage], tools: Sequence[object] | None = None):
        yield ChatChunk(delta="正在思考")
        await asyncio.sleep(10)
        yield ChatChunk(delta="永远不会到")

    async def complete(self, messages: Sequence[ChatMessage]) -> tuple[str, Usage]:
        await asyncio.sleep(10)
        return "", Usage()


async def test_agent_times_out_and_keeps_partial_output():
    events = [
        event
        async for event in stream_agent(
            SlowProvider(), build_default_registry(), [{"role": "user", "content": "在吗"}],
            timeout_seconds=0.2,
        )
    ]

    assert any(event["type"] == "timeout" for event in events)
    final = next(event for event in events if event["type"] == "final")
    assert "正在思考" in final["text"], "超时前已经吐出的内容要保留"
    assert "超时" in final["text"]


def test_history_is_trimmed_by_token_budget():
    """按 token 预算裁剪：超出预算的旧消息被丢掉，最新一条必须保留。"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.db.base import Base
    from app.services.chat import append_message, ensure_session, load_history

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    long_text = "这是一段很长的历史内容。" * 40  # 每条约 480 字符
    with Session(engine) as db:
        session = ensure_session(db, None, "上下文预算测试")
        for index in range(8):
            append_message(db, session.id, "user", f"{index}-{long_text}")
        append_message(db, session.id, "user", "最新的一句话")

        trimmed = load_history(db, session.id, max_tokens=600)
        untrimmed = load_history(db, session.id, max_tokens=100000)

    assert len(untrimmed) == 9
    assert len(trimmed) < len(untrimmed), "超出预算时应该丢掉旧消息"
    assert trimmed[-1]["content"] == "最新的一句话", "最新一条无论如何都要保留"
    assert sum(estimate_tokens(item["content"]) for item in trimmed) < 900


def test_history_always_keeps_latest_even_if_it_exceeds_budget():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.db.base import Base
    from app.services.chat import append_message, ensure_session, load_history

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        session = ensure_session(db, None, "超长单条")
        append_message(db, session.id, "user", "长" * 2000)
        history = load_history(db, session.id, max_tokens=10)

    assert len(history) == 1

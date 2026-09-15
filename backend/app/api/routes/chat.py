"""对话接口：默认流式（SSE），另有一个一次性返回的同步版本方便联调。

数据库会话的生命周期要特别小心：流式响应是在接口函数返回之后才写的，
那时依赖注入的会话可能已经关闭，所以落库时另开一个短会话（见 _persist）。
"""

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, sessionmaker

from ...agent.tools import build_default_registry
from ...core.config import Settings
from ...db.session import get_session_factory
from ...kb.embedding import EmbeddingProvider
from ...kb.service import KnowledgeSource
from ...llm.base import LLMProvider, Usage
from ...schemas.chat import ChatRequest, ChatResponse
from ...schemas.kb import SourceOut
from ...services import chat as chat_service
from ...services.dialogue import stream_dialogue
from ..deps import embedding_dep, enforce_rate_limit, get_db, provider_dep, settings_dep

router = APIRouter(prefix="/chat", tags=["chat"], dependencies=[Depends(enforce_rate_limit)])


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _source_out(sources: list[KnowledgeSource]) -> list[SourceOut]:
    return [SourceOut(**source.__dict__) for source in sources]


def _prepare(db: Session, payload: ChatRequest, embedding, settings: Settings):
    session = chat_service.ensure_session(db, payload.session_id, payload.message)
    if payload.mode and payload.mode != session.mode:
        session.mode = payload.mode
        db.commit()
        db.refresh(session)
    chat_service.append_message(db, session.id, "user", payload.message)
    return session


async def _knowledge(db, payload, embedding, settings) -> list[KnowledgeSource]:
    return await chat_service.collect_knowledge(
        db, embedding, settings, payload.message, payload.use_knowledge
    )


def _persist(
    factory: sessionmaker[Session],
    session_id: str,
    text: str,
    provider: LLMProvider,
    usage: Usage,
) -> None:
    """流式结束后另开一个短会话把回答与用量写库。"""
    with factory() as db:
        chat_service.append_message(db, session_id, "assistant", text)
        chat_service.record_usage(db, session_id, provider.model, usage)


@router.post("/stream")
async def chat_stream(
    payload: ChatRequest,
    db: Session = Depends(get_db),
    provider: LLMProvider = Depends(provider_dep),
    embedding: EmbeddingProvider = Depends(embedding_dep),
    settings: Settings = Depends(settings_dep),
) -> StreamingResponse:
    # 数据库是同步驱动，放进线程池执行，别卡住事件循环
    session = await run_in_threadpool(_prepare, db, payload, embedding, settings)
    sources = await _knowledge(db, payload, embedding, settings)
    history = await run_in_threadpool(
        chat_service.load_history, db, session.id, settings.history_max_tokens
    )
    context = chat_service.build_context(history, chat_service.knowledge_prompt(sources))

    registry = build_default_registry()
    max_steps = payload.max_steps or settings.agent_max_steps
    factory = get_session_factory()
    mode = payload.mode or session.mode
    knowledge = chat_service.knowledge_prompt(sources)

    async def event_stream() -> AsyncIterator[str]:
        yield _sse(
            {
                "type": "meta",
                "session_id": session.id,
                "mode": mode,
                "sources": [s.__dict__ for s in sources],
            }
        )
        collected: list[str] = []
        usage = Usage()
        steps = 0
        tool_calls: list[str] = []
        members: list[dict] = []

        try:
            stream = stream_dialogue(
                mode=mode,
                provider=provider,
                registry=registry,
                context=context,
                question=payload.message,
                knowledge=knowledge,
                max_steps=max_steps,
                settings=settings,
                system_prompt=payload.system_prompt,
            )
            async for event in stream:
                if event["type"] == "token":
                    collected.append(event["text"])
                    yield _sse(event)
                elif event["type"] in ("action", "tool", "plan", "member"):
                    if event["type"] == "action":
                        tool_calls.append(event["tool"])
                    yield _sse(event)
                elif event["type"] == "final":
                    text = event.get("text") or "".join(collected)
                    usage = Usage(
                        int(event.get("usage", {}).get("prompt_tokens", 0)),
                        int(event.get("usage", {}).get("completion_tokens", 0)),
                    )
                    steps = int(event.get("steps", 0))
                    members = event.get("members", [])
                    await run_in_threadpool(_persist, factory, session.id, text, provider, usage)
                    yield _sse(
                        {
                            "type": "final",
                            "text": text,
                            "session_id": session.id,
                            "mode": mode,
                            "steps": steps,
                            "tool_calls": tool_calls,
                            "members": members,
                            "usage": {
                                "prompt_tokens": usage.prompt_tokens,
                                "completion_tokens": usage.completion_tokens,
                            },
                        }
                    )
        except Exception as exc:  # noqa: BLE001 流已开始，只能把错误当事件吐出
            yield _sse({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
            return
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("", response_model=ChatResponse)
async def chat_once(
    payload: ChatRequest,
    db: Session = Depends(get_db),
    provider: LLMProvider = Depends(provider_dep),
    embedding: EmbeddingProvider = Depends(embedding_dep),
    settings: Settings = Depends(settings_dep),
) -> ChatResponse:
    session = await run_in_threadpool(_prepare, db, payload, embedding, settings)
    sources = await _knowledge(db, payload, embedding, settings)
    history = await run_in_threadpool(
        chat_service.load_history, db, session.id, settings.history_max_tokens
    )
    context = chat_service.build_context(history, chat_service.knowledge_prompt(sources))

    registry = build_default_registry()
    max_steps = payload.max_steps or settings.agent_max_steps
    mode = payload.mode or session.mode
    knowledge = chat_service.knowledge_prompt(sources)
    text = ""
    steps = 0
    usage = Usage()
    tool_calls: list[str] = []
    members: list[dict] = []

    stream = stream_dialogue(
        mode=mode,
        provider=provider,
        registry=registry,
        context=context,
        question=payload.message,
        knowledge=knowledge,
        max_steps=max_steps,
        settings=settings,
        system_prompt=payload.system_prompt,
    )
    async for event in stream:
        if event["type"] == "token":
            text += event["text"]
        elif event["type"] == "action":
            tool_calls.append(event["tool"])
        elif event["type"] == "final":
            text = event.get("text") or text
            steps = int(event.get("steps", 0))
            members = event.get("members", [])
            usage = Usage(
                int(event.get("usage", {}).get("prompt_tokens", 0)),
                int(event.get("usage", {}).get("completion_tokens", 0)),
            )

    await run_in_threadpool(chat_service.append_message, db, session.id, "assistant", text)
    await run_in_threadpool(chat_service.record_usage, db, session.id, provider.model, usage)

    return ChatResponse(
        session_id=session.id,
        text=text,
        steps=steps,
        mode=mode,
        usage={"prompt_tokens": usage.prompt_tokens, "completion_tokens": usage.completion_tokens},
        sources=_source_out(sources),
        tool_calls=tool_calls,
        members=members,
    )

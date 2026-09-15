"""对话接口：默认流式（SSE），另有一个一次性返回的同步版本方便联调。

数据库会话的生命周期要特别小心：流式响应是在接口函数返回之后才写的，
那时依赖注入的会话可能已经关闭，所以落库时另开一个短会话（见 _persist）。
"""

import json
import logging
import time
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, sessionmaker

from ...agent.tools import build_default_registry
from ...core.config import Settings
from ...core.observability import current_request_id
from ...db.session import get_session_factory
from ...kb.embedding import EmbeddingProvider
from ...kb.service import KnowledgeSource
from ...llm.base import LLMProvider, Usage
from ...schemas.chat import ChatRequest, ChatResponse
from ...schemas.kb import SourceOut
from ...services import chat as chat_service
from ...services.dialogue import stream_dialogue
from ..deps import (
    Principal,
    embedding_dep,
    enforce_rate_limit,
    get_db,
    provider_dep,
    settings_dep,
)

router = APIRouter(prefix="/chat", tags=["chat"], dependencies=[Depends(enforce_rate_limit)])
logger = logging.getLogger(__name__)


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _source_out(sources: list[KnowledgeSource]) -> list[SourceOut]:
    return [SourceOut(**source.__dict__) for source in sources]


def _prepare(
    db: Session,
    payload: ChatRequest,
    embedding,
    settings: Settings,
    owner_id: str,
):
    try:
        session = chat_service.ensure_session(
            db, payload.session_id, payload.message, owner_id=owner_id
        )
    except chat_service.SessionAccessDenied as exc:
        raise HTTPException(status_code=404, detail="会话不存在") from exc
    if payload.mode and payload.mode != session.mode:
        session.mode = payload.mode
        db.commit()
        db.refresh(session)
    chat_service.append_message(db, session.id, "user", payload.message, owner_id=owner_id)
    return session


async def _knowledge(db, payload, embedding, settings, owner_id: str) -> list[KnowledgeSource]:
    return await chat_service.collect_knowledge(
        db,
        embedding,
        settings,
        payload.message,
        payload.use_knowledge,
        owner_id=owner_id,
    )


def _persist(
    factory: sessionmaker[Session],
    session_id: str,
    text: str,
    provider: LLMProvider,
    usage: Usage,
    owner_id: str,
    settings: Settings,
    request_id: str,
) -> float:
    """流式结束后另开一个短会话把回答与用量写库。"""
    with factory() as db:
        chat_service.append_message(
            db, session_id, "assistant", text, owner_id=owner_id
        )
        return chat_service.record_usage(
            db,
            session_id,
            provider.model,
            usage,
            owner_id=owner_id,
            settings=settings,
            request_id=request_id,
        )


@router.post("/stream")
async def chat_stream(
    payload: ChatRequest,
    db: Session = Depends(get_db),
    provider: LLMProvider = Depends(provider_dep),
    embedding: EmbeddingProvider = Depends(embedding_dep),
    settings: Settings = Depends(settings_dep),
    principal: Principal = Depends(enforce_rate_limit),
) -> StreamingResponse:
    # 数据库是同步驱动，放进线程池执行，别卡住事件循环
    session = await run_in_threadpool(
        _prepare, db, payload, embedding, settings, principal.owner_id
    )
    sources = await _knowledge(db, payload, embedding, settings, principal.owner_id)
    history = await run_in_threadpool(
        chat_service.load_history,
        db,
        session.id,
        settings.history_max_tokens,
        owner_id=principal.owner_id,
    )
    context = chat_service.build_context(history, chat_service.knowledge_prompt(sources))

    registry = build_default_registry()
    max_steps = payload.max_steps or settings.agent_max_steps
    factory = get_session_factory()
    mode = payload.mode or session.mode
    knowledge = chat_service.knowledge_prompt(sources)
    started = time.perf_counter()
    request_id = current_request_id()

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
        first_token_ms: float | None = None
        cost = 0.0

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
                    if first_token_ms is None:
                        first_token_ms = (time.perf_counter() - started) * 1000
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
                    cost = await run_in_threadpool(
                        _persist,
                        factory,
                        session.id,
                        text,
                        provider,
                        usage,
                        principal.owner_id,
                        settings,
                        request_id,
                    )
                    logger.info(
                        "chat_completed mode=%s model=%s sources=%d steps=%d "
                        "tool_calls=%d first_token_ms=%.1f duration_ms=%.1f cost=%.8f",
                        mode,
                        provider.model,
                        len(sources),
                        steps,
                        len(tool_calls),
                        first_token_ms or 0.0,
                        (time.perf_counter() - started) * 1000,
                        cost,
                    )
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
                                "cost": cost,
                            },
                            "request_id": request_id,
                        }
                    )
        except Exception as exc:  # noqa: BLE001 流已开始，只能把错误当事件吐出
            logger.exception(
                "chat_stream_failed mode=%s model=%s duration_ms=%.1f",
                mode,
                provider.model,
                (time.perf_counter() - started) * 1000,
            )
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
    principal: Principal = Depends(enforce_rate_limit),
) -> ChatResponse:
    started = time.perf_counter()
    session = await run_in_threadpool(
        _prepare, db, payload, embedding, settings, principal.owner_id
    )
    sources = await _knowledge(db, payload, embedding, settings, principal.owner_id)
    history = await run_in_threadpool(
        chat_service.load_history,
        db,
        session.id,
        settings.history_max_tokens,
        owner_id=principal.owner_id,
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

    await run_in_threadpool(
        chat_service.append_message,
        db,
        session.id,
        "assistant",
        text,
        owner_id=principal.owner_id,
    )
    cost = await run_in_threadpool(
        chat_service.record_usage,
        db,
        session.id,
        provider.model,
        usage,
        owner_id=principal.owner_id,
        settings=settings,
    )
    logger.info(
        "chat_completed mode=%s model=%s sources=%d steps=%d tool_calls=%d "
        "duration_ms=%.1f cost=%.8f",
        mode,
        provider.model,
        len(sources),
        steps,
        len(tool_calls),
        (time.perf_counter() - started) * 1000,
        cost,
    )

    return ChatResponse(
        session_id=session.id,
        text=text,
        steps=steps,
        mode=mode,
        usage={
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
        },
        cost=cost,
        request_id=current_request_id(),
        sources=_source_out(sources),
        tool_calls=tool_calls,
        members=members,
    )

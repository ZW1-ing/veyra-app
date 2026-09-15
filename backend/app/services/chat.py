"""对话编排：会话准备、历史拼装、知识注入、结果落库。

路由层只做 HTTP 的事，这里放业务逻辑，方便单独测试。
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import Settings
from ..db.models import MessageRow, SessionRow, UsageRow
from ..kb.service import KnowledgeSource, render_sources, search_knowledge
from ..llm.base import Usage, estimate_tokens

HISTORY_MAX_MESSAGES = 200  # 单条数上限；真正的裁剪靠 token 预算
PER_MESSAGE_OVERHEAD = 4  # 每条消息的角色标记等固定开销


def ensure_session(db: Session, session_id: str | None, title_hint: str = "") -> SessionRow:
    if session_id:
        existing = db.get(SessionRow, session_id)
        if existing:
            return existing

    title = (title_hint.strip()[:30] or "新会话")
    session = SessionRow(title=title)
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def append_message(
    db: Session,
    session_id: str,
    role: str,
    content: str,
    agent_id: str | None = None,
    tool_name: str | None = None,
) -> MessageRow:
    row = MessageRow(
        session_id=session_id,
        role=role,
        content=content,
        agent_id=agent_id,
        tool_name=tool_name,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def load_history(
    db: Session,
    session_id: str,
    max_tokens: int = 3000,
    limit: int = HISTORY_MAX_MESSAGES,
) -> list[dict[str, str]]:
    """按 token 预算取历史。

    只按条数截断不够用：三条长文档和三十条短消息的 token 量差着数量级，
    前者照样会把上下文撑爆。这里从最新往回累加，超预算就停，
    但无论如何保留最新一条——否则用户刚问的那句会被裁掉。
    """
    rows: Sequence[MessageRow] = (
        db.execute(
            select(MessageRow)
            .where(MessageRow.session_id == session_id)
            .order_by(MessageRow.created_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )

    selected: list[MessageRow] = []
    used = 0
    for row in rows:  # rows 已经是「从新到旧」
        cost = estimate_tokens(row.content) + PER_MESSAGE_OVERHEAD
        if selected and max_tokens > 0 and used + cost > max_tokens:
            break
        selected.append(row)
        used += cost

    return [{"role": row.role, "content": row.content} for row in reversed(selected)]


def build_context(history: list[dict[str, str]], knowledge: str = "") -> list[dict[str, str]]:
    """把检索到的资料作为 system 消息插到最前面，历史消息保持原顺序。"""
    context: list[dict[str, str]] = []
    if knowledge:
        context.append({"role": "system", "content": knowledge})
    context.extend(history)
    return context


async def collect_knowledge(
    db: Session,
    embedding,
    settings: Settings,
    query: str,
    enabled: bool,
) -> list[KnowledgeSource]:
    if not enabled:
        return []
    return await search_knowledge(db, embedding, settings, query)


def knowledge_prompt(sources: Sequence[KnowledgeSource]) -> str:
    return render_sources(sources)


def record_usage(db: Session, session_id: str, model: str, usage: Usage) -> None:
    db.add(
        UsageRow(
            session_id=session_id,
            model=model,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
        )
    )
    db.commit()

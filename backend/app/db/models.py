"""数据模型：会话、消息、知识库文档、知识库分块。

设计取舍：
- 主键用 32 位十六进制字符串，而不是自增整数，方便以后分库或与前端对齐。
- 消息与会话是「一对多 + 级联删除」，删会话就删干净，不留孤儿数据。
- 向量暂时以 JSON 存进 MySQL：学习阶段够用、可读性好；数据量上来后换向量库（见 README）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

# MySQL 的 DATETIME 默认精确到秒，同一秒内写入的多条消息会排序错乱
# （用户消息排到回答后面）。这里统一用微秒精度。
Timestamp = DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")


def new_id() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    return datetime.now(UTC)


class SessionRow(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(
        String(64), default="anonymous", server_default="anonymous"
    )
    title: Mapped[str] = mapped_column(String(200), default="新会话")
    mode: Mapped[str] = mapped_column(String(16), default="single")  # single | swarm
    created_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow, onupdate=utcnow)

    messages: Mapped[list[MessageRow]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="MessageRow.created_at",
        lazy="selectin",
    )

    __table_args__ = (Index("ix_sessions_owner_updated", "owner_id", "updated_at"),)


class MessageRow(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    # 不在这里加 index=True：下面的复合索引 (session_id, created_at) 已经覆盖了
    # 按会话查消息的场景，再建一个单列索引只增加写入成本，还会和外键自动索引打架。
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(16))  # system | user | assistant | tool
    content: Mapped[str] = mapped_column(Text)
    agent_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tool_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow)

    session: Mapped[SessionRow] = relationship(back_populates="messages")

    __table_args__ = (Index("ix_messages_session_created", "session_id", "created_at"),)


class DocumentRow(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(
        String(64), default="anonymous", server_default="anonymous"
    )
    name: Mapped[str] = mapped_column(String(255))
    source_type: Mapped[str] = mapped_column(String(16), default="text")  # text | file | url
    char_count: Mapped[int] = mapped_column(Integer, default=0)
    # 正文的 sha256，用来识别「同一份内容重复入库」
    content_hash: Mapped[str] = mapped_column(String(64), default="", server_default=text("''"))
    # 记录入库时用的分块与嵌入配置。
    # 没有这几个字段的话，换了嵌入模型之后检索会静默变差（维度对不上，余弦相似度直接算成 0）。
    # server_default 要和迁移里写的一致，否则 alembic check 会报「默认值漂移」
    chunk_size: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # 空串默认值要写成 text("''")：直接写 server_default="" 时数据库反射回来的是
    # TextClause，Alembic 会误判成「默认值不一致」，alembic check 一直报红。
    embedding_model: Mapped[str] = mapped_column(
        String(64), default="", server_default=text("''")
    )
    embedding_dim: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow)

    chunks: Mapped[list[ChunkRow]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="ChunkRow.chunk_index",
    )

    __table_args__ = (Index("ix_documents_owner_created", "owner_id", "created_at"),)


class ChunkRow(Base):
    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)
    token_count: Mapped[int] = mapped_column(Integer, default=0)

    document: Mapped[DocumentRow] = relationship(back_populates="chunks")


class UsageRow(Base):
    """按次记录 token 用量与费用，对应 Veyra 的「用量统计」。"""

    __tablename__ = "usage_records"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(
        String(64), default="anonymous", server_default="anonymous"
    )
    session_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    request_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    model: Mapped[str] = mapped_column(String(64), default="")
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow)

    __table_args__ = (Index("ix_usage_records_owner_created", "owner_id", "created_at"),)

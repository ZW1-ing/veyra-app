"""引擎与会话工厂。

这里的 engine 是懒加载的：测试里先设置 DATABASE_URL 再调用 reset_engine()，
就会用新的连接串重新建引擎，不用重启进程。
"""

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ..core.config import get_settings
from .base import Base

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        settings = get_settings()
        kwargs: dict = {"pool_pre_ping": True, "future": True}
        if settings.database_url.startswith("sqlite"):
            # SQLite 在测试里用内存库，需要允许跨线程
            kwargs["connect_args"] = {"check_same_thread": False}
            kwargs.pop("pool_pre_ping")
        _engine = create_engine(settings.database_url, **kwargs)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(
            bind=get_engine(), autoflush=False, expire_on_commit=False, future=True
        )
    return _session_factory


def reset_engine() -> None:
    """释放当前引擎并清空缓存，调用方拿到的一定是新引擎。"""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None


def init_db() -> None:
    """开发期建表用；生产用 Alembic 迁移（见 README）。"""
    from . import models  # noqa: F401  确保模型已注册到 metadata

    Base.metadata.create_all(bind=get_engine())


def get_db() -> Iterator[Session]:
    """FastAPI 依赖注入用的会话。"""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()

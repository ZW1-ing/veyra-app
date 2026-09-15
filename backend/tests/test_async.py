"""确认异步接口里的同步数据库操作没有卡住事件循环。"""

import asyncio
import time

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.base import Base
from app.kb import service as kb_service
from app.kb.embedding import HashEmbedding


async def test_slow_db_query_does_not_block_event_loop(monkeypatch):
    """把慢查询放到线程池后，事件循环应该仍在正常调度其它任务。

    如果同步查询留在事件循环里，这 0.3 秒内心跳计数会停在个位数。
    """

    def slow_load(db, owner_id="anonymous"):
        time.sleep(0.3)
        return []

    monkeypatch.setattr(kb_service, "_load_candidates", slow_load)

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    settings = Settings(database_url="sqlite+pysqlite:///:memory:")

    ticks = 0

    async def heartbeat():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.005)
            ticks += 1

    with Session(engine) as db:
        task = asyncio.create_task(heartbeat())
        started = time.perf_counter()
        result = await kb_service.search_knowledge(db, HashEmbedding(dim=32), settings, "任意问题")
        elapsed = time.perf_counter() - started
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert result == []
    assert elapsed >= 0.3, "慢查询的耗时应该被真实等到"
    assert ticks >= 20, f"事件循环被阻塞了，0.3 秒内只跳了 {ticks} 次"

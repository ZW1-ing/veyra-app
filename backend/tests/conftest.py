"""测试夹具：把数据库切到临时 SQLite，模型切到 mock，保证离线可跑。"""

import os

import pytest


@pytest.fixture(scope="session", autouse=True)
def _isolated_env(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("db") / "test.db"
    os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{db_path.as_posix()}"
    os.environ["LLM_PROVIDER"] = "mock"
    os.environ["EMBEDDING_PROVIDER"] = "hash"
    os.environ["EMBEDDING_DIM"] = "128"
    os.environ["AGENT_MAX_STEPS"] = "3"

    from app.core.config import reset_settings_cache
    from app.db import session as db_session

    reset_settings_cache()
    db_session.reset_engine()
    yield
    db_session.reset_engine()


@pytest.fixture
def app_instance():
    from app.main import create_app

    return create_app()


@pytest.fixture
def client(app_instance):
    from fastapi.testclient import TestClient

    with TestClient(app_instance) as test_client:
        yield test_client


def parse_sse(body: str) -> list[dict]:
    """把 SSE 文本还原成事件列表，供断言使用。"""
    import json

    events = []
    for line in body.splitlines():
        if not line.startswith("data: "):
            continue
        payload = line[6:]
        if payload == "[DONE]":
            events.append({"type": "done"})
            continue
        events.append(json.loads(payload))
    return events

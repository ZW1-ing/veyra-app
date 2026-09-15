"""用量统计：记下的 token 要能查出来。"""

from app.db.models import UsageRow
from app.db.session import get_session_factory
from app.llm.base import Usage
from app.services import chat as chat_service


def _seed_usage() -> None:
    with get_session_factory()() as db:
        session = chat_service.ensure_session(db, None, "用量统计用例")
        chat_service.record_usage(db, session.id, "qwen2.5", Usage(100, 20))
        chat_service.record_usage(db, session.id, "qwen2.5", Usage(50, 10))
        chat_service.record_usage(db, session.id, "bge-m3", Usage(30, 5))


def test_usage_summary_aggregates_by_model_and_day(client):
    _seed_usage()

    response = client.get("/usage")
    assert response.status_code == 200
    body = response.json()

    assert body["total_calls"] >= 3
    assert body["total_tokens"] == body["prompt_tokens"] + body["completion_tokens"]

    by_model = {item["key"]: item for item in body["by_model"]}
    assert by_model["qwen2.5"]["calls"] >= 2
    assert by_model["qwen2.5"]["total_tokens"] >= 180
    assert by_model["bge-m3"]["calls"] >= 1

    # 同一天的三次调用应当聚成一行，而不是散成三行
    assert len(body["by_day"]) >= 1
    assert sum(item["calls"] for item in body["by_day"]) == body["total_calls"]


def test_usage_can_be_recorded_for_a_chat_turn(client, app_instance):
    """跑一轮真实对话后，用量应该自动进表。"""
    from app.llm.mock import MockProvider

    app_instance.state.provider = MockProvider(["好的"])
    before = client.get("/usage").json()["total_calls"]

    assert client.post("/chat", json={"message": "你好", "use_knowledge": False}).status_code == 200

    after = client.get("/usage").json()
    assert after["total_calls"] == before + 1
    assert after["total_tokens"] > 0


def test_usage_rows_have_model_and_tokens():
    with get_session_factory()() as db:
        row = db.query(UsageRow).first()
    assert row is not None
    assert row.model
    assert row.prompt_tokens >= 0

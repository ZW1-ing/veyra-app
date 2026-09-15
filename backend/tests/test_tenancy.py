"""API Key 对应租户：会话、知识库和用量都不能串数据。"""

import pytest


@pytest.fixture
def tenant_keys(monkeypatch):
    monkeypatch.setenv("API_KEYS", "key-a,key-b")
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "0")
    from app.core.config import reset_settings_cache

    reset_settings_cache()
    yield {"a": {"X-API-Key": "key-a"}, "b": {"X-API-Key": "key-b"}}
    monkeypatch.delenv("API_KEYS", raising=False)
    monkeypatch.delenv("RATE_LIMIT_PER_MINUTE", raising=False)
    reset_settings_cache()


def test_sessions_are_isolated_by_api_key(client, tenant_keys):
    created = client.post("/sessions", json={"title": "A 的会话"}, headers=tenant_keys["a"])
    assert created.status_code == 201
    session_id = created.json()["id"]

    listed_b = client.get("/sessions", headers=tenant_keys["b"]).json()
    assert session_id not in {item["id"] for item in listed_b}
    assert client.get(f"/sessions/{session_id}", headers=tenant_keys["b"]).status_code == 404
    assert client.delete(f"/sessions/{session_id}", headers=tenant_keys["b"]).status_code == 404

    blocked_chat = client.post(
        "/chat",
        json={"session_id": session_id, "message": "尝试读取别人的会话", "use_knowledge": False},
        headers=tenant_keys["b"],
    )
    assert blocked_chat.status_code == 404


def test_knowledge_base_is_isolated_by_api_key(client, tenant_keys):
    text = "租户 A 的私有资料：代号赤霄，只在 A 的知识库里可见。"
    created = client.post(
        "/kb/documents",
        json={"name": "tenant-a.md", "text": text},
        headers=tenant_keys["a"],
    )
    assert created.status_code == 201
    document_id = created.json()["id"]

    listed_b = client.get("/kb/documents", headers=tenant_keys["b"]).json()
    assert document_id not in {item["id"] for item in listed_b}

    found_b = client.post(
        "/kb/search",
        json={"query": "代号赤霄是什么"},
        headers=tenant_keys["b"],
    )
    assert found_b.status_code == 200
    assert found_b.json() == []

    assert (
        client.delete(f"/kb/documents/{document_id}", headers=tenant_keys["b"]).status_code
        == 404
    )
    assert client.delete(f"/kb/documents/{document_id}", headers=tenant_keys["a"]).status_code == 204


def test_usage_is_isolated_by_api_key(client, tenant_keys):
    before_b = client.get("/usage", headers=tenant_keys["b"]).json()["total_calls"]

    response = client.post(
        "/chat",
        json={"message": "租户 A 的记录", "use_knowledge": False},
        headers=tenant_keys["a"],
    )
    assert response.status_code == 200

    usage_a = client.get("/usage", headers=tenant_keys["a"]).json()
    usage_b = client.get("/usage", headers=tenant_keys["b"]).json()
    assert usage_a["total_calls"] >= 1
    assert usage_b["total_calls"] == before_b

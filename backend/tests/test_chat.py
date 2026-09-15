from tests.conftest import parse_sse


def test_chat_once_persists_messages_and_usage(client):
    response = client.post("/chat", json={"message": "你好"})
    assert response.status_code == 200
    body = response.json()
    assert "[mock]" in body["text"]
    assert body["usage"]["completion_tokens"] > 0

    session_id = body["session_id"]
    messages = client.get(f"/sessions/{session_id}/messages").json()
    roles = [m["role"] for m in messages]
    assert roles == ["user", "assistant"]
    assert messages[0]["content"] == "你好"


def test_chat_stream_emits_tokens_then_final(client):
    response = client.post("/chat/stream", json={"message": "流式测试"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    events = parse_sse(response.text)
    types = [e["type"] for e in events]
    assert types[0] == "meta"
    assert "token" in types
    assert types[-1] == "done"

    final = next(e for e in events if e["type"] == "final")
    streamed = "".join(e["text"] for e in events if e["type"] == "token")
    assert final["text"] == streamed
    assert final["session_id"]


def test_chat_continues_existing_session(client):
    first = client.post("/chat", json={"message": "第一条"}).json()
    second = client.post(
        "/chat", json={"session_id": first["session_id"], "message": "第二条"}
    ).json()
    assert second["session_id"] == first["session_id"]

    messages = client.get(f"/sessions/{first['session_id']}/messages").json()
    assert [m["content"] for m in messages] == ["第一条", first["text"], "第二条", second["text"]]

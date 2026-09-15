def test_session_crud_flow(client):
    created = client.post("/sessions", json={"title": "面试准备"})
    assert created.status_code == 201
    session_id = created.json()["id"]

    listed = client.get("/sessions")
    assert listed.status_code == 200
    assert any(item["id"] == session_id for item in listed.json())

    detail = client.get(f"/sessions/{session_id}")
    assert detail.status_code == 200
    assert detail.json()["title"] == "面试准备"
    assert detail.json()["messages"] == []

    deleted = client.delete(f"/sessions/{session_id}")
    assert deleted.status_code == 204
    assert client.get(f"/sessions/{session_id}").status_code == 404


def test_missing_session_returns_404(client):
    assert client.get("/sessions/not-exists").status_code == 404
    assert client.get("/sessions/not-exists/messages").status_code == 404

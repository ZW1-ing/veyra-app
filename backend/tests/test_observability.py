"""请求追踪：入口接收或生成请求 ID，并原样回给调用方。"""


def test_request_id_is_returned(client):
    response = client.get("/sessions", headers={"X-Request-ID": "trace-12345678"})
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "trace-12345678"


def test_invalid_request_id_is_replaced(client):
    response = client.get("/sessions", headers={"X-Request-ID": "bad id"})
    request_id = response.headers["X-Request-ID"]
    assert request_id != "bad id"
    assert len(request_id) == 16

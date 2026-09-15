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


def test_prometheus_metrics_are_available(client):
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "veyra_http_requests_total" in response.text
    assert "veyra_chat_tokens_total" in response.text


def test_prometheus_metrics_respect_api_key(client, monkeypatch):
    monkeypatch.setenv("API_KEYS", "metrics-key")
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "0")
    from app.core.config import reset_settings_cache

    reset_settings_cache()
    try:
        assert client.get("/metrics").status_code == 401
        assert (
            client.get("/metrics", headers={"X-API-Key": "metrics-key"}).status_code
            == 200
        )
    finally:
        monkeypatch.delenv("API_KEYS", raising=False)
        monkeypatch.delenv("RATE_LIMIT_PER_MINUTE", raising=False)
        reset_settings_cache()

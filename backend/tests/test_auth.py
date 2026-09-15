"""鉴权与限流：接口默认关闭鉴权（本地开发），配置了 key 之后必须校验。"""


import pytest

from app.core.ratelimit import limiter


@pytest.fixture
def auth_env(monkeypatch):
    """临时开启鉴权与低限额，测完恢复。"""

    def apply(keys: str, limit: int = 120):
        monkeypatch.setenv("API_KEYS", keys)
        monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", str(limit))
        from app.core.config import reset_settings_cache

        reset_settings_cache()
        limiter.reset()

    yield apply

    monkeypatch.delenv("API_KEYS", raising=False)
    monkeypatch.delenv("RATE_LIMIT_PER_MINUTE", raising=False)
    from app.core.config import reset_settings_cache

    reset_settings_cache()
    limiter.reset()


def test_health_is_open_even_when_auth_enabled(client, auth_env):
    """容器探活不该需要密钥，否则编排系统没法判断服务是否就绪。"""
    auth_env("secret-key")
    assert client.get("/health").status_code == 200


def test_protected_endpoints_reject_missing_or_wrong_key(client, auth_env):
    auth_env("secret-key", limit=0)

    assert client.get("/sessions").status_code == 401
    assert client.get("/sessions", headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.post("/chat", json={"message": "你好"}).status_code == 401


def test_protected_endpoints_accept_valid_key(client, auth_env):
    auth_env("secret-key", limit=0)

    ok = client.get("/sessions", headers={"X-API-Key": "secret-key"})
    assert ok.status_code == 200


def test_multiple_keys_are_supported(client, auth_env):
    auth_env("key-a, key-b", limit=0)

    for key in ("key-a", "key-b"):
        assert client.get("/sessions", headers={"X-API-Key": key}).status_code == 200


def test_rate_limit_returns_429_with_retry_after(client, auth_env):
    auth_env("secret-key", limit=3)
    headers = {"X-API-Key": "secret-key"}

    for _ in range(3):
        assert client.get("/sessions", headers=headers).status_code == 200

    blocked = client.get("/sessions", headers=headers)
    assert blocked.status_code == 429
    assert int(blocked.headers["retry-after"]) >= 1


def test_limiter_counts_per_key(auth_env):
    """不同 key 各算各的额度，一个被限流不影响另一个。"""
    limiter.reset()
    assert limiter.check("k1", limit=1) == (True, 0)
    assert limiter.check("k1", limit=1)[0] is False
    assert limiter.check("k2", limit=1) == (True, 0)

"""租户每日预算与模型额度。"""

import pytest


@pytest.fixture
def quota_env(monkeypatch):
    def apply(key: str, quotas: str, prices: str = "{}"):
        monkeypatch.setenv("API_KEYS", key)
        monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "0")
        monkeypatch.setenv("TENANT_QUOTAS", quotas)
        monkeypatch.setenv("MODEL_PRICES", prices)
        from app.core.config import reset_settings_cache

        reset_settings_cache()
        return {"X-API-Key": key}

    yield apply

    for name in ("API_KEYS", "RATE_LIMIT_PER_MINUTE", "TENANT_QUOTAS", "MODEL_PRICES"):
        monkeypatch.delenv(name, raising=False)
    from app.core.config import reset_settings_cache

    reset_settings_cache()


def test_daily_token_quota_blocks_follow_up_request(client, quota_env):
    headers = quota_env(
        "quota-token",
        '{"quota-token":{"daily_tokens":1}}',
    )

    first = client.post(
        "/chat",
        json={"message": "第一次调用", "use_knowledge": False},
        headers=headers,
    )
    assert first.status_code == 200

    blocked = client.post(
        "/chat",
        json={"message": "第二次调用", "use_knowledge": False},
        headers=headers,
    )
    assert blocked.status_code == 429
    assert "token 额度已用完" in blocked.json()["detail"]
    assert int(blocked.headers["retry-after"]) >= 1

    quota = client.get("/usage", headers=headers).json()["quota"]
    assert quota["daily_tokens_limit"] == 1
    assert quota["daily_tokens_used"] > 1
    assert quota["daily_tokens_remaining"] == 0


def test_model_token_quota_is_enforced_per_model(client, quota_env):
    headers = quota_env(
        "quota-model",
        '{"quota-model":{"model_tokens":{"mock-assistant":1}}}',
    )

    assert (
        client.post(
            "/chat",
            json={"message": "第一次模型调用", "use_knowledge": False},
            headers=headers,
        ).status_code
        == 200
    )

    blocked = client.post(
        "/chat",
        json={"message": "第二次模型调用", "use_knowledge": False},
        headers=headers,
    )
    assert blocked.status_code == 429
    assert "mock-assistant" in blocked.json()["detail"]


def test_daily_cost_quota_uses_recorded_model_cost(client, quota_env):
    headers = quota_env(
        "quota-cost",
        '{"quota-cost":{"daily_cost":0.000001}}',
        '{"mock-assistant":{"prompt_per_million":1000000,"completion_per_million":2000000}}',
    )

    first = client.post(
        "/chat",
        json={"message": "昂贵调用", "use_knowledge": False},
        headers=headers,
    )
    assert first.status_code == 200
    assert first.json()["cost"] > 0

    blocked = client.post(
        "/chat",
        json={"message": "再次调用", "use_knowledge": False},
        headers=headers,
    )
    assert blocked.status_code == 429
    assert "费用额度已用完" in blocked.json()["detail"]

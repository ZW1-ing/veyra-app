"""租户每日额度：token、成本和模型级 token 上限。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.config import Settings, TenantQuota
from ..db.models import UsageRow


@dataclass(frozen=True)
class QuotaDecision:
    allowed: bool
    scope: str = ""
    detail: str = ""
    retry_after: int = 0


@dataclass(frozen=True)
class DailyUsage:
    tokens: int
    cost: float
    model_tokens: dict[str, int]


def quota_for(key: str, settings: Settings) -> TenantQuota:
    return settings.tenant_quotas.get(key, settings.default_tenant_quota)


def _timezone(settings: Settings) -> ZoneInfo:
    try:
        return ZoneInfo(settings.quota_timezone)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def quota_window(settings: Settings, now: datetime | None = None) -> tuple[datetime, datetime]:
    """返回数据库可直接比较的 naive UTC 起止时间。"""
    timezone = _timezone(settings)
    local_now = (now or datetime.now(UTC)).astimezone(timezone)
    start = datetime.combine(local_now.date(), time.min, tzinfo=timezone)
    end = start + timedelta(days=1)
    return (
        start.astimezone(UTC).replace(tzinfo=None),
        end.astimezone(UTC).replace(tzinfo=None),
    )


def daily_usage(db: Session, owner_id: str, settings: Settings) -> DailyUsage:
    start, end = quota_window(settings)
    rows = db.execute(
        select(
            UsageRow.model,
            func.coalesce(func.sum(UsageRow.prompt_tokens + UsageRow.completion_tokens), 0),
            func.coalesce(func.sum(UsageRow.cost), 0.0),
        )
        .where(
            UsageRow.owner_id == owner_id,
            UsageRow.created_at >= start,
            UsageRow.created_at < end,
        )
        .group_by(UsageRow.model)
    ).all()

    model_tokens = {str(model or ""): int(tokens or 0) for model, tokens, _ in rows}
    return DailyUsage(
        tokens=sum(model_tokens.values()),
        cost=round(sum(float(cost or 0) for _, _, cost in rows), 8),
        model_tokens=model_tokens,
    )


def _retry_after(settings: Settings) -> int:
    _, end = quota_window(settings)
    now = datetime.now(UTC).replace(tzinfo=None)
    return max(1, math.ceil((end - now).total_seconds()))


def check_quota(
    db: Session,
    *,
    quota_key: str,
    owner_id: str,
    model: str,
    settings: Settings,
) -> QuotaDecision:
    quota = quota_for(quota_key, settings)
    if (
        quota.daily_tokens <= 0
        and quota.daily_cost <= 0
        and not any(limit > 0 for limit in quota.model_tokens.values())
    ):
        return QuotaDecision(allowed=True)

    usage = daily_usage(db, owner_id, settings)

    if quota.daily_tokens > 0 and usage.tokens >= quota.daily_tokens:
        return QuotaDecision(
            allowed=False,
            scope="daily_tokens",
            detail=f"今日 token 额度已用完（{usage.tokens}/{quota.daily_tokens}）",
            retry_after=_retry_after(settings),
        )

    model_limit = quota.model_tokens.get(model, 0)
    model_used = usage.model_tokens.get(model, 0)
    if model_limit > 0 and model_used >= model_limit:
        return QuotaDecision(
            allowed=False,
            scope=f"model:{model}",
            detail=f"模型 {model} 的今日额度已用完（{model_used}/{model_limit} token）",
            retry_after=_retry_after(settings),
        )

    if quota.daily_cost > 0 and usage.cost >= quota.daily_cost:
        return QuotaDecision(
            allowed=False,
            scope="daily_cost",
            detail=f"今日费用额度已用完（${usage.cost:.4f}/${quota.daily_cost:.4f}）",
            retry_after=_retry_after(settings),
        )

    return QuotaDecision(allowed=True)


def quota_status(
    db: Session,
    *,
    quota_key: str,
    owner_id: str,
    settings: Settings,
) -> dict:
    quota = quota_for(quota_key, settings)
    usage = daily_usage(db, owner_id, settings)
    start, end = quota_window(settings)
    del start

    return {
        "timezone": _timezone(settings).key,
        "resets_at": end.replace(tzinfo=UTC),
        "daily_tokens_limit": quota.daily_tokens or None,
        "daily_tokens_used": usage.tokens,
        "daily_tokens_remaining": max(0, quota.daily_tokens - usage.tokens)
        if quota.daily_tokens > 0
        else None,
        "daily_cost_limit": quota.daily_cost or None,
        "daily_cost_used": usage.cost,
        "daily_cost_remaining": max(0.0, round(quota.daily_cost - usage.cost, 8))
        if quota.daily_cost > 0
        else None,
        "model_token_limits": [
            {
                "model": model,
                "token_limit": limit,
                "token_used": usage.model_tokens.get(model, 0),
                "token_remaining": max(0, limit - usage.model_tokens.get(model, 0)),
            }
            for model, limit in quota.model_tokens.items()
            if limit > 0
        ],
    }

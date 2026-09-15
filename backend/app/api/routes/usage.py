"""用量统计：把每次对话记下的 token 用量聚合成可看的报表。

数据在 usage_records 表里一直是只进不出，这个接口把它变成能查的东西：
按天看趋势、按模型看分布。
"""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...core.config import Settings
from ...db.models import UsageRow
from ...schemas.usage import UsageBucket, UsageSummary
from ..deps import Principal, enforce_rate_limit, get_db, settings_dep

router = APIRouter(prefix="/usage", tags=["usage"], dependencies=[Depends(enforce_rate_limit)])


def _bucket(key: str, calls: int, prompt: int, completion: int, cost: float) -> UsageBucket:
    return UsageBucket(
        key=str(key),
        calls=int(calls or 0),
        prompt_tokens=int(prompt or 0),
        completion_tokens=int(completion or 0),
        total_tokens=int(prompt or 0) + int(completion or 0),
        cost=round(float(cost or 0), 8),
    )


@router.get("", response_model=UsageSummary)
def usage_summary(
    days: int = Query(default=14, ge=1, le=365),
    db: Session = Depends(get_db),
    principal: Principal = Depends(enforce_rate_limit),
    settings: Settings = Depends(settings_dep),
) -> UsageSummary:
    # 时间范围在 Python 里算：SQLite 与 MySQL 的日期函数名不同，
    # 传一个固定时间点进去两边都能正确比较（库里存的是 UTC 的 naive 值）。
    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days)

    totals = db.execute(
        select(
            func.count(UsageRow.id),
            func.coalesce(func.sum(UsageRow.prompt_tokens), 0),
            func.coalesce(func.sum(UsageRow.completion_tokens), 0),
            func.coalesce(func.sum(UsageRow.cost), 0.0),
        )
        .where(
            UsageRow.created_at >= cutoff,
            UsageRow.owner_id == principal.owner_id,
        )
    ).one()

    day_rows = db.execute(
        select(
            func.date(UsageRow.created_at),
            func.count(UsageRow.id),
            func.coalesce(func.sum(UsageRow.prompt_tokens), 0),
            func.coalesce(func.sum(UsageRow.completion_tokens), 0),
            func.coalesce(func.sum(UsageRow.cost), 0.0),
        )
        .where(
            UsageRow.created_at >= cutoff,
            UsageRow.owner_id == principal.owner_id,
        )
        .group_by(func.date(UsageRow.created_at))
        .order_by(func.date(UsageRow.created_at))
    ).all()

    model_rows = db.execute(
        select(
            UsageRow.model,
            func.count(UsageRow.id),
            func.coalesce(func.sum(UsageRow.prompt_tokens), 0),
            func.coalesce(func.sum(UsageRow.completion_tokens), 0),
            func.coalesce(func.sum(UsageRow.cost), 0.0),
        )
        .where(
            UsageRow.created_at >= cutoff,
            UsageRow.owner_id == principal.owner_id,
        )
        .group_by(UsageRow.model)
        .order_by(func.count(UsageRow.id).desc())
    ).all()

    return UsageSummary(
        total_calls=int(totals[0] or 0),
        prompt_tokens=int(totals[1] or 0),
        completion_tokens=int(totals[2] or 0),
        total_tokens=int(totals[1] or 0) + int(totals[2] or 0),
        total_cost=round(float(totals[3] or 0), 8),
        pricing_configured=bool(settings.pricing_configured),
        days=days,
        by_day=[_bucket(*row) for row in day_rows],
        by_model=[_bucket(*row) for row in model_rows],
    )

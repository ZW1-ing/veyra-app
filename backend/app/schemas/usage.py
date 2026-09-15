"""用量统计出入参。"""

from datetime import datetime

from pydantic import BaseModel


class UsageBucket(BaseModel):
    """按某个维度（日期或模型）聚合出来的一格。"""

    key: str
    calls: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost: float


class ModelTokenQuota(BaseModel):
    model: str
    token_limit: int
    token_used: int
    token_remaining: int


class QuotaStatus(BaseModel):
    timezone: str
    resets_at: datetime
    daily_tokens_limit: int | None
    daily_tokens_used: int
    daily_tokens_remaining: int | None
    daily_cost_limit: float | None
    daily_cost_used: float
    daily_cost_remaining: float | None
    model_token_limits: list[ModelTokenQuota]


class UsageSummary(BaseModel):
    total_calls: int
    total_tokens: int
    prompt_tokens: int
    completion_tokens: int
    days: int
    total_cost: float
    pricing_configured: bool
    by_day: list[UsageBucket]
    by_model: list[UsageBucket]
    quota: QuotaStatus

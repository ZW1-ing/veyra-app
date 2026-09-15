"""用量统计出入参。"""

from pydantic import BaseModel


class UsageBucket(BaseModel):
    """按某个维度（日期或模型）聚合出来的一格。"""

    key: str
    calls: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class UsageSummary(BaseModel):
    total_calls: int
    total_tokens: int
    prompt_tokens: int
    completion_tokens: int
    days: int
    by_day: list[UsageBucket]
    by_model: list[UsageBucket]

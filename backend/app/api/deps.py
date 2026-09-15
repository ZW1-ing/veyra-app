"""FastAPI 依赖：数据库会话、配置、模型与向量化实现。"""

import logging
from collections.abc import Iterator

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from ..core.config import Settings, get_settings
from ..core.ratelimit import limiter
from ..db.session import get_db as _get_db
from ..kb.embedding import EmbeddingProvider
from ..llm.base import LLMProvider

logger = logging.getLogger(__name__)


def get_db() -> Iterator[Session]:
    yield from _get_db()


def settings_dep() -> Settings:
    return get_settings()


def provider_dep(request: Request) -> LLMProvider:
    """模型后端挂在 app.state 上，测试里可以直接替换。"""
    return request.app.state.provider


def embedding_dep(request: Request) -> EmbeddingProvider:
    return request.app.state.embedding


def require_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> str:
    """校验 API Key。

    没有配置任何 key 时直接放行（本地开发），但会打一条警告，
    提醒部署时必须配置，否则接口对任何能连上端口的人都是开放的。
    """
    settings = get_settings()
    allowed = settings.api_key_set
    if not allowed:
        logger.warning("未配置 API_KEYS，接口处于无鉴权状态，仅限本地开发使用")
        return "anonymous"

    if not x_api_key or x_api_key not in allowed:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少或无效的 API Key（请在请求头带上 X-API-Key）",
            headers={"WWW-Authenticate": "X-API-Key"},
        )
    return x_api_key


def enforce_rate_limit(api_key: str = Depends(require_api_key)) -> str:
    settings = get_settings()
    allowed, retry_after = limiter.check(api_key, settings.rate_limit_per_minute)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"请求过于频繁，请 {retry_after} 秒后重试",
            headers={"Retry-After": str(retry_after)},
        )
    return api_key

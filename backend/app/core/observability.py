"""请求级追踪：给每个请求分配 ID，并统一记录耗时日志。"""

from __future__ import annotations

import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from contextvars import ContextVar

from fastapi import Request, Response

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
_request_id: ContextVar[str] = ContextVar("request_id", default="-")


def current_request_id() -> str:
    return _request_id.get()


class RequestIdFilter(logging.Filter):
    """让普通日志自动带上当前请求 ID。"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = current_request_id()
        return True


async def request_context_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    incoming = request.headers.get(REQUEST_ID_HEADER, "")
    request_id = incoming if _REQUEST_ID_PATTERN.fullmatch(incoming) else uuid.uuid4().hex[:16]
    token = _request_id.set(request_id)
    started = time.perf_counter()
    response: Response | None = None

    try:
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response
    except Exception:
        logger.exception(
            "request_failed method=%s path=%s duration_ms=%.1f",
            request.method,
            request.url.path,
            (time.perf_counter() - started) * 1000,
        )
        raise
    finally:
        if request.url.path != "/health":
            logger.info(
                "request_completed method=%s path=%s status=%s duration_ms=%.1f",
                request.method,
                request.url.path,
                response.status_code if response is not None else 500,
                (time.perf_counter() - started) * 1000,
            )
        _request_id.reset(token)

"""Prometheus 抓取端点。"""

from fastapi import APIRouter, Depends, Response

from ...core.metrics import latest_metrics
from ..deps import Principal, require_api_key

router = APIRouter(tags=["metrics"])


@router.get("/metrics", include_in_schema=False)
def metrics(_: Principal = Depends(require_api_key)) -> Response:
    body, content_type = latest_metrics()
    return Response(content=body, media_type=content_type)

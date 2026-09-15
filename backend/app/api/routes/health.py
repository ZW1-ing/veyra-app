"""健康检查：同时探数据库，方便容器编排做就绪判断。"""

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..deps import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
def health(request: Request, db: Session = Depends(get_db)) -> dict:
    database = "ok"
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 健康检查不该因为探活失败而 500
        database = f"error: {type(exc).__name__}"

    provider = request.app.state.provider
    return {
        "status": "ok" if database == "ok" else "degraded",
        "database": database,
        "provider": provider.name,
        "model": provider.model,
    }

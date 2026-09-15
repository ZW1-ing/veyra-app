"""会话与消息接口。"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...db.models import SessionRow
from ...schemas.session import MessageOut, SessionCreate, SessionDetail, SessionOut
from ..deps import enforce_rate_limit, get_db

# 鉴权与限流挂在整个路由组上；/health 刻意不挂，容器探活不该需要密钥
router = APIRouter(
    prefix="/sessions", tags=["sessions"], dependencies=[Depends(enforce_rate_limit)]
)


@router.post("", response_model=SessionOut, status_code=status.HTTP_201_CREATED)
def create_session(payload: SessionCreate, db: Session = Depends(get_db)) -> SessionRow:
    row = SessionRow(title=(payload.title or "新会话")[:200], mode=payload.mode)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("", response_model=list[SessionOut])
def list_sessions(db: Session = Depends(get_db), limit: int = 50) -> list[SessionRow]:
    rows = db.execute(
        select(SessionRow).order_by(SessionRow.updated_at.desc()).limit(max(1, min(limit, 200)))
    ).scalars().all()
    return list(rows)


@router.get("/{session_id}", response_model=SessionDetail)
def get_session(session_id: str, db: Session = Depends(get_db)) -> SessionRow:
    row = db.get(SessionRow, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return row


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(session_id: str, db: Session = Depends(get_db)) -> None:
    row = db.get(SessionRow, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    db.delete(row)
    db.commit()


@router.get("/{session_id}/messages", response_model=list[MessageOut])
def list_messages(session_id: str, db: Session = Depends(get_db)) -> list:
    row = db.get(SessionRow, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return row.messages

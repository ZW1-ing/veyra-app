"""会话与消息接口。"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...db.models import SessionRow
from ...schemas.session import MessageOut, SessionCreate, SessionDetail, SessionOut
from ..deps import Principal, enforce_rate_limit, get_db

# 鉴权与限流挂在整个路由组上；/health 刻意不挂，容器探活不该需要密钥
router = APIRouter(
    prefix="/sessions", tags=["sessions"], dependencies=[Depends(enforce_rate_limit)]
)


def _owned_session(db: Session, session_id: str, owner_id: str) -> SessionRow:
    row = db.get(SessionRow, session_id)
    if row is None or row.owner_id != owner_id:
        raise HTTPException(status_code=404, detail="会话不存在")
    return row


@router.post("", response_model=SessionOut, status_code=status.HTTP_201_CREATED)
def create_session(
    payload: SessionCreate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(enforce_rate_limit),
) -> SessionRow:
    row = SessionRow(
        title=(payload.title or "新会话")[:200],
        mode=payload.mode,
        owner_id=principal.owner_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("", response_model=list[SessionOut])
def list_sessions(
    db: Session = Depends(get_db),
    limit: int = 50,
    principal: Principal = Depends(enforce_rate_limit),
) -> list[SessionRow]:
    rows = db.execute(
        select(SessionRow)
        .where(SessionRow.owner_id == principal.owner_id)
        .order_by(SessionRow.updated_at.desc())
        .limit(max(1, min(limit, 200)))
    ).scalars().all()
    return list(rows)


@router.get("/{session_id}", response_model=SessionDetail)
def get_session(
    session_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(enforce_rate_limit),
) -> SessionRow:
    return _owned_session(db, session_id, principal.owner_id)


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(
    session_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(enforce_rate_limit),
) -> None:
    row = _owned_session(db, session_id, principal.owner_id)
    db.delete(row)
    db.commit()


@router.get("/{session_id}/messages", response_model=list[MessageOut])
def list_messages(
    session_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(enforce_rate_limit),
) -> list:
    row = _owned_session(db, session_id, principal.owner_id)
    return row.messages

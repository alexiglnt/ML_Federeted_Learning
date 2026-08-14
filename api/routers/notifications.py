"""Reading and acknowledging notifications.

Creation happens in `api/services/notifications.py`, called from the
contribution-review flow in `uploads.py`. Nothing here writes a notification —
this router only ever reads the caller's own and marks them read.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session, selectinload

from api.db import get_db, utcnow
from api.deps import get_current_user
from api.models import Notification, User
from api.schemas import NotificationOut

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


def _out(notification: Notification) -> NotificationOut:
    return NotificationOut(
        id=notification.id,
        kind=notification.kind.value,
        title=notification.title,
        body=notification.body,
        project_slug=notification.project.slug if notification.project else None,
        contribution_id=notification.contribution_id,
        created_at=notification.created_at,
        read_at=notification.read_at,
    )


@router.get("", response_model=list[NotificationOut])
def list_notifications(
    unread_only: bool = False,
    limit: int = Query(default=50, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    stmt = (
        select(Notification)
        .where(Notification.recipient_id == user.id)
        .options(selectinload(Notification.project))
        .order_by(Notification.created_at.desc())
        .limit(limit)
    )
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    return [_out(n) for n in db.scalars(stmt)]


@router.get("/unread-count")
def unread_count(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """For the bell badge. Polled, so kept to a single indexed count query."""
    count = db.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.recipient_id == user.id, Notification.read_at.is_(None))
    )
    return {"count": int(count or 0)}


@router.post("/{notification_id}/read", response_model=NotificationOut)
def mark_read(
    notification_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    notification = db.scalar(
        select(Notification)
        .where(Notification.id == notification_id)
        .options(selectinload(Notification.project))
    )
    if notification is None or notification.recipient_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such notification.")
    if notification.read_at is None:
        notification.read_at = utcnow()
        db.commit()
        db.refresh(notification)
    return _out(notification)


@router.post("/read-all")
def mark_all_read(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    result = db.execute(
        update(Notification)
        .where(Notification.recipient_id == user.id, Notification.read_at.is_(None))
        .values(read_at=utcnow())
    )
    db.commit()
    return {"count": result.rowcount}


@router.delete("")
def clear_notifications(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Delete every notification of the caller's own. Nothing else references
    a notification's id, so this is a plain bulk delete, not a cascade."""
    result = db.execute(delete(Notification).where(Notification.recipient_id == user.id))
    db.commit()
    return {"count": result.rowcount}

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from sqlalchemy import select
from .db import as_dict
from .models import Notification, NotificationRead, User
from .schemas import Input
from .security import principal, db_dependency
from .sessions import profile_for

router = APIRouter(prefix='/v1/workspaces/{workspace_id}/notifications')


class ReadNotifications(Input):
    ids: list[str] = Field(default_factory=list, max_length=100)
    all: bool = False


@router.get('')
def notifications(workspace_id: str, actor=Depends(principal), db=Depends(db_dependency, scope='function')):
    actor.require('dashboard:read')
    if actor.user_id is None:
        raise HTTPException(403, 'Notifications belong to a signed-in person')
    rows = list(db.scalars(select(Notification).where(Notification.workspace_id == workspace_id)
                           .order_by(Notification.created_at.desc()).limit(100)))
    read = set(db.scalars(select(NotificationRead.notification_id).where(NotificationRead.user_id == actor.user_id,
                         NotificationRead.notification_id.in_([r.id for r in rows]))))
    enabled = profile_for(db, actor.user_id).notifications_enabled
    return {'items': [{**as_dict(r), 'read': r.id in read} for r in rows],
            'unread': sum(r.id not in read for r in rows) if enabled else 0, 'enabled': enabled}


@router.post('/read')
def read_notifications(workspace_id: str, body: ReadNotifications, actor=Depends(principal), db=Depends(db_dependency, scope='function')):
    actor.require('dashboard:read')
    if actor.user_id is None:
        raise HTTPException(403, 'Notifications belong to a signed-in person')
    db.scalar(select(User).where(User.id == actor.user_id).with_for_update())
    query = select(Notification.id).where(Notification.workspace_id == workspace_id)
    if not body.all:
        query = query.where(Notification.id.in_(body.ids))
    ids = list(db.scalars(query.order_by(Notification.created_at.desc()).limit(100)))
    existing = set(db.scalars(select(NotificationRead.notification_id).where(NotificationRead.user_id == actor.user_id,
                             NotificationRead.notification_id.in_(ids))))
    for notification_id in set(ids) - existing:
        db.add(NotificationRead(user_id=actor.user_id, notification_id=notification_id))
    return {'status': 'read', 'count': len(ids)}

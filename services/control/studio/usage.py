"""Durable, shared workspace admission limits for the controlled beta."""
from datetime import timedelta
from fastapi import HTTPException
from sqlalchemy import select, func
from .config import settings
from .db import now
from .models import Workspace, UsageRecord, Call


def admit_turn(db, workspace_id, operation_key):
    db.scalar(select(Workspace).where(Workspace.id == workspace_id).with_for_update())
    if db.scalar(select(UsageRecord.id).where(UsageRecord.workspace_id == workspace_id,
                                           UsageRecord.operation_key == operation_key)):
        return
    midnight = now().replace(hour=0, minute=0, second=0, microsecond=0)
    used = db.scalar(select(func.count()).select_from(UsageRecord).where(UsageRecord.workspace_id == workspace_id,
                     UsageRecord.created_at >= midnight, UsageRecord.kind == 'turn'))
    if used >= settings.workspace_daily_turn_limit:
        raise HTTPException(429, 'This workspace has reached its daily conversation allowance. Please try again tomorrow.')
    db.add(UsageRecord(workspace_id=workspace_id, operation_key=operation_key, kind='turn'))
    db.flush()


def admit_voice(db, workspace_id):
    db.scalar(select(Workspace).where(Workspace.id == workspace_id).with_for_update())
    active = db.scalar(select(func.count()).select_from(Call).where(Call.workspace_id == workspace_id,
                       Call.transport == 'browser', Call.state.in_(['created', 'connected', 'ending']),
                       Call.created_at > now() - timedelta(minutes=20),
                       (Call.state != 'created') | (Call.created_at > now() - timedelta(minutes=2))))
    if active >= settings.workspace_voice_concurrency:
        raise HTTPException(429, 'All voice sessions are in use. End another session or try again shortly.')

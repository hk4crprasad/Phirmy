"""Off-loop call transactions and cancellation-safe media teardown."""
import asyncio
import contextlib
import logging

from fastapi import HTTPException
from sqlalchemy import select

from .async_work import durable_to_thread
from .db import now, session_scope
from .domain import settle_call
from .models import Call, Workspace

log = logging.getLogger(__name__)


def locked_call(db, workspace_id, call_id):
    # Match admission/settlement ordering: workspace before call.
    db.scalar(select(Workspace.id).where(Workspace.id == workspace_id).with_for_update())
    call = db.scalar(select(Call).where(Call.workspace_id == workspace_id, Call.id == call_id).with_for_update())
    if call is None:
        raise HTTPException(404, 'Call not found')
    return call


def settle(workspace_id, call_id, session, failed, failure_code):
    with session_scope(write=True) as db:
        call = locked_call(db, workspace_id, call_id)
        duration = int((now() - call.connected_at).total_seconds() * 1000) if call.connected_at else 0
        if failed:
            call.failure_code = failure_code
        if session is not None:
            session.record_audio_usage(db)
        from .transfers import retain_parent
        if retain_parent(db,call):return
        settle_call(db, call, max(0, duration), 'failed' if failed else 'completed')


async def finalize(session, workspace_id, call_id, *, admitted, failed, failure_code, tasks=()):
    """Caller shields this entire cleanup, then releases its ownership claim.

    A failed handshake must not settle somebody else's active call. Once the
    admission transaction committed, settle even if constructing the session
    failed or cancellation arrived during its off-thread initialization.
    """
    try:
        if session is not None:
            session.closed = True
            failed = failed or session.provider_failed
        for task in tasks:
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(*(task for task in tasks if task is not None), return_exceptions=True)
        if session is not None:
            try:
                await session.close_providers()
            finally:
                if session.dg is not None:
                    with contextlib.suppress(Exception):
                        await asyncio.wait_for(session.dg.close(), 4)
    finally:
        try:
            if admitted:
                await durable_to_thread(settle, workspace_id, call_id, session, failed, failure_code)
        finally:
            if session is not None:
                try:
                    await durable_to_thread(session.recording.finish, workspace_id, call_id)
                except Exception:
                    log.warning('Recording persistence failed for call %s', call_id)

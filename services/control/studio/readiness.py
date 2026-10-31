import asyncio
from datetime import timedelta
import httpx
from sqlalchemy import select, text

from .config import settings
from .db import now, session_scope
from .models import WorkerHeartbeat
from .rate_limits import connection


def database_and_worker():
    with session_scope() as db:
        db.execute(text('SELECT 1'))
        active = db.scalar(select(WorkerHeartbeat.id).where(WorkerHeartbeat.group == settings.worker_group,
                           WorkerHeartbeat.state == 'active', WorkerHeartbeat.last_seen_at > now()-timedelta(seconds=30)).limit(1))
        return bool(active)


async def readiness():
    checks = {}
    try:
        checks['worker'] = 'ok' if await asyncio.to_thread(database_and_worker) else 'unavailable'
        checks['database'] = 'ok'
    except Exception:
        checks.update(database='unavailable', worker='unavailable')
    if settings.redis_url:
        try:
            good = await asyncio.to_thread(lambda: connection(settings.redis_url).ping())
            checks['redis'] = 'ok' if good else 'unavailable'
        except Exception:
            checks['redis'] = 'unavailable'
    else:
        checks['redis'] = 'unavailable' if settings.app_env == 'production' else 'disabled-development'
    if settings.vector_endpoint:
        try:
            async with httpx.AsyncClient(timeout=2, follow_redirects=False) as client:
                response = await client.get(settings.vector_endpoint.rstrip('/')+'/readyz',
                                            headers={'api-key':settings.vector_api_key} if settings.vector_api_key else {})
                checks['qdrant'] = 'ok' if response.status_code == 200 else 'unavailable'
        except Exception:
            checks['qdrant'] = 'unavailable'
    else:
        checks['qdrant'] = 'unavailable' if settings.app_env == 'production' else 'disabled-development'
    try:
        from .isolation import provider
        proof=await asyncio.wait_for(provider.run({'operation':'health'}),2)
        checks['content_sandbox']='ok' if proof.get('ready') is True else 'unavailable'
    except Exception:checks['content_sandbox']='unavailable'
    ready = all(value in {'ok','disabled-development'} for value in checks.values())
    return {'status':'ok' if ready else 'unavailable','checks':checks}, 200 if ready else 503


def heartbeat(identity, state='active'):
    with session_scope(write=True) as db:
        row = db.get(WorkerHeartbeat, identity)
        if row is None:
            row = WorkerHeartbeat(id=identity, group=settings.worker_group)
            db.add(row)
        row.state, row.last_seen_at = state, now()

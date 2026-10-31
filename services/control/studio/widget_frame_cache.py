"""Brief public CSP metadata cache; never used for widget authorization.

One Redis hash contains either a loading claim, a policy, or transaction guards.
Guard hashes do not expire. A crashed writer loses caching until recovery, rather
than leaving an old grant. Redis must use noeviction; otherwise caching is off.
"""
from functools import lru_cache
from datetime import timedelta
import json
import logging
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
import redis
from sqlalchemy import event, select

from .config import settings
from .db import SessionLocal, now, session_scope

CONFIG = json.loads((Path(__file__).resolve().parents[3]/'config/widget-frame-cache.json').read_text())
READ = CONFIG['read_script']
CLAIM = """
if redis.call('EXISTS',KEYS[1]) == 0 then
  redis.call('HSET',KEYS[1],'load',ARGV[1]); redis.call('PEXPIRE',KEYS[1],ARGV[2]); return 1
end
return 0
"""
PUBLISH = """
if redis.call('HLEN',KEYS[1]) == 1 and redis.call('HGET',KEYS[1],'load') == ARGV[1] then
  redis.call('HDEL',KEYS[1],'load'); redis.call('HSET',KEYS[1],'value',ARGV[2]);
  redis.call('PEXPIRE',KEYS[1],ARGV[3]); return 1
end
return 0
"""
GUARD = """
redis.call('HDEL',KEYS[1],'value','load')
redis.call('HSET',KEYS[1],ARGV[1],'1'); redis.call('PERSIST',KEYS[1]); return 1
"""
RELEASE = """
redis.call('HDEL',KEYS[1],'value','load',ARGV[1])
if redis.call('HLEN',KEYS[1]) == 0 then redis.call('DEL',KEYS[1]) end
return 1
"""
log = logging.getLogger(__name__)


@lru_cache(maxsize=4)
def _connection(url):
    client = redis.Redis.from_url(url, decode_responses=True, socket_timeout=.2,
                                 socket_connect_timeout=.2, retry_on_timeout=False)
    if client.config_get('maxmemory-policy').get('maxmemory-policy') != 'noeviction':
        client.close()
        log.warning('Widget frame caching disabled: Redis must use noeviction')
        return None
    return client


def connection():
    return _connection(settings.redis_url) if settings.redis_url else None


def key(public_id):
    return settings.widget_frame_cache_namespace+':'+public_id


def lookup(public_id):
    """Claim before the DB snapshot, then publish only if no writer intervened."""
    from .models import Agent, Installation, OriginVerification
    from .origin_ownership import normalize_origin, platform_origins
    cache = None
    token = str(uuid4())
    claimed = False
    try:
        cache = connection()
        if cache is not None:
            cached = cache.eval(READ, 1, key(public_id))
            if cached:
                return json.loads(cached)
            claimed = bool(cache.eval(CLAIM, 1, key(public_id), token, CONFIG['ttl_ms']))
    except (redis.RedisError, ValueError):
        cache = None  # No stale-on-error. Read current committed DB state below.
    with session_scope() as db:
        installation = db.scalar(select(Installation).join(Agent, Installation.agent_id == Agent.id).where(
            Installation.public_id == public_id, Installation.enabled.is_(True), Agent.archived.is_(False)))
        if installation is None:
            raise HTTPException(404, 'Widget not found')
        instant = now()
        deadline = instant+timedelta(milliseconds=CONFIG['ttl_ms'])
        proofs = {row.origin: row.verified_until for row in db.scalars(select(OriginVerification).where(
            OriginVerification.workspace_id == installation.workspace_id,
            OriginVerification.verified_at.is_not(None), OriginVerification.verified_until > instant))}
        platform = platform_origins()
        ancestors = []
        for configured in installation.allowed_origins:
            origin = normalize_origin(configured)
            if origin in platform or origin in proofs:
                ancestors.append(origin)
                if origin not in platform:
                    deadline = min(deadline, proofs[origin])
        policy = {'frame_ancestors': sorted(set(ancestors))}
    ttl = int((deadline-now()).total_seconds()*1000)
    if cache is not None and claimed and ttl > 0:
        try:
            cache.eval(PUBLISH, 1, key(public_id), token, json.dumps(policy), ttl)
        except redis.RedisError:
            pass
    return policy


def guard(db, workspace_ids):
    """Fence policy loads before a mutation, until its outer transaction ends."""
    from .models import Installation, Workspace
    if not settings.redis_url:
        return
    state = db.info.setdefault('widget-frame-guards', {'token':'guard:'+str(uuid4()), 'keys':set(), 'workspaces':set()})
    fresh = set(workspace_ids)-state['workspaces']
    if not fresh:
        return
    # Serializes installation creation and origin changes, including bulk purges.
    with db.no_autoflush:
        list(db.scalars(select(Workspace.id).where(Workspace.id.in_(fresh)).order_by(Workspace.id).with_for_update()))
        public_ids = set(db.scalars(select(Installation.public_id).where(Installation.workspace_id.in_(fresh))))
    try:
        cache = connection()
        if cache is not None:
            for public_id in public_ids:
                cache_key = key(public_id)
                cache.eval(GUARD, 1, cache_key, state['token'])
                state['keys'].add(cache_key)
            state['client'] = cache
    except redis.RedisError:
        # Cannot revoke a cache another replica might still read: refuse the
        # mutation before SQL instead of silently leaving an old framing grant.
        raise HTTPException(503, 'Widget policy cache is unavailable; retry this change') from None
    state['workspaces'].update(fresh)


def recover(workspace_id, apply=False):
    """Clear crash guards only after serializing with every live policy writer."""
    from .models import Installation, Workspace
    cache = connection()
    if cache is None:
        raise RuntimeError('Configure a noeviction Redis instance before cache recovery')
    with session_scope(write=True) as db:
        workspace = db.scalar(select(Workspace).where(Workspace.id == workspace_id).with_for_update())
        if workspace is None:
            raise ValueError('Workspace not found')
        keys = [key(value) for value in db.scalars(select(Installation.public_id).where(Installation.workspace_id == workspace_id))]
        guarded = [value for value in keys if any(name.startswith('guard:') for name in cache.hkeys(value))]
        if apply and guarded:
            cache.delete(*guarded)
        return {'guarded_entries':len(guarded), 'cleared':len(guarded) if apply else 0, 'dry_run':not apply}


@event.listens_for(SessionLocal, 'before_flush')
def _before_flush(db, context, instances):
    from .models import Agent, Installation, OriginVerification, Workspace
    workspace_ids = set()
    for row in db.new | db.dirty | db.deleted:
        if isinstance(row, (Installation, OriginVerification, Agent)):
            workspace_ids.add(row.workspace_id)
        elif isinstance(row, Workspace) and row in db.deleted:
            workspace_ids.add(row.id)
    if workspace_ids:
        guard(db, workspace_ids)


@event.listens_for(SessionLocal, 'do_orm_execute')
def _before_bulk(execute):
    from .models import Agent, Installation, OriginVerification, Workspace
    if not settings.redis_url or not (execute.is_update or execute.is_delete):
        return
    table = getattr(execute.statement, 'table', None)
    for model in (Installation, OriginVerification, Agent, Workspace):
        if table is not None and table.name == model.__tablename__:
            column = model.id if model is Workspace else model.workspace_id
            query = select(column).distinct()
            # Executemany may bind different IDs: conservatively fence all rows.
            if not isinstance(execute.parameters, list) and execute.statement.whereclause is not None:
                query = query.where(execute.statement.whereclause)
            guard(execute.session, set(execute.session.scalars(query, execute.parameters if isinstance(execute.parameters, dict) else None)))
            return


@event.listens_for(SessionLocal, 'after_transaction_end')
def _transaction_ended(db, transaction):
    if transaction.parent is not None:
        return  # SAVEPOINT release is not an outer commit/rollback.
    state = db.info.pop('widget-frame-guards', None)
    if state and state.get('client') is not None:
        for cache_key in state['keys']:
            try:
                state['client'].eval(RELEASE, 1, cache_key, state['token'])
            except redis.RedisError:
                log.warning('Widget policy cache guard retained after transaction; authoritative reads only')

"""Real Redis fencing tests; no Docker and no external content/provider access."""
from datetime import timedelta
import json
import os
from uuid import uuid4

from fastapi import HTTPException
import pytest
import redis
from sqlalchemy import event, update

from conftest import verify_test_origin
from studio import widget_frame_cache as cache
from studio.config import settings
from studio.db import SessionLocal, engine, now, session_scope
from studio.models import Agent, Installation, OriginVerification

ORIGIN = 'https://frame-cache.example'


@pytest.fixture
def cached_widget(sample, monkeypatch):
    url = os.environ.get('STUDIO_TEST_REDIS_URL')
    if not url:
        if os.environ.get('CI', '').casefold() in {'true', '1'}:
            pytest.fail('CI must provide STUDIO_TEST_REDIS_URL for actual Redis checks')
        pytest.skip('Set STUDIO_TEST_REDIS_URL to run real Redis cache integration (mandatory in CI)')
    client, workspace_id, base, fixture = sample
    monkeypatch.setattr(settings, 'redis_url', url)
    monkeypatch.setattr(settings, 'widget_frame_cache_namespace', 'test:frame:'+uuid4().hex)
    connection = cache.connection()
    assert connection is not None, 'Redis must use noeviction for frame policy guards'
    with session_scope(write=True) as db:
        row = db.get(Installation, fixture['installation_id'])
        row.allowed_origins = [ORIGIN, settings.app_origin]
        public_id = row.public_id
    proof_id = verify_test_origin(client, base, ORIGIN, monkeypatch)
    yield client, workspace_id, base, fixture, public_id, proof_id, connection
    keys = list(connection.scan_iter(match=settings.widget_frame_cache_namespace+':*'))
    if keys:
        connection.delete(*keys)


def test_hot_policy_skips_database_and_revocation_invalidates(cached_widget):
    client, _, base, _, public_id, proof_id, connection = cached_widget
    url = '/v1/public/widgets/'+public_id+'/frame-policy'
    assert ORIGIN in client.get(url).json()['frame_ancestors']
    statements = []
    def query(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)
    event.listen(engine, 'before_cursor_execute', query)
    try:
        assert ORIGIN in client.get(url).json()['frame_ancestors']
    finally:
        event.remove(engine, 'before_cursor_execute', query)
    assert not statements
    assert client.delete(base+'/origins/'+proof_id).status_code == 200
    assert connection.eval(cache.READ, 1, cache.key(public_id)) is None
    assert ORIGIN not in client.get(url).json()['frame_ancestors']


@pytest.mark.parametrize('commit', [False, True])
def test_writer_blocks_cache_through_savepoint_and_outer_commit_or_rollback(cached_widget, commit):
    _, _, _, fixture, public_id, _, connection = cached_widget
    assert ORIGIN in cache.lookup(public_id)['frame_ancestors']
    with SessionLocal() as db:
        if engine.dialect.name == 'sqlite':
            db.connection().exec_driver_sql('BEGIN IMMEDIATE')
        with db.begin_nested():
            db.get(Installation, fixture['installation_id']).allowed_origins = [settings.app_origin]
            db.flush()
        assert connection.eval(cache.READ, 1, cache.key(public_id)) is None
        assert connection.pttl(cache.key(public_id)) == -1  # No stale grant if writer stalls/crashes.
        assert connection.eval(cache.CLAIM, 1, cache.key(public_id), 'racing-load', 5000) == 0
        if commit:
            db.commit()
        else:
            db.rollback()
    assert not connection.exists(cache.key(public_id))
    assert (ORIGIN in cache.lookup(public_id)['frame_ancestors']) is not commit


def test_inflight_old_snapshot_cannot_repopulate_after_mutation(cached_widget):
    _, _, _, fixture, public_id, _, connection = cached_widget
    cache_key = cache.key(public_id)
    assert connection.eval(cache.CLAIM, 1, cache_key, 'old-loader', 5000) == 1
    with session_scope(write=True) as db:
        db.get(Installation, fixture['installation_id']).enabled = False
    stale = json.dumps({'frame_ancestors':[ORIGIN]})
    assert connection.eval(cache.PUBLISH, 1, cache_key, 'old-loader', stale, 5000) == 0
    with pytest.raises(HTTPException, match='Widget not found'):
        cache.lookup(public_id)


def test_bulk_agent_archive_invalidates_policy(cached_widget):
    _, _, _, fixture, public_id, _, connection = cached_widget
    cache.lookup(public_id)
    with session_scope(write=True) as db:
        db.execute(update(Agent).where(Agent.id == fixture['agent_id']).values(archived=True))
    assert connection.eval(cache.READ, 1, cache.key(public_id)) is None
    with pytest.raises(HTTPException, match='Widget not found'):
        cache.lookup(public_id)


def test_cache_never_outlives_origin_proof(cached_widget):
    _, _, _, _, public_id, proof_id, connection = cached_widget
    with session_scope(write=True) as db:
        db.get(OriginVerification, proof_id).verified_until = now()+timedelta(seconds=2)
    assert ORIGIN in cache.lookup(public_id)['frame_ancestors']
    ttl = connection.pttl(cache.key(public_id))
    assert 0 < ttl <= 2000


def test_redis_outage_reads_current_db_but_refuses_unfenced_mutation(cached_widget, monkeypatch):
    _, _, _, fixture, public_id, _, _ = cached_widget
    cache.lookup(public_id)
    def unavailable():
        raise redis.ConnectionError('synthetic outage')
    monkeypatch.setattr(cache, 'connection', unavailable)
    assert ORIGIN in cache.lookup(public_id)['frame_ancestors']
    with pytest.raises(HTTPException, match='Widget policy cache is unavailable'):
        with session_scope(write=True) as db:
            db.get(Installation, fixture['installation_id']).enabled = False
    with session_scope() as db:
        assert db.get(Installation, fixture['installation_id']).enabled


def test_crash_guard_recovery_is_scoped_and_dry_run_by_default(cached_widget):
    _, workspace_id, _, _, public_id, _, connection = cached_widget
    cache_key = cache.key(public_id)
    other_key = cache.key('other-workspace-widget')
    for value in (cache_key, other_key):
        connection.eval(cache.GUARD, 1, value, 'guard:crashed-process')
    assert cache.recover(workspace_id) == {'guarded_entries':1, 'cleared':0, 'dry_run':True}
    assert connection.exists(cache_key)
    assert cache.recover(workspace_id, apply=True)['cleared'] == 1
    assert not connection.exists(cache_key) and connection.exists(other_key)
    assert ORIGIN in cache.lookup(public_id)['frame_ancestors']

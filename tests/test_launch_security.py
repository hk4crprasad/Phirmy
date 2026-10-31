from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from types import SimpleNamespace
import logging
import hashlib
import hmac
import os
import time
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest
from redis import Redis
from redis.exceptions import ConnectionError
from sqlalchemy import text

from studio import rate_limits
from studio.config import Settings, settings
from studio.db import engine, now, session_scope
from studio.main import create_app, initialize_database, verify_database_schema
from studio.models import APIKey
from studio.security import Principal, digest


@pytest.mark.parametrize('scope', ['developer:write', 'team:write', 'billing:write'])
def test_legacy_admin_key_cannot_manage_security_or_billing(scope):
    with pytest.raises(HTTPException) as exc:
        Principal(None, 'workspace', 'admin', [scope]).require(scope)
    assert exc.value.status_code == 403
    Principal('owner', 'workspace', 'owner').require(scope)


def test_legacy_key_cannot_mint_revoke_invite_or_pay(account):
    client, ws, base = account
    secret = 'legacy-key-never-used-outside-tests'
    with session_scope(write=True) as db:
        row = APIKey(workspace_id=ws, name='Legacy admin', prefix='legacy',
                     secret_hash=digest(secret), scopes=['developer:write', 'team:write', 'billing:write'])
        db.add(row)
        db.flush()
        key_id = row.id
    headers = {'X-API-Key': secret}
    assert client.post(base + '/keys', json={'name': 'Escalated', 'scopes': ['kb:write']}, headers=headers).status_code == 403
    assert client.delete(base + '/keys/' + key_id, headers=headers).status_code == 403
    assert client.post(base + '/invitations', json={'email': 'invite@example.test', 'role': 'builder'}, headers=headers).status_code == 403
    # Assert authorization before any payment-provider configuration or call.
    assert client.post(base + '/payments/orders', json={'amount_minor': 10000}, headers=headers).status_code == 403
    assert client.get(base + '/wallet', headers=headers).status_code == 403


@pytest.mark.parametrize('scope', ['developer:write', 'team:write', 'billing:write'])
def test_new_keys_cannot_be_granted_dashboard_mutation_scopes(account, scope):
    client, ws, base = account
    assert client.post(base + '/keys', json={'name': 'Denied', 'scopes': [scope]}).status_code == 422


def test_key_expiry_usage_scope_and_rate_limit(account):
    client, ws, base = account
    result = client.post(base + '/keys', json={'name': 'Bounded', 'scopes': ['kb:read'],
                          'expires_at': (now() + timedelta(hours=1)).isoformat(),
                          'requests_per_minute': 2})
    assert result.status_code == 201
    row = result.json()['key']
    assert row['last_used_at'] is None and row['requests_per_minute'] == 2
    headers = {'X-API-Key': result.json()['secret']}
    assert client.get(base + '/knowledge', headers=headers).status_code == 200
    with session_scope() as db:
        assert db.get(APIKey, row['id']).last_used_at is not None
    assert client.post(base + '/agents', json={'name': 'No escalation'}, headers=headers).status_code == 403
    response = client.get(base + '/knowledge', headers=headers)
    assert response.status_code == 429 and int(response.headers['retry-after']) > 0
    with session_scope(write=True) as db:
        db.get(APIKey, row['id']).expires_at = now() - timedelta(seconds=1)
    assert client.get(base + '/knowledge', headers=headers).status_code == 401
    listed = client.get(base + '/keys').json()['items'][0]
    assert listed['last_used_at'] and listed['expires_at']
    assert 'secret_hash' not in listed and result.json()['secret'] not in str(listed)


@pytest.mark.parametrize('extra', [
    {'expires_at': '2000-01-01T00:00:00Z'},
    {'expires_at': '2030-01-01T00:00:00'},
    {'requests_per_minute': 0}, {'requests_per_minute': 601},
])
def test_invalid_key_policy_rejected(account, extra):
    client, ws, base = account
    assert client.post(base + '/keys', json={'name': 'Invalid', 'scopes': ['kb:read'], **extra}).status_code == 422


def test_existing_key_schema_migrates_without_losing_credentials(account):
    client, ws, base = account
    with engine.begin() as conn:
        conn.execute(text('DROP TABLE api_keys'))
        conn.execute(text('CREATE TABLE api_keys (id VARCHAR(36) PRIMARY KEY, created_at DATETIME, workspace_id VARCHAR(36), name VARCHAR(120), prefix VARCHAR(16), secret_hash VARCHAR(64), scopes JSON, revoked_at DATETIME)'))
        conn.execute(text("INSERT INTO api_keys (id, workspace_id, name, prefix, secret_hash, scopes) VALUES ('old-key', :ws, 'Old key', 'old', :hash, '[\"kb:read\"]')"), {'ws': ws, 'hash': digest('existing-test-secret')})
    initialize_database()
    initialize_database()
    verify_database_schema()
    with session_scope() as db:
        row = db.get(APIKey, 'old-key')
        assert row.secret_hash == digest('existing-test-secret')
        assert row.expires_at is None and row.last_used_at is None and row.requests_per_minute == 60


def test_fallback_is_atomic_bounded_and_expires(monkeypatch, caplog):
    monkeypatch.setattr(settings, 'redis_url', '')
    clock = [100.0]
    monkeypatch.setattr(rate_limits, 'time', SimpleNamespace(monotonic=lambda: clock[0]))
    limiter = rate_limits.RateLimiter()
    def attempt(_):
        try:
            limiter.check('private@example.test', 10, 60)
            return True
        except HTTPException as exc:
            assert exc.status_code == 429
            return False
    with caplog.at_level(logging.WARNING):
        with ThreadPoolExecutor(max_workers=16) as pool:
            assert sum(pool.map(attempt, range(100))) == 10
    assert 'private@example.test' not in caplog.text
    assert 'per-process' in caplog.text
    assert 'private@example.test' not in str(limiter.entries)
    clock[0] += 60
    assert attempt(0)
    limiter.entries = {str(i): (deque([clock[0]]), 60) for i in range(10000)}
    with pytest.raises(HTTPException):
        limiter.check('new identity', 1, 60)
    assert len(limiter.entries) == 10000


def test_redis_outage_falls_back_and_reconnects(monkeypatch, caplog):
    monkeypatch.setattr(settings, 'redis_url', 'redis://credential-must-not-be-logged@invalid')
    clock = [100.0]
    monkeypatch.setattr(rate_limits, 'time', SimpleNamespace(monotonic=lambda: clock[0]))
    attempts = []
    def broken(url):
        attempts.append(url)
        raise ConnectionError('contains sensitive URL')
    monkeypatch.setattr(rate_limits, 'connection', broken)
    limiter = rate_limits.RateLimiter()
    limiter.check('outage', 1, 60)
    with pytest.raises(HTTPException):
        limiter.check('outage', 1, 60)
    assert len(attempts) == 1
    clock[0] += 6
    limiter.check('different', 1, 60)
    assert len(attempts) == 2
    assert 'credential-must-not' not in caplog.text and 'sensitive URL' not in caplog.text


def test_signin_email_lockout_survives_ip_rotation(monkeypatch):
    monkeypatch.setattr(settings, 'trusted_proxy_ips', '192.0.2.1')
    email = 'locked@example.test'
    with TestClient(create_app(start_worker=False), client=('192.0.2.1', 50000)) as client:
        for i in range(10):
            client.headers['X-Forwarded-For'] = '198.51.100.' + str(i)
            assert client.post('/v1/auth/signin', json={'email': email.upper() if i % 2 else email, 'password': 'Wrong password'}).status_code == 401
        response = client.post('/v1/auth/signin', json={'email': email, 'password': 'Wrong password'})
        assert response.status_code == 429 and int(response.headers['retry-after']) > 0
        assert client.post('/v1/auth/signin', json={'email': 'other@example.test', 'password': 'Wrong password'}).status_code == 401


@pytest.mark.parametrize('trusted,peer,expected', [
    ('', '198.51.100.9', '198.51.100.9'),
    ('192.0.2.1', '198.51.100.9', '198.51.100.9'),
    ('192.0.2.1', '192.0.2.1', '203.0.113.8'),
])
def test_forwarded_ip_only_from_explicit_proxy(monkeypatch, trusted, peer, expected):
    from fastapi import Request
    monkeypatch.setattr(settings, 'trusted_proxy_ips', trusted)
    app = create_app(start_worker=False)
    @app.get('/__test_client')
    def who(request: Request):
        return {'ip': request.client.host}
    with TestClient(app, client=(peer, 50000)) as client:
        response = client.get('/__test_client', headers={'X-Forwarded-For': '203.0.113.8'})
        assert response.json()['ip'] == expected


@pytest.mark.parametrize('network', ['*', '0.0.0.0/0', '::/0'])
def test_trust_all_proxy_configuration_rejected(network):
    configured = Settings(_env_file=None, trusted_proxy_ips=network)
    with pytest.raises((RuntimeError, ValueError)):
        configured.initialize()


def test_split_database_password_requires_explicit_project_host():
    configured = Settings(_env_file=None, supabase_db_host='', supabase_db_password='synthetic-only')
    with pytest.raises(RuntimeError, match='SUPABASE_DB_HOST is required'):
        configured.initialize()


def test_cost_routes_limit_ip_and_actor_separately(account, monkeypatch):
    client, ws, base = account
    seen = []
    monkeypatch.setattr(rate_limits.limiter, 'check', lambda key, limit, period: seen.append((key, limit, period)))
    response = client.post(base + '/keys', json={'name': 'Local', 'scopes': ['kb:read']})
    assert response.status_code == 201
    assert any(key.startswith('cost:/keys:ip:') for key, _, _ in seen)
    assert any(key.startswith(f'cost:/keys:actor:{ws}:user:') for key, _, _ in seen)


def test_real_redis_atomic_shared_window_and_expiration(monkeypatch):
    url = os.environ.get('STUDIO_TEST_REDIS_URL')
    if not url:
        pytest.skip('Set STUDIO_TEST_REDIS_URL to a disposable Redis instance')
    monkeypatch.setattr(settings, 'redis_url', url)
    first, second = rate_limits.RateLimiter(), rate_limits.RateLimiter()
    key = 'shared-test:' + str(uuid4())
    def attempt(i):
        try:
            (first if i % 2 else second).check(key, 10, .5)
            return True
        except HTTPException as exc:
            assert exc.status_code == 429
            return False
    # Separate limiter objects simulate independent API processes sharing Redis.
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(attempt, range(40))) == 10
    assert not first.entries and not second.entries
    opaque = hmac.new(settings.app_secret.encode(), key.encode(), hashlib.sha256).hexdigest()
    client = Redis.from_url(url)
    redis_key = 'studio:rate:v1:' + opaque
    assert 0 < client.pttl(redis_key) <= 500
    time.sleep(.55)
    assert not client.exists(redis_key)
    first.check(key, 10, .5)
    client.delete(redis_key)

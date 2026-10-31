from datetime import timedelta
import asyncio

from fastapi import Request
from fastapi.testclient import TestClient
import httpx
import pytest
from sqlalchemy import select

from studio import readiness as readiness_module
from studio.config import settings
from studio.db import now, session_scope
from studio.http_security import RequestSecurity
from studio.main import create_app
from studio.models import WorkerHeartbeat, UserProfile


@pytest.fixture(autouse=True)
def fake_sandbox_health_for_dependency_aggregation(monkeypatch):
    # These are readiness/header unit tests. Real sandbox readiness is covered
    # separately by the mandatory sandbox integration test.
    from studio import isolation
    class Health:
        async def run(self, request, fetch=None):
            assert request == {'operation': 'health'}
            return {'ready': True}
    monkeypatch.setattr(isolation, 'provider', Health())


def test_minimal_liveness_and_worker_readiness(client):
    assert client.get('/healthz').json() == {'status':'ok'}
    assert client.get('/readyz').status_code == 503
    readiness_module.heartbeat('isolated-worker')
    result = client.get('/readyz')
    assert result.status_code == 200 and result.json()['checks']['database'] == 'ok'
    with session_scope(write=True) as db:
        db.get(WorkerHeartbeat, 'isolated-worker').last_seen_at = now()-timedelta(seconds=31)
    assert client.get('/readyz').status_code == 503
    readiness_module.heartbeat('isolated-worker')
    readiness_module.heartbeat('isolated-worker', 'stopped')
    assert client.get('/readyz').status_code == 503


def test_production_dependencies_fail_closed_and_errors_redacted(client, monkeypatch):
    readiness_module.heartbeat('worker')
    monkeypatch.setattr(settings, 'app_env', 'production')
    monkeypatch.setattr(settings, 'redis_url', '')
    monkeypatch.setattr(settings, 'vector_endpoint', '')
    response = client.get('/readyz')
    assert response.status_code == 503
    assert response.json()['checks']['redis'] == response.json()['checks']['qdrant'] == 'unavailable'
    def broken():
        raise RuntimeError('postgresql://user:private-password@host/database')
    monkeypatch.setattr(readiness_module, 'database_and_worker', broken)
    response = client.get('/readyz')
    assert response.status_code == 503 and 'private-password' not in response.text


def test_readiness_uses_configured_authenticated_dependencies(client, monkeypatch):
    readiness_module.heartbeat('worker')
    monkeypatch.setattr(settings, 'app_env', 'production')
    monkeypatch.setattr(settings, 'redis_url', 'redis://fake')
    monkeypatch.setattr(settings, 'vector_endpoint', 'https://qdrant.example.test')
    monkeypatch.setattr(settings, 'vector_api_key', 'fake-key')
    class Redis:
        def ping(self):return True
    monkeypatch.setattr(readiness_module, 'connection', lambda url: Redis())
    original = httpx.AsyncClient
    calls = []
    async def handle(request):
        calls.append(request)
        assert request.url == 'https://qdrant.example.test/readyz'
        assert request.headers['api-key'] == 'fake-key'
        return httpx.Response(200)
    monkeypatch.setattr(readiness_module.httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(handle), **kw))
    assert client.get('/readyz').status_code == 200
    assert len(calls) == 1


def test_production_docs_require_verified_browser_identity(account, monkeypatch):
    client, _, _ = account
    with session_scope(write=True) as db:
        db.scalar(select(UserProfile)).email_verified_at = now()
    monkeypatch.setattr(settings, 'app_env', 'production')
    assert client.get('/openapi.json').status_code == 200
    result = client.get('/docs')
    assert result.status_code == 200 and 'nonce-' in result.headers['content-security-policy']
    assert 'includeSubDomains' in result.headers['strict-transport-security']
    client.cookies.clear()
    assert client.get('/docs').status_code == 401
    assert client.get('/openapi.json').status_code == 401
    assert client.get('/redoc').status_code == 404


def test_unverified_session_cannot_open_production_docs(account, monkeypatch):
    client, _, _ = account
    monkeypatch.setattr(settings, 'app_env', 'production')
    assert client.get('/docs').status_code == client.get('/openapi.json').status_code == 403


def test_body_limits_preserve_payload_and_reject_compression(client, monkeypatch):
    monkeypatch.setattr(settings, 'request_json_max_bytes', 1024)
    response = client.post('/v1/auth/signin', content=b'x'*1025, headers={'Content-Type':'application/json'})
    assert response.status_code == 413
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert client.post('/v1/auth/signin', content=b'zip', headers={'Content-Encoding':'gzip'}).status_code == 415
    assert client.post('/v1/auth/signin', content=b'{}', headers={'Content-Length':'nonsense'}).status_code == 400


@pytest.mark.asyncio
async def test_chunked_body_cannot_bypass_limit_and_no_handler_work_runs(monkeypatch):
    monkeypatch.setattr(settings, 'request_json_max_bytes', 10)
    called = []
    async def app(scope, receive, send):called.append(True)
    events = iter([{'type':'http.request','body':b'a'*8,'more_body':True},
                   {'type':'http.request','body':b'b'*8,'more_body':False}])
    async def receive():return next(events)
    sent = []
    async def send(message):sent.append(message)
    await RequestSecurity(app)({'type':'http','method':'POST','headers':[]}, receive, send)
    assert not called and sent[0]['status'] == 413


@pytest.mark.asyncio
async def test_request_timeout_and_exact_webhook_bytes(monkeypatch):
    monkeypatch.setattr(settings, 'request_body_timeout_seconds', .01)
    async def slow():await asyncio.sleep(1)
    sent = []
    async def send(message):sent.append(message)
    async def forbidden(*args):raise AssertionError('Overslow body must not reach handler')
    await RequestSecurity(forbidden)({'type':'http','method':'POST','headers':[]}, slow, send)
    assert sent[0]['status'] == 408
    raw = b'{ "signature-sensitive" : "exact bytes" }'
    events = iter([{'type':'http.request','body':raw[:8],'more_body':True},
                   {'type':'http.request','body':raw[8:],'more_body':False}])
    async def receive():return next(events)
    async def capture(scope, receive, send):
        assert (await receive())['body'] == raw
    await RequestSecurity(capture)({'type':'http','method':'POST','headers':[]}, receive, send)

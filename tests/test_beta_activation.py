from studio.legal import current as legal_policy
"""Activation contracts without SMTP deliveries, provider credits or remote DDL."""
import json
import smtplib
import ssl
from urllib.parse import parse_qs, urlparse
from unittest.mock import AsyncMock
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, delete
from studio import account_routes, connectors, identity_routes, main, mail_outbox
from studio.config import settings
from studio.db import session_scope
from studio.models import ConnectorCredential, OAuthIdentity, SchemaMigration, User, EmailOutbox, Workspace
from studio.secrets import decrypt


@pytest.mark.parametrize('security', ['starttls', 'ssl'])
def test_account_email_uses_verified_tls_and_sanitizes_failures(monkeypatch, security):
    calls = []
    class SMTP:
        def __init__(self, host, port, **options):
            calls.append(('connect', host, port))
            if security == 'ssl':
                assert options['context'].verify_mode == ssl.CERT_REQUIRED
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def starttls(self, context):
            assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
            calls.append(('tls',))
        def login(self, *args):
            calls.append(('login',))
        def send_message(self, message):
            assert message['To'] == 'qa@example.test'
            calls.append(('sent',))
    monkeypatch.setattr(settings, 'smtp_host', 'smtp.example.test')
    monkeypatch.setattr(settings, 'smtp_user', 'fixture-user')
    monkeypatch.setattr(settings, 'smtp_security', security)
    monkeypatch.setattr(mail_outbox.smtplib, 'SMTP_SSL' if security == 'ssl' else 'SMTP', SMTP)
    account_routes.send_account_email('qa@example.test', 'Verification', 'https://example.test/verify')
    assert calls == []
    assert mail_outbox.process_outbox() == 1
    assert [x[0] for x in calls] == (['connect', 'tls', 'login', 'sent'] if security == 'starttls' else ['connect', 'login', 'sent'])
    def fail(*args, **kwargs):
        raise smtplib.SMTPAuthenticationError(535, b'private provider detail')
    monkeypatch.setattr(SMTP, 'send_message', fail)
    identity = account_routes.send_account_email('qa@example.test', 'Verification', 'https://example.test/verify')
    assert mail_outbox.process_outbox() == 0
    with session_scope() as db:
        row = db.get(EmailOutbox, identity)
        assert row.state == 'pending' and row.error_code == 'delivery_failed'
        assert 'private provider detail' not in row.encrypted_payload


def test_failed_verification_delivery_retains_retryable_registration(client, monkeypatch):
    monkeypatch.setattr(settings, 'require_email_verification', True)
    def fail(*args):
        raise OSError('Email unavailable')
    monkeypatch.setattr(mail_outbox, 'deliver_message', fail)
    assert client.post('/v1/auth/signup', json={'legal_accepted':True,'legal_version':legal_policy()['version'],'name': 'QA', 'email': 'delivery@example.test',
                       'password': 'Long-QA-Password-123', 'workspace_name': 'QA'}).status_code == 202
    assert mail_outbox.process_outbox() == 0
    with session_scope() as db:
        assert db.scalar(select(User).where(User.email == 'delivery@example.test')) is not None
        assert db.scalar(select(Workspace)) is None
        assert db.scalar(select(EmailOutbox)).state == 'pending'


def test_google_new_account_and_calendar_connection_are_distinct(client, monkeypatch):
    monkeypatch.setattr(settings, 'google_client_id', 'fixture-id')
    monkeypatch.setattr(settings, 'google_client_secret', 'fixture-secret')
    claims = AsyncMock(return_value={'sub': 'google-new-user', 'email': 'google@example.test', 'name': 'Google QA'})
    monkeypatch.setattr(identity_routes, 'google_claims', claims)
    assert client.post('/v1/auth/signup-intent',json={'legal_accepted':True,'legal_version':legal_policy()['version']}).status_code==202
    response = client.get('/v1/auth/google/start', follow_redirects=False)
    state = parse_qs(urlparse(response.headers['location']).query)['state'][0]
    result = client.get('/v1/auth/google/callback', params={'state': state, 'code': 'fixture'}, follow_redirects=False)
    assert result.headers['location'].endswith('/app')
    account = client.get('/v1/auth/me').json()
    assert account['user']['email_verified'] and not account['user']['has_password']
    assert client.post('/v1/auth/signin', json={'email': 'google@example.test', 'password': 'Invalid-QA-Password-123'}).status_code == 401
    ws = account['workspaces'][0]['id']
    response = client.get('/v1/auth/google/start', params={'purpose': 'calendar', 'workspace_id': ws}, follow_redirects=False)
    query = parse_qs(urlparse(response.headers['location']).query)
    assert query['access_type'] == ['offline'] and 'calendar.events' in query['scope'][0]
    claims.return_value = {'sub': 'separate-calendar-identity', 'email': 'calendar@example.test', '_refresh_token': 'fixture-refresh'}
    tested = AsyncMock()
    monkeypatch.setattr(connectors, 'test_connection', tested)
    result = client.get('/v1/auth/google/callback', params={'state': query['state'][0], 'code': 'fixture'}, follow_redirects=False)
    assert result.headers['location'].endswith('/app/integrations?connected=google_calendar')
    tested.assert_awaited_once()
    with session_scope() as db:
        secret = db.scalar(select(ConnectorCredential).where(ConnectorCredential.workspace_id == ws))
        assert json.loads(decrypt(secret.encrypted_data))['refresh_token'] == 'fixture-refresh'
        assert db.scalar(select(OAuthIdentity).where(OAuthIdentity.subject == 'separate-calendar-identity')) is None
    assert 'fixture-refresh' not in client.get('/v1/workspaces/' + ws + '/connections').text


def test_production_startup_requires_migrated_schema_and_performs_no_ddl(monkeypatch):
    monkeypatch.setattr(settings, 'app_env', 'production')
    def forbidden():
        raise AssertionError('Production startup must not apply DDL')
    monkeypatch.setattr(main, 'initialize_database', forbidden)
    with TestClient(main.create_app(start_worker=False)) as api:
        assert api.get('/healthz').status_code == 200
    with session_scope(write=True) as db:
        db.execute(delete(SchemaMigration))
    with pytest.raises(RuntimeError, match='revision'):
        with TestClient(main.create_app(start_worker=False)):
            pass

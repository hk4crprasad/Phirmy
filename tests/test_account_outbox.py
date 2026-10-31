from studio.legal import current as legal_policy
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from types import SimpleNamespace
import threading

import pytest
from sqlalchemy import func, select

from studio import account_policy, mail_outbox
from studio.config import settings
from studio.db import now, session_scope
from studio.models import EmailOutbox, User, Workspace
from studio.secrets import decrypt
from studio.security import password_matches


def registration(client, password='Original-Account-Password'):
    return client.post('/v1/auth/signup', json={'legal_accepted':True,'legal_version':legal_policy()['version'],'name':'Private account','email':'private@example.test',
                       'password':password,'workspace_name':'Private workspace'})


def test_signup_is_uniform_never_authenticates_existing_user_or_changes_password(client, monkeypatch):
    monkeypatch.setattr(settings, 'require_email_verification', True)
    first = registration(client)
    second = registration(client, 'Attacker-Selected-Password')
    assert first.status_code == second.status_code == 202
    assert first.json() == second.json()
    assert 'set-cookie' not in first.headers and 'set-cookie' not in second.headers
    assert client.get('/v1/auth/me').status_code == 401
    with session_scope() as db:
        assert db.scalar(select(func.count()).select_from(User)) == 1
        assert db.scalar(select(func.count()).select_from(Workspace)) == 0
        user = db.scalar(select(User))
        assert password_matches('Original-Account-Password', user.password_hash)
        assert not password_matches('Attacker-Selected-Password', user.password_hash)
        assert db.scalar(select(func.count()).select_from(EmailOutbox)) == 2


def test_forgot_existing_unknown_and_smtp_outage_have_identical_response(account, monkeypatch):
    client, _, _ = account
    monkeypatch.setattr(settings, 'smtp_host', 'not-contacted.example.test')
    def forbidden(*args):
        raise AssertionError('Requests must not invoke SMTP')
    monkeypatch.setattr(mail_outbox, 'deliver_message', forbidden)
    existing = client.post('/v1/auth/forgot-password', json={'email':'qa@example.test'})
    missing = client.post('/v1/auth/forgot-password', json={'email':'unknown@example.test'})
    assert existing.status_code == missing.status_code == 202
    assert existing.json() == missing.json()
    assert 'set-cookie' not in existing.headers and 'set-cookie' not in missing.headers
    with session_scope() as db:
        row = db.scalar(select(EmailOutbox).where(EmailOutbox.recipient == 'unknown@example.test'))
        assert __import__('json').loads(decrypt(row.encrypted_payload))['noop'] is True


def test_uniform_response_floor_and_jitter_are_independent_of_account_existence(monkeypatch):
    sleeps = []
    monkeypatch.setattr(settings, 'auth_response_floor_ms', 500)
    monkeypatch.setattr(account_policy.secrets, 'randbelow', lambda _: 0)
    for elapsed in [.05, .12]:
        ticks = iter([10, 10 + elapsed])
        monkeypatch.setattr(account_policy, 'time', SimpleNamespace(monotonic=lambda:next(ticks), sleep=sleeps.append))
        with account_policy.uniform_auth_response():
            pass
    assert sleeps == pytest.approx([.45, .38])


def test_workspace_limit_and_verified_sensitive_actions(account, monkeypatch):
    client, _, _ = account
    monkeypatch.setattr(settings, 'max_owned_workspaces', 1)
    assert client.post('/v1/workspaces', json={'name':'Too many'}).status_code == 409
    monkeypatch.setattr(settings, 'require_email_verification', True)
    assert client.post('/v1/workspaces', json={'name':'Unverified'}).status_code == 403
    assert client.post('/v1/auth/password', json={'current_password':'Long-Local-Test-Password',
                      'new_password':'Changed-Private-Password'}).status_code == 403
    # Production cannot bypass verification by setting the development switch false.
    monkeypatch.setattr(settings, 'app_env', 'production')
    monkeypatch.setattr(settings, 'require_email_verification', False)
    assert account_policy.verification_required()


def test_mail_is_transactional_encrypted_and_idempotent():
    with pytest.raises(RuntimeError):
        with session_scope(write=True) as db:
            mail_outbox.enqueue_email(db, 'qa@example.test', 'Private', 'reset-token-private', operation_key='rollback')
            raise RuntimeError('rollback transaction')
    with session_scope(write=True) as db:
        assert db.scalar(select(EmailOutbox)) is None
        first = mail_outbox.enqueue_email(db, 'qa@example.test', 'Private', 'reset-token-private', operation_key='one')
        second = mail_outbox.enqueue_email(db, 'qa@example.test', 'Private', 'reset-token-private', operation_key='one')
        assert first == second
        row = db.get(EmailOutbox, first)
        assert 'reset-token-private' not in row.encrypted_payload


def test_outbox_exclusive_claim_retry_redaction_and_dead_letter(monkeypatch):
    with session_scope(write=True) as db:
        identity = mail_outbox.enqueue_email(db, 'qa@example.test', 'Notice', 'body')
    entered, release = threading.Event(), threading.Event()
    sent = []
    def slow(*args):
        sent.append(args[-1]); entered.set(); assert release.wait(5)
    monkeypatch.setattr(mail_outbox, 'deliver_message', slow)
    with ThreadPoolExecutor(max_workers=2) as pool:
        one = pool.submit(mail_outbox.process_outbox, 1)
        assert entered.wait(5)
        assert pool.submit(mail_outbox.process_outbox, 1).result() == 0
        release.set()
        assert one.result() == 1
    assert sent == [identity]
    with session_scope(write=True) as db:
        identity = mail_outbox.enqueue_email(db, 'qa@example.test', 'Retry', 'body')
    def fail(*args):
        raise OSError('smtp://user:secret@host private failure')
    monkeypatch.setattr(mail_outbox, 'deliver_message', fail)
    monkeypatch.setattr(settings, 'email_max_attempts', 2)
    assert mail_outbox.process_outbox(1) == 0
    with session_scope(write=True) as db:
        row = db.get(EmailOutbox, identity)
        assert row.state == 'pending' and row.attempts == 1 and row.next_attempt_at > now()
        assert row.error_code == 'delivery_failed' and 'secret' not in row.error_code
        row.next_attempt_at = now() - timedelta(seconds=1)
    assert mail_outbox.process_outbox(1) == 0
    with session_scope() as db:
        assert db.get(EmailOutbox, identity).state == 'failed'


def test_stale_outbox_sender_cannot_overwrite_new_lease(monkeypatch):
    with session_scope(write=True) as db:
        identity = mail_outbox.enqueue_email(db, 'qa@example.test', 'Leased', 'body')
    def changed_owner(*args):
        with session_scope(write=True) as db:
            db.get(EmailOutbox, identity).lease_token = 'new-owner'
    monkeypatch.setattr(mail_outbox, 'deliver_message', changed_owner)
    assert mail_outbox.process_outbox(1) == 0
    with session_scope() as db:
        row = db.get(EmailOutbox, identity)
        assert row.lease_token == 'new-owner' and row.sent_at is None and row.state == 'sending'

import json
from uuid import uuid4

import pytest
from sqlalchemy import select

from studio import mail_outbox
from studio.config import settings
from studio.db import now, session_scope
from studio.models import EmailOutbox
from studio.secrets import decrypt


def body(**changes):
    return {'name': 'Alex Morgan', 'email': 'alex@example.com', 'company': 'Studio & Co',
            'interest': 'both', 'message': 'We would like an agent to answer our customer questions.',
            'contact_permission': True, **changes}


def send(client, data=None, key=None, origin='https://phirmy.com'):
    return client.post('/v1/public/contact', json=data or body(), headers={
        'origin': origin, 'idempotency-key': key or str(uuid4())})


def rows():
    with session_scope() as db:
        return db.scalars(select(EmailOutbox).where(EmailOutbox.operation_key.like('public-contact:%'))).all()


def test_enquiry_encrypted_with_fixed_recipient_reply_to_and_safe_html(client):
    response = send(client, body(name='<b>Alex</b>', message='An enquiry with <script>alert(1)</script> and enough context.'))
    assert response.status_code == 202
    assert response.headers['cache-control'].endswith('no-store')
    row, = rows()
    assert row.recipient == 'support@phirmy.com'
    assert row.state == 'pending' and row.attempts == 0
    assert 'alex@example.com' not in row.encrypted_payload
    payload = json.loads(decrypt(row.encrypted_payload))
    assert payload['reply_to'] == 'alex@example.com'
    assert '<script>' not in payload['html_body'] and '<b>Alex' not in payload['html_body']
    assert '&lt;script&gt;' in payload['html_body']
    assert response.json()['reference'] in payload['body']
    assert 'Permission: May contact me about this enquiry.' in payload['body']


def test_same_reference_retries_once_and_rejects_changed_message(client):
    key = str(uuid4())
    first = send(client, key=key)
    again = send(client, key=key)
    assert first.status_code == again.status_code == 202
    assert first.json() == again.json()
    assert send(client, body(message='This is a different message with another purpose.'), key=key).status_code == 409
    assert len(rows()) == 1


@pytest.mark.parametrize('changes', [
    {'email': 'not-an-email'}, {'email': 'alex@example.com\r\nBcc: elsewhere@example.com'},
    {'name': 'Alex\r\nInjected'}, {'name': ' '}, {'contact_permission': False},
    {'message': 'too short'}, {'message': 'a'*4001}, {'recipient': 'elsewhere@example.com'},
    {'interest': 'unknown'},
])
def test_invalid_enquiries_never_queue(client, changes):
    assert send(client, body(**changes)).status_code == 422
    assert rows() == []


def test_origin_honeypot_and_reference_guards(client, monkeypatch):
    assert send(client, origin='https://attacker.example').status_code == 403
    assert send(client, origin='').status_code == 403
    assert send(client, key='invalid').status_code == 422
    assert send(client, body(fax_number='automated')).status_code == 202
    assert rows() == []
    monkeypatch.setattr(settings, 'app_env', 'production')
    assert send(client, origin='http://localhost:3200').status_code == 403


def test_rate_limits_prevent_repeat_email_and_ip_abuse(client):
    for _ in range(3):
        assert send(client).status_code == 202
    assert send(client).status_code == 429
    assert len(rows()) == 3
    for index in range(2):
        # The rejected fourth enquiry consumed an IP attempt; only one remains.
        response = send(client, body(email=f'another{index}@example.com'))
        assert response.status_code == (202 if index == 0 else 429)


def test_missing_smtp_is_actionable_and_does_not_fake_receipt(client, monkeypatch):
    monkeypatch.setattr(settings, 'app_env', 'production')
    monkeypatch.setattr(settings, 'smtp_host', '')
    result = send(client)
    assert result.status_code == 503
    assert 'support@phirmy.com' in result.json()['detail']
    assert rows() == []


@pytest.mark.parametrize('security', ['ssl', 'starttls'])
def test_worker_uses_configured_smtp_and_preserves_retry_and_reply_to(client, monkeypatch, security):
    sent = []; connections = []; tls = []
    class FakeSMTP:
        def __init__(self, host, port, **options):
            connections.append((host, port, options))
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def starttls(self, **kwargs): tls.append(kwargs)
        def login(self, user, password): assert (user, password) == ('test-user', 'test-password')
        def send_message(self, message): sent.append(message)
    monkeypatch.setattr(mail_outbox.smtplib, 'SMTP', FakeSMTP)
    monkeypatch.setattr(mail_outbox.smtplib, 'SMTP_SSL', FakeSMTP)
    for key, value in {'smtp_host': 'smtp.example.test', 'smtp_port': 465 if security=='ssl' else 587,
                       'smtp_security': security, 'smtp_user':'test-user', 'smtp_password':'test-password',
                       'smtp_from':'Phirmy <sender@example.com>'}.items():
        monkeypatch.setattr(settings, key, value)
    assert send(client).status_code == 202
    assert sent == []  # The HTTP handler never blocks on SMTP.
    assert mail_outbox.process_outbox(1) == 1
    assert len(sent) == 1
    message = sent[0]
    assert message['From'] == settings.smtp_from
    assert message['To'] == 'support@phirmy.com'
    assert message['Reply-To'] == 'alex@example.com'
    assert message.get_body(preferencelist=('plain',)) and message.get_body(preferencelist=('html',))
    assert bool(tls) == (security == 'starttls')
    assert ('context' in connections[0][2]) == (security == 'ssl')
    assert mail_outbox.process_outbox(1) == 0


def test_smtp_failure_leaves_enquiry_for_retry(client, monkeypatch):
    assert send(client).status_code == 202
    def fail(*args): raise RuntimeError('sensitive provider details must not be saved')
    monkeypatch.setattr(mail_outbox, 'deliver_message', fail)
    assert mail_outbox.process_outbox(1) == 0
    row, = rows()
    assert row.state == 'pending' and row.attempts == 1 and row.error_code == 'delivery_failed'
    monkeypatch.setattr(mail_outbox, 'deliver_message', lambda *args: None)
    with session_scope(write=True) as db:
        db.get(EmailOutbox, row.id).next_attempt_at = now()
    assert mail_outbox.process_outbox(1) == 1
    assert rows()[0].state == 'sent'


def test_concurrent_changed_payload_with_same_reference_cannot_replace_enquiry(client):
    from concurrent.futures import ThreadPoolExecutor
    key = str(uuid4())
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda message: send(client, body(message=message), key=key),
                                ['The first request for a voice agent consultation.',
                                 'The other request for a website chat consultation.']))
    assert sorted(result.status_code for result in results) == [202, 409]
    assert len(rows()) == 1

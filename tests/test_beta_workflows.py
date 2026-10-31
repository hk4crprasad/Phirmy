import asyncio
import csv
import hashlib
import hmac
import io
import json
from datetime import timedelta
from unittest.mock import AsyncMock
import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from studio.config import settings
from studio.db import session_scope, now
from studio.main import create_app
from studio.models import Call, Delivery, Membership, UsageRecord, Contact, ConnectorCredential
from studio import chat_routes, connectors, identity_routes, operations_routes, workers
from studio.secrets import decrypt
from conftest import signup


@pytest.mark.asyncio
async def test_agent_calendar_availability_sync_and_cancellation(account, monkeypatch):
    client, ws, base = account
    monkeypatch.setattr(connectors, 'test_connection', AsyncMock())
    assert client.put(base + '/connections/google_calendar', json={'credentials': {
        'client_id': 'fixture', 'client_secret': 'fixture', 'refresh_token': 'fixture'}}).status_code == 200
    context = {'workspace_id': ws, 'operation_id': 'calendar-agent-turn', 'user_text': 'Please book this appointment'}
    start, end = (now() + timedelta(days=1)).isoformat(), (now() + timedelta(days=1, minutes=30)).isoformat()
    events = []
    async def provider(method, url, **kwargs):
        if 'oauth2' in url:
            return {'access_token': 'fixture-access'}
        assert kwargs['headers']['Authorization'] == 'Bearer fixture-access'
        if url.endswith('freeBusy'):
            return {'calendars': {'primary': {'busy': []}}}
        if method == 'GET':
            from fastapi import HTTPException
            raise HTTPException(502, 'Provider request failed (HTTP 404)')
        events.append(kwargs['json'])
        return {'id': kwargs['json']['id']}
    monkeypatch.setattr(connectors, 'request', provider)
    checked = await connectors.agent_calendar_action('check_calendar_availability', {'start': start, 'end': end}, context)
    assert checked['remote_calendar_checked'] is True and not checked['busy']
    appointment = client.post(base + '/appointments', headers={'Idempotency-Key': 'calendar-qa'},
        json={'title': 'Calendar QA', 'start': start, 'end': end, 'timezone': 'UTC'}).json()
    args = {'appointment_id': appointment['id']}
    denied = await connectors.agent_calendar_action('sync_calendar_appointment', args, {**context, 'user_text': 'Hello'})
    assert 'error' in denied and not events
    result = await connectors.agent_calendar_action('sync_calendar_appointment', args, context)
    assert result['state'] == 'succeeded' and result['status'] == 'synced'
    assert (await connectors.agent_calendar_action('sync_calendar_appointment', args, context)) == result
    assert len(events) == 1
    assert client.post(base + '/appointments/' + appointment['id'] + '/cancel').status_code == 200
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as error:
        await connectors.agent_calendar_action('sync_calendar_appointment', args, {**context, 'operation_id': 'after-cancel'})
    assert error.value.status_code == 409 and len(events) == 1


def installation(client, base, agent_id, voice=False):
    response = client.post(base + '/installations', json={'name': 'QA website', 'agent_id': agent_id,
                           'allowed_origins': [settings.app_origin], 'theme': {'voice_enabled': voice}})
    assert response.status_code == 201
    return response.json()


def session(client, widget, variables=None):
    return client.post('/v1/public/sessions', headers={'Origin': settings.app_origin},
                       json={'visitor_email':'visitor@example.test','installation_public_id': widget['public_id'], 'public_key':widget['theme'].get('publishable_key'), 'variables': variables or {}})


def turn(client, state, text, identity):
    return client.post('/v1/public/chat', headers={'Origin': settings.app_origin, 'Authorization': 'Bearer ' + state['session_token']},
                       json={'session_id': state['id'], 'message': text, 'client_message_id': identity})


def test_widget_variables_recent_context_and_idempotent_usage(account, monkeypatch):
    client, ws, base = account
    agent = client.post(base + '/agents', json={'name': 'Personal assistant'}).json()
    config = agent['draft_config']
    config['greeting'] = 'Hello {{customer_name}}'
    config['variables'] = [{'name': 'customer_name', 'description': 'Your name', 'default': None, 'required': True}]
    draft = client.put(base + '/agents/' + agent['id'] + '/draft', json={'expected_revision': 1, 'config': config}).json()
    assert client.post(base + '/agents/' + agent['id'] + '/publish', json={'expected_draft_revision': draft['draft_revision']}).status_code == 201
    widget = installation(client, base, agent['id'])
    assert session(client, widget).status_code == 422
    state = session(client, widget, {'customer_name': 'Alex'}).json()
    assert state['greeting'] == 'Hello Alex'
    captured = []
    async def answer(config, question, passages, history=None, tool_context=None):
        captured.append((config, history))
        yield 'Acknowledged ' + question
    monkeypatch.setattr(chat_routes, 'answer_stream', answer)
    for index in range(15):
        response = turn(client, state, 'Context ' + str(index), 'message-' + str(index))
        assert 'chat.completed' in response.text
    assert captured[-1][0]['_runtime_variables']['customer_name'] == 'Alex'
    history = [row['text'] for row in captured[-1][1]]
    assert 'Context 13' in history and 'Context 0' not in history and 'Context 14' not in history
    assert 'chat.completed' in turn(client, state, 'Context 14', 'message-14').text
    with session_scope() as db:
        assert db.scalar(select(func.count()).select_from(UsageRecord).where(UsageRecord.workspace_id == ws)) == 15


def test_workspace_allowance_cannot_be_reset_by_new_widget_session(sample, monkeypatch):
    client, ws, base, fixture = sample
    monkeypatch.setattr(settings, 'workspace_daily_turn_limit', 1)
    widget = installation(client, base, fixture['agent_id'])
    first = session(client, widget).json()
    assert turn(client, first, 'A first question', 'first').status_code == 200
    second = session(client, widget).json()
    assert turn(client, second, 'A second question', 'second').status_code == 429
    assert turn(client, first, 'A first question', 'first').status_code == 200


def test_public_voice_origin_binding_limits_and_revocation(sample, monkeypatch):
    client, ws, base, fixture = sample
    import studio.llm
    monkeypatch.setattr(studio.llm, 'live_voice_ready', lambda *args: True)
    monkeypatch.setattr(settings, 'workspace_voice_concurrency', 1)
    widget = installation(client, base, fixture['agent_id'], voice=True)
    state = session(client, widget).json()
    headers = {'Origin': settings.app_origin, 'Authorization': 'Bearer ' + state['session_token']}
    body = {'installation_public_id': widget['public_id']}
    assert client.post('/v1/public/voice/sessions', headers={**headers, 'Origin': 'https://unlisted.example'}, json=body).status_code == 403
    result = client.post('/v1/public/voice/sessions', headers=headers, json=body)
    assert result.status_code == 201
    assert client.post('/v1/public/voice/sessions', headers=headers, json=body).status_code == 429
    other = session(client, widget).json()
    assert client.post('/v1/public/voice/sessions/' + result.json()['call_id'] + '/stop',
                       headers={**headers, 'Authorization': 'Bearer ' + other['session_token']}).status_code == 403
    assert client.post('/v1/public/voice/sessions/' + result.json()['call_id'] + '/stop', headers=headers).status_code == 200
    assert client.delete(base + '/installations/' + widget['id']).status_code == 200
    assert client.post('/v1/public/voice/sessions', headers=headers, json=body).status_code == 403
    assert turn(client, state, 'Question', 'after-disable').status_code == 403


@pytest.mark.asyncio
async def test_webhook_signature_retry_rotation_and_disable(account, monkeypatch):
    client, ws, base = account
    monkeypatch.setattr(operations_routes, 'validate_public_url', AsyncMock())
    import studio.knowledge
    monkeypatch.setattr(studio.knowledge, 'validate_public_url', AsyncMock())
    result = client.post(base + '/webhooks', json={'url': 'https://receiver.example/events', 'events': ['lead.created']})
    assert result.status_code == 201
    endpoint = result.json()['endpoint']
    assert client.post(base + '/leads', json={'name': 'QA', 'evidence': 'Asked to follow up'}).status_code == 201
    with session_scope() as db:
        delivery_id = db.scalar(select(Delivery.id).where(Delivery.workspace_id == ws))
    secret = result.json()['signing_secret']
    received = []
    def handler(request):
        signature = hmac.new(secret.encode(), request.headers['X-Studio-Timestamp'].encode() + b'.' + request.content, hashlib.sha256).hexdigest()
        assert hmac.compare_digest(request.headers['X-Studio-Signature'], 'v1=' + signature)
        received.append(json.loads(request.content))
        return httpx.Response(500 if len(received) == 1 else 200)
    original_client = httpx.AsyncClient
    monkeypatch.setattr(workers.httpx, 'AsyncClient', lambda **kwargs: original_client(transport=httpx.MockTransport(handler)))
    await workers.deliver_webhook(delivery_id)
    with session_scope() as db:
        delivery = db.get(Delivery, delivery_id)
        assert delivery.state == 'pending' and delivery.attempt == 1 and delivery.next_attempt_at > now()
    secret = client.post(base + '/webhooks/' + endpoint['id'] + '/rotate-secret').json()['signing_secret']
    await workers.deliver_webhook(delivery_id)
    with session_scope() as db:
        assert db.get(Delivery, delivery_id).state == 'success'
    assert received[0]['id'] == received[1]['id']
    assert secret not in client.get(base + '/webhooks').text
    assert client.delete(base + '/webhooks/' + endpoint['id']).status_code == 200
    assert client.post(base + '/deliveries/' + delivery_id + '/replay').status_code == 409


def test_notification_reads_are_personal_and_tenant_scoped(account):
    client, ws, base = account
    client.post(base + '/leads', json={'name': 'QA', 'evidence': 'Asked to follow up'})
    first = client.get(base + '/notifications').json()
    assert first['unread'] == 1
    with TestClient(create_app(start_worker=False)) as other:
        signup(other, 'notification-qa@example.test')
        user = other.get('/v1/auth/me').json()['user']
        with session_scope(write=True) as db:
            db.add(Membership(workspace_id=ws, user_id=user['id'], role='operator'))
        assert client.post(base + '/notifications/read', json={'all': True}).status_code == 200
        assert client.get(base + '/notifications').json()['unread'] == 0
        assert other.get(base + '/notifications').json()['unread'] == 1
        assert other.post(base + '/notifications/read', json={'ids': [first['items'][0]['id']]}).status_code == 200


def test_contact_import_preview_revocation_export_and_campaign(sample):
    client, ws, base, fixture = sample
    rows = [{'name': '=SUM(1,2)', 'phone': '+12025550123', 'consent': 'granted', 'consent_note': 'Requested a callback', 'variables': {'customer_name': 'Alex'}}, {'phone': 'bad'}]
    preview = client.post(base + '/contacts/import', json={'contacts': rows}).json()
    assert preview['dry_run'] and preview['accepted'] == 1 and len(preview['errors']) == 1
    assert client.post(base + '/contacts/import', json={'contacts': rows, 'dry_run': False}).status_code == 422
    assert client.get(base + '/contacts').json()['total'] == 0
    assert client.post(base + '/contacts/import', json={'contacts': rows[:1] * 2, 'dry_run': False}).json()['duplicates'] == 1
    contact = client.get(base + '/contacts').json()['items'][0]
    assert "'=SUM" in client.get(base + '/contacts/export.csv').text
    agent = client.get(base + '/agents/' + fixture['agent_id']).json()
    campaign = client.post(base + '/campaigns', json={'name': 'Address book QA', 'agent_version_id': agent['published_version_id']}).json()
    assert client.post(base + '/campaigns/' + campaign['id'] + '/contacts/from-addressbook', json={'contact_ids': [contact['id']]}).status_code == 200
    saved = client.get(base + '/campaigns/' + campaign['id']).json()
    assert saved['contacts'][0]['variables']['customer_name'] == 'Alex'
    updated = {k: contact[k] for k in ['name', 'phone', 'email', 'variables', 'consent', 'consent_note']}
    updated['consent'] = 'revoked'
    assert client.put(base + '/contacts/' + contact['id'], json=updated).status_code == 200
    client.post(base + '/contacts/import', json={'contacts': rows[:1], 'dry_run': False})
    assert client.get(base + '/contacts').json()['items'][0]['consent'] == 'revoked'
    assert client.post(base + '/campaigns/' + campaign['id'] + '/contacts/from-addressbook', json={'contact_ids': [contact['id']]}).status_code == 409
    upload = client.post(base + '/contacts/import.csv', files={'file': ('contacts.csv', b'phone,name\n+12025550124,Alex\n', 'text/csv')})
    assert upload.status_code == 200 and upload.json()['dry_run']


def test_scheduling_connections_keep_keys_private(account, monkeypatch):
    client, ws, base = account
    request = AsyncMock(return_value={'resource': {'name': 'QA'}})
    monkeypatch.setattr(connectors, 'request', request)
    result = client.put(base + '/connections/calendly', json={'credentials': {'access_token': 'private-qa-calendly', 'booking_url': 'https://calendly.com/qa/meeting'}})
    assert result.status_code == 200 and 'private-qa-calendly' not in result.text
    assert request.await_args.args[:2] == ('GET', 'https://api.calendly.com/users/me')
    link = client.get(base + '/connections/calendly/scheduling-link').json()
    assert link['url'] == 'https://calendly.com/qa/meeting' and link['booking_confirmed'] is False
    assert client.put(base + '/connections/calendly', json={'credentials': {'access_token': 'private', 'booking_url': 'https://evil.example/meeting'}}).status_code == 422


def test_tenant_twilio_signature_uses_tenant_binding(sample, monkeypatch):
    from twilio.request_validator import RequestValidator
    client, ws, base, fixture = sample
    monkeypatch.setattr(connectors, 'test_connection', AsyncMock())
    monkeypatch.setattr(settings, 'live_calls_enabled', True)
    monkeypatch.setattr(settings, 'media_public_origin', 'https://voice.example.test')
    monkeypatch.setattr(settings, 'twilio_account_sid', 'AC-global')
    monkeypatch.setattr(settings, 'twilio_auth_token', 'global-token')
    result = client.put(base + '/connections/twilio', json={'credentials': {'account_sid': 'AC-tenant', 'auth_token': 'tenant-token'}})
    assert result.status_code == 200 and 'tenant-token' not in result.text
    version = client.get(base + '/agents/' + fixture['agent_id']).json()['published_version_id']
    with session_scope(write=True) as db:
        call = Call(workspace_id=ws, agent_version_id=version, mode='live', transport='pstn', state='connected',
                    connected_at=now() - timedelta(seconds=1), provider_call_id='CA-tenant-test', metadata_data={'provider': 'twilio'})
        db.add(call); db.flush(); call_id = call.id
    path = '/v1/provider-webhooks/twilio/status?call_id=' + call_id
    form = {'AccountSid': 'AC-tenant', 'CallSid': 'CA-tenant-test', 'CallStatus': 'completed'}
    url = settings.media_public_origin + path
    bad = RequestValidator('global-token').compute_signature(url, form)
    assert client.post(path, data=form, headers={'X-Twilio-Signature': bad}).status_code == 401
    good = RequestValidator('tenant-token').compute_signature(url, form)
    assert client.post(path, data=form, headers={'X-Twilio-Signature': good}).status_code == 200

"""Authenticated dashboard testing must not depend on public CAPTCHA keys."""
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from studio.config import settings
from studio.db import session_scope, now
from studio.main import create_app
from studio.models import ConversationContext, Membership
from test_widget_protection import installation


def preview(sample, monkeypatch):
    row = installation(sample)
    from studio.sessions import profile_for
    with session_scope(write=True) as db:
        owner = db.scalar(select(Membership.user_id).where(Membership.workspace_id == sample[1], Membership.role == 'owner'))
        profile_for(db, owner).email_verified_at = now()
    monkeypatch.setattr(settings, 'app_env', 'production')
    monkeypatch.setattr(settings, 'widget_bot_challenge_enabled', True)
    monkeypatch.setattr(settings, 'turnstile_site_key', '')
    monkeypatch.setattr(settings, 'turnstile_secret_key', '')
    return row, {'Origin': settings.app_origin, 'X-Studio-Preview': '1'}, {
        'installation_public_id': row['public_id'], 'public_key': row['theme']['publishable_key']}


def test_owner_preview_works_without_turnstile_but_public_stays_protected(sample, monkeypatch):
    client, _, _, _ = sample
    row, headers, body = preview(sample, monkeypatch)
    config = '/v1/public/installations/' + row['public_id'] + '?public_key=' + row['theme']['publishable_key']
    public_config = client.post(config, headers={'Origin': settings.app_origin})
    assert public_config.json()['challenge']['required'] is True
    owner_config = client.post(config, headers=headers)
    assert owner_config.status_code == 200 and owner_config.json()['challenge']['required'] is False
    assert client.post('/v1/public/sessions', headers={'Origin': settings.app_origin}, json=body).status_code == 503
    response = client.post('/v1/public/sessions', headers=headers, json=body)
    assert response.status_code == 201, response.text
    session = response.json()
    token_headers = {'Origin': settings.app_origin, 'Authorization': 'Bearer ' + session['session_token']}
    assert client.post('/v1/public/conversation', headers=token_headers).status_code == 200
    with session_scope() as db:
        context = db.scalar(select(ConversationContext).where(ConversationContext.conversation_id == session['id']))
        assert context.variables['_dashboard_preview_user_id']


def test_preview_header_without_authenticated_account_is_rejected(sample, monkeypatch):
    _, headers, body = preview(sample, monkeypatch)
    with TestClient(create_app(start_worker=False)) as anonymous:
        response = anonymous.post('/v1/public/sessions', headers=headers, json=body)
        assert response.status_code == 401


def test_preview_requires_csrf_and_application_origin(sample, monkeypatch):
    client, _, _, _ = sample
    _, headers, body = preview(sample, monkeypatch)
    assert client.post('/v1/public/sessions', headers={**headers, 'X-CSRF-Token': ''}, json=body).status_code == 403
    assert client.post('/v1/public/sessions', headers={**headers, 'Origin': 'https://untrusted.example'}, json=body).status_code == 403


def test_preview_requires_membership_in_the_installation_workspace(sample, monkeypatch):
    client, ws, _, _ = sample
    _, headers, body = preview(sample, monkeypatch)
    with session_scope(write=True) as db:
        db.execute(delete(Membership).where(Membership.workspace_id == ws))
    assert client.post('/v1/public/sessions', headers=headers, json=body).status_code == 404


def test_workspace_api_key_cannot_claim_dashboard_preview(sample, monkeypatch):
    client, _, base, _ = sample
    key = client.post(base + '/keys', json={'name': 'Preview boundary', 'scopes': ['widget:write']})
    assert key.status_code == 201, key.text
    _, headers, body = preview(sample, monkeypatch)
    response = client.post('/v1/public/sessions', headers={**headers, 'X-API-Key': key.json()['secret']}, json=body)
    assert response.status_code == 403


def test_public_challenge_can_be_disabled_and_reenabled_in_production(sample, monkeypatch):
    client, _, _, _ = sample
    row, _, body = preview(sample, monkeypatch)
    monkeypatch.setattr(settings, 'widget_bot_challenge_enabled', False)
    headers = {'Origin': settings.app_origin}
    config = '/v1/public/installations/' + row['public_id'] + '?public_key=' + row['theme']['publishable_key']
    assert client.post(config, headers=headers).json()['challenge']['required'] is False
    response = client.post('/v1/public/sessions', headers=headers, json=body)
    assert response.status_code == 201, response.text
    token_headers = {**headers, 'Authorization': 'Bearer ' + response.json()['session_token']}
    assert client.post('/v1/public/conversation', headers=token_headers).status_code == 200
    monkeypatch.setattr(settings, 'widget_bot_challenge_enabled', True)
    assert client.post('/v1/public/sessions', headers=headers, json=body).status_code == 503
    assert client.post('/v1/public/conversation', headers=token_headers).status_code == 403

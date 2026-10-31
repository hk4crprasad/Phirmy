from studio.legal import current as legal_policy
import base64
import hashlib
import json
import re
from datetime import timedelta
from email.parser import BytesParser
from email.policy import default
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from unittest.mock import AsyncMock
import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from studio.config import settings
from studio.db import now, session_scope
from studio.main import create_app
from studio.models import AuthSession, OAuthAttempt, OAuthIdentity, User, Workspace
from studio.security import digest
from studio.secrets import decrypt
from studio.sessions import signing_key
from studio import identity_routes


def test_email_verification_required_private_expiring_and_single_use(client, monkeypatch):
    monkeypatch.setattr(settings, 'require_email_verification', True)
    response = client.post('/v1/auth/signup', json={'legal_accepted':True,'legal_version':legal_policy()['version'],'name': 'Verified QA', 'email': 'verified@example.test',
                           'password': 'Long-Local-QA-Password', 'workspace_name': 'Verified QA'})
    assert response.status_code == 202
    assert response.json()['verification_required'] is True
    assert 'set-cookie' not in response.headers
    assert client.post('/v1/auth/signin', json={'email':'verified@example.test','password':'Long-Local-QA-Password'}).status_code == 200
    client.headers['X-CSRF-Token'] = client.cookies['studio_csrf']
    assert client.get('/v1/auth/me').json()['workspaces'] == []
    assert client.post('/v1/workspaces', json={'name':'Unverified'}).json()['detail']['code'] == 'email_verification_required'
    from studio.mail_outbox import process_outbox
    process_outbox(20)
    message = max((Path(settings.data_dir) / 'mail-outbox').glob('*.eml'), key=lambda p: p.stat().st_mtime_ns)
    body = BytesParser(policy=default).parsebytes(message.read_bytes()).get_content()
    token = re.search(r'token=([A-Za-z0-9_-]+)', body)[1]
    assert token not in response.text
    assert client.post('/v1/auth/verify-email', json={'token': token}).status_code == 200
    client.headers['X-CSRF-Token'] = client.cookies['studio_csrf']
    assert client.post('/v1/auth/verify-email', json={'token': token}).status_code == 400
    assert client.get('/v1/auth/me').json()['user']['email_verified'] is True
    base = '/v1/workspaces/' + client.get('/v1/auth/me').json()['workspaces'][0]['id']
    assert client.post(base + '/agents', json={'name': 'Verified agent'}).status_code == 201


def test_jwt_refresh_rotation_replay_revokes_family_and_checks_csrf(account):
    client, ws, base = account
    original = dict(client.cookies)
    claims = jwt.decode(original['studio_session'], signing_key(), algorithms=['HS256'],
                        audience='voice-studio-dashboard', issuer=settings.app_origin)
    assert claims['exp'] - claims['iat'] == settings.access_token_seconds
    assert client.post('/v1/auth/refresh', headers={'X-CSRF-Token': 'invalid'}).status_code == 403
    assert client.post('/v1/auth/refresh').status_code == 200
    current = dict(client.cookies)
    assert current['studio_session'] != original['studio_session']
    assert current['studio_refresh'] != original['studio_refresh']
    assert client.get('/v1/auth/me').status_code == 200
    # An opaque refresh credential cannot be substituted for an access JWT.
    assert client.get('/v1/auth/me', headers={'Cookie': 'studio_session=' + current['studio_refresh']}).status_code == 401
    expired = jwt.encode({**claims, 'exp': now() - timedelta(seconds=30)}, signing_key(), algorithm='HS256')
    assert client.get('/v1/auth/me', headers={'Cookie': 'studio_session=' + expired}).status_code == 401
    assert client.post('/v1/auth/refresh', headers={'Cookie': 'studio_refresh=' + original['studio_refresh'],
                       'X-CSRF-Token': original['studio_csrf']}).status_code == 401
    assert client.get('/v1/auth/me', headers={'Cookie': 'studio_session=' + current['studio_session']}).status_code == 401


def test_session_revocation_and_profile_are_personal(account):
    client, ws, base = account
    with TestClient(create_app(start_worker=False)) as other:
        signed = other.post('/v1/auth/signin', json={'email': 'qa@example.test', 'password': 'Long-Local-Test-Password'})
        assert signed.status_code == 200
        other.headers['X-CSRF-Token'] = other.cookies['studio_csrf']
        rows = client.get('/v1/auth/sessions').json()['items']
        assert len(rows) == 2 and sum(r['current'] for r in rows) == 1
        assert not any('token_hash' in row or 'csrf_hash' in row for row in rows)
        assert client.post('/v1/auth/sessions/revoke-others').status_code == 200
        assert other.get('/v1/auth/me').status_code == 401
    profile = client.patch('/v1/auth/profile', json={'name': 'My updated name', 'timezone': 'Europe/London',
                                                   'avatar_color': 'forest', 'notifications_enabled': False})
    assert profile.status_code == 200 and profile.json()['user']['name'] == 'My updated name'
    assert client.patch('/v1/auth/profile', json={'name': 'QA', 'timezone': 'Invalid/Timezone'}).status_code == 422


def start_google(client):
    result = client.get('/v1/auth/google/start', follow_redirects=False)
    assert result.status_code == 303
    query = parse_qs(urlparse(result.headers['location']).query)
    state = query['state'][0]
    with session_scope() as db:
        attempt = db.scalar(select(OAuthAttempt).where(OAuthAttempt.state_hash == digest(state)))
        data = json.loads(decrypt(attempt.encrypted_data))
    challenge = base64.urlsafe_b64encode(hashlib.sha256(data['verifier'].encode()).digest()).rstrip(b'=').decode()
    assert query['code_challenge'] == [challenge] and query['code_challenge_method'] == ['S256']
    assert query['nonce'] == [data['nonce']]
    return state


def test_google_state_pkce_single_use_and_no_silent_account_link(account, monkeypatch):
    client, ws, base = account
    monkeypatch.setattr(settings, 'google_client_id', 'test-client')
    monkeypatch.setattr(settings, 'google_client_secret', 'test-client-secret')
    monkeypatch.setattr(identity_routes, 'google_claims', AsyncMock(return_value={'sub': 'google-qa', 'email': 'qa@example.test', 'name': 'QA'}))
    state = start_google(client)
    bad = client.get('/v1/auth/google/callback?code=fixture&state=bad', follow_redirects=False)
    assert bad.headers['location'].endswith('auth_error=google_state')
    # A previous authenticated session does not implicitly request account linking.
    state = start_google(client)
    result = client.get('/v1/auth/google/callback?code=fixture&state=' + state, follow_redirects=False)
    assert result.headers['location'].endswith('auth_error=google_link_required')
    state_response = client.get('/v1/auth/google/start?return_to=/app/profile', follow_redirects=False)
    state = parse_qs(urlparse(state_response.headers['location']).query)['state'][0]
    result = client.get('/v1/auth/google/callback?code=fixture&state=' + state, follow_redirects=False)
    assert result.headers['location'].endswith('/app/profile')
    assert client.get('/v1/auth/me').json()['user']['providers'] == ['google']
    assert client.get('/v1/auth/me').json()['user']['email_verified'] is True
    assert client.get('/v1/auth/google/callback?code=fixture&state=' + state, follow_redirects=False).headers['location'].endswith('auth_error=google_state')
    assert client.get('/v1/auth/google/start?return_to=https://evil.example', follow_redirects=False).status_code == 422


@pytest.mark.asyncio
async def test_google_id_token_signature_audience_nonce_and_verified_email(monkeypatch):
    import httpx
    from cryptography.hazmat.primitives.asymmetric import rsa
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    jwk['kid'] = 'google-fixture'
    claims = {'sub': 'google-test', 'iss': 'https://accounts.google.com', 'aud': 'client-id',
              'nonce': 'nonce', 'email': 'verified@example.test', 'email_verified': True,
              'iat': now(), 'exp': now() + timedelta(minutes=5)}
    token = jwt.encode(claims, key, algorithm='RS256', headers={'kid': 'google-fixture'})
    original_client = httpx.AsyncClient
    def handler(request):
        return httpx.Response(200, json={'id_token': token} if request.url.host == 'oauth2.googleapis.com' else {'keys': [jwk]})
    monkeypatch.setattr(identity_routes.httpx, 'AsyncClient', lambda **kwargs: original_client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(settings, 'google_client_id', 'client-id')
    assert (await identity_routes.google_claims('code', {'nonce': 'nonce', 'verifier': 'verifier'}))['email'] == 'verified@example.test'
    with pytest.raises(ValueError):
        await identity_routes.google_claims('code', {'nonce': 'wrong-nonce', 'verifier': 'verifier'})
    token = jwt.encode({**claims, 'aud': 'other-client'}, key, algorithm='RS256', headers={'kid': 'google-fixture'})
    with pytest.raises(jwt.InvalidAudienceError):
        await identity_routes.google_claims('code', {'nonce': 'nonce', 'verifier': 'verifier'})
    token = jwt.encode({**claims, 'email_verified': False}, key, algorithm='RS256', headers={'kid': 'google-fixture'})
    with pytest.raises(ValueError):
        await identity_routes.google_claims('code', {'nonce': 'nonce', 'verifier': 'verifier'})

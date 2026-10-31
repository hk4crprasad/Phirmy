from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import HTTPException
import pytest
from sqlalchemy import func, select

from studio import origin_ownership
from studio.config import settings
from studio.db import now, session_scope
from studio.models import OriginVerification, Membership
from studio.secrets import encrypt
from conftest import verify_test_origin

ORIGIN = 'https://owned.example'


def create_widget(sample):
    client, _, base, fixture = sample
    result = client.post(base+'/installations', json={'name':'Verified site','agent_id':fixture['agent_id'],
                       'allowed_origins':[ORIGIN, settings.app_origin], 'theme':{'restrict_origins':False}})
    assert result.status_code == 201
    return result.json()


def config(client, widget, origin=ORIGIN, key=None):
    return client.post('/v1/public/installations/'+widget['public_id'], headers={'Origin':origin},
                       params={'public_key':widget['theme']['publishable_key'] if key is None else key})


def test_claimed_site_never_auto_enables_external_origin_and_verified_site_works(sample, monkeypatch):
    client, ws, base, _ = sample
    widget = create_widget(sample)
    assert widget['ownership_required'] and ORIGIN in widget['unverified_origins']
    assert config(client, widget).status_code == 403
    assert config(client, widget, settings.app_origin).status_code == 200
    assert client.get('/v1/public/widgets/'+widget['public_id']+'/frame-policy').json()['frame_ancestors'] == [settings.app_origin]
    proof_id = verify_test_origin(client, base, ORIGIN, monkeypatch)
    assert config(client, widget).status_code == 200
    assert config(client, widget, key='wrong').status_code == 403
    assert ORIGIN in client.get('/v1/public/widgets/'+widget['public_id']+'/frame-policy').json()['frame_ancestors']
    response = client.post('/v1/public/sessions', headers={'Origin':ORIGIN},json={
        'installation_public_id':widget['public_id'],'public_key':widget['theme']['publishable_key'],
        'visitor_email':'visitor@example.test'})
    assert response.status_code == 201
    state = response.json()
    headers = {'Origin':ORIGIN,'Authorization':'Bearer '+state['session_token']}
    assert client.post('/v1/public/conversation', headers=headers).status_code == 200
    assert client.post('/v1/public/conversation', headers={**headers,'Origin':'https://replay.example'}).status_code == 403
    assert client.delete(base+'/origins/'+proof_id).status_code == 200
    assert config(client, widget).status_code == 403
    assert client.post('/v1/public/conversation', headers=headers).status_code == 403
    assert client.post('/v1/public/sessions/resume', headers={**headers,'Authorization':'Bearer '+state['resume_token']}).status_code == 403
    assert ORIGIN not in client.get('/v1/public/widgets/'+widget['public_id']+'/frame-policy').json()['frame_ancestors']


def test_proof_is_per_workspace_per_origin_and_expires(sample, monkeypatch):
    client, ws, base, _ = sample
    widget = create_widget(sample)
    proof_id = verify_test_origin(client, base, ORIGIN, monkeypatch)
    assert config(client, widget).status_code == 200
    assert config(client, widget, 'https://sub.owned.example').status_code == 403
    with session_scope(write=True) as db:
        db.get(OriginVerification, proof_id).verified_until = now()-timedelta(seconds=1)
    assert config(client, widget).status_code == 403
    assert client.post('/v1/workspaces/not-your-workspace/origins',json={'origin':ORIGIN}).status_code == 404


def test_expired_rotated_and_malformed_proofs_fail_closed(account, monkeypatch):
    client, ws, base = account
    record = client.post(base+'/origins', json={'origin':ORIGIN}).json()
    class Wrong:
        async def verify(self,*args):return {'success':True}
    monkeypatch.setattr(origin_ownership,'provider',Wrong())
    assert client.post(base+'/origins/'+record['id']+'/verify',json={'method':'dns'}).status_code == 400
    with session_scope(write=True) as db:db.get(OriginVerification,record['id']).expires_at=now()-timedelta(seconds=1)
    assert client.post(base+'/origins/'+record['id']+'/verify',json={'method':'dns'}).status_code == 410
    replacement = client.post(base+'/origins',json={'origin':ORIGIN}).json()
    assert replacement['dns']['value'] != record['dns']['value']
    class Rotated:
        async def verify(self,*args):
            with session_scope(write=True) as db:db.get(OriginVerification,record['id']).encrypted_token=encrypt('changed')
            return True
    monkeypatch.setattr(origin_ownership,'provider',Rotated())
    assert client.post(base+'/origins/'+record['id']+'/verify',json={'method':'dns'}).status_code == 409


def test_membership_is_rechecked_after_external_network_wait(account, monkeypatch):
    client, ws, base = account
    record = client.post(base+'/origins',json={'origin':ORIGIN}).json()
    class Revoked:
        async def verify(self,*args):
            with session_scope(write=True) as db:db.delete(db.scalar(select(Membership).where(Membership.workspace_id==ws)))
            return True
    monkeypatch.setattr(origin_ownership,'provider',Revoked())
    assert client.post(base+'/origins/'+record['id']+'/verify',json={'method':'dns'}).status_code == 404
    with session_scope() as db:assert db.get(OriginVerification,record['id']).verified_at is None


def test_role_demotion_during_proof_check_cannot_use_cached_owner_permissions(account, monkeypatch):
    client, ws, base = account
    record = client.post(base+'/origins',json={'origin':ORIGIN}).json()
    class Demoted:
        async def verify(self,*args):
            with session_scope(write=True) as db:
                db.scalar(select(Membership).where(Membership.workspace_id==ws)).role = 'analyst'
            return True
    monkeypatch.setattr(origin_ownership,'provider',Demoted())
    assert client.post(base+'/origins/'+record['id']+'/verify',json={'method':'dns'}).status_code == 403


@pytest.mark.parametrize('value',['null','https://*.example','https://example/path','https://user:password@example','https://bad\nsite.example','javascript:alert(1)'])
def test_malformed_origin_cannot_create_proof_or_csp_directive(account,value):
    client, _, base = account
    assert client.post(base+'/origins',json={'origin':value}).status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize('method',['dns','meta','file'])
async def test_real_proof_adapter_validates_exact_value_and_public_origin(monkeypatch,method):
    public = AsyncMock()
    monkeypatch.setattr(origin_ownership,'validate_public_url',public)
    token='synthetic-token'
    def dns_answer(name, kind, **kwargs):
        assert name=='_voice-studio-challenge.owned.example' and kind=='TXT'
        assert kwargs['lifetime']==3 and kwargs['search'] is False
        return [SimpleNamespace(strings=((origin_ownership.PREFIX+token).encode(),))]
    monkeypatch.setattr(origin_ownership.dns.resolver,'resolve',dns_answer)
    async def fetch(url, **kwargs):
        assert kwargs['same_origin']==('https','owned.example') and kwargs['max_bytes']==128000
        body=(origin_ownership.PREFIX+token).encode() if method=='file' else ('<meta name="voice-studio-verification" content="'+token+'">').encode()
        return url,body,'text/html'
    monkeypatch.setattr(origin_ownership,'safe_fetch',fetch)
    adapter=origin_ownership.PublicOwnershipProvider()
    assert await adapter.verify(ORIGIN,method,token) is True
    assert await adapter.verify(ORIGIN,method,'wrong-token') is False
    assert public.await_count==2


@pytest.mark.asyncio
async def test_private_or_rebound_origin_is_rejected_before_http_or_dns(monkeypatch):
    denied=AsyncMock(side_effect=ValueError('private address'))
    fetch=AsyncMock()
    monkeypatch.setattr(origin_ownership,'validate_public_url',denied)
    monkeypatch.setattr(origin_ownership,'safe_fetch',fetch)
    with pytest.raises(ValueError):
        await origin_ownership.PublicOwnershipProvider().verify('https://127.0.0.1','file','token')
    fetch.assert_not_awaited()

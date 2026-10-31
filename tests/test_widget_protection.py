import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import io
import json
import re
import wave

from fastapi import HTTPException
from fastapi.testclient import TestClient
import httpx
import pytest
from sqlalchemy import func,select

from studio import bot_challenge,isolation,widget_protection
from studio.config import settings
from studio.db import now,session_scope,uid
from studio.main import create_app
from studio.models import Conversation,EmailOutbox,Installation,Message,WidgetAdmission,WidgetBucket,WidgetEmailChallenge,WidgetMarketingConsent
from studio.secrets import decrypt


def installation(sample):
    client,_,base,fixture=sample
    response=client.post(base+'/installations',json={'agent_id':fixture['agent_id'],'name':'Protected widget',
        'allowed_origins':[settings.app_origin],'theme':{'collect_email':False}})
    assert response.status_code==201
    return response.json()


def start(sample,row=None,**extra):
    client=sample[0];row=row or installation(sample)
    response=client.post('/v1/public/sessions',headers={'Origin':settings.app_origin},json={
        'installation_public_id':row['public_id'],'public_key':row['theme']['publishable_key'],**extra})
    assert response.status_code==201,response.text
    session=response.json()
    return session,{'Origin':settings.app_origin,'Authorization':'Bearer '+session['session_token']}


def change_policy(sample,row,**values):
    response=sample[0].put(sample[2]+'/installations/'+row['id']+'/protection',json={**widget_protection.defaults(),**values})
    assert response.status_code==200,response.text
    return response.json()


def request_code(sample,headers,email='visitor@example.test'):
    response=sample[0].post('/v1/public/email/request',headers=headers,json={'email':email})
    assert response.status_code==202,response.text
    challenge=response.json()
    with session_scope() as db:
        mail=db.scalar(select(EmailOutbox).where(EmailOutbox.operation_key=='widget-otp:'+challenge['challenge_id']))
        code=re.search(r'code is (\d{6})',json.loads(decrypt(mail.encrypted_payload))['body'])[1]
    assert code not in json.dumps(challenge)
    return challenge,code


def test_default_email_is_optional_and_unverified_opt_in_is_never_stored(sample):
    row=installation(sample);session,headers=start(sample,row)
    assert session['theme']['collect_email'] is False and not session['lead_captured']
    session,headers=start(sample,row,visitor_email='visitor@example.test',marketing_opt_in=True)
    data=sample[0].get(sample[2]+'/conversations/'+session['id']+'/messages').json()
    assert data['visitor']['email_verified'] is False and 'marketing_opt_in' not in data['visitor']
    leads=sample[0].get(sample[2]+'/leads').json()['items']
    assert not leads[0]['email_verified'] and not leads[0]['marketing_opt_in']
    assert 'marketing_opt_in' not in json.loads(leads[0]['evidence'])
    with session_scope() as db:assert db.scalar(select(func.count()).select_from(WidgetMarketingConsent))==0


@pytest.mark.asyncio
async def test_siteverify_exact_contract_and_fail_closed(monkeypatch):
    monkeypatch.setattr(settings,'app_env','production');monkeypatch.setattr(settings,'widget_bot_challenge_enabled',True)
    with pytest.raises(HTTPException) as missing:await bot_challenge.enforce('token','203.0.113.7','https://shop.example')
    assert missing.value.status_code==503
    monkeypatch.setattr(settings,'turnstile_site_key','synthetic-site');monkeypatch.setattr(settings,'turnstile_secret_key','synthetic-secret')
    expected={'success':True,'hostname':'shop.example','action':'widget_session','challenge_ts':now().isoformat()}
    original=httpx.AsyncClient;calls=[]
    def provider(request):
        assert str(request.url)=='https://challenges.cloudflare.com/turnstile/v0/siteverify'
        data=json.loads(request.content);calls.append(data)
        assert data['remoteip']=='203.0.113.7' and data['response']=='single-use-token' and data['secret']=='synthetic-secret'
        assert len(data['idempotency_key'])==36
        return httpx.Response(200,json=expected)
    monkeypatch.setattr(bot_challenge.httpx,'AsyncClient',lambda **options:original(transport=httpx.MockTransport(provider),**options))
    assert await bot_challenge.TurnstileProvider().verify('single-use-token','203.0.113.7','shop.example') is True
    for changed in [{'success':1},{'hostname':'other.example'},{'action':'login'},
                    {'challenge_ts':(now()-timedelta(seconds=301)).isoformat()},{'challenge_ts':'bad'}]:
        previous=expected.copy();expected.update(changed)
        assert await bot_challenge.TurnstileProvider().verify('single-use-token','203.0.113.7','shop.example') is False
        expected.clear();expected.update(previous)
    assert len(calls)==6


def test_session_verifies_real_peer_before_admission_and_rejects_replayed_fake_token(sample,monkeypatch):
    row=installation(sample);seen=set();calls=[]
    class Fake:
        async def verify(self,token,remote_ip,hostname):
            calls.append((remote_ip,hostname))
            if token in seen:return False
            seen.add(token);return token=='fake-provider-token'
    monkeypatch.setattr(bot_challenge,'provider',Fake())
    monkeypatch.setattr(settings,'widget_bot_challenge_enabled',True)
    monkeypatch.setattr(settings,'turnstile_site_key','fake-site');monkeypatch.setattr(settings,'turnstile_secret_key','fake-secret')
    client=sample[0];body={'installation_public_id':row['public_id'],'public_key':row['theme']['publishable_key']}
    assert client.post('/v1/public/sessions',headers={'Origin':settings.app_origin},json=body).status_code==403
    body['bot_token']='fake-provider-token'
    assert client.post('/v1/public/sessions',headers={'Origin':settings.app_origin,'X-Forwarded-For':'192.0.2.200'},json=body).status_code==201
    assert calls==[('testclient','localhost')]
    assert client.post('/v1/public/sessions',headers={'Origin':settings.app_origin},json=body).status_code==403
    with session_scope() as db:assert db.scalar(select(func.count()).select_from(Conversation))==1


def test_origin_revocation_during_siteverify_cannot_start_a_session(sample,monkeypatch):
    row=installation(sample)
    class Fake:
        async def verify(self,*args):
            with session_scope(write=True) as db:db.get(Installation,row['id']).enabled=False
            return True
    monkeypatch.setattr(bot_challenge,'provider',Fake())
    monkeypatch.setattr(settings,'widget_bot_challenge_enabled',True)
    monkeypatch.setattr(settings,'turnstile_site_key','fake-site');monkeypatch.setattr(settings,'turnstile_secret_key','fake-secret')
    response=sample[0].post('/v1/public/sessions',headers={'Origin':settings.app_origin},json={
        'installation_public_id':row['public_id'],'public_key':row['theme']['publishable_key'],'bot_token':'fake-token'})
    assert response.status_code==403
    with session_scope() as db:assert db.scalar(select(func.count()).select_from(WidgetAdmission))==0


def test_installation_and_global_ip_quotas_are_independent_of_workspace(sample,monkeypatch):
    first=installation(sample);second=installation(sample)
    change_policy(sample,first,daily_sessions=1)
    start(sample,first)
    body={'installation_public_id':first['public_id'],'public_key':first['theme']['publishable_key']}
    assert sample[0].post('/v1/public/sessions',headers={'Origin':settings.app_origin},json=body).status_code==429
    start(sample,second)
    monkeypatch.setattr(settings,'widget_ip_daily_sessions',2)
    body={'installation_public_id':second['public_id'],'public_key':second['theme']['publishable_key']}
    assert sample[0].post('/v1/public/sessions',headers={'Origin':settings.app_origin,'X-Forwarded-For':'198.51.100.9'},json=body).status_code==429
    with TestClient(create_app(start_worker=False),client=('203.0.113.9',4567)) as other:
        assert other.post('/v1/public/sessions',headers={'Origin':settings.app_origin},json=body).status_code==201


def test_spend_admission_is_atomic_alerts_survive_denial_and_retries_do_not_charge_twice(sample):
    row=installation(sample);change_policy(sample,row,monthly_spend_cap_minor=300)
    session,headers=start(sample,row);client=sample[0]
    def turn(index):
        return client.post('/v1/public/chat',headers=headers,json={'session_id':session['id'],
            'client_message_id':str(index),'message':'What are your opening hours?'})
    with ThreadPoolExecutor(max_workers=6) as pool:responses=list(pool.map(turn,range(12)))
    assert sum(response.status_code==200 for response in responses)==3
    assert all(response.status_code in {200,429} for response in responses)
    successful=next(index for index,response in enumerate(responses) if response.status_code==200)
    assert turn(successful).status_code==200
    with session_scope() as db:
        bucket=db.scalar(select(WidgetBucket).where(WidgetBucket.installation_id==row['id'],WidgetBucket.period==now().strftime('%Y-%m')))
        assert bucket.reserved_minor==300
        assert db.scalar(select(func.count()).select_from(WidgetAdmission).where(WidgetAdmission.kind=='turn'))==3
        assert db.scalar(select(func.count()).select_from(Message).where(Message.role=='user'))==3
        assert db.scalar(select(func.count()).select_from(EmailOutbox).where(EmailOutbox.operation_key.like('widget-cap:%')))==2
    change_policy(sample,row,monthly_spend_cap_minor=0)
    assert turn(100).status_code==429
    with session_scope() as db:
        assert db.scalar(select(func.count()).select_from(EmailOutbox).where(EmailOutbox.operation_key.like('widget-cap:%')))==3


def test_email_proof_wrong_code_boundaries_attempt_limit_and_no_consent_before_success(sample,monkeypatch):
    session,headers=start(sample,visitor_email='visitor@example.test',marketing_opt_in=True)
    challenge,code=request_code(sample,headers)
    client=sample[0];body={'challenge_id':challenge['challenge_id'],'code':code,'marketing_opt_in':True}
    wrong='000000' if code!='000000' else '111111'
    assert client.post('/v1/public/email/verify',headers=headers,json={**body,'code':wrong}).status_code==400
    with session_scope() as db:
        assert db.get(WidgetEmailChallenge,challenge['challenge_id']).attempts==1
        assert db.scalar(select(func.count()).select_from(WidgetMarketingConsent))==0
    assert client.post('/v1/public/email/verify',headers=headers,json=body).status_code==409
    monkeypatch.setattr(settings,'widget_marketing_consent_enabled',True)
    assert client.post('/v1/public/email/verify',headers={**headers,'Origin':'https://evil.example'},json=body).status_code==403
    second,other=start(sample)
    assert client.post('/v1/public/email/verify',headers=other,json=body).status_code==400
    assert client.post('/v1/public/email/verify',headers=headers,json=body).json()=={'email_verified':True,'marketing_opt_in':True}
    assert client.post('/v1/public/email/verify',headers=headers,json=body).status_code==200
    with session_scope() as db:assert db.scalar(select(func.count()).select_from(WidgetMarketingConsent))==1
    lead=next(row for row in client.get(sample[2]+'/leads').json()['items'] if row['email']=='visitor@example.test')
    assert lead['email_verified'] and lead['marketing_opt_in']


@pytest.mark.parametrize('ending',['expiry','attempts','rotation'])
def test_expired_exhausted_and_replaced_email_codes_cannot_verify(sample,ending):
    session,headers=start(sample);challenge,code=request_code(sample,headers)
    with session_scope(write=True) as db:
        row=db.get(WidgetEmailChallenge,challenge['challenge_id'])
        if ending=='expiry':row.expires_at=now()-timedelta(seconds=1)
        elif ending=='attempts':row.attempts=5
        else:row.consumed_at=now()
    response=sample[0].post('/v1/public/email/verify',headers=headers,json={'challenge_id':challenge['challenge_id'],'code':code})
    assert response.status_code==400
    with session_scope() as db:assert db.scalar(select(func.count()).select_from(WidgetMarketingConsent))==0


def wav(seconds):
    buffer=io.BytesIO()
    with wave.open(buffer,'wb') as output:
        output.setframerate(16000);output.setnchannels(1);output.setsampwidth(2);output.writeframes(b'\0\0'*int(seconds*16000))
    return buffer.getvalue()


@pytest.mark.asyncio
@pytest.mark.sandbox
async def test_untrusted_audio_is_canonicalized_and_duration_capped_in_isolation():
    audio,duration=await isolation.canonical_audio(wav(.2))
    with wave.open(io.BytesIO(audio),'rb') as source:
        assert source.getframerate()==16000 and source.getnchannels()==1 and source.getnframes()==3200
    assert duration==200
    with pytest.raises(ValueError,match='30 seconds'):await isolation.canonical_audio(wav(31))
    with pytest.raises(ValueError):await isolation.canonical_audio(b'not an audio file')

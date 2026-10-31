import asyncio
import hashlib
import hmac
import io
import json
import re
import wave
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock
import numpy as np
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select,func
from studio.config import settings
from studio.db import session_scope,now
from studio.models import *
from studio.main import create_app
from studio.security import digest
from studio.domain import bind_variables,default_agent
from studio import preview_routes,connectors,payment_routes
from studio.recording import AudioTimeline
from studio.agent_tools import execute,tool_definitions


@pytest.mark.parametrize('mode,expected',[('test',('rzp_test_fixture','test-fixture-secret')),('live',('rzp_live_fixture','live-fixture-secret'))])
def test_payment_mode_selects_an_entire_matching_pair(mode,expected):
    from studio.config import Settings
    configured=Settings(_env_file=None,razorpay_mode=mode,razorpay_test_key_id='rzp_test_fixture',razorpay_test_key_secret='test-fixture-secret',razorpay_live_key_id='rzp_live_fixture',razorpay_live_key_secret='live-fixture-secret',razorpay_key_id='rzp_live_legacy',razorpay_key_secret='legacy-secret')
    assert configured.razorpay_credentials()==expected
    assert configured.capabilities()['payment_mode']==mode


def test_test_mode_cannot_fall_back_to_legacy_live_credentials():
    from studio.config import Settings
    configured=Settings(_env_file=None,razorpay_mode='test',razorpay_key_id='rzp_live_legacy',razorpay_key_secret='legacy-secret')
    assert configured.razorpay_credentials()==('','')
    assert configured.capabilities()['payments'] is False


def test_incomplete_mode_pair_does_not_mix_credentials():
    from studio.config import Settings
    configured=Settings(_env_file=None,razorpay_mode='test',razorpay_test_key_id='rzp_test_fixture',razorpay_key_id='rzp_test_legacy',razorpay_key_secret='legacy-secret')
    assert configured.razorpay_credentials()==('rzp_test_fixture','')
    assert configured.capabilities()['payments'] is False
from studio.workers import execute_job,campaign_ready_at,maintenance
from conftest import signup


PAGE={'url':'https://business.example/','name':'Gift business','title':'Gift business','text':'We sell personal gifts including brass cufflinks and watches. Engraving accepts twenty characters. Shipping is only available in India.','links':[],'offer':'Gift business sells personal gifts, cufflinks and watches.'}


def preview(client,monkeypatch):
    monkeypatch.setattr(preview_routes,'fetch_preview',AsyncMock(return_value=PAGE))
    response=client.post('/v1/public/preview',json={'url':'business.example'})
    assert response.status_code==201,response.text
    return response.json()


def test_first_value_has_no_account_and_expires(client,monkeypatch):
    result=preview(client,monkeypatch)
    assert 'studio_session' not in client.cookies
    assert 'sells personal gifts' in result['answer']['text']
    assert result['answer']['citations'][0]['url']==PAGE['url']
    assert result['elapsed_ms']<1000
    assert client.post('/v1/public/preview/question',json={'question':'What can I buy?'}).status_code==200
    assert 'token_hash' not in json.dumps(result)
    with TestClient(create_app(start_worker=False)) as other:
        assert other.post('/v1/public/preview/question',json={'question':'What can I buy?'}).status_code==410
    with session_scope(write=True) as db:
        db.scalar(select(Preview)).expires_at=now()-timedelta(seconds=1)
    assert client.get('/v1/public/preview').status_code==410


def test_preview_social_turns_and_missing_evidence_are_not_cited(client,monkeypatch):
    preview(client,monkeypatch)
    for question in ['hi', ' Hi! ', 'HELLO 👋', 'hey there', 'good morning', 'hiii', 'thanks', 'Thank you!']:
        response=client.post('/v1/public/preview/question',json={'question':question})
        assert response.status_code==200,response.text
        answer=response.json()
        assert answer['mode']=='conversation'
        assert answer['citations']==[]
        assert "couldn't verify" not in answer['text']
    missing=client.post('/v1/public/preview/question',json={'question':'Explain quantum teleportation'}).json()
    assert missing['mode']=='not-found' and missing['citations']==[]
    fact=client.post('/v1/public/preview/question',json={'question':'What is the engraving limit?'}).json()
    assert fact['mode']=='source-excerpt'
    assert 'twenty characters' in fact['text']
    assert fact['citations'][0]['url']==PAGE['url']


@pytest.mark.parametrize('question',['Hi, what is the engraving limit?', 'Thanks! What is the engraving limit?'])
def test_preview_social_prefix_preserves_the_actual_question(question):
    answer=preview_routes.source_answer(PAGE,question)
    assert answer['mode']=='source-excerpt'
    assert 'twenty characters' in answer['text']
    assert answer['citations'][0]['url']==PAGE['url']


def test_preview_does_not_treat_hi_prefix_in_a_word_as_a_greeting():
    answer=preview_routes.source_answer(PAGE,'high frequency oscillators')
    assert answer['mode']=='not-found' and answer['citations']==[]


def test_preview_claim_preserves_knowledge_and_publishes(client,monkeypatch):
    preview(client,monkeypatch);ws=signup(client);base='/v1/workspaces/'+ws
    saved=client.post(base+'/preview/claim')
    assert saved.status_code==201,saved.text
    agent=client.get(base+'/agents/'+saved.json()['agent_id']).json()
    assert agent['published_version_id']
    assert len(agent['draft_config']['knowledge_snapshot_ids'])==1
    source=client.get(base+'/knowledge/'+saved.json()['kb_id']+'/sources').json()['items'][0]
    assert source['canonical_url']==PAGE['url'] and source['raw_object_key']
    website=client.get(base+'/website-assistants').json()['items'][0]
    assert website['agent_id']==agent['id'] and website['job']['state']=='queued'
    assert website['installation']['theme']['publishable_key'].startswith('cyne_pk_')
    assert client.post(base+'/preview/claim').status_code==410
    assert len(client.get(base+'/agents').json()['items'])==1


@pytest.mark.asyncio
async def test_preview_respects_robots_and_rejects_empty_page(monkeypatch):
    monkeypatch.setattr(preview_routes,'safe_fetch',AsyncMock(return_value=('https://site.example/robots.txt',b'User-agent: *\nDisallow: /','text/plain')))
    with pytest.raises(HTTPException) as exc:await preview_routes.fetch_preview('https://site.example/')
    assert exc.value.status_code==422


def test_preview_rejects_foreign_origin(client,monkeypatch):
    monkeypatch.setattr(preview_routes,'fetch_preview',AsyncMock(return_value=PAGE))
    assert client.post('/v1/public/preview',json={'url':'business.example'},headers={'Origin':'https://evil.example'}).status_code==403
    assert not preview_routes.fetch_preview.called


def test_reset_is_private_once_only_and_revokes_sessions(account):
    client,ws,base=account
    response=client.post('/v1/auth/forgot-password',json={'email':'qa@example.test'})
    assert response.status_code==202 and 'token' not in response.text
    from studio.mail_outbox import process_outbox
    process_outbox(20)
    messages=list((Path(settings.data_dir)/'mail-outbox').glob('*.eml'))
    from email.parser import BytesParser
    from email.policy import default
    parsed=[BytesParser(policy=default).parsebytes(path.read_bytes()) for path in messages]
    content=next(message.get_content() for message in parsed if message['Subject']=='Reset your Phirmy password')
    token=re.search(r'token=([A-Za-z0-9_-]+)',content)[1]
    assert client.post('/v1/auth/reset-password',json={'token':token,'password':'A-New-Private-Password-2026'}).status_code==200
    assert client.get('/v1/auth/me').status_code==401
    assert client.post('/v1/auth/reset-password',json={'token':token,'password':'Another-Private-Password-2026'}).status_code==400
    assert client.post('/v1/auth/signin',json={'email':'qa@example.test','password':'A-New-Private-Password-2026'}).status_code==200
    assert client.post('/v1/auth/forgot-password',json={'email':'missing@example.test'}).json()['message']==response.json()['message']
    assert client.post('/v1/auth/forgot-password',json={'email':'invalid'}).status_code==422


def test_invitation_identity_replay_roles_and_owner_guard(account):
    client,ws,base=account
    result=client.post(base+'/invitations',json={'email':'teammate@example.test','role':'operator'})
    assert result.status_code==201,result.text
    token=result.json()['accept_url'].split('token=')[1]
    assert 'token_hash' not in client.get(base+'/invitations').text
    assert client.post('/v1/auth/accept-invitation',json={'token':token}).status_code==403
    with TestClient(create_app(start_worker=False)) as teammate:
        signup(teammate,'teammate@example.test')
        user_id=teammate.get('/v1/auth/me').json()['user']['id']
        assert teammate.post('/v1/auth/accept-invitation',json={'token':token}).status_code==200
        assert teammate.post('/v1/auth/accept-invitation',json={'token':token}).status_code==410
        assert teammate.get(base+'/calls').status_code==200
        assert teammate.post(base+'/invitations',json={'email':'outsider@example.test'}).status_code==403
        assert client.patch(base+'/members/'+user_id,json={'role':'analyst'}).status_code==200
        assert teammate.post(base+'/leads',json={'name':'Denied','evidence':'X'}).status_code==403
        assert client.delete(base+'/members/'+user_id).status_code==200
        assert teammate.get(base+'/calls').status_code==404
    owner_id=client.get('/v1/auth/me').json()['user']['id']
    assert client.delete(base+'/members/'+owner_id).status_code==409


def test_connector_secrets_encrypted_and_writes_idempotent(account,monkeypatch):
    client,ws,base=account
    monkeypatch.setattr(connectors,'test_connection',AsyncMock(return_value=None))
    connected=client.put(base+'/connections/hubspot',json={'credentials':{'access_token':'private-hubspot-token'}})
    assert connected.status_code==200 and connected.json()['state']=='connected'
    assert 'private-hubspot-token' not in client.get(base+'/connections').text
    with session_scope() as db:
        assert 'private-hubspot-token' not in db.scalar(select(ConnectorCredential)).encrypted_data
    lead=client.post(base+'/leads',json={'name':'A person','email':'person@example.test','evidence':'Requested follow-up'}).json()
    mocked=AsyncMock(return_value={'remote_id':'crm-123','status':'synced'})
    monkeypatch.setattr(connectors,'execute_action',mocked)
    body={'action':'sync_lead','input':{'lead_id':lead['id']}}
    for _ in range(2):
        result=client.post(base+'/connections/hubspot/actions',json=body,headers={'Idempotency-Key':'same-sync'})
        assert result.status_code==202,result.text
    assert mocked.await_count==1
    assert client.delete(base+'/connections/hubspot').json()['state']=='disconnected'
    assert client.post(base+'/connections/hubspot/actions',json=body,headers={'Idempotency-Key':'new-sync'}).status_code==409


@pytest.mark.asyncio
async def test_calendar_denies_busy_and_uses_stable_provider_id(monkeypatch):
    seen=[]
    async def mock(method,url,**kwargs):
        seen.append((method,url,kwargs))
        if 'oauth2' in url:return {'access_token':'token'}
        if method=='GET':raise HTTPException(502,'Provider request failed (HTTP 404)')
        if url.endswith('freeBusy'):return {'calendars':{'primary':{'busy':[]}}}
        return {'id':kwargs['json']['id']}
    monkeypatch.setattr(connectors,'request',mock)
    source={'id':'stable-local-appointment','title':'Meet','start_at':(now()+timedelta(days=1)).isoformat(),'end_at':(now()+timedelta(days=1,minutes=30)).isoformat(),'timezone':'Asia/Kolkata'}
    credentials={'client_id':'id','client_secret':'secret','refresh_token':'refresh'}
    first=await connectors.execute_action('google_calendar','sync_appointment',credentials,source,'appointment-identity')
    second=await connectors.execute_action('google_calendar','sync_appointment',credentials,source,'different-operator-request')
    assert first['remote_id']==second['remote_id']
    async def busy(method,url,**kwargs):
        if 'oauth2' in url:return {'access_token':'token'}
        if method=='GET':raise HTTPException(502,'Provider request failed (HTTP 404)')
        return {'calendars':{'primary':{'busy':[{'start':'occupied'}]}}}
    monkeypatch.setattr(connectors,'request',busy)
    with pytest.raises(HTTPException) as exc:await connectors.execute_action('google_calendar','sync_appointment',credentials,source,'id')
    assert exc.value.status_code==409
    async def unknown(method, url, **kwargs):
        if 'oauth2' in url:return {'access_token': 'token'}
        if method == 'GET':raise HTTPException(502, 'Provider request failed (HTTP 404)')
        assert url.endswith('freeBusy'), 'Unknown availability must never create an event'
        return {'calendars': {}}
    monkeypatch.setattr(connectors, 'request', unknown)
    with pytest.raises(HTTPException) as exc:await connectors.execute_action('google_calendar', 'sync_appointment', credentials, source, 'unknown')
    assert exc.value.status_code == 409


def test_capture_webhook_credits_once_and_rejects_tampering(account,monkeypatch,tmp_path):
    client,ws,base=account
    from billing_fakes import enable_checkout,PROFILE
    enable_checkout(monkeypatch,tmp_path)
    assert client.put(base+'/billing/profile',json=PROFILE).status_code==200
    quote_token=client.get(base+'/billing/quote?amount_minor=10000').json()['quote_token']
    for key,value in {'live_payments_enabled':True,'razorpay_key_id':'test_id','razorpay_key_secret':'test_secret','razorpay_webhook_secret':'webhook_secret'}.items():monkeypatch.setattr(settings,key,value)
    mock=AsyncMock(return_value={'id':'order_qa','amount':11800,'currency':'INR'})
    monkeypatch.setattr(payment_routes,'provider',mock)
    order=client.post(base+'/payments/orders',json={'amount_minor':10000,'quote_token':quote_token},headers={'Idempotency-Key':'purchase-one'})
    assert order.status_code==201,order.text
    assert client.post(base+'/payments/orders',json={'amount_minor':10000,'quote_token':quote_token},headers={'Idempotency-Key':'purchase-one'}).status_code==201
    assert mock.await_count==1
    payment={'id':'pay_qa','order_id':'order_qa','status':'captured','amount':11800,'currency':'INR'}
    event={'event':'payment.captured','payload':{'payment':{'entity':payment}}}
    body=json.dumps(event).encode();signature=hmac.new(b'webhook_secret',body,hashlib.sha256).hexdigest()
    for _ in range(2):assert client.post('/v1/provider-webhooks/razorpay',content=body,headers={'X-Razorpay-Signature':signature,'X-Razorpay-Event-Id':'event_capture_fixture','Content-Type':'application/json'}).status_code==200
    assert client.get(base+'/wallet').json()['balance_minor']==10000
    from studio.billing_inbox import process_inbox
    asyncio.run(process_inbox());asyncio.run(process_inbox())
    assert client.get(base+'/wallet').json()['balance_minor']==20000
    assert client.post('/v1/provider-webhooks/razorpay',content=body+b' ',headers={'X-Razorpay-Signature':signature}).status_code==401
    with session_scope() as db:assert len(list(db.scalars(select(Ledger).where(Ledger.operation_key=='razorpay:order_qa'))))==1


def test_uncaptured_payment_never_credits(account,monkeypatch):
    client,ws,base=account
    with session_scope(write=True) as db:db.add(PaymentOrder(workspace_id=ws,amount_minor=10000,provider_order_id='order_unpaid',operation_key='unpaid',state='created'))
    with session_scope(write=True) as db:
        with pytest.raises(HTTPException):payment_routes.credit_capture(db,{'id':'payment','order_id':'order_unpaid','amount':10000,'currency':'INR','status':'authorized'})
    assert client.get(base+'/wallet').json()['balance_minor']==10000


def test_recording_stereo_download_expiry_and_retention(sample):
    client,ws,base,fixture=sample
    version=client.get(base+'/agents/'+fixture['agent_id']).json()['published_version_id']
    with session_scope(write=True) as db:
        call=Call(workspace_id=ws,agent_version_id=version);db.add(call);db.flush();call_id=call.id
    recording=AudioTimeline({'recording':{'enabled':True,'retention_days':1},'behavior':{'max_connected_seconds':10}})
    recording.started-=.05
    pcm=np.arange(320,dtype=np.int16).tobytes();recording.add(pcm,16000,0);recording.add(pcm,16000,1);recording.finish(ws,call_id)
    row=client.get(base+'/recordings').json()['items'][0]
    assert 'object_key' not in row
    response=client.get(base+'/recordings/'+row['id']+'/audio')
    assert response.status_code==200
    with wave.open(io.BytesIO(response.content)) as audio:assert audio.getnchannels()==2 and audio.getframerate()==16000
    with session_scope(write=True) as db:db.get(Recording,row['id']).expires_at=now()-timedelta(seconds=1)
    assert client.get(base+'/recordings/'+row['id']+'/audio').status_code==410
    asyncio.run(maintenance())
    with session_scope() as db:assert db.get(Recording,row['id']).deleted_at is not None


@pytest.mark.asyncio
async def test_tools_enforce_consent_tenant_identity_and_booking(sample):
    client,ws,base,fixture=sample
    from studio.models import Conversation
    from studio.tool_safety import confirmation_text, execute_confirmation, mark_presented
    with session_scope(write=True) as db:
        conversation=Conversation(workspace_id=ws);db.add(conversation);db.flush();conversation_id=conversation.id
    context={'workspace_id':ws,'conversation_id':conversation_id,'operation_id':'lead-turn','user_text':'I am interested'}
    assert 'error' in execute('capture_lead',{'name':'A','email':'invented@example.test','phone':''},context)
    context['user_text']='Contact me at actual@example.test for a follow-up'
    args={'name':'A','email':'actual@example.test','phone':''}
    proposal=execute('capture_lead',args,context)['confirmation']
    readback=confirmation_text(proposal);mark_presented(context,proposal['id'],readback)
    confirmed_context={**context,'user_text':'Confirm request','last_assistant_text':readback}
    first=await execute_confirmation({},confirmed_context,proposal['id']);second=await execute_confirmation({},confirmed_context,proposal['id'])
    assert first['result']['lead_id']==second['result']['lead_id']
    with session_scope() as db:assert len(list(db.scalars(select(Lead))))==1
    start=now()+timedelta(days=1)
    booking={'title':'Customer meeting','start':start.isoformat(),'end':(start+timedelta(minutes=30)).isoformat(),'timezone':'Asia/Kolkata'}
    context.update(operation_id='book-turn',user_text='Book an appointment with me tomorrow at the agreed time')
    proposal=execute('book_appointment',booking,context)['confirmation']
    readback=confirmation_text(proposal);mark_presented(context,proposal['id'],readback)
    confirmed_context={**context,'user_text':'Confirm request','last_assistant_text':readback}
    result=(await execute_confirmation({},confirmed_context,proposal['id']))['result']
    assert result['state']=='local' and result['remote_calendar_synced'] is False
    assert (await execute_confirmation({},confirmed_context,proposal['id']))['result']['appointment_id']==result['appointment_id']
    context['operation_id']='other-book-turn'
    proposal=execute('book_appointment',booking,context)['confirmation']
    readback=confirmation_text(proposal);mark_presented(context,proposal['id'],readback)
    conflict=await execute_confirmation({},{**context,'user_text':'Confirm request','last_assistant_text':readback},proposal['id'])
    assert 'error' in conflict['result']
    with session_scope() as db:assert len(list(db.scalars(select(Appointment))))==1


def test_runtime_variables_required_and_no_mutation():
    config=default_agent();config['greeting']='Hi {{name}}';config['variables']=[{'name':'name','required':True,'default':None,'description':''}]
    with pytest.raises(HTTPException):bind_variables(config,{})
    assert bind_variables(config,{'name':'Ada'})['greeting']=='Hi Ada'
    assert config['greeting']=='Hi {{name}}'


def test_campaign_concurrency_and_bounded_retry(sample):
    client,ws,base,fixture=sample
    version=client.get(base+'/agents/'+fixture['agent_id']).json()['published_version_id']
    campaign=client.post(base+'/campaigns',json={'name':'Parallel','agent_version_id':version,'concurrency':3,'max_attempts':2,'budget_minor':3000,'retry_delay_seconds':30}).json()
    client.post(base+'/campaigns/'+campaign['id']+'/contacts',json={'dry_run':False,'contacts':[{'phone':'+12025550123'},{'phone':'+12025550124'},{'phone':'+12025550125'}]})
    client.post(base+'/campaigns/'+campaign['id']+'/start')
    job=next(x for x in client.get(base+'/jobs').json()['items'] if x['kind']=='campaign')
    # One prior busy result can be retried, without redoing completed contacts.
    with session_scope(write=True) as db:
        call=Call(workspace_id=ws,agent_version_id=version,state='busy',ended_at=now()-timedelta(minutes=2));db.add(call);db.flush()
        db.add(Attempt(workspace_id=ws,campaign_id=campaign['id'],contact_identity=hashlib.sha256(b'+12025550123').hexdigest(),attempt_index=1,state='failed',outcome='busy',call_id=call.id))
    asyncio.run(execute_job(job['id']))
    assert client.get(base+'/campaigns/'+campaign['id']).json()['state']=='completed'
    rows=client.get(base+'/campaigns/'+campaign['id']+'/attempts').json()['items']
    assert len(rows)==4 and sum(x['attempt_index']==2 for x in rows)==1


def test_csv_export_neutralizes_formula_and_tenant_boundary(account):
    client,ws,base=account
    client.post(base+'/leads',json={'name':'=HYPERLINK("bad")','evidence':'Manual contact'})
    response=client.get(base+'/exports/leads')
    assert response.status_code==200 and "'=HYPERLINK" in response.text
    assert client.get(base+'/exports/unknown').status_code==404

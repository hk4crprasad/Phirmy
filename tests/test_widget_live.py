import json
import pytest
from sqlalchemy import select, func
from studio.config import settings
from studio.db import session_scope, uid
from studio.models import Conversation, Message, Lead, Membership
from studio import chat_routes


def start(sample, **values):
    client, ws, base, fixture = sample
    row = client.get(base+'/installations').json()['items'][0]
    response = client.post('/v1/public/sessions',headers={'Origin':settings.app_origin},json={'installation_public_id':row['public_id'],'visitor_email':'visitor@example.test',**values})
    assert response.status_code == 201, response.text
    state = response.json()
    return state, {'Origin':settings.app_origin,'Authorization':'Bearer '+state['session_token']}


def test_email_gate_and_explicit_marketing_evidence(sample):
    client, ws, base, fixture = sample
    row = client.get(base+'/installations').json()['items'][0]
    from studio.models import Installation
    with session_scope(write=True) as db:
        installation=db.get(Installation,row['id']);installation.theme={**installation.theme,'collect_email':True}
    for email in [None,'invalid','<bad>@']:
        assert client.post('/v1/public/sessions',headers={'Origin':settings.app_origin},json={'installation_public_id':row['public_id'],'visitor_email':email}).status_code == 422
    state, headers = start(sample, marketing_opt_in=True)
    assert state['lead_captured']
    data=client.get(base+'/conversations/'+state['id']+'/messages').json()
    assert data['visitor']['email']=='visitor@example.test' and 'marketing_opt_in' not in data['visitor']
    leads=client.get(base+'/leads').json()['items']
    assert len(leads)==1 and json.loads(leads[0]['evidence'])['email_verified'] is False
    before=len(leads)
    assert client.post('/v1/public/sessions/resume',headers={**headers,'Authorization':'Bearer '+state['resume_token']}).status_code==200
    assert len(client.get(base+'/leads').json()['items'])==before
    second,_=start(sample)
    assert 'marketing_opt_in' not in client.get(base+'/conversations/'+second['id']+'/messages').json()['visitor']
    kinds={row['kind'] for row in client.get(base+'/notifications').json()['items']}
    assert {'lead.created','conversation.started'} <= kinds


def test_operator_takeover_reply_idempotence_and_resume_ai(sample,monkeypatch):
    client, ws, base, fixture=sample
    state, headers=start(sample)
    path=base+'/conversations/'+state['id']
    assert client.post(path+'/messages',json={'text':'Hi','client_message_id':'r1'}).status_code==409
    result=client.patch(path+'/mode',json={'mode':'human'})
    assert result.status_code==200 and result.json()['assigned_user_id']
    async def forbidden(*args,**kwargs):
        raise AssertionError('AI must remain paused')
        yield ''
    monkeypatch.setattr(chat_routes,'answer_stream',forbidden)
    response=client.post('/v1/public/chat',headers=headers,json={'session_id':state['id'],'message':'Can you help?','client_message_id':'visitor1'})
    assert 'chat.human_queued' in response.text and 'chat.text.delta' not in response.text
    reply={'text':'Yes, I can help you personally.','client_message_id':'r1'}
    first=client.post(path+'/messages',json=reply)
    assert first.status_code==201
    assert client.post(path+'/messages',json=reply).json()['id']==first.json()['id']
    assert client.post(path+'/messages',json={**reply,'text':'different'}).status_code==409
    visitor=client.get('/v1/public/conversation',headers=headers)
    assert visitor.status_code==200 and visitor.json()['items'][-1]['role']=='operator'
    assert len(visitor.json()['items'])==2
    assert client.get('/v1/public/conversation',headers={**headers,'Origin':'https://wrong.test'}).status_code==403
    assert client.patch(path+'/mode',json={'mode':'open'}).json()['assigned_user_id'] is None
    assert client.patch(path+'/mode',json={'mode':'resolved'}).status_code==200
    assert client.post('/v1/public/chat',headers=headers,json={'session_id':state['id'],'message':'Closed?','client_message_id':'v2'}).status_code==409
    assert client.patch('/v1/workspaces/foreign/conversations/'+state['id']+'/mode',json={'mode':'human'}).status_code==404


def test_inflight_generation_stops_on_takeover(sample,monkeypatch):
    client, ws, base, fixture=sample
    state, headers=start(sample)
    async def answer(*args,**kwargs):
        yield 'Partial answer'
        with session_scope(write=True) as db:
            db.get(Conversation,state['id']).state='human'
        yield 'THIS MUST NOT REACH THE VISITOR'
    monkeypatch.setattr(chat_routes,'answer_stream',answer)
    response=client.post('/v1/public/chat',headers=headers,json={'session_id':state['id'],'message':'Tell me about support','client_message_id':'inflight'})
    assert 'chat.interrupted' in response.text and 'THIS MUST NOT' not in response.text
    rows=client.get(base+'/conversations/'+state['id']+'/messages').json()['items']
    assert rows[-1]['metadata_data']['interrupted'] and not rows[-1]['metadata_data']['streaming']


def test_dictation_auth_bounds_and_provider_failures(sample,monkeypatch):
    state, headers=start(sample);client=sample[0]
    url='/v1/public/voice/transcribe'
    assert client.post(url,headers=headers,content=b'audio').status_code==409
    monkeypatch.setattr(settings,'deepgram_api_key','synthetic-key')
    assert client.post(url,headers={**headers,'Origin':'https://wrong.test','Content-Type':'audio/wav'},content=b'audio').status_code==403
    assert client.post(url,headers={**headers,'Content-Type':'text/plain'},content=b'audio').status_code==415
    assert client.post(url,headers={**headers,'Content-Type':'audio/wav'},content=b'x'*(5*1024*1024+1)).status_code==413


@pytest.mark.sandbox
def test_dictation_uses_real_decoder_before_forwarding_canonical_audio(sample,monkeypatch):
    state, headers=start(sample);client=sample[0]
    url='/v1/public/voice/transcribe'
    monkeypatch.setattr(settings,'deepgram_api_key','synthetic-key')
    import httpx
    requests=[]
    async def post(self,url,**kwargs):
        requests.append(kwargs)
        return httpx.Response(200,request=httpx.Request('POST',url),json={'results':{'channels':[{'alternatives':[{'transcript':'Show me the collection.'}]}]}})
    monkeypatch.setattr(httpx.AsyncClient,'post',post)
    import io,wave
    audio=io.BytesIO()
    with wave.open(audio,'wb') as output:
        output.setnchannels(1);output.setsampwidth(2);output.setframerate(16000);output.writeframes(b'\0\0'*3200)
    result=client.post(url,headers={**headers,'Content-Type':'audio/wav'},content=audio.getvalue())
    assert result.status_code==200,result.text
    assert result.json()['text']=='Show me the collection.'
    assert requests[0]['headers']['Authorization']=='Token synthetic-key'
    assert requests[0]['headers']['Content-Type']=='audio/wav' and requests[0]['content'].startswith(b'RIFF')
    assert 'synthetic-key' not in result.text


def test_operator_permissions_and_assignment_lock(sample):
    client, ws, base, fixture=sample
    state, headers=start(sample);path=base+'/conversations/'+state['id']
    assert client.patch(path+'/mode',json={'mode':'human'}).status_code==200
    # A second authenticated operator may read but cannot steal/reply/release it.
    from conftest import bootstrap_account
    response=bootstrap_account(client, '/v1/auth/signup',json={'name':'Other operator','email':'operator@example.test','password':'Long-Test-Operator-Password','workspace_name':'Other workspace'})
    assert response.status_code==200
    client.headers['X-CSRF-Token']=client.cookies['studio_csrf']
    assert client.get(path+'/messages').status_code==404
    with session_scope(write=True) as db:db.add(Membership(workspace_id=ws,user_id=response.json()['user']['id'],role='operator'))
    assert client.get(path+'/messages').status_code==200
    assert client.patch(path+'/mode',json={'mode':'human'}).status_code==409
    assert client.patch(path+'/mode',json={'mode':'open'}).status_code==403
    assert client.post(path+'/messages',json={'text':'Not assigned','client_message_id':'second'}).status_code==409
    with session_scope(write=True) as db:
        member=db.scalar(select(Membership).where(Membership.workspace_id==ws,Membership.user_id==response.json()['user']['id']));member.role='builder'
    assert client.patch(path+'/mode',json={'mode':'human'}).status_code==403


def test_interrupted_reply_retry_keeps_one_message(sample,monkeypatch):
    client, ws, base, fixture=sample;state,headers=start(sample)
    async def answer(*args,**kwargs):
        yield 'Partial'
        with session_scope(write=True) as db:db.get(Conversation,state['id']).state='human'
        yield 'Stop'
    monkeypatch.setattr(chat_routes,'answer_stream',answer)
    body={'session_id':state['id'],'message':'Please help me','client_message_id':'retry-interrupted'}
    assert 'chat.interrupted' in client.post('/v1/public/chat',headers=headers,json=body).text
    assert client.patch(base+'/conversations/'+state['id']+'/mode',json={'mode':'open'}).status_code==200
    assert 'chat.completed' in client.post('/v1/public/chat',headers=headers,json=body).text
    assert client.post('/v1/public/chat',headers=headers,json={**body,'message':'changed'}).status_code==409
    with session_scope() as db:assert db.scalar(select(func.count()).select_from(Message).where(Message.conversation_id==state['id'],Message.role=='assistant'))==1


@pytest.mark.parametrize('method',['get','post'])
def test_conversation_refresh_requires_the_signed_origin(sample,method):
    state,headers=start(sample);client=sample[0]
    refresh=getattr(client,method)
    assert refresh('/v1/public/conversation',headers=headers).status_code==200
    assert refresh('/v1/public/conversation',headers={'Authorization':headers['Authorization']}).status_code==403
    assert refresh('/v1/public/conversation',headers={**headers,'Origin':'https://other.example'}).status_code==403


@pytest.mark.parametrize('origin',['null','http://localhost:5555','https://unlisted.example'])
def test_keyed_widget_cannot_bypass_origin_proof_with_unlisted_or_opaque_origin(sample,origin):
    client,ws,base,fixture=sample
    row=client.post(base+'/installations',json={'name':'Portable embed','agent_id':fixture['agent_id'],'allowed_origins':['https://production.example']}).json()
    url='/v1/public/installations/'+row['public_id'];key=row['theme']['publishable_key']
    assert client.post(url,headers={'Origin':origin},params={'public_key':key}).status_code==403
    assert client.post(url,headers={'Origin':origin},params={'public_key':'wrong'}).status_code==403
    response=client.post('/v1/public/sessions',headers={'Origin':origin},json={'installation_public_id':row['public_id'],'public_key':key,'visitor_email':'tester@example.test'})
    assert response.status_code==403,response.text
    from studio.models import Installation
    with session_scope(write=True) as db:
        item=db.get(Installation,row['id']);item.theme={**item.theme,'restrict_origins':True}
    assert client.post(url,headers={'Origin':origin},params={'public_key':key}).status_code==403

import asyncio
import hashlib
import json
from datetime import timedelta
from types import SimpleNamespace as N
from unittest.mock import AsyncMock
import httpcore
import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from twilio.request_validator import RequestValidator
from studio import http_tools,llm,model_routes,twilio_routes
from studio.config import settings
from studio.db import session_scope,now
from studio.models import HTTPTool,HTTPToolVersion,ToolExecution,Call,LLMProfile
from studio.llm import Turn,options,environment_profile
from studio.network import PublicBackend
from studio.security import capability


def payload(**extra):
    return {'name':'lookup_order','description':'Look up an order when the customer asks for order status.','url':'https://api.example.test/orders/{{order_id}}','method':'POST','arguments':{'type':'object','properties':{'order_id':{'type':'string'}},'required':['order_id'],'additionalProperties':False},'body_template':{'id':'{{order_id}}'},'headers':{'Authorization':'Bearer sensitive-secret-value'},'side_effecting':False,**extra}


def create_tool(account,monkeypatch,**extra):
    client,ws,base=account
    monkeypatch.setattr(http_tools,'validate_public_url',AsyncMock())
    result=client.post(base+'/tools',json=payload(**extra))
    assert result.status_code==201,result.text
    return result.json()


def test_curl_import_never_executes_and_declares_arguments(account):
    client,ws,base=account
    response=client.post(base+'/tools/import-curl',json={'text':'''curl -X POST https://api.example.test/orders -H 'Content-Type: application/json' -d '{"id":"{{order_id}}"}' '''})
    assert response.status_code==200
    assert response.json()['method']=='POST'
    assert 'order_id' in response.json()['arguments']['properties']
    for invalid in ['curl https://api.example.test -d @/etc/passwd','curl https://api.example.test -o /tmp/unsafe','curl https://api.example.test ; touch /tmp/unsafe']:
        assert client.post(base+'/tools/import-curl',json={'text':invalid}).status_code==422


def test_tool_headers_write_only_and_revisions_immutable(account,monkeypatch):
    client,ws,base=account;tool=create_tool(account,monkeypatch)
    assert tool['headers']=={'Authorization':None} and tool['has_secret'] is True
    assert 'sensitive-secret-value' not in client.get(base+'/tools').text
    changed=payload(description='New behavior',headers=None)
    assert client.put(base+'/tools/'+tool['id'],json=changed).json()['revision']==2
    with session_scope() as db:
        rows=list(db.scalars(select(HTTPToolVersion).where(HTTPToolVersion.tool_id==tool['id']).order_by(HTTPToolVersion.revision)))
        assert len(rows)==2 and rows[0].description!=rows[1].description
        assert 'sensitive-secret-value' not in rows[0].encrypted_headers


def test_tool_template_types_url_encoding_and_schema_guards(account,monkeypatch):
    client,ws,base=account
    assert http_tools.render({'count':'{{n}}','name':'Hello {{name}}'},{'n':3,'name':'Ada "x"'})=={'count':3,'name':'Hello Ada "x"'}
    assert http_tools.render('https://api.example.test/{{value}}',{'value':'../?a=2'},url=True).endswith('..%2F%3Fa%3D2')
    monkeypatch.setattr(http_tools,'validate_public_url',AsyncMock())
    assert client.post(base+'/tools',json=payload(url='https://{{host}}/orders')).status_code==422
    assert client.post(base+'/tools',json=payload(arguments={'type':'object','$ref':'http://169.254.169.254/'})).status_code==422
    assert client.post(base+'/tools',json=payload(headers={'Host':'internal'})).status_code==422


def test_tool_dry_run_no_network_and_attachment_publish(sample,monkeypatch):
    client,ws,base,fixture=sample
    tool=create_tool((client,ws,base),monkeypatch,mock_response={'status':'example'})
    result=client.post(base+'/tools/'+tool['id']+'/test',json={'arguments':{'order_id':'ORD-1'},'mock':True},headers={'Idempotency-Key':'mock'})
    assert result.status_code==200 and result.json()['state']=='mock' and result.json()['external_request'] is False
    assert client.put(base+'/tools/'+tool['id']+'/access',json={'agent_ids':[fixture['agent_id']]}).status_code==200
    agent=client.get(base+'/agents/'+fixture['agent_id']).json()
    assert client.post(base+'/agents/'+agent['id']+'/publish',json={'expected_draft_revision':agent['draft_revision']}).status_code==201
    config=client.get(base+'/agents/'+agent['id']+'/versions').json()['items'][0]['config']
    assert http_tools.attached_definitions(config,ws)[0]['name']=='lookup_order'
    assert client.delete(base+'/tools/'+tool['id']).status_code==200
    assert http_tools.attached_definitions(config,ws)==[]


def test_tool_background_is_durable_and_argument_checked(account,monkeypatch):
    client,ws,base=account;tool=create_tool(account,monkeypatch,execution_mode='background')
    url=base+'/tools/'+tool['id']+'/test'
    assert client.post(url,json={'arguments':{'unexpected':1}},headers={'Idempotency-Key':'bad'}).status_code==422
    first=client.post(url,json={'arguments':{'order_id':'ORD-1'}},headers={'Idempotency-Key':'stable'})
    assert first.status_code==200 and first.json()['state']=='queued' and first.json()['completion_confirmed'] is False
    second=client.post(url,json={'arguments':{'order_id':'ORD-1'}},headers={'Idempotency-Key':'stable'})
    assert second.json()['id']==first.json()['id']
    assert client.post(url,json={'arguments':{'order_id':'ORD-2'}},headers={'Idempotency-Key':'stable'}).status_code==409
    with session_scope() as db:assert len(list(db.scalars(select(ToolExecution))))==1


@pytest.mark.asyncio
async def test_actual_tool_execution_pins_revision_redacts_and_deduplicates(account,monkeypatch):
    client,ws,base=account;tool=create_tool(account,monkeypatch)
    requests=[]
    def endpoint(request):
        requests.append(request)
        assert request.headers['Authorization']=='Bearer sensitive-secret-value'
        assert json.loads(request.content)=={'id':'ORD-1'}
        return httpx.Response(200,json={'status':'shipped','echo':'Bearer sensitive-secret-value'})
    monkeypatch.setattr(http_tools,'PublicTransport',lambda:httpx.MockTransport(endpoint))
    # A later edit must not change an already published tool revision.
    assert client.put(base+'/tools/'+tool['id'],json=payload(url='https://changed.example.test',headers={'Authorization':'Bearer new-secret'})).status_code==200
    result=await http_tools.invoke(ws,tool['id'],1,{'order_id':'ORD-1'},{},'execution-1')
    assert result['state']=='succeeded' and result['result']['response']['status']=='shipped'
    assert 'sensitive-secret-value' not in json.dumps(result)
    assert str(requests[0].url)=='https://api.example.test/orders/ORD-1'
    replay=await http_tools.invoke(ws,tool['id'],1,{'order_id':'ORD-1'},{},'execution-1')
    assert replay['id']==result['id'] and len(requests)==1
    with pytest.raises(HTTPException) as conflict:await http_tools.invoke(ws,tool['id'],2,{'order_id':'ORD-1'},{},'execution-1')
    assert conflict.value.status_code==409
    assert http_tools.redact({'nested':['quoted "secret" value']},['"secret"'])=={'nested':['quoted [redacted] value']}


@pytest.mark.asyncio
async def test_stream_failure_after_text_never_replays(monkeypatch):
    import openai
    class BrokenStream(FakeStream):
        async def iterate(self):
            yield N(choices=[N(finish_reason=None,delta=N(content='Partial',tool_calls=[]))])
            raise httpx.ReadError('Lost stream')
    create=AsyncMock(return_value=BrokenStream([]))
    class Client:
        def __init__(self,**kwargs):self.chat=N(completions=N(create=create))
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
    monkeypatch.setattr(openai,'AsyncOpenAI',Client)
    profile={'api_key':'fake','base_url':'https://compatible.example/v1','model':'model','api_style':'chat_completions','token_parameter':'max_tokens','options':{}}
    output=[]
    with pytest.raises(httpx.ReadError):
        async for delta in Turn(profile,'Test',[{'role':'user','content':'Hi'}]).stream():output.append(delta)
    assert output==['Partial'] and create.await_count==1


@pytest.mark.asyncio
async def test_responses_tool_results_keep_call_identity(monkeypatch):
    import openai
    call=N(type='function_call',call_id='function-1',name='lookup_order',arguments='{"order_id":"123"}')
    create=AsyncMock(return_value=FakeStream([N(type='response.completed',response=N(output=[call]))]))
    class Client:
        def __init__(self,**kwargs):self.responses=N(create=create)
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
    monkeypatch.setattr(openai,'AsyncOpenAI',Client)
    profile={'api_key':'fake','base_url':'https://api.openai.com/v1','model':'model','api_style':'responses','token_parameter':'max_output_tokens','options':{}}
    messages=[{'role':'user','content':'Where is 123?'}]
    turn=Turn(profile,'Test',messages,limit=1200)
    assert [x async for x in turn.stream()]==[]
    turn.append_results([{'status':'shipped'}])
    assert messages[-1]['type']=='function_call_output' and messages[-1]['call_id']=='function-1'
    assert create.await_args.kwargs['max_output_tokens']==1200


@pytest.mark.asyncio
async def test_media_watcher_honors_persisted_stop_without_input(sample):
    from studio.media import VoiceSession
    from studio.domain import default_agent
    client,ws,base,fixture=sample
    with session_scope(write=True) as db:
        call=Call(workspace_id=ws,mode='simulation',transport='browser',state='ending')
        db.add(call);db.flush();call_id=call.id
    socket=N(close=AsyncMock())
    session=VoiceSession(socket,ws,call_id,default_agent(),'simulation')
    await asyncio.wait_for(session.watch_idle(),3)
    socket.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_slow_dispatch_database_does_not_block_media_loop(monkeypatch):
    import threading,time
    from studio import workers
    entered=threading.Event();release=threading.Event();stop=asyncio.Event()
    entered_at=[]
    def slow_database(**kwargs):
        entered_at.append(time.monotonic())
        entered.set();release.wait(2);return None,None
    monkeypatch.setattr(workers,'maintenance',AsyncMock())
    monkeypatch.setattr(workers,'claim_dispatch',slow_database)
    task=asyncio.create_task(workers.worker_loop(stop))
    try:
        # A synchronous dispatcher would freeze this coroutine until release times out.
        while not entered.is_set():await asyncio.sleep(.005)
        await asyncio.sleep(.02)
        # Measure responsiveness while dispatch is blocked, excluding unrelated
        # heartbeat/outbox initialization before the injected query starts.
        assert time.monotonic()-entered_at[0]<.5
    finally:
        stop.set();release.set();await asyncio.wait_for(task,3)


@pytest.mark.asyncio
async def test_public_socket_resolution_pins_address_and_blocks_rebinding(monkeypatch):
    backend=N(connect_tcp=AsyncMock(return_value='socket'))
    monkeypatch.setattr('socket.getaddrinfo',lambda *a,**kw:[(2,1,6,'',('8.8.8.8',443))])
    assert await PublicBackend(backend).connect_tcp('site.example',443)=='socket'
    assert backend.connect_tcp.await_args.args[0]=='8.8.8.8'
    backend.connect_tcp.reset_mock()
    monkeypatch.setattr('socket.getaddrinfo',lambda *a,**kw:[(2,1,6,'',('127.0.0.1',443))])
    with pytest.raises(httpcore.ConnectError):await PublicBackend(backend).connect_tcp('site.example',443)
    assert not backend.connect_tcp.called


def test_api_specific_token_options_and_temperature_omission(monkeypatch):
    monkeypatch.setattr(settings,'openai_base_url','https://api.openai.com/v1')
    p=environment_profile('gpt-5.6-luna')
    assert p['api_style']=='responses' and 'max_output_tokens' in options(p,1200)
    assert 'temperature' not in options(p,1200)
    monkeypatch.setattr(settings,'openai_base_url','https://compatible.example/v1')
    p=environment_profile('custom-model')
    assert p['api_style']=='chat_completions' and options(p,100)=={'max_tokens':100}


class FakeStream:
    def __init__(self,events):self.events=events
    async def __aenter__(self):return self
    async def __aexit__(self,*args):pass
    def __aiter__(self):return self.iterate()
    async def iterate(self):
        for item in self.events:yield item


@pytest.mark.asyncio
async def test_compatible_stream_fragments_and_tool_round_trip(monkeypatch):
    import openai
    events=[N(choices=[N(finish_reason=None,delta=N(content=None,tool_calls=[N(index=0,id='call1',function=N(name='lookup_',arguments='{"order_'))]))]),N(choices=[N(finish_reason=None,delta=N(content=None,tool_calls=[N(index=0,id=None,function=N(name='order',arguments='id":"123"}'))]))]),N(choices=[N(finish_reason='tool_calls',delta=N(content=None,tool_calls=[]))])]
    create=AsyncMock(return_value=FakeStream(events))
    class Client:
        def __init__(self,**kwargs):self.chat=N(completions=N(create=create))
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
    monkeypatch.setattr(openai,'AsyncOpenAI',Client)
    profile={'api_key':'fake','base_url':'https://compatible.example/v1','model':'model','api_style':'chat_completions','token_parameter':'max_tokens','options':{}}
    messages=[{'role':'user','content':'Where is 123?'}]
    turn=Turn(profile,'Be helpful',messages)
    assert [x async for x in turn.stream()]==[]
    assert turn.calls==[{'id':'call1','name':'lookup_order','arguments':'{"order_id":"123"}'}]
    turn.append_results([{'state':'shipped'}])
    assert messages[-1]['role']=='tool' and messages[-1]['tool_call_id']=='call1'
    assert 'temperature' not in create.await_args.kwargs


@pytest.mark.asyncio
async def test_parameter_negotiation_only_before_streaming(monkeypatch):
    import openai
    response=httpx.Response(400,request=httpx.Request('POST','https://compatible.example/v1/chat/completions'))
    bad=openai.BadRequestError('Unsupported parameter max_tokens; use max_completion_tokens',response=response,body={'error':{'message':'Unsupported parameter max_tokens'}})
    create=AsyncMock(side_effect=[bad,FakeStream([N(choices=[N(finish_reason=None,delta=N(content='OK',tool_calls=[]))]),N(choices=[N(finish_reason='stop',delta=N(content=None,tool_calls=[]))])])])
    class Client:
        def __init__(self,**kwargs):self.chat=N(completions=N(create=create))
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
    monkeypatch.setattr(openai,'AsyncOpenAI',Client)
    profile={'api_key':'fake','base_url':'https://compatible.example/v1','model':'model','api_style':'chat_completions','token_parameter':'max_tokens','options':{}}
    turn=Turn(profile,'Test',[{'role':'user','content':'Hi'}])
    assert ''.join([x async for x in turn.stream()])=='OK'
    assert create.await_count==2
    assert 'max_completion_tokens' in create.await_args.kwargs and 'max_tokens' not in create.await_args.kwargs


def test_model_registration_fetches_docs_tests_and_hides_key(account,monkeypatch):
    client,ws,base=account
    monkeypatch.setattr(model_routes,'validate_public_url',AsyncMock())
    monkeypatch.setattr(model_routes,'safe_fetch',AsyncMock(return_value=('https://docs.example/model',b'<main>Use max_completion_tokens for this model.</main>','text/html')))
    probe=AsyncMock(return_value={'status':'passed','first_token_ms':42,'text':'OK','tools_schema_accepted':True})
    monkeypatch.setattr(model_routes,'probe',probe)
    body={'name':'My model','model':'custom','base_url':'https://compatible.example/v1','api_key':'model-private-key','api_style':'chat_completions','token_parameter':'max_completion_tokens','documentation_url':'https://docs.example/model'}
    result=client.post(base+'/models',json=body)
    assert result.status_code==201,result.text
    assert 'model-private-key' not in result.text and 'encrypted_key' not in result.text
    assert model_routes.safe_fetch.await_count==1 and probe.await_count==1
    body['token_parameter']='max_tokens'
    assert client.post(base+'/models',json=body).status_code==422


def test_twilio_signature_identity_and_callback_replay(sample,monkeypatch):
    client,ws,base,fixture=sample
    monkeypatch.setattr(settings,'twilio_account_sid','ACtest')
    monkeypatch.setattr(settings,'twilio_auth_token','twilio-test-secret')
    monkeypatch.setattr(settings,'live_calls_enabled',True)
    monkeypatch.setattr(settings,'media_public_origin','https://voice.example.test')
    version=client.get(base+'/agents/'+fixture['agent_id']).json()['published_version_id']
    with session_scope(write=True) as db:
        call=Call(workspace_id=ws,agent_version_id=version,mode='live',transport='pstn',state='connected',provider_call_id='CAtest',connected_at=now()-timedelta(seconds=10),metadata_data={'provider':'twilio'})
        db.add(call);db.flush();call_id=call.id
    path='/v1/provider-webhooks/twilio/status?call_id='+call_id
    body={'AccountSid':'ACtest','CallSid':'CAtest','CallStatus':'completed'}
    assert client.post(path,data=body).status_code==401
    signature=RequestValidator(settings.twilio_auth_token).compute_signature(settings.media_public_origin+path,body)
    for _ in range(2):assert client.post(path,data=body,headers={'X-Twilio-Signature':signature}).status_code==200
    with session_scope() as db:assert db.get(Call,call_id).state=='completed'
    assert client.post(path,data={**body,'AccountSid':'ACwrong'},headers={'X-Twilio-Signature':signature}).status_code==401


def test_carrier_answer_pins_leg_and_preserves_connected_state(sample,monkeypatch):
    from studio import carrier
    client,ws,base,fixture=sample
    monkeypatch.setattr(settings,'media_public_origin','https://voice.example.test')
    version=client.get(base+'/agents/'+fixture['agent_id']).json()['published_version_id']
    with session_scope(write=True) as db:
        call=Call(workspace_id=ws,agent_version_id=version,mode='live',transport='pstn',state='ringing',destination='+12025550123',provider_call_id='request-id',metadata_data={'provider':'plivo'})
        db.add(call);db.flush();call_id=call.id
    monkeypatch.setattr(carrier,'verified_form',AsyncMock(return_value={'CallUUID':'leg-id','To':'+12025550123'}))
    path='/v1/provider-webhooks/plivo/answer?call_id='+call_id
    first=client.post(path)
    assert first.status_code==200 and 'wss://voice.example.test/v1/carrier-media/' in first.text
    with session_scope(write=True) as db:
        call=db.get(Call,call_id);assert call.provider_call_id=='leg-id';call.state='connected'
    assert client.post(path).status_code==200
    with session_scope() as db:assert db.get(Call,call_id).state=='connected'
    monkeypatch.setattr(carrier,'verified_form',AsyncMock(return_value={'CallUUID':'another-leg','To':'+12025550123'}))
    assert client.post(path).status_code==403


@pytest.mark.parametrize('environment',['production','test'])
@pytest.mark.parametrize('profile',[{}, {'model':None}, {'model':''}, {'model':'   '}, {'model':12}])
def test_incomplete_model_profile_fails_clearly_before_provider_use_without_an_invented_default(monkeypatch,environment,profile):
    from unittest.mock import Mock
    import openai
    monkeypatch.setattr(settings,'app_env',environment)
    client=Mock();monkeypatch.setattr(openai,'AsyncOpenAI',client)
    with pytest.raises(HTTPException,match='nonempty model identifier') as error:
        Turn({**profile,'api_key':'synthetic'},'System',[])
    assert error.value.status_code==409
    client.assert_not_called()


def test_declared_fake_model_identity_is_preserved_in_billing_context():
    turn=Turn({'model':'explicit-synthetic-model','api_key':'synthetic'},'System',[])
    assert turn.billing_context['model']=='explicit-synthetic-model'

import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from cryptography.fernet import Fernet
from sqlalchemy import select,text,update,delete,func
from sqlalchemy.exc import DBAPIError
import pytest

from studio import plans,metering,llm,media
from studio.config import settings
from studio.db import now,session_scope,uid,engine
from studio.domain import default_agent,settle_call
from studio.models import PlanCatalogSnapshot,WorkspaceSubscription,TariffSnapshot,MeterEvent,CallCostRecord,StoredObjectMeter,Call


def test_configuration_defined_plans_are_draft_closed_and_snapshotted(account,monkeypatch,tmp_path):
    client,ws,base=account;original=plans.catalog()
    public=client.get('/v1/public/plans').json()
    assert {row['id'] for row in public['items']}=={'free','starter','growth','custom'}
    assert public['status']=='DRAFT' and public['paid_activation_enabled'] is False
    assert 'provider_rates' not in public
    with session_scope(write=True) as db:
        first=metering.snapshot(db,ws,'first');first_id=first.id;first_body=first.content
    modified={key:value for key,value in original.items() if key!='content_hash'}
    modified['provider_rates']['llm_output_minor_per_million_tokens']*=2
    path=tmp_path/'plans.json';path.write_text(json.dumps(modified));monkeypatch.setattr(settings,'plans_config_path',str(path))
    with session_scope(write=True) as db:
        catalog=plans.catalog_snapshot(db)
        current=db.scalar(select(WorkspaceSubscription).where(WorkspaceSubscription.workspace_id==ws))
        current.catalog_id=catalog.id;db.flush()
        second=metering.snapshot(db,ws,'second')
        assert second.content['provider_rates']!=first_body['provider_rates']
        assert db.get(TariffSnapshot,first_id).content==first_body
    with pytest.raises(DBAPIError):
        with engine.begin() as db:db.execute(update(TariffSnapshot).where(TariffSnapshot.id==first_id).values(content={}))
    path.write_text('{"status":"DRAFT"}')
    with pytest.raises(ValueError,match='configuration'):plans.catalog()


def test_monthly_windows_follow_workspace_timezone_including_dst():
    from datetime import datetime,timezone
    start,end=plans.month_bounds(datetime(2026,3,15,tzinfo=timezone.utc),'America/New_York')
    assert start.isoformat()=='2026-03-01T05:00:00+00:00'
    assert end.isoformat()=='2026-04-01T04:00:00+00:00'


def test_draft_prices_block_checkout_even_with_legacy_live_flag(account,monkeypatch):
    client,_,base=account
    from studio import payment_routes
    for name,value in {'paid_activation_enabled':True,'live_payments_enabled':True,
                       'razorpay_key_id':'test_id','razorpay_key_secret':'fixture-secret'}.items():
        monkeypatch.setattr(settings,name,value)
    provider=AsyncMock();monkeypatch.setattr(payment_routes,'provider',provider)
    response=client.post(base+'/payments/orders',json={'amount_minor':10000},headers={'Idempotency-Key':'draft-checkout'})
    assert response.status_code==409 and 'approved prices' in response.json()['detail']
    provider.assert_not_awaited()


def test_read_only_billing_key_does_not_initialize_or_change_a_subscription(account):
    client,_,base=account
    response=client.post(base+'/keys',json={'name':'Billing reader','scopes':['billing:read']})
    assert response.status_code==201
    assert client.get(base+'/billing/usage',headers={'X-API-Key':response.json()['secret']}).status_code==200
    with session_scope() as db:
        assert db.scalar(select(func.count()).select_from(WorkspaceSubscription))==0
        assert db.scalar(select(func.count()).select_from(PlanCatalogSnapshot))==0


def test_immutable_usage_storage_balance_retry_and_release(account):
    client,ws,base=account;key=ws+'/documents/'+('a'*64)
    with session_scope(write=True) as db:
        first=metering.record_usage(db,ws,'turn-one','chat_turns',1,scope_id='conversation-one')
        identity=first.id
        assert metering.record_usage(db,ws,'turn-one','chat_turns',1,scope_id='conversation-one').id==identity
        metering.stored(db,ws,key,256);metering.stored(db,ws,key,256)
    summary=client.get(base+'/billing/usage').json()
    assert summary['usage']['chat_turns']==1 and summary['usage']['storage_bytes']==256
    with session_scope(write=True) as db:metering.removed(db,ws,key);metering.removed(db,ws,key)
    assert client.get(base+'/billing/usage').json()['usage']['storage_bytes']==0
    for statement in [update(MeterEvent).where(MeterEvent.id==identity).values(quantity=999),delete(MeterEvent).where(MeterEvent.id==identity)]:
        with pytest.raises(DBAPIError):
            with engine.begin() as db:db.execute(statement)


def test_utf8_tts_cached_llm_and_duration_cost_units_use_integer_arithmetic(account):
    _,ws,_=account;rates=plans.catalog()['provider_rates'];text_value='नमस्ते 🙂'
    with session_scope(write=True) as db:
        line=metering.record_cost(db,ws,'fish-one','fish','tts',{'tts_utf8_bytes':len(text_value.encode()),'tts_characters':len(text_value),'tts_ms':1000},call_id='synthetic-call')
        assert line.cost_micro_minor==len(text_value.encode())*rates['tts_minor_per_million_utf8_bytes']
        assert metering.record_cost(db,ws,'fish-one','fish','tts',line.units,call_id='synthetic-call').id==line.id
        identity=line.id
        model=metering.record_cost(db,ws,'llm-one','openai','llm',{'input_tokens':100,'cached_input_tokens':40,'output_tokens':5},call_id='synthetic-call')
        assert model.cost_micro_minor==60*rates['llm_input_minor_per_million_tokens']+40*rates['llm_cached_input_minor_per_million_tokens']+5*rates['llm_output_minor_per_million_tokens']
        stt=metering.record_cost(db,ws,'stt-one','deepgram','stt',{'stt_ms':1000},call_id='synthetic-call')
        assert stt.cost_micro_minor==(rates['stt_minor_per_minute']*metering.MICRO+59)//60
        development=metering.record_cost(db,ws,'dev-real-request','openai','llm',{'input_tokens':10},mode='development',source='provider_usage')
        assert development.cost_micro_minor>0
        synthetic=metering.record_cost(db,ws,'dev-synthetic-request','openai','llm',{'input_tokens':10},mode='development',source='synthetic')
        assert synthetic.cost_micro_minor==0
    with pytest.raises(DBAPIError):
        with engine.begin() as db:db.execute(update(CallCostRecord).where(CallCostRecord.id==identity).values(cost_micro_minor=0))


@pytest.mark.asyncio
@pytest.mark.parametrize('style',['responses','chat_completions'])
async def test_real_turn_wrapper_records_final_usage_in_both_documented_stream_formats(account,monkeypatch,style):
    import openai
    _,ws,_=account;requests=[]
    usage=SimpleNamespace(input_tokens=100,output_tokens=5,input_tokens_details=SimpleNamespace(cached_tokens=40,cache_write_tokens=0))
    class Stream:
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        def __aiter__(self):return self.events()
        async def events(self):
            if style=='responses':
                yield SimpleNamespace(type='response.output_text.delta',delta='Hello')
                yield SimpleNamespace(type='response.completed',response=SimpleNamespace(output=[],usage=usage))
            else:
                yield SimpleNamespace(usage=None,choices=[SimpleNamespace(finish_reason=None,delta=SimpleNamespace(content='Hello',tool_calls=[]))])
                yield SimpleNamespace(usage=None,choices=[SimpleNamespace(finish_reason='stop',delta=SimpleNamespace(content=None,tool_calls=[]))])
                yield SimpleNamespace(choices=[],usage=SimpleNamespace(prompt_tokens=100,completion_tokens=5,prompt_tokens_details=SimpleNamespace(cached_tokens=40,cache_write_tokens=0)))
    async def create(**kwargs):requests.append(kwargs);return Stream()
    class Client:
        def __init__(self,**kwargs):self.responses=SimpleNamespace(create=create);self.chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
    monkeypatch.setattr(openai,'AsyncOpenAI',Client)
    profile={**llm.environment_profile(),'api_key':'synthetic-llm-key','api_style':style,'workspace_id':ws}
    turn=llm.Turn(profile,'Stable system instructions',[{'role':'user','content':'Hello'}])
    assert ''.join([part async for part in turn.stream()])=='Hello'
    if style=='chat_completions':assert requests[0]['stream_options']=={'include_usage':True}
    with session_scope() as db:
        record=db.scalar(select(CallCostRecord).where(CallCostRecord.workspace_id==ws))
        assert record.units=={'input_tokens':100,'cached_input_tokens':40,'output_tokens':5}
        assert record.source=='provider_usage' and record.cost_micro_minor>0


@pytest.mark.asyncio
async def test_media_meter_counts_submitted_utf8_bytes_and_pcm_seconds_without_real_providers(account,monkeypatch):
    _,ws,_=account;config=default_agent();config['greeting']='नमस्ते 🙂';config['recording']['enabled']=False
    with session_scope(write=True) as db:
        call=Call(workspace_id=ws,state='connected',mode='live');db.add(call);db.flush();call_id=call.id
    class Socket:
        async def send_json(self,*args):pass
        async def send_bytes(self,*args):pass
    async def speech(text_stream,*args):
        from fishaudio.types import FlushEvent
        async for item in text_stream:
            if not isinstance(item,FlushEvent):
                yield b'\0'*4800
    session=media.VoiceSession(Socket(),ws,call_id,config,'live')
    monkeypatch.setattr(session.fish,'stream',speech)
    monkeypatch.setattr(session.fish,'prepare',lambda *args:None)
    session.dg=SimpleNamespace(send=AsyncMock())
    await session.recognition_audio(b'\0'*3200)
    await session.respond()
    with session_scope(write=True) as db:session.record_audio_usage(db)
    with session_scope() as db:
        lines=list(db.scalars(select(CallCostRecord).where(CallCostRecord.call_id==call_id)))
        tts=next(line for line in lines if line.provider=='fish');stt=next(line for line in lines if line.provider=='deepgram')
        assert tts.units['tts_utf8_bytes']==len(config['greeting'].encode()) and tts.units['tts_ms']==100
        assert stt.units['stt_ms']==100


def test_actual_chat_turns_conversations_and_uploads_emit_usage_without_double_counting(sample):
    client,ws,base,fixture=sample;widget=client.get(base+'/installations').json()['items'][0]
    state=client.post('/v1/public/sessions',headers={'Origin':settings.app_origin},json={'installation_public_id':widget['public_id']}).json()
    headers={'Origin':settings.app_origin,'Authorization':'Bearer '+state['session_token']}
    payload={'session_id':state['id'],'client_message_id':'meter-one','message':'What are your opening hours?'}
    assert client.post('/v1/public/chat',headers=headers,json=payload).status_code==200
    assert client.post('/v1/public/chat',headers=headers,json=payload).status_code==200
    body=b'Documented service hours Monday to Friday.'
    for _ in range(2):
        assert client.post(base+'/knowledge/'+fixture['kb_id']+'/documents',files={'file':('hours.txt',body,'text/plain')}).status_code==202
    summary=client.get(base+'/billing/usage').json()
    assert summary['usage']['conversations']==1 and summary['usage']['chat_turns']==1
    assert summary['usage']['storage_bytes']==len(body)


@pytest.mark.asyncio
async def test_embedding_cost_uses_reported_tokens_and_cache_hits_do_not_create_provider_cost(account,monkeypatch):
    from studio import retrieval,cache
    _,ws,_=account;cached={};vector=[1.0]+[0.0]*(settings.embedding_dimensions-1)
    monkeypatch.setattr(cache,'get_vectors',lambda texts:[cached.get(text) for text in texts])
    def put(texts,vectors):cached.update(zip(texts,vectors))
    monkeypatch.setattr(cache,'put_vectors',put)
    create=AsyncMock(return_value=SimpleNamespace(data=[SimpleNamespace(index=0,embedding=vector)],usage=SimpleNamespace(prompt_tokens=7,total_tokens=7)))
    client=SimpleNamespace(embeddings=SimpleNamespace(create=create))
    with metering.scope(workspace_id=ws):
        assert await retrieval.embed(['A documented fact.'],client=client)==[vector]
        assert await retrieval.embed(['A documented fact.'],client=client)==[vector]
    assert create.await_count==1
    with session_scope() as db:
        lines=list(db.scalars(select(CallCostRecord).where(CallCostRecord.provider=='embedding')))
        assert len(lines)==1 and lines[0].units=={'input_tokens':7} and lines[0].source=='provider_usage'


@pytest.mark.asyncio
async def test_interrupted_model_stream_records_usage_as_unreported_instead_of_inventing_tokens(account,monkeypatch):
    _,ws,_=account
    turn=llm.Turn({**llm.environment_profile(),'workspace_id':ws},'system',[])
    async def interrupted():
        turn.request_started=True
        yield 'Partial response'
        raise RuntimeError('Synthetic disconnect')
    monkeypatch.setattr(turn,'_stream',interrupted)
    with pytest.raises(RuntimeError):
        async for _ in turn.stream():pass
    with session_scope() as db:
        row=db.scalar(select(CallCostRecord))
        assert row.source=='unreported' and row.units=={}

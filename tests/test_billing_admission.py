import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock,Mock

from fastapi import HTTPException
from sqlalchemy import select,func
import pytest

from studio import admission,metering,plans,llm,storage,media
from studio.config import settings
from studio.db import session_scope,uid,now
from studio.models import BudgetAdmission,CallCostRecord,EmailOutbox,MeterEvent,WorkspaceSubscription,Call,Agent,KnowledgeBase
from studio.domain import default_agent,settle_call


def configure(monkeypatch,tmp_path,**limits):
    body=plans.catalog();body.pop('content_hash',None)
    plan=body['plans']['free']
    for key,value in limits.items():
        if key=='spend_cap_minor':plan[key]=value
        else:plan['included'][key]=value
    path=tmp_path/'catalog.json';path.write_text(json.dumps(body))
    monkeypatch.setattr(settings,'plans_config_path',str(path))
    monkeypatch.setattr(settings,'billing_development_allowances_enabled',False)
    return body


def test_quota_denial_preserves_only_alert_and_replays_do_not_spend_twice(account,monkeypatch,tmp_path):
    client,ws,base=account;configure(monkeypatch,tmp_path,chat_turns=5)
    with session_scope(write=True) as db:
        for index in range(5):metering.record_usage(db,ws,'chat:'+str(index),'chat_turns',1)
        metering.record_usage(db,ws,'chat:0','chat_turns',1)
    with pytest.raises(HTTPException) as error:
        with session_scope(write=True) as db:
            db.add(Agent(workspace_id=ws,name='Must roll back',draft_config={}))
            metering.record_usage(db,ws,'chat:denied','chat_turns',1)
    assert error.value.status_code==429 and 'chat turns' in error.value.detail
    with session_scope() as db:
        assert db.scalar(select(func.count()).select_from(MeterEvent))==5
        assert db.scalar(select(func.count()).select_from(Agent))==0
        assert db.scalar(select(func.count()).select_from(EmailOutbox).where(EmailOutbox.operation_key.like('workspace-cap:%')))==2 # 80 and 100, deduplicated
    summary=client.get(base+'/billing/usage').json();assert summary['usage']['chat_turns']==5


def test_concurrent_spend_holds_are_shared_and_unknown_usage_keeps_cap(account,monkeypatch,tmp_path):
    _,ws,_=account;configure(monkeypatch,tmp_path,spend_cap_minor=100)
    def hold(index):
        try:
            with session_scope(write=True) as db:
                admission.reserve(db,ws,'parallel:'+str(index),kind='provider',cost=75*metering.MICRO)
            return 'held'
        except HTTPException:return 'denied'
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(hold,range(2)))
    assert sorted(results)==['denied','held']
    with session_scope(write=True) as db:
        row=db.scalar(select(BudgetAdmission).where(BudgetAdmission.state=='held'))
        row.state='unknown'
    with pytest.raises(HTTPException,match='spending cap'):
        with session_scope(write=True) as db:admission.reserve(db,ws,'after-disconnect',cost=26*metering.MICRO)


def test_measured_provider_usage_releases_unused_hold_and_overrun_pauses(account,monkeypatch,tmp_path):
    _,ws,_=account;configure(monkeypatch,tmp_path,spend_cap_minor=100)
    values={'workspace_id':ws}
    admission.provider_hold(values,'llm:first','openai',{'input_tokens':500}) # 50 paise bound
    with session_scope(write=True) as db:
        metering.record_cost(db,ws,'llm:first','openai','llm',{'input_tokens':100},source='provider_usage')
        row=db.scalar(select(BudgetAdmission).where(BudgetAdmission.operation_key==metering.operation('llm:first')))
        assert row.state=='completed' and row.measured_micro_minor==10*metering.MICRO
        admission.reserve(db,ws,'can-use-remainder',cost=90*metering.MICRO)
    with session_scope(write=True) as db:
        metering.record_cost(db,ws,'can-use-remainder','openai','llm',{'output_tokens':181},source='provider_usage')
        assert db.scalar(select(WorkspaceSubscription)).operator_paused is True
    with pytest.raises(HTTPException,match='paused'):
        with session_scope(write=True) as db:admission.reserve(db,ws,'blocked-after-overrun')


@pytest.mark.asyncio
async def test_actual_turn_refuses_provider_before_zero_cap_or_unbounded_request(account,monkeypatch,tmp_path):
    _,ws,_=account;configure(monkeypatch,tmp_path,spend_cap_minor=0)
    import openai
    provider=Mock();monkeypatch.setattr(openai,'AsyncOpenAI',provider)
    profile={**llm.environment_profile(),'workspace_id':ws,'api_key':'fixture'}
    with pytest.raises(HTTPException,match='spending cap'):
        async for _ in llm.Turn(profile,'Stable system',[{'role':'user','content':'Hello'}]).stream():pass
    provider.assert_not_called()
    profile['token_parameter']='omit'
    with pytest.raises(HTTPException,match='bounded output'):
        async for _ in llm.Turn(profile,'system',[]).stream():pass
    profile['token_parameter']='max_output_tokens'
    monkeypatch.setattr(settings,'billing_max_llm_input_bytes',8)
    with pytest.raises(HTTPException,match='input budget'):
        async for _ in llm.Turn(profile,'Stable system',[]).stream():pass
    provider.assert_not_called()


def test_storage_reserves_before_io_and_ambiguous_write_remains_counted(account,monkeypatch,tmp_path):
    _,ws,_=account;configure(monkeypatch,tmp_path,storage_bytes=10)
    fake=Mock();fake.put.side_effect=OSError('simulated uncertain storage result')
    monkeypatch.setattr(storage,'get_store',lambda:fake)
    with pytest.raises(OSError):storage.put_checked(ws,'documents',b'12345678','text/plain')
    with pytest.raises(HTTPException,match='storage bytes'):
        storage.put_checked(ws,'documents',b'abcdefgh','text/plain')
    assert fake.put.call_count==1
    fake.put.side_effect=lambda ws,category,body,mime:storage.object_key(ws,category,body)
    key=storage.put_checked(ws,'documents',b'12345678','text/plain')
    assert fake.put.call_count==2
    with session_scope() as db:
        assert admission.usage(db,ws,plans.subscription(db,ws),'storage_bytes')==8
        assert not list(db.scalars(select(BudgetAdmission).where(BudgetAdmission.kind=='storage',BudgetAdmission.state=='held')))
    with session_scope(write=True) as db:metering.removed(db,ws,key)
    storage.put_checked(ws,'documents',b'abcdefgh','text/plain')


def test_upload_is_rejected_before_object_provider(account,monkeypatch,tmp_path):
    client,_,base=account;configure(monkeypatch,tmp_path,storage_bytes=0)
    with session_scope(write=True) as db:
        kb=KnowledgeBase(workspace_id=account[1],name='Bounded files');db.add(kb);db.flush();kb_id=kb.id
    fake=Mock();monkeypatch.setattr(storage,'get_store',lambda:fake)
    response=client.post(base+'/knowledge/'+kb_id+'/documents',files={'file':('info.txt',b'text','text/plain')})
    assert response.status_code==429,response.text
    fake.put.assert_not_called()


def test_widgets_and_pending_seats_have_plan_limits(account,monkeypatch,tmp_path):
    client,_,base=account;configure(monkeypatch,tmp_path,widgets=1,seats=2)
    agent=client.post(base+'/agents',json={'name':'Widget plan'}).json()
    body={'agent_id':agent['id'],'name':'One widget','allowed_origins':[settings.app_origin]}
    assert client.post(base+'/installations',json=body).status_code==201
    assert client.post(base+'/installations',json=body).status_code==429
    invite=client.post(base+'/invitations',json={'email':'first@example.test','role':'operator'})
    assert invite.status_code==201,invite.text
    assert client.post(base+'/invitations',json={'email':'second@example.test','role':'operator'}).status_code==429
    identity=invite.json()['invitation']['id']
    assert client.delete(base+'/invitations/'+identity).status_code==200
    assert client.post(base+'/invitations',json={'email':'second@example.test','role':'operator'}).status_code==201


def test_production_ignores_development_allowances(account,monkeypatch,tmp_path):
    _,ws,_=account;configure(monkeypatch,tmp_path,widgets=1,spend_cap_minor=5000)
    monkeypatch.setattr(settings,'billing_development_allowances_enabled',True)
    monkeypatch.setattr(settings,'app_env','production')
    with session_scope(write=True) as db:
        _,limits,cap=admission.policy(db,ws)
        assert limits['widgets']==1 and cap==5000


def test_voice_reserves_full_duration_and_settlement_releases_unused_minutes(account,monkeypatch,tmp_path):
    _,ws,_=account;configure(monkeypatch,tmp_path,voice_ms=60000)
    config=default_agent('Minute plan');config['behavior']['max_connected_seconds']=60
    client,_,base=account
    agent=client.post(base+'/agents',json={'name':'Minute plan'}).json()
    config['name']='Minute plan'
    client.put(base+'/agents/'+agent['id']+'/draft',json={'expected_revision':1,'config':config})
    published=client.post(base+'/agents/'+agent['id']+'/publish',json={'expected_draft_revision':2})
    assert published.status_code==201,published.text
    first=client.post(base+'/voice/sessions',json={'agent_id':agent['id'],'mode':'simulation'})
    assert first.status_code==201,first.text
    assert client.post(base+'/voice/sessions',json={'agent_id':agent['id'],'mode':'simulation'}).status_code==429
    with session_scope(write=True) as db:settle_call(db,db.get(Call,first.json()['call_id']),1000)
    # Only 59 seconds remain, so a new 60-second reservation still cannot fit.
    assert client.post(base+'/voice/sessions',json={'agent_id':agent['id'],'mode':'simulation'}).status_code==429
    with session_scope() as db:
        row=db.scalar(select(BudgetAdmission).where(BudgetAdmission.scope_id==first.json()['call_id'],BudgetAdmission.kind=='resource'))
        assert row.state=='completed'


def test_tts_streaming_holds_check_each_chunk_before_spend(account,monkeypatch,tmp_path):
    _,ws,_=account;configure(monkeypatch,tmp_path,spend_cap_minor=30)
    values={'workspace_id':ws}
    admission.provider_extend(values,'tts:one','fish',{'tts_utf8_bytes':50}) # 25 paise
    with pytest.raises(HTTPException,match='spending cap'):
        admission.provider_extend(values,'tts:one','fish',{'tts_utf8_bytes':50})
    with session_scope(write=True) as db:
        line=metering.record_cost(db,ws,'tts:one','fish','tts',{'tts_utf8_bytes':50},source='observed_input')
        assert line.cost_micro_minor==25*metering.MICRO
        parent=db.scalar(select(BudgetAdmission).where(BudgetAdmission.operation_key==metering.operation('tts:one')))
        assert parent.state=='completed' and parent.reserved_micro_minor==25*metering.MICRO


def test_legacy_and_abandoned_objects_are_backfilled_without_deleting(account,tmp_path,monkeypatch):
    _,ws,_=account
    real=storage.LocalObjectStore(tmp_path/'objects')
    monkeypatch.setattr(storage,'get_store',lambda:real)
    key=real.put(ws,'documents',b'legacy content','text/plain')
    assert storage.reconcile(ws)=={'objects':1,'bytes':14,'untracked_objects':1,'applied':False}
    assert storage.reconcile(ws,apply=True)['untracked_objects']==1
    assert storage.reconcile(ws,apply=True)['untracked_objects']==0
    real.delete(ws,key)
    storage.reconcile(ws,apply=True)
    # An incomplete/concurrent listing is not proof that a stored object was deleted.
    with session_scope() as db:assert metering.usage_summary(db,ws)['usage']['storage_bytes']==14


def test_azure_inventory_is_workspace_prefixed_and_uses_paged_size_properties(account,monkeypatch):
    _,ws,_=account
    monkeypatch.setattr(settings,'azure_storage_prefix','isolated-fixture')
    container=Mock();container.list_blobs.return_value=[SimpleNamespace(name='isolated-fixture/'+ws+'/documents/one',size=12)]
    client=Mock();client.get_container_client.return_value=container
    store=storage.AzureBlobObjectStore(client=client)
    assert list(store.inventory(ws))==[(ws+'/documents/one',12)]
    container.list_blobs.assert_called_once_with(name_starts_with='isolated-fixture/'+ws+'/',results_per_page=500)


def test_widget_cost_holds_use_the_installation_cap_and_owner_outbox(sample,monkeypatch):
    client,ws,base,fixture=sample
    from studio.models import Installation,WidgetProtection
    with session_scope(write=True) as db:
        installation=db.get(Installation,fixture['installation_id'])
        installation_id=installation.id
        db.add(WidgetProtection(workspace_id=ws,installation_id=installation_id,policy={'monthly_spend_cap_minor':20}))
    values={'workspace_id':ws,'installation_id':installation_id}
    admission.provider_hold(values,'widget-first','openai',{'input_tokens':100}) # 10 paise
    with pytest.raises(HTTPException,match='assistant has reached'):
        admission.provider_hold(values,'widget-next','openai',{'input_tokens':101})
    with session_scope() as db:
        assert db.scalar(select(func.count()).select_from(EmailOutbox).where(EmailOutbox.operation_key.like('widget-cap:%')))==1


@pytest.mark.asyncio
async def test_audio_frame_budget_counts_pcm_before_sending_to_deepgram(account):
    _,ws,_=account
    config=default_agent('Audio quota')
    session=media.VoiceSession(SimpleNamespace(),ws,uid(),config,'live')
    session.admitted_max_seconds=1;session.dg=SimpleNamespace(send=AsyncMock())
    await session.recognition_audio(b'\0'*32000)
    with pytest.raises(HTTPException,match='audio allowance'):await session.recognition_audio(b'\0\0')
    assert session.dg.send.await_count==1


def test_carrier_answer_deadline_does_not_extend_on_replay(monkeypatch):
    from datetime import datetime,timedelta,timezone
    from studio.carrier_config import remaining_seconds
    import studio.db
    start=datetime(2026,10,25,tzinfo=timezone.utc)
    monkeypatch.setattr(studio.db,'now',lambda:start)
    call=SimpleNamespace(metadata_data={'admitted_max_seconds':60})
    assert remaining_seconds(call)==60
    monkeypatch.setattr(studio.db,'now',lambda:start+timedelta(seconds=15))
    assert remaining_seconds(call)==45
    monkeypatch.setattr(studio.db,'now',lambda:start+timedelta(seconds=61))
    assert remaining_seconds(call)==0


def test_legacy_production_storage_fails_closed_until_inventory_is_complete(account,monkeypatch,tmp_path):
    from sqlalchemy import delete
    from studio.models import StorageInventoryState
    _,ws,_=account;real=storage.LocalObjectStore(tmp_path/'objects')
    real.put(ws,'documents',b'legacy','text/plain');monkeypatch.setattr(storage,'get_store',lambda:real)
    with session_scope(write=True) as db:db.execute(delete(StorageInventoryState).where(StorageInventoryState.workspace_id==ws))
    monkeypatch.setattr(settings,'app_env','production')
    with pytest.raises(HTTPException,match='requires reconciliation'):
        storage.put_checked(ws,'documents',b'new','text/plain')
    storage.reconcile(ws,apply=True)
    storage.put_checked(ws,'documents',b'new','text/plain')
    with session_scope() as db:
        summary=metering.usage_summary(db,ws)
        assert summary['storage_inventory_ready'] is True and summary['usage']['storage_bytes']==9


def test_deployment_reconciles_only_workspaces_missing_inventory(account,monkeypatch,tmp_path):
    from sqlalchemy import delete
    from studio.models import Workspace,StorageInventoryState
    from reconcile_storage import reconcile_pending
    _,ws,_=account
    real=storage.LocalObjectStore(tmp_path/'objects')
    real.put(ws,'documents',b'legacy','text/plain')
    monkeypatch.setattr(storage,'get_store',lambda:real)
    with session_scope(write=True) as db:
        db.execute(delete(StorageInventoryState).where(StorageInventoryState.workspace_id==ws))
        other=Workspace(name='Already initialized');db.add(other);db.flush()
        db.add(StorageInventoryState(workspace_id=other.id))
    assert reconcile_pending()['workspaces']==1
    with session_scope() as db:
        assert db.scalar(select(StorageInventoryState.id).where(StorageInventoryState.workspace_id==ws)) is None
    assert reconcile_pending(apply=True)=={'workspaces':1,'objects':1,'bytes':6,'untracked_objects':1,'applied':True}
    assert reconcile_pending(apply=True)['workspaces']==0


def test_deployment_inventory_failure_does_not_mark_workspace_ready(account,monkeypatch):
    from sqlalchemy import delete
    from studio.models import StorageInventoryState
    from reconcile_storage import reconcile_pending
    _,ws,_=account
    with session_scope(write=True) as db:
        db.execute(delete(StorageInventoryState).where(StorageInventoryState.workspace_id==ws))
    class Unavailable:
        def inventory(self,workspace_id):raise RuntimeError('Storage unavailable')
    monkeypatch.setattr(storage,'get_store',lambda:Unavailable())
    with pytest.raises(RuntimeError,match='Storage unavailable'):reconcile_pending(apply=True)
    with session_scope() as db:
        assert db.scalar(select(StorageInventoryState.id).where(StorageInventoryState.workspace_id==ws)) is None

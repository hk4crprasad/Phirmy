import json
import pytest
from sqlalchemy import select,func,delete
from sqlalchemy.exc import IntegrityError
from studio.db import session_scope
from studio.models import *
from studio.workers import execute_job
from studio.storage import get_store
from studio.config import settings
from studio.agent_deletion import collect


def agent(sample):
    client,ws,base,fixture=sample
    return client,ws,base,fixture,client.get(base+'/agents/'+fixture['agent_id']).json()


@pytest.mark.asyncio
async def test_delete_full_agent_graph_and_preserve_shared_resources(sample,monkeypatch):
    client,ws,base,fixture,row=agent(sample)
    widget=client.get(base+'/installations').json()['items'][0]
    state=client.post('/v1/public/sessions',headers={'Origin':settings.app_origin},json={'installation_public_id':widget['public_id'],'visitor_email':'delete-me@example.test'}).json()
    client.post('/v1/public/chat',headers={'Origin':settings.app_origin,'Authorization':'Bearer '+state['session_token']},json={'session_id':state['id'],'message':'Please create a support ticket','client_message_id':'delete-turn'})
    from studio.widget_protection import defaults
    from studio.secrets import decrypt
    from studio.models import EmailOutbox,WidgetEmailChallenge,WidgetMarketingConsent,WidgetBucket,WidgetAdmission,WidgetProtection,ToolConsent
    assert client.put(base+'/installations/'+widget['id']+'/protection',json=defaults()).status_code==200
    visitor_headers={'Origin':settings.app_origin,'Authorization':'Bearer '+state['session_token']}
    challenge=client.post('/v1/public/email/request',headers=visitor_headers,json={'email':'delete-me@example.test'}).json()
    with session_scope() as db:
        mail=db.scalar(select(EmailOutbox).where(EmailOutbox.operation_key=='widget-otp:'+challenge['challenge_id']))
        mail_id=mail.id
        import re
        code=re.search(r'code is (\d{6})',json.loads(decrypt(mail.encrypted_payload))['body'])[1]
    monkeypatch.setattr(settings,'widget_marketing_consent_enabled',True)
    assert client.post('/v1/public/email/verify',headers=visitor_headers,json={
        'challenge_id':challenge['challenge_id'],'code':code,'marketing_opt_in':True}).status_code==200
    other=client.post(base+'/agents',json={'name':'Keep me'}).json()
    with session_scope() as db:before_ledger=db.scalar(select(func.count()).select_from(Ledger));plan=collect(db,ws,row['id'])
    preview=client.get(base+'/agents/'+row['id']+'/deletion-preview')
    assert preview.status_code==200 and preview.json()['counts']['conversations']==1
    assert client.post(base+'/agents/'+row['id']+'/delete',json={'confirmation':'wrong name'}).status_code==422
    response=client.post(base+'/agents/'+row['id']+'/delete',json={'confirmation':row['name']})
    assert response.status_code==202,response.text
    job=response.json()
    assert client.post(base+'/agents/'+row['id']+'/delete',json={'confirmation':row['name']}).json()['id']==job['id']
    assert client.post(base+'/jobs/'+job['id']+'/cancel').status_code==409
    assert client.post('/v1/public/conversation',headers={'Origin':settings.app_origin,'Authorization':'Bearer '+state['session_token']}).status_code==403
    await execute_job(job['id'])
    status=client.get(base+'/jobs/'+job['id']).json()
    assert status['state']=='completed',status
    with session_scope() as db:
        assert db.get(Agent,row['id']) is None and db.get(Agent,other['id'])
        assert db.get(Installation,widget['id']) is None and db.get(Conversation,state['id']) is None
        assert not list(db.scalars(select(Lead).where(Lead.email=='delete-me@example.test')))
        assert db.scalar(select(func.count()).select_from(Ledger))==before_ledger
        assert not list(db.scalars(select(AgentVersion).where(AgentVersion.agent_id==row['id'])))
        for model in [WidgetProtection,WidgetBucket,WidgetAdmission]:
            assert not list(db.scalars(select(model).where(model.installation_id==widget['id'])))
        assert not list(db.scalars(select(ToolConsent).where(ToolConsent.scope_key=='conversation:'+state['id'])))
        assert db.get(WidgetEmailChallenge,challenge['challenge_id']) is None and db.get(EmailOutbox,mail_id) is None
        assert not list(db.scalars(select(WidgetMarketingConsent)))


@pytest.mark.asyncio
async def test_shared_knowledge_and_blob_are_preserved(sample):
    client,ws,base,fixture,row=agent(sample)
    with session_scope() as db:original=db.get(Agent,row['id']);snapshots=original.draft_config['knowledge_snapshot_ids']
    other=client.post(base+'/agents',json={'name':'Shared knowledge user'}).json()
    config=other['draft_config'];config['knowledge_snapshot_ids']=snapshots
    assert client.put(base+'/agents/'+other['id']+'/draft',json={'expected_revision':1,'config':config}).status_code==200
    preview=client.get(base+'/agents/'+row['id']+'/deletion-preview').json()
    assert preview['shared_knowledge_preserved']==1 and preview['counts']['kb_ids']==0
    job=client.post(base+'/agents/'+row['id']+'/delete',json={'confirmation':row['name']}).json()
    await execute_job(job['id'])
    assert client.get(base+'/jobs/'+job['id']).json()['state']=='completed'
    with session_scope() as db:assert db.get(Snapshot,snapshots[0]) is not None


@pytest.mark.asyncio
async def test_storage_failure_is_retryable_and_financial_call_is_scrubbed(sample,monkeypatch):
    client,ws,base,fixture,row=agent(sample)
    with session_scope(write=True) as db:
        version=db.get(Agent,row['id']).published_version_id
        call=Call(workspace_id=ws,agent_version_id=version,agent_name=row['name'],state='completed',destination='+12345678901',analysis={'private':'data'});db.add(call);db.flush();call_id=call.id
        db.add(Ledger(workspace_id=ws,call_id=call_id,amount_minor=0,kind='voice',operation_key='delete-financial',description='Financial record'))
        key=get_store().put(ws,'recordings',b'private-audio','audio/wav')
        from datetime import timedelta
        from studio.db import now
        db.add(Recording(workspace_id=ws,call_id=call_id,object_key=key,duration_ms=10,size_bytes=13,expires_at=now()+timedelta(days=1)))
    job=client.post(base+'/agents/'+row['id']+'/delete',json={'confirmation':row['name']}).json()
    original=get_store().delete
    def fail(*args):raise RuntimeError('Synthetic storage outage')
    monkeypatch.setattr(get_store(),'delete',fail)
    await execute_job(job['id'])
    assert client.get(base+'/jobs/'+job['id']).json()['state']=='failed'
    with session_scope() as db:assert db.get(Agent,row['id']) is not None
    monkeypatch.setattr(get_store(),'delete',original)
    assert client.post(base+'/jobs/'+job['id']+'/retry').status_code==202
    await execute_job(job['id'])
    assert client.get(base+'/jobs/'+job['id']).json()['state']=='completed'
    with session_scope() as db:
        call=db.get(Call,call_id);assert call and call.agent_version_id is None and call.destination=='' and call.analysis=={}
    with pytest.raises(FileNotFoundError):get_store().get(ws,key)


def test_blocks_running_work_tenant_role_and_immutable_versions(sample):
    client,ws,base,fixture,row=agent(sample)
    assert client.get('/v1/workspaces/foreign/agents/'+row['id']+'/deletion-preview').status_code==404
    with session_scope(write=True) as db:
        db.add(Call(workspace_id=ws,agent_version_id=db.get(Agent,row['id']).published_version_id,state='connected'))
    response=client.post(base+'/agents/'+row['id']+'/delete',json={'confirmation':row['name']})
    assert response.status_code==409 and 'End active calls' in response.text
    with pytest.raises(IntegrityError):
        with session_scope(write=True) as db:db.execute(delete(AgentVersion).where(AgentVersion.agent_id==row['id']))
    with session_scope(write=True) as db:
        membership=db.scalar(select(Membership).where(Membership.workspace_id==ws));membership.role='builder'
    assert client.get(base+'/agents/'+row['id']+'/deletion-preview').status_code==403


@pytest.mark.asyncio
async def test_vector_cache_scope_and_shared_content_addressed_object(sample,monkeypatch):
    client,ws,base,fixture,row=agent(sample)
    from studio import retrieval,cache,widget_frame_cache
    with session_scope(write=True) as db:
        owned_source=db.scalar(select(Source).where(Source.workspace_id==ws,Source.kb_id==fixture['kb_id']))
        shared_key=get_store().put(ws,'snapshots',b'shared raw page','text/html');owned_source.raw_object_key=shared_key
        kb=KnowledgeBase(workspace_id=ws,name='Unrelated knowledge');db.add(kb);db.flush()
        db.add(Source(workspace_id=ws,kb_id=kb.id,canonical_url='https://other.example/',content_hash='other-hash',raw_object_key=shared_key))
        plan=collect(db,ws,row['id']);snapshots=plan['snapshots'];cache_keys=plan['cache_keys']
    calls=[]
    async def vector_request(self,method,path,**kwargs):calls.append((method,path,kwargs));return {'result':{'status':'completed'}}
    monkeypatch.setattr(settings,'vector_endpoint','https://synthetic-vector.example')
    monkeypatch.setattr(retrieval.Qdrant,'request',vector_request)
    removed=[]
    from types import SimpleNamespace
    monkeypatch.setattr(settings,'redis_url','redis://synthetic')
    monkeypatch.setattr(cache,'connection',lambda url:SimpleNamespace(delete=lambda *keys:removed.extend(keys)))
    # This unit fakes retrieval cache deletion only; policy fencing has its own
    # real Redis integration coverage.
    monkeypatch.setattr(widget_frame_cache,'connection',lambda:None)
    job=client.post(base+'/agents/'+row['id']+'/delete',json={'confirmation':row['name']}).json()
    await execute_job(job['id'])
    assert client.get(base+'/jobs/'+job['id']).json()['state']=='completed'
    assert calls[0][2]['json']['filter']['must']==[{'key':'workspace_id','match':{'value':ws}},{'key':'snapshot_id','match':{'any':sorted(snapshots)}}]
    assert set(removed)==cache_keys and get_store().get(ws,shared_key)==b'shared raw page'


def test_running_crawl_blocks_deletion_and_builder_cannot_retry(sample):
    client,ws,base,fixture,row=agent(sample)
    with session_scope(write=True) as db:
        db.add(Job(workspace_id=ws,kind='crawl',state='running',payload={'kb_id':fixture['kb_id']}))
    result=client.post(base+'/agents/'+row['id']+'/delete',json={'confirmation':row['name']})
    assert result.status_code==409 and 'Stop running' in result.text
    with session_scope(write=True) as db:
        job=Job(workspace_id=ws,kind='agent_delete',state='failed',payload={'agent_id':row['id']});db.add(job);db.flush();job_id=job.id
        membership=db.scalar(select(Membership).where(Membership.workspace_id==ws));membership.role='builder'
    assert client.post(base+'/jobs/'+job_id+'/retry').status_code==403


def test_pending_delete_knowledge_cannot_be_attached_or_recrawled(sample):
    client,ws,base,fixture,row=agent(sample)
    with session_scope() as db:config=db.get(Agent,row['id']).draft_config
    response=client.post(base+'/agents/'+row['id']+'/delete',json={'confirmation':row['name']});assert response.status_code==202
    assert client.post(base+'/knowledge/'+fixture['kb_id']+'/recrawls').status_code==409
    assert client.post(base+'/agents',json={'name':'Too late','config':config}).status_code==409


@pytest.mark.asyncio
async def test_empty_agent_delete_needs_no_storage_provider(sample,monkeypatch):
    client,ws,base,fixture=sample
    row=client.post(base+'/agents',json={'name':'Empty draft'}).json()
    from studio import storage
    monkeypatch.setattr(storage,'get_store',lambda:pytest.fail('No storage needed for an empty draft'))
    job=client.post(base+'/agents/'+row['id']+'/delete',json={'confirmation':row['name']}).json()
    await execute_job(job['id'])
    assert client.get(base+'/jobs/'+job['id']).json()['state']=='completed'

"""Durable queue concurrency, fencing and bounded embedding fan-out."""
import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from studio import knowledge, workers
from studio.config import settings
from studio.db import session_scope, now, uid
from studio.job_control import get_job
from studio.models import Job, KnowledgeBase, Store, Source, Chunk, Snapshot, WebhookEndpoint, Delivery


async def until(predicate):
    async def poll():
        while not predicate():
            await asyncio.sleep(.005)
    await asyncio.wait_for(poll(), 3)


@pytest.mark.asyncio
async def test_pool_runs_jobs_and_webhook_without_waiting_for_slow_job(account, monkeypatch):
    _,ws,_=account
    monkeypatch.setattr(settings,'worker_concurrency',2)
    monkeypatch.setattr(settings,'worker_poll_seconds',.01)
    monkeypatch.setattr(workers,'maintenance',AsyncMock())
    release=asyncio.Event();started=[];active=peak=0;delivered=[]
    async def handler(job_id):
        nonlocal active,peak
        started.append(job_id);active+=1;peak=max(peak,active)
        try:await release.wait()
        finally:active-=1
    async def delivery(delivery_id):
        delivered.append(delivery_id)
        with session_scope(write=True) as db:db.get(Delivery,delivery_id).state='success'
    monkeypatch.setitem(workers.HANDLERS,'pool_fixture',handler)
    monkeypatch.setattr(workers,'deliver_webhook',delivery)
    with session_scope(write=True) as db:
        jobs=[Job(workspace_id=ws,kind='pool_fixture') for _ in range(5)]
        db.add_all(jobs)
        endpoint=WebhookEndpoint(workspace_id=ws,url='https://webhook.example',secret='unused',event_types=['fixture'])
        db.add(endpoint);db.flush()
        item=Delivery(workspace_id=ws,endpoint_id=endpoint.id,event_id=uid(),event_type='fixture',payload={})
        db.add(item);db.flush();delivery_id=item.id
    stop=asyncio.Event();task=asyncio.create_task(workers.worker_loop(stop))
    try:
        await until(lambda:len(started)==2 and delivered)
        assert delivered==[delivery_id] and active==2
        release.set()
        def completed():
            with session_scope() as db:return all(db.get(Job,j.id).state=='completed' for j in jobs)
        await until(completed)
    finally:
        stop.set();release.set();await asyncio.wait_for(task,3)
    assert peak==2 and len(set(started))==5
    with session_scope() as db:assert all(db.get(Job,j.id).state=='completed' for j in jobs)


@pytest.mark.parametrize('resource_key,model',[('kb_id',KnowledgeBase),('store_id',Store)])
def test_busy_knowledge_does_not_starve_unrelated_jobs_or_overlap(account,resource_key,model):
    _,ws,_=account
    with session_scope(write=True) as db:
        kb=model(workspace_id=ws,name='Busy',website_url='https://busy.example');db.add(kb);db.flush()
        first=Job(workspace_id=ws,kind='crawl',payload={resource_key:kb.id},state='running',lease_token=uid(),lease_until=now()+timedelta(minutes=3))
        db.add(first)
        db.add_all(Job(workspace_id=ws,kind='crawl',payload={resource_key:kb.id}) for _ in range(25))
        other=Job(workspace_id=ws,kind='fixture');db.add(other);db.flush()
    claimed,_=workers.claim_dispatch()
    assert claimed[0]==other.id
    assert workers.claim_dispatch()==(None,None)
    with session_scope(write=True) as db:db.get(Job,first.id).lease_until=now()-timedelta(seconds=1)
    recovered,_=workers.claim_dispatch()
    assert recovered[0]==first.id and recovered[1]!=first.lease_token
    assert workers.claim_dispatch()==(None,None)


@pytest.mark.asyncio
async def test_stale_claim_cannot_execute_or_overwrite_replacement(account, monkeypatch):
    _,ws,_=account
    with session_scope(write=True) as db:
        job=Job(workspace_id=ws,kind='fencing_fixture');db.add(job);db.flush();job_id=job.id
    old,_=workers.claim_dispatch()
    with session_scope(write=True) as db:db.get(Job,job_id).lease_until=now()-timedelta(seconds=1)
    replacement,_=workers.claim_dispatch()
    handler=AsyncMock()
    monkeypatch.setitem(workers.HANDLERS,'fencing_fixture',handler)
    await workers.execute_job(*old)
    handler.assert_not_awaited()
    async def lose_lease(job_id):
        with session_scope(write=True) as db:
            job=db.get(Job,job_id);job.lease_token=uid();job.result={'owner':'replacement'}
        with session_scope(write=True) as db:get_job(db,job_id).result={'owner':'stale'}
    monkeypatch.setitem(workers.HANDLERS,'fencing_fixture',lose_lease)
    await workers.execute_job(*replacement)
    with session_scope() as db:
        job=db.get(Job,job_id)
        assert job.state=='running' and job.result=={'owner':'replacement'} and not job.error


def test_expired_resource_owner_recovers_before_an_older_queued_sibling(account):
    _, ws, _ = account
    with session_scope(write=True) as db:
        kb = KnowledgeBase(workspace_id=ws, name='Recovery ordering')
        db.add(kb); db.flush()
        queued = Job(workspace_id=ws, kind='crawl', payload={'kb_id':kb.id}, created_at=now()-timedelta(hours=2))
        expired = Job(workspace_id=ws, kind='crawl', payload={'kb_id':kb.id}, state='running',
                      lease_until=now()-timedelta(seconds=1), lease_token=uid())
        db.add_all([queued, expired]); db.flush()
        identity, token = expired.id, expired.lease_token
    recovered, _ = workers.claim_dispatch()
    assert recovered[0] == identity and recovered[1] != token
    assert workers.claim_dispatch() == (None, None)


@pytest.mark.asyncio
async def test_long_job_renews_lease_and_worker_stop_drains_it(account, monkeypatch):
    _,ws,_=account
    entered=asyncio.Event();ended=asyncio.Event()
    monkeypatch.setattr(workers,'JOB_HEARTBEAT_SECONDS',.02)
    async def slow(job_id):
        entered.set()
        try:await asyncio.Event().wait()
        finally:ended.set()
    monkeypatch.setitem(workers.HANDLERS,'heartbeat_fixture',slow)
    with session_scope(write=True) as db:
        job=Job(workspace_id=ws,kind='heartbeat_fixture');db.add(job);db.flush();job_id=job.id
    claimed,_=workers.claim_dispatch()
    task=asyncio.create_task(workers.execute_job(*claimed))
    try:
        await asyncio.wait_for(entered.wait(),1)
        with session_scope(write=True) as db:db.get(Job,job_id).lease_until=now()+timedelta(milliseconds=100)
        await asyncio.sleep(.08)
        with session_scope() as db:assert db.get(Job,job_id).lease_until>now()+timedelta(minutes=2)
        assert workers.claim_dispatch()==(None,None)
    finally:
        task.cancel();await asyncio.gather(task,return_exceptions=True)
    assert ended.is_set()


def test_webhook_claim_is_exclusive_and_recovers_expired_delivery(account):
    _,ws,_=account
    with session_scope(write=True) as db:
        endpoint=WebhookEndpoint(workspace_id=ws,url='https://webhook.example',secret='unused',event_types=[])
        db.add(endpoint);db.flush()
        item=Delivery(workspace_id=ws,endpoint_id=endpoint.id,event_id=uid(),event_type='fixture',payload={})
        db.add(item);db.flush();delivery_id=item.id
    assert workers.claim_dispatch()==(None,delivery_id)
    assert workers.claim_dispatch()==(None,None)
    with session_scope(write=True) as db:db.get(Delivery,delivery_id).next_attempt_at=now()-timedelta(seconds=1)
    assert workers.claim_dispatch()==(None,delivery_id)


@pytest.mark.asyncio
@pytest.mark.parametrize('fail',[False,True])
async def test_index_batches_overlap_obey_shared_limit_and_cancel_on_failure(account, monkeypatch, fail):
    _,ws,_=account
    monkeypatch.setattr(settings,'index_concurrency',2)
    monkeypatch.setattr(knowledge,'vector_configured',lambda:True)
    snapshots=[]
    with session_scope(write=True) as db:
        kb=KnowledgeBase(workspace_id=ws,name='Index');db.add(kb);db.flush()
        for index in range(2):
            source=Source(workspace_id=ws,kb_id=kb.id,canonical_url='https://fixture.example/'+str(index),content_hash=str(index))
            db.add(source);db.flush()
            db.add_all(Chunk(workspace_id=ws,source_id=source.id,ordinal=i,text_content=str(i)) for i in range(96))
            snapshot=Snapshot(workspace_id=ws,kb_id=kb.id,revision=index+1,source_ids=[source.id]);db.add(snapshot);db.flush();snapshots.append(snapshot.id)
    active=peak=0;upserted=[]
    async def embed(texts):
        nonlocal active,peak
        active+=1;peak=max(peak,active)
        try:
            if fail and '0' in texts:
                await asyncio.sleep(.01);raise RuntimeError('Fixture embedding failure')
            await asyncio.sleep(.05)
            return [[int(text)] for text in texts]
        finally:active-=1
    class VectorFixture:
        def __init__(self,client):assert client is not None
        async def ensure_collection(self):pass
        async def upsert(self,workspace,snapshot,chunks,vectors):
            assert workspace==ws
            assert vectors==[[int(chunk['text_content'])] for chunk in chunks]
            upserted.extend((snapshot,chunk['id']) for chunk in chunks)
    monkeypatch.setattr(knowledge,'embed',embed)
    monkeypatch.setattr(knowledge,'Qdrant',VectorFixture)
    results=await asyncio.gather(*(knowledge.index_snapshot(ws,snapshot) for snapshot in snapshots),return_exceptions=True)
    assert peak==2 and active==0
    if fail:assert all(isinstance(result,RuntimeError) for result in results)
    else:assert results==[None,None] and len(upserted)==len(set(upserted))==192
    with session_scope() as db:assert all(db.get(Snapshot,snapshot).state=='building' for snapshot in snapshots)


@pytest.mark.asyncio
@pytest.mark.parametrize('dimensions_match',[True,False])
async def test_concurrent_qdrant_creation_requires_compatible_readback(monkeypatch, dimensions_match):
    import httpx
    from studio.retrieval import Qdrant
    calls=[]
    async def request(method,path,**kwargs):
        calls.append((method,path))
        if len(calls)==1 or len(calls)==2:
            response=httpx.Response(404 if len(calls)==1 else 409,request=httpx.Request(method,'https://vector.example'+path))
            response.raise_for_status()
        return {'result':{'config':{'params':{'vectors':{'size':settings.embedding_dimensions if dimensions_match else 42,'distance':'Cosine'}}}}}
    backend=Qdrant();monkeypatch.setattr(backend,'request',request)
    if dimensions_match:
        await backend.ensure_collection()
        assert len(calls)==5
    else:
        with pytest.raises(RuntimeError,match='incompatible'):await backend.ensure_collection()
        assert len(calls)==3

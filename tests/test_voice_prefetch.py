import asyncio
import threading
from types import SimpleNamespace as NS
from unittest.mock import patch

import pytest
from sqlalchemy import select

from studio import admission,knowledge,metering,retrieval
from studio.config import settings
from studio.db import session_scope
from studio.models import BudgetAdmission,CallCostRecord,Chunk,VoiceTimingRecord
from studio.voice_prefetch import InterimPrefetch
from test_voice_latency import voice
from voice_latency_fixture import SyntheticVoiceProviders


@pytest.fixture
def tuning(monkeypatch):
    monkeypatch.setattr(settings,'voice_prefetch_enabled',True)
    monkeypatch.setattr(settings,'voice_prefetch_debounce_ms',10)
    monkeypatch.setattr(settings,'voice_prefetch_max_requests',2)
    monkeypatch.setattr(settings,'voice_prefetch_result_ttl_seconds',5)


async def valid(*args):return True


async def started(prefetch):
    if prefetch.pending is not None:await asyncio.wait_for(prefetch.pending,1)
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_changed_hypotheses_debounce_and_only_exact_normalized_final_reuses(tuning):
    queries=[]
    async def fetch(query,snapshots):
        queries.append((query,snapshots));return {'passages':[],'answerable':False}
    prefetch=InterimPrefetch(fetch,valid)
    try:
        prefetch.observe('How does delivery happen?', ['snapshot-one'])
        prefetch.observe('How  does delivery work?', ['snapshot-one'])
        assert not queries
        await started(prefetch)
        result=await prefetch.take(' How does delivery  work? ',['snapshot-one'])
        assert result[0]['answerable'] is False and len(queries)==1
        assert await prefetch.take('How does delivery work.', ['snapshot-one']) is None
        assert await prefetch.take('How does delivery work?', ['another-snapshot']) is None
    finally:await prefetch.close()


@pytest.mark.asyncio
async def test_only_two_paid_queries_can_run_even_across_new_utterances(tuning):
    release=asyncio.Event();queries=[]
    async def fetch(query,snapshots):
        queries.append(query);await release.wait();return {'passages':[]}
    prefetch=InterimPrefetch(fetch,valid)
    try:
        for query in ['How does delivery work?', 'How does shipping work?', 'How does tracking work?']:
            prefetch.observe(query,[]);await started(prefetch)
        assert len(queries)==2
        prefetch.reset()
        prefetch.observe('How does a refund work?',[]);await started(prefetch)
        assert len(queries)==2  # Old billed work still occupies both bounded slots.
        release.set()
        await asyncio.gather(*list(prefetch.active))
        assert await prefetch.take('How does delivery work?',[]) is None
    finally:
        release.set();await prefetch.close()


@pytest.mark.asyncio
async def test_final_wait_cancellation_does_not_lose_reportable_speculative_usage(tuning):
    entered,release=asyncio.Event(),asyncio.Event()
    completed=[]
    async def fetch(*args):
        entered.set();await release.wait();completed.append(True);return {'passages':[]}
    prefetch=InterimPrefetch(fetch,valid)
    try:
        prefetch.observe('How does delivery work?',[])
        await asyncio.wait_for(entered.wait(),1)
        task=asyncio.create_task(prefetch.take('How does delivery work?',[]))
        await asyncio.sleep(0);task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        assert prefetch.active and not completed
        release.set()
        assert (await prefetch.take('How does delivery work?',[]))[0]=={'passages':[]}
        assert completed==[True]
    finally:
        release.set();await prefetch.close()


@pytest.mark.asyncio
async def test_stale_or_revoked_results_and_disabled_prefetch_are_never_reused(tuning,monkeypatch):
    clock=[0.0];requests=[];allowed=[True]
    async def fetch(*args):requests.append(args);return {'passages':[]}
    async def authorize(*args):return allowed[0]
    prefetch=InterimPrefetch(fetch,authorize,clock=lambda:clock[0])
    try:
        prefetch.observe('How does delivery work?',[]);await started(prefetch)
        assert await prefetch.take('How does delivery work?',[]) is not None
        allowed[0]=False
        assert await prefetch.take('How does delivery work?',[]) is None
        allowed[0]=True;clock[0]=6
        assert await prefetch.take('How does delivery work?',[]) is None
        prefetch.reset()
        prefetch.observe('How does a refund work?',[])
        monkeypatch.setattr(settings,'voice_prefetch_enabled',False)
        await started(prefetch)
        assert len(requests)==1
    finally:await prefetch.close()


@pytest.mark.asyncio
async def test_purged_or_changed_passages_fail_final_authorization(sample):
    _,workspace_id,_,fixture=sample
    with session_scope() as db:
        from studio.models import AgentVersion
        version=db.scalar(select(AgentVersion).where(AgentVersion.agent_id==fixture['agent_id']))
        snapshots=version.config['knowledge_snapshot_ids']
    chunks,sources=knowledge._retrieval_rows(workspace_id,snapshots)
    assert chunks
    chunk=chunks[0];source=sources[chunk.source_id]
    result={'passages':[{'chunk_id':chunk.id,'source_revision_id':source.id,'text':chunk.text_content,
                         'url':source.canonical_url,'title':source.title}]}
    assert knowledge.valid_prefetch(workspace_id,snapshots,result)
    with session_scope(write=True) as db:db.get(Chunk,chunk.id).text_content='Updated synthetic source'
    assert not knowledge.valid_prefetch(workspace_id,snapshots,result)
    with session_scope(write=True) as db:db.delete(db.get(Chunk,chunk.id))
    assert not knowledge.valid_prefetch(workspace_id,snapshots,result)
    assert not knowledge.valid_prefetch('foreign',snapshots,result)


@pytest.mark.asyncio
async def test_actual_final_voice_turn_uses_prefetched_retrieval_and_records_timing(voice,tuning):
    _,_,_,call_id,session,_=voice
    fixture=SyntheticVoiceProviders(retrieval_delay=0,model_first_token=0,token_delay=0,fish_connect=0,fish_first_audio=0,tokens=2)
    requests=[]
    async def fetch(*args):
        requests.append(args);return await fixture.retrieval(*args)
    question='How does this synthetic service work?'
    with fixture.installed(),patch('studio.media.retrieve',fetch):
        session.prefetch.observe(session.retrieval_query(question),[])
        await started(session.prefetch)
        await session.user_text(question,input_kind='stt_final')
        await session.task
    assert len(requests)==1
    with session_scope() as db:
        timing=db.scalar(select(VoiceTimingRecord).where(VoiceTimingRecord.call_id==call_id))
        assert 'retrieval_prefetch_reused' in timing.marks_ms
        assert timing.durations_ms['retrieval_prefetch_ms'] is not None


@pytest.fixture
def uncached_embeddings(monkeypatch):
    from studio import cache
    monkeypatch.setattr(cache,'get_vectors',lambda texts:[None]*len(texts))
    monkeypatch.setattr(cache,'put_vectors',lambda *args:None)
    monkeypatch.setattr(settings,'embedding_dimensions',2)


@pytest.mark.asyncio
async def test_canceled_embedding_admission_is_observed_then_released_before_io(account,uncached_embeddings,monkeypatch):
    _,workspace_id,_=account
    entered,release=threading.Event(),threading.Event()
    original=admission.provider_hold
    def blocked(*args,**kwargs):
        entered.set();assert release.wait(3);return original(*args,**kwargs)
    monkeypatch.setattr(admission,'provider_hold',blocked)
    requests=[]
    async def create(**kwargs):requests.append(kwargs)
    client=NS(embeddings=NS(create=create))
    with metering.scope(workspace_id=workspace_id):task=asyncio.create_task(retrieval.embed(['Synthetic query'],client=client))
    try:
        assert await asyncio.to_thread(entered.wait,1)
        task.cancel();await asyncio.sleep(0)
        assert not task.done()
    finally:release.set()
    with pytest.raises(asyncio.CancelledError):await task
    assert not requests
    with session_scope() as db:
        assert db.scalar(select(BudgetAdmission)).state=='completed'
        assert not list(db.scalars(select(CallCostRecord)))


@pytest.mark.asyncio
async def test_canceled_inflight_embedding_keeps_unknown_hold_and_no_automatic_replay(account,uncached_embeddings):
    _,workspace_id,_=account
    entered=asyncio.Event();requests=[]
    async def create(**kwargs):
        requests.append(kwargs);entered.set();await asyncio.Event().wait()
    client=NS(embeddings=NS(create=create))
    with metering.scope(workspace_id=workspace_id):task=asyncio.create_task(retrieval.embed(['Synthetic query'],client=client))
    await asyncio.wait_for(entered.wait(),1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):await task
    assert len(requests)==1
    with session_scope() as db:
        assert db.scalar(select(CallCostRecord)).source=='unreported'
        assert db.scalar(select(BudgetAdmission)).state=='unknown'


@pytest.mark.asyncio
async def test_reported_embedding_usage_settles_even_when_vector_cache_write_is_canceled(account,uncached_embeddings,monkeypatch):
    _,workspace_id,_=account
    from studio import cache
    entered,release=threading.Event(),threading.Event()
    def store(*args):entered.set();assert release.wait(3)
    monkeypatch.setattr(cache,'put_vectors',store)
    async def create(**kwargs):
        return NS(data=[NS(index=0,embedding=[1.0,0.0])],usage=NS(prompt_tokens=7))
    client=NS(embeddings=NS(create=create))
    with metering.scope(workspace_id=workspace_id):task=asyncio.create_task(retrieval.embed(['Synthetic query'],client=client))
    try:
        assert await asyncio.to_thread(entered.wait,1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
    finally:release.set()
    with session_scope() as db:
        line=db.scalar(select(CallCostRecord))
        assert line.source=='provider_usage' and line.units=={'input_tokens':7}
        assert db.scalar(select(BudgetAdmission)).state=='completed'

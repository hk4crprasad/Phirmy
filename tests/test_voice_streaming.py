import asyncio
from contextlib import suppress
import threading

from fishaudio.types import FlushEvent
import pytest
from sqlalchemy import select

from studio import admission, llm, metering, providers
from studio import knowledge
from studio.config import settings
from studio.db import session_scope
from studio.models import BudgetAdmission
from studio.streaming_budget import SpeechBudget
from test_voice_latency import voice
from voice_latency_fixture import SyntheticVoiceProviders


@pytest.mark.asyncio
async def test_first_short_unpunctuated_delta_reaches_fish_before_model_finishes(voice):
    _, _, _, _, session, transport = voice
    fixture = SyntheticVoiceProviders(retrieval_delay=0,model_first_token=0,token_delay=10,fish_connect=0,fish_first_audio=0)
    fixture.chunks = ['A streaming fragment without punctuation ', 'done.']
    with fixture.installed():
        await session.user_text('Synthetic immediate forwarding',input_kind='stt_final')
        async def audio_arrives():
            while not transport.audio:
                await asyncio.sleep(.001)
        try:
            await asyncio.wait_for(audio_arrives(),2)
            assert fixture.active_model_streams  # Audio precedes the slow remainder.
            assert len(fixture.text_submissions[0]) < 80
            assert not any(value in fixture.text_submissions[0] for value in '.?!,;')
        finally:
            await session.interrupt()
    assert not fixture.active_model_streams and all(socket.closed for socket in fixture.sockets)


@pytest.mark.asyncio
async def test_sentence_and_turn_flushes_are_control_events_not_billed_text(voice):
    _, _, _, _, session, _ = voice
    fixture = SyntheticVoiceProviders(retrieval_delay=0,model_first_token=0,token_delay=0,fish_connect=0,fish_first_audio=0,tokens=2)
    with fixture.installed():
        await session.user_text('Synthetic flush controls',input_kind='stt_final')
        await session.task
    events = fixture.sockets[0].events
    assert events[0]['event']=='start' and events[-1]['event']=='stop'
    assert sum(event['event']=='flush' for event in events)>=2
    assert ''.join(fixture.text_submissions)==''.join(fixture.chunks)


@pytest.mark.asyncio
async def test_tool_pause_flushes_before_confirmation_work(voice,monkeypatch):
    _, _, workspace_id, call_id, session, _ = voice
    class ToolTurn:
        def __init__(self,*args,**kwargs):
            self.calls = [{'id':'ticket-proposal','name':'create_support_ticket','arguments':'{"subject":"Synthetic support"}'}]
        async def stream(self):
            yield 'I can help. '
    monkeypatch.setattr(llm,'Turn',ToolTurn)
    config = {**session.config,'tools':[{'name':'create_support_ticket'}]}
    context = {'workspace_id':workspace_id,'call_id':call_id,'operation_id':'synthetic-tool-pause',
        'user_text':'Please create a support ticket','voice_stream':True}
    fixture = SyntheticVoiceProviders()
    with fixture.installed():
        parts = [part async for part in providers.answer_stream(config,context['user_text'],[],[],context)]
    assert parts[0]=='I can help. '
    assert isinstance(parts[1],FlushEvent)
    assert isinstance(parts[-1],str) and parts[-1]


@pytest.mark.asyncio
async def test_sender_failure_reaches_consumer_without_waiting_for_audio():
    async def broken():
        raise RuntimeError('synthetic text producer failure')
        yield ''
    fixture = SyntheticVoiceProviders(fish_connect=0)
    with fixture.installed():
        async def consume():
            async for _ in providers.speech_stream(broken(),'synthetic-voice'):pass
        with pytest.raises(RuntimeError,match='synthetic text producer failure'):
            await asyncio.wait_for(consume(),1)
    assert all(socket.closed for socket in fixture.sockets)


@pytest.mark.asyncio
async def test_playback_failure_closes_provider_generator_and_model(voice):
    _, _, _, _, session, transport = voice
    async def disconnected(frame):
        raise RuntimeError('synthetic playback transport disconnect')
    transport.send_bytes = disconnected
    fixture = SyntheticVoiceProviders(retrieval_delay=0,model_first_token=0,token_delay=.1,fish_connect=0,fish_first_audio=0)
    with fixture.installed():
        await session.user_text('Synthetic playback failure',input_kind='stt_final')
        await asyncio.wait_for(session.task,2)
    assert not fixture.active_model_streams and all(socket.closed for socket in fixture.sockets)


@pytest.mark.asyncio
async def test_speech_credit_batches_small_deltas_and_settles_only_actual_bytes(voice,monkeypatch):
    _, _, workspace_id, call_id, _, _ = voice
    monkeypatch.setattr(settings,'voice_tts_reservation_bytes',128)
    operation = 'synthetic:batched-speech'
    budget = SpeechBudget({'workspace_id':workspace_id,'call_id':call_id},operation)
    for _ in range(200):
        await budget.reserve(1)
    assert budget.submitted_bytes==200 and budget.reserved_bytes==256
    with session_scope(write=True) as db:
        children = list(db.scalars(select(BudgetAdmission).where(BudgetAdmission.kind=='stream_chunk')))
        assert len(children)==2
        metering.record_cost(db,workspace_id,operation,'fish','tts',{'tts_utf8_bytes':200},call_id=call_id,source='observed_input')
        parent = db.scalar(select(BudgetAdmission).where(BudgetAdmission.operation_key==metering.operation(operation)))
        assert parent.state=='completed' and parent.measured_micro_minor < parent.reserved_micro_minor
        assert metering.usage_summary(db,workspace_id)['held_cost_micro_minor']==0


@pytest.mark.asyncio
async def test_cancel_observes_inflight_budget_transaction_before_settlement(monkeypatch):
    entered, release, committed = threading.Event(), threading.Event(), threading.Event()
    def grant(*args):
        entered.set()
        assert release.wait(3)
        committed.set()
    monkeypatch.setattr(admission,'provider_extend',grant)
    budget = SpeechBudget({},'synthetic-blocking-grant')
    task = asyncio.create_task(budget.reserve(1))
    assert await asyncio.to_thread(entered.wait,1)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert committed.is_set() and budget.submitted_bytes==0


@pytest.mark.asyncio
async def test_interrupt_clears_before_cleanup_and_preserves_new_task_pointer(voice):
    _, _, _, _, session, transport = voice
    entered, release = asyncio.Event(), asyncio.Event()
    async def old_response():
        try:
            entered.set()
            await asyncio.Event().wait()
        finally:
            await release.wait()
    session.task = asyncio.create_task(old_response())
    await entered.wait()
    interruption = asyncio.create_task(session.interrupt())
    async def clear_arrives():
        while not any(event['type']=='server.clear' for event in transport.events):
            await asyncio.sleep(0)
    await asyncio.wait_for(clear_arrives(),1)
    assert not interruption.done() and session.task is None
    newer = asyncio.create_task(asyncio.Event().wait())
    session.task = newer
    release.set()
    await interruption
    assert session.task is newer
    newer.cancel()
    with suppress(asyncio.CancelledError):
        await newer


@pytest.mark.asyncio
async def test_retrieval_database_read_does_not_block_audio_event_loop(voice, monkeypatch):
    _, _, workspace_id, _, _, _ = voice
    main_thread = threading.get_ident()
    entered, release = threading.Event(), threading.Event()
    original = knowledge._retrieval_rows
    def slow_rows(*args):
        assert threading.get_ident()!=main_thread
        entered.set()
        assert release.wait(2)
        return original(*args)
    monkeypatch.setattr(knowledge,'_retrieval_rows',slow_rows)
    task = asyncio.create_task(knowledge.retrieve(workspace_id,[],'synthetic query'))
    try:
        assert await asyncio.to_thread(entered.wait,1)
        await asyncio.sleep(0)  # The audio loop remains schedulable during DB work.
        release.set()
        result = await asyncio.wait_for(task,2)
        assert result['answerable'] is False
    finally:
        release.set()
        await asyncio.gather(task,return_exceptions=True)


@pytest.mark.asyncio
async def test_model_profile_resolution_does_not_run_on_audio_loop(voice, monkeypatch):
    _, _, workspace_id, _, session, _ = voice
    main_thread = threading.get_ident()
    original = llm.resolve
    def resolve(*args):
        assert threading.get_ident()!=main_thread
        return original(*args)
    monkeypatch.setattr(llm,'resolve',resolve)
    parts = [part async for part in providers.answer_stream(session.config,'Synthetic query',[],[],{'workspace_id':workspace_id})]
    assert parts

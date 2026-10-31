import asyncio
import logging

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from studio import media, voice_latency
from studio.db import session_scope
from studio.domain import default_agent
from studio.models import Call, VoiceTimingRecord
from voice_latency_fixture import SyntheticVoiceProviders


class Transport:
    def __init__(self):
        self.events, self.audio = [], []
    async def send_json(self, event):
        self.events.append(event)
    async def send_bytes(self, frame):
        self.audio.append(frame)


@pytest_asyncio.fixture
async def voice(account):
    client, workspace_id, base = account
    with session_scope(write=True) as db:
        call = Call(workspace_id=workspace_id,mode='live',transport='browser',state='connected')
        db.add(call)
        db.flush()
        call_id = call.id
    config = default_agent()
    config['recording']['enabled'] = False
    transport = Transport()
    session = media.VoiceSession(transport,workspace_id,call_id,config,'live',timing_source='synthetic')
    try:
        yield client, base, workspace_id, call_id, session, transport
    finally:
        await session.close_providers()


def test_monotonic_stage_durations_and_missing_audio_are_distinct():
    clock = [10.0]
    trace = voice_latency.Trace('workspace','call',0,'synthetic','stt_final',clock=lambda:clock[0])
    with trace.measure('retrieval'):
        clock[0] += .025
    trace.mark('llm_request_started')
    clock[0] += .075
    trace.mark('llm_first_token')
    clock[0] += .1
    trace.mark('tts_first_text_sent')
    clock[0] += .1
    trace.mark('first_tts_byte')
    assert trace.values()['input_to_first_audio_ms'] is None
    clock[0] += .02
    trace.mark('first_audio_sent')
    trace.finish('completed')
    values = trace.values()
    assert values['retrieval_ms']==25 and values['llm_first_token_ms']==75
    assert values['tts_first_byte_ms']==100 and values['tts_byte_to_audio_sent_ms']==20
    assert values['final_transcript_to_first_audio_ms']==320


@pytest.mark.asyncio
async def test_actual_pipeline_persists_scoped_timings_and_resets_context(voice):
    client, base, workspace_id, call_id, session, transport = voice
    fixture = SyntheticVoiceProviders(retrieval_delay=.002,model_first_token=.002,token_delay=.002,
        fish_connect=.002,fish_first_audio=.002,tokens=4)
    with fixture.installed():
        await session.user_text('Synthetic voice question',input_kind='stt_final')
        await session.task
    assert transport.audio and voice_latency.current.get() is None
    assert not fixture.active_model_streams and all(socket.closed for socket in fixture.sockets)
    result = client.get(base+'/calls/'+call_id)
    assert result.status_code==200
    detail = result.json()['voice_timing']
    assert detail['summaries'][0]['source']=='synthetic'
    assert detail['summaries'][0]['completed_stt_turns']==1
    record = detail['items'][0]
    marks = record['marks_ms']
    assert marks['stt_final']==0
    assert 0 <= marks['retrieval_started'] <= marks['retrieval_complete'] <= marks['llm_request_started']
    assert marks['llm_first_token'] <= marks['tts_first_text_sent'] <= marks['first_tts_byte'] <= marks['first_audio_sent']
    assert record['durations_ms']['final_transcript_to_first_audio_ms'] > 0
    assert 'Synthetic voice question' not in str(record)
    assert client.get('/v1/workspaces/foreign/calls/'+call_id).status_code==404


@pytest.mark.asyncio
async def test_cancel_before_audio_records_interruption_and_closes_model_and_fish(voice):
    client, base, _, call_id, session, transport = voice
    fixture = SyntheticVoiceProviders(retrieval_delay=0,model_first_token=10,fish_connect=0)
    with fixture.installed():
        await session.user_text('Synthetic interrupted question',input_kind='stt_final')
        async def opened():
            while not fixture.active_model_streams:
                await asyncio.sleep(.001)
        await asyncio.wait_for(opened(),2)
        await session.interrupt()
    assert not fixture.active_model_streams and all(socket.closed for socket in fixture.sockets)
    assert not transport.audio
    detail = client.get(base+'/calls/'+call_id).json()['voice_timing']
    assert detail['items'][0]['status']=='interrupted'
    assert detail['items'][0]['durations_ms']['final_transcript_to_first_audio_ms'] is None
    assert detail['summaries'][0]['completed_stt_turns']==0


@pytest.mark.asyncio
async def test_provider_failure_is_not_a_zero_latency_success(voice, monkeypatch):
    client, base, _, call_id, session, _ = voice
    async def failed(*args, **kwargs):
        raise RuntimeError('synthetic disconnected provider')
        yield b''
    monkeypatch.setattr(session.fish,'stream',failed)
    monkeypatch.setattr(session.fish,'prepare',lambda *args:None)
    await session.respond()
    detail = client.get(base+'/calls/'+call_id).json()['voice_timing']
    assert detail['items'][0]['status']=='failed'
    assert detail['items'][0]['durations_ms']['input_to_first_audio_ms'] is None
    assert detail['summaries'][0]['final_transcript_to_first_audio_p50_ms'] is None


def test_persistence_is_idempotent_and_rejects_foreign_call(voice):
    _, _, workspace_id, call_id, _, _ = voice
    trace = voice_latency.Trace(workspace_id,call_id,0,'synthetic','stt_final')
    trace.finish('interrupted')
    assert voice_latency.persist(trace) and voice_latency.persist(trace)
    foreign = voice_latency.Trace('foreign',call_id,0,'synthetic','stt_final')
    assert voice_latency.persist(foreign) is False
    with session_scope() as db:
        assert db.scalar(select(func.count()).select_from(VoiceTimingRecord))==1


def test_summary_excludes_greetings_failures_and_separates_sources(voice):
    client, base, workspace_id, call_id, _, _ = voice
    for source,kind,status,elapsed in [('synthetic','stt_final','completed',100),
        ('synthetic','greeting','completed',1000),('synthetic','stt_final','failed',0),
        ('live','stt_final','completed',300)]:
        clock = [0.0]
        trace = voice_latency.Trace(workspace_id,call_id,0,source,kind,clock=lambda:clock[0])
        clock[0] = elapsed/1000
        trace.mark('first_audio_sent')
        trace.finish(status)
        voice_latency.persist(trace)
    summaries = client.get(base+'/calls/'+call_id).json()['voice_timing']['summaries']
    groups = {row['source']:row for row in summaries}
    assert groups['synthetic']['completed_stt_turns']==1 and groups['synthetic']['final_transcript_to_first_audio_p50_ms']==100
    assert groups['live']['completed_stt_turns']==1 and groups['live']['final_transcript_to_first_audio_p50_ms']==300


@pytest.mark.asyncio
async def test_metric_persistence_outage_does_not_mask_response_or_leak_exception(voice, monkeypatch, caplog):
    _, _, _, _, session, transport = voice
    session.mode = 'simulation'
    def failed(trace):
        raise RuntimeError('synthetic-private-credential')
    monkeypatch.setattr(voice_latency,'persist',failed)
    with caplog.at_level(logging.WARNING):
        await session.respond()
    assert transport.events[-1]['state']=='listening'
    assert 'Voice timing persistence failed' in caplog.text and 'synthetic-private-credential' not in caplog.text


def test_nearest_rank_percentiles_preserve_absence():
    assert voice_latency.percentile([], .95) is None
    assert voice_latency.percentile([40,10,30,20], .5)==20
    assert voice_latency.percentile([40,10,30,20], .95)==40

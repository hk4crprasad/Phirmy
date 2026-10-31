from unittest.mock import patch

import pytest
from sqlalchemy import select

from studio import voice_greetings
from studio.config import settings
from studio.db import session_scope
from studio.domain import default_agent
from studio.models import CallCostRecord, VoiceTimingRecord
from studio.voice_greetings import GreetingCache
from test_voice_latency import voice
from voice_latency_fixture import SyntheticVoiceProviders


def test_greeting_keys_fence_tenants_versions_exact_disclosures_and_voice(monkeypatch):
    cache=GreetingCache()
    config=default_agent()
    key=cache.key('workspace','version',config,'Static AI greeting.')
    assert key is not None
    cache.put(key,b'\x01\x00'*100)
    assert cache.get(key)==b'\x01\x00'*100
    assert cache.get(cache.key('other','version',config,'Static AI greeting.')) is None
    assert cache.get(cache.key('workspace','other',config,'Static AI greeting.')) is None
    assert cache.get(cache.key('workspace','version',config,'Static AI greeting. This call is being recorded.')) is None
    changed={**config,'speech':{**config['speech'],'voice_id':'another-voice'}}
    assert cache.get(cache.key('workspace','version',changed,'Static AI greeting.')) is None
    for altered in [{**config,'_runtime_variables':{'name':'Private caller'}},
                    {**config,'variables':[{'name':'name','default':'Private caller'}]}]:
        assert cache.key('workspace','version',altered,'Personalized hello') is None
    assert cache.key('workspace','version',config,'Hello {{ name }}') is None
    assert cache.key('workspace',None,config,'Hello') is None
    monkeypatch.setattr(settings,'voice_greeting_cache_enabled',False)
    assert cache.key('workspace','version',config,'Hello') is None and cache.get(key) is None


def test_cache_expires_and_bounds_memory_entries_and_pcm_size():
    clock=[0.0];cache=GreetingCache(clock=lambda:clock[0])
    config=default_agent()
    for index in range(100):
        key=cache.key('workspace',str(index),config,'Hello')
        cache.put(key,b'\0'*100_000)
    assert cache.size<=cache.MAX_TOTAL_BYTES and len(cache.items)<=cache.MAX_ENTRIES
    assert cache.get(cache.key('workspace','0',config,'Hello')) is None
    assert cache.get(key)==b'\0'*100_000
    cache.put(key,b'\0'*(cache.MAX_CLIP_BYTES+2))
    cache.put(key,b'\0')
    assert cache.get(key)==b'\0'*100_000  # Invalid replacements do not poison it.
    clock[0]=cache.TTL_SECONDS
    assert cache.get(key) is None and cache.size==0 and not cache.items


@pytest.mark.asyncio
async def test_cached_greeting_replays_audio_transcript_without_new_fish_cost(voice):
    _,_,_,call_id,session,transport=voice
    session.agent_version_id='synthetic-version'
    fixture=SyntheticVoiceProviders(fish_connect=0,fish_first_audio=0)
    cache=GreetingCache()
    with fixture.installed(),patch.object(voice_greetings,'cache',cache):
        await session.respond()
        first_audio=list(transport.audio)
        assert first_audio and len(fixture.sockets)==1
        await session.respond()
        assert len(fixture.sockets)==1 and len(transport.audio)==2*len(first_audio)
        from studio.media import HEADER
        assert [x[HEADER.size:] for x in transport.audio[len(first_audio):]]==[x[HEADER.size:] for x in first_audio]
        final=[e for e in transport.events if e['type']=='server.transcript' and e['final']]
        assert len(final)==2 and final[0]['text']==final[1]['text']==session.config['greeting']
        with session_scope() as db:
            costs=list(db.scalars(select(CallCostRecord).where(CallCostRecord.call_id==call_id,CallCostRecord.provider=='fish')))
            timings=list(db.scalars(select(VoiceTimingRecord).where(VoiceTimingRecord.call_id==call_id)))
        assert len(costs)==1 and costs[0].units['tts_utf8_bytes']==len(session.config['greeting'].encode())
        assert sum('greeting_cache_hit' in row.marks_ms for row in timings)==1
        assert all(row.status=='completed' for row in timings)


@pytest.mark.asyncio
async def test_personalized_and_interrupted_greetings_are_not_cached(voice):
    _,_,_,_,session,transport=voice
    session.agent_version_id='synthetic-version'
    fixture=SyntheticVoiceProviders(fish_connect=0,fish_first_audio=0)
    cache=GreetingCache()
    with fixture.installed(),patch.object(voice_greetings,'cache',cache):
        session.config['_runtime_variables']={'name':'Private caller'}
        await session.respond()
        await session.respond()
        assert len(fixture.sockets)==2 and not cache.items
        session.config.pop('_runtime_variables')
        async def disconnected(*args):raise RuntimeError('Synthetic disconnected playback')
        transport.send_bytes=disconnected
        await session.respond()
        assert not cache.items and all(socket.closed for socket in fixture.sockets)


@pytest.mark.asyncio
async def test_recording_announcement_changes_cache_and_silence_checkins_do_not_cache(voice):
    _,_,_,_,session,_=voice
    session.agent_version_id='synthetic-version'
    fixture=SyntheticVoiceProviders(fish_connect=0,fish_first_audio=0)
    cache=GreetingCache()
    with fixture.installed(),patch.object(voice_greetings,'cache',cache):
        await session.respond()
        session.recording.enabled=True
        before = len(fixture.text_submissions)
        await session.respond()
        assert len(fixture.sockets)==2 and len(cache.items)==2
        assert ''.join(fixture.text_submissions[before:]) == session.config['greeting'] + ' This call is being recorded.'
        await session.respond(announcement='Synthetic check-in')
        await session.respond(announcement='Synthetic check-in')
        assert len(fixture.sockets)==4 and len(cache.items)==2

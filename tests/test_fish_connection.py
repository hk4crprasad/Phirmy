import asyncio
from contextlib import aclosing
from unittest.mock import AsyncMock, patch

import msgpack
import pytest
from fishaudio.types import FlushEvent

from studio.fish_stream import FishCall
from studio.config import settings
from test_voice_latency import voice
from voice_latency_fixture import SyntheticVoiceProviders


async def words():
    yield 'Synthetic greeting.'
    yield FlushEvent()


@pytest.mark.asyncio
async def test_prepare_is_empty_idempotent_and_stream_uses_exact_socket():
    fixture = SyntheticVoiceProviders(fish_connect=0, fish_first_audio=0)
    owner = FishCall()
    with fixture.installed():
        try:
            prepared = owner.prepare('voice')
            assert owner.prepare('voice') is prepared
            await prepared.task
            assert len(fixture.sockets)==1 and fixture.text_submissions==[]
            assert [event['event'] for event in fixture.sockets[0].events]==['start']
            audio = [chunk async for chunk in owner.stream(words(),'voice')]
            assert audio and len(fixture.sockets)==1
            assert fixture.sockets[0].closed
            assert [event['event'] for event in fixture.sockets[0].events]==['start','text','flush','stop']
            # finish closes the documented session; a new turn must get a new one.
            assert [chunk async for chunk in owner.stream(words(),'voice')]
            assert len(fixture.sockets)==2 and all(socket.closed for socket in fixture.sockets)
        finally:await owner.close()


@pytest.mark.asyncio
async def test_close_cancels_connect_and_never_leaves_prepared_socket():
    fixture = SyntheticVoiceProviders(fish_connect=30)
    owner = FishCall()
    with fixture.installed():
        generation = owner.prepare('voice')
        await asyncio.sleep(0)
        await asyncio.wait_for(owner.close(),1)
        assert generation.task.cancelled() and not fixture.sockets
        with pytest.raises(RuntimeError,match='closed'):owner.prepare('voice')


@pytest.mark.asyncio
async def test_cancel_after_first_audio_closes_sender_and_socket_without_replay():
    fixture = SyntheticVoiceProviders(fish_connect=0,fish_first_audio=0)
    owner = FishCall()
    producer_closed = asyncio.Event()
    async def slow_words():
        try:
            yield 'Synthetic prefix'
            await asyncio.Event().wait()
        finally:producer_closed.set()
    with fixture.installed():
        async with aclosing(owner.stream(slow_words(),'voice')) as audio:
            assert await anext(audio)
        assert producer_closed.is_set()
        assert fixture.text_submissions==['Synthetic prefix']
        assert all(socket.closed for socket in fixture.sockets)
        await owner.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('event',[{'event':'finish','reason':'stop'}, {'event':'finish','reason':'error'},
                                 {'event':'audio','audio':b'x'}])
async def test_premature_finish_error_and_invalid_pcm_fail_closed(event):
    fixture = SyntheticVoiceProviders(fish_connect=0,fish_first_audio=30)
    owner = FishCall()
    async def slow_words():
        await asyncio.Event().wait()
        yield 'Never submitted'
    with fixture.installed():
        prepared=owner.prepare('voice')
        socket=await prepared.task
        await socket.outputs.put(msgpack.packb(event,use_bin_type=True))
        with pytest.raises(RuntimeError):
            await asyncio.wait_for(anext(owner.stream(slow_words(),'voice')),1)
        assert not fixture.text_submissions and socket.closed
        await owner.close()


@pytest.mark.asyncio
async def test_media_connects_while_retrieval_is_waiting(voice):
    _,_,_,_,session,_=voice
    fixture=SyntheticVoiceProviders(fish_connect=0,fish_first_audio=0,model_first_token=0,token_delay=0,tokens=1)
    entered,release=asyncio.Event(),asyncio.Event()
    async def retrieval(*args):
        entered.set()
        await release.wait()
        return {'answerable':True,'passages':[]}
    with fixture.installed(),patch('studio.media.retrieve',retrieval):
        await session.user_text('Synthetic parallel retrieval question')
        await asyncio.wait_for(entered.wait(),1)
        prepared=session.fish.generation
        await asyncio.wait_for(prepared.task,1)
        assert len(fixture.sockets)==1 and not fixture.text_submissions
        release.set()
        await asyncio.wait_for(session.task,3)
        assert fixture.text_submissions and all(socket.closed for socket in fixture.sockets)


@pytest.mark.asyncio
async def test_cancellation_during_retrieval_closes_unused_prepared_connection(voice):
    _,_,_,_,session,_=voice
    fixture=SyntheticVoiceProviders(fish_connect=0)
    entered=asyncio.Event()
    async def retrieval(*args):
        entered.set()
        await asyncio.Event().wait()
    with fixture.installed(),patch('studio.media.retrieve',retrieval):
        await session.user_text('Synthetic interrupted retrieval question')
        await asyncio.wait_for(entered.wait(),1)
        await session.fish.generation.task
        await session.interrupt()
        assert fixture.sockets and all(socket.closed for socket in fixture.sockets)
        assert not fixture.text_submissions and fixture.model_requests==0


@pytest.mark.asyncio
async def test_disabled_preconnect_does_not_open_before_retrieval(voice,monkeypatch):
    _,_,_,_,session,_=voice
    monkeypatch.setattr(settings,'voice_fish_preconnect_enabled',False)
    fixture=SyntheticVoiceProviders(fish_connect=0,fish_first_audio=0,model_first_token=0,token_delay=0,tokens=1)
    async def retrieval(*args):
        assert session.fish.generation is None and not fixture.sockets
        return {'answerable':True,'passages':[]}
    with fixture.installed(),patch('studio.media.retrieve',retrieval):
        await session.user_text('Synthetic no preconnect question')
        await session.task
    assert len(fixture.sockets)==1 and fixture.sockets[0].closed

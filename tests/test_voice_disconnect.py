import asyncio
import json
from contextlib import suppress
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from test_voice_latency import voice
from voice_latency_fixture import SyntheticVoiceProviders


@pytest.mark.asyncio
@pytest.mark.parametrize('termination',['clean','exception','invalid_json'])
async def test_recognition_disconnect_wakes_pending_client_receive_and_cleans_streams(voice,termination):
    _,_,_,_,session,transport=voice
    fixture=SyntheticVoiceProviders(retrieval_delay=0,fish_connect=0,model_first_token=30)
    class Deepgram:
        async def __aiter__(self):
            if termination=='exception':raise RuntimeError('Private provider diagnostic must not escape')
            if termination=='invalid_json':yield 'not json'
            return
    session.dg=Deepgram()
    receive_canceled=asyncio.Event()
    async def receive():
        try:await asyncio.Event().wait()
        finally:receive_canceled.set()
    with fixture.installed():
        await session.user_text('Synthetic ongoing voice response')
        async def model_started():
            while not fixture.active_model_streams:await asyncio.sleep(.001)
        await asyncio.wait_for(model_started(),2)
        pending=asyncio.create_task(session.receive(receive(),timeout=30))
        await session.recognize()
        with pytest.raises(RuntimeError,match='Speech recognition disconnected'):
            await asyncio.wait_for(pending,1)
        assert session.provider_failed and receive_canceled.is_set()
        session.closed=True
        await session.close_providers()
    assert not fixture.active_model_streams and all(socket.closed for socket in fixture.sockets)
    assert any(event['type']=='server.clear' for event in transport.events)
    assert not any('Private provider diagnostic' in str(event) for event in transport.events)


@pytest.mark.asyncio
async def test_intentional_recognition_shutdown_is_not_a_provider_failure(voice):
    _,_,_,_,session,_=voice
    class Deepgram:
        async def __aiter__(self):
            await asyncio.Event().wait()
            yield '{}'
    session.dg=Deepgram()
    task=asyncio.create_task(session.recognize())
    await asyncio.sleep(0)
    session.closed=True
    task.cancel()
    with suppress(asyncio.CancelledError):await task
    assert not session.provider_failed and not session.provider_failure.is_set()


@pytest.mark.asyncio
async def test_receive_timeout_and_external_cancel_do_not_leave_pending_waiters(voice):
    _,_,_,_,session,_=voice
    cleaned=asyncio.Event()
    async def receive():
        try:await asyncio.Event().wait()
        finally:cleaned.set()
    with pytest.raises(asyncio.TimeoutError):await session.receive(receive(),timeout=.01)
    assert cleaned.is_set()
    cleaned.clear()
    task=asyncio.create_task(session.receive(receive(),timeout=30))
    await asyncio.sleep(.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):await task
    assert cleaned.is_set()


@pytest.mark.asyncio
async def test_common_carrier_recognition_path_enforces_admitted_duration_before_send(voice):
    _,_,_,_,session,_=voice
    session.admitted_max_seconds=1
    session.dg=type('Deepgram',(),{'send':AsyncMock()})()
    await session.recognition_audio(b'\0'*32_000)
    with pytest.raises(HTTPException) as error:await session.recognition_audio(b'\0\0')
    assert error.value.status_code==429
    assert session.stt_samples==16_000 and session.dg.send.await_count==1


@pytest.mark.parametrize('provider',['twilio','plivo'])
def test_actual_carrier_socket_closes_on_recognition_disconnect_and_records_stt(sample,monkeypatch,provider):
    import base64
    from sqlalchemy import select
    from studio import twilio_routes, carrier, llm
    from studio.config import settings
    from studio.db import session_scope
    from studio.media import VoiceSession
    from studio.models import Call, CallCostRecord
    from studio.security import capability
    client,workspace_id,base,fixture=sample
    agent=client.get(base+'/agents/'+fixture['agent_id']).json()
    with session_scope(write=True) as db:
        call=Call(workspace_id=workspace_id,agent_version_id=agent['published_version_id'],mode='live',
                  transport='pstn',state='connecting',provider_call_id='synthetic-carrier-leg',
                  metadata_data={'provider':provider,'admitted_max_seconds':10})
        db.add(call);db.flush();call_id=call.id
    monkeypatch.setattr(settings,'live_calls_enabled',True)
    monkeypatch.setattr(twilio_routes,'live_voice_ready',lambda *args:True)
    monkeypatch.setattr(llm,'live_voice_ready',lambda *args:True)
    monkeypatch.setattr(twilio_routes,'call_credentials',lambda call:{'account_sid':'synthetic-account'})
    sockets=[]
    class Deepgram:
        def __init__(self):self.received=asyncio.Event();self.closed=False
        async def send(self,pcm):self.received.set()
        async def __aiter__(self):
            await self.received.wait()
            return
            yield ''
        async def close(self):self.closed=True
    async def connect(url,**kwargs):
        assert url.startswith('wss://api.deepgram.com/')
        socket=Deepgram();sockets.append(socket);return socket
    monkeypatch.setattr(twilio_routes.websockets,'connect',connect)
    class Session(VoiceSession):
        async def respond(self,*args,**kwargs):await asyncio.Event().wait()
    monkeypatch.setattr(twilio_routes,'VoiceSession',Session)
    monkeypatch.setattr(carrier,'VoiceSession',Session)
    token=capability({'aud':'twilio-media' if provider=='twilio' else 'carrier','workspace_id':workspace_id,'call_id':call_id,'provider_call_id':'synthetic-carrier-leg'})
    from test_media_lifecycle import assert_no_sql_on_running_loop
    path='/v1/twilio-media/' if provider=='twilio' else '/v1/carrier-media/'
    with assert_no_sql_on_running_loop(), client.websocket_connect(path+token) as ws:
        ws.send_json({'event':'start','streamSid':'synthetic-stream','start':{'accountSid':'synthetic-account',
            'callSid':'synthetic-carrier-leg','callId':'synthetic-carrier-leg','streamSid':'synthetic-stream','streamId':'synthetic-stream','mediaFormat':{
                'encoding':'audio/x-mulaw','sampleRate':8000}}})
        ws.send_json({'event':'media','streamSid':'synthetic-stream','streamId':'synthetic-stream',
                      'media':{'track':'inbound','payload':base64.b64encode(b'\xff'*800).decode()}})
        while ws.receive()['type']!='websocket.close':pass
    assert sockets and all(socket.closed for socket in sockets)
    with session_scope() as db:
        assert db.get(Call,call_id).state=='failed'
        costs=list(db.scalars(select(CallCostRecord).where(CallCostRecord.call_id==call_id,CallCostRecord.provider=='deepgram')))
        assert len(costs)==1 and costs[0].units['stt_ms']>0


@pytest.mark.asyncio
async def test_silence_sends_one_checkin_then_ends_idle_call(voice):
    _,_,_,_,session,transport=voice
    session.config['behavior']={**session.config['behavior'],'silence_prompt_seconds':0,'idle_end_seconds':1}
    prompts=[]
    async def checkin(*args,**kwargs):prompts.append(kwargs['announcement'])
    session.respond=checkin
    transport.close=AsyncMock()
    await asyncio.wait_for(session.watch_idle(),4)
    assert len(prompts)==1 and session.checkin_sent
    assert transport.close.await_count==1
    assert any(event['type']=='server.idle' and event['reason']=='idle_timeout' for event in transport.events)

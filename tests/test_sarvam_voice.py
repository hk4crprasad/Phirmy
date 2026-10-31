"""Offline Sarvam wire contracts through the real browser/carrier media engine."""
import asyncio
import base64
from contextlib import aclosing
import json
from urllib.parse import parse_qs, urlsplit

import httpx
from openai import AsyncOpenAI
import pytest
from sqlalchemy import select
from fishaudio.types import FlushEvent

from studio.config import settings
from studio import llm_connections, sarvam_stt, sarvam_tts
from studio.db import session_scope
from studio.models import Call, CallCostRecord, Turn as StoredTurn
from studio.voice_config import speech_config, voice_profile


@pytest.mark.asyncio
async def test_markdown_speech_preserves_product_facts_across_arbitrary_token_splits():
    from studio.speech_text import speech_chunks
    text = ('## Products\n- **Pink Crystal Silver-Tone Bracelet** — ₹79,900.50\n'
            '- [Demo Gold Bracelet](https://example.test/products/gold) — ₹64,900\n'
            '- _नीला ब्रेसलेट_ — ₹5,00,000\nSKU P_001.\n')
    async def fragments():
        for character in text:
            yield character
        yield FlushEvent()
    spoken = ''.join([part async for part in speech_chunks(fragments()) if isinstance(part, str)])
    assert not any(marker in spoken for marker in ('**', '##', 'https://', '](', '`'))
    for fact in ('Pink Crystal Silver-Tone Bracelet', '₹79,900.50', 'Demo Gold Bracelet',
                 '₹64,900', 'नीला ब्रेसलेट', '₹5,00,000', 'P_001'):
        assert fact in spoken


@pytest.mark.asyncio
async def test_symbol_only_model_fragments_never_reach_sarvam(wire):
    from studio.speech_text import speech_chunks
    async def formatted():
        for part in ['**', 'Demo bracelet', '**', ' — ', '₹', '79,900.50', '\n', '***', '\n']:
            yield part
            if part == '**':
                yield FlushEvent()
    owner = sarvam_tts.SarvamCall(speech_config({}))
    try:
        audio = b''.join([part async for part in owner.stream(speech_chunks(formatted()),
            settings.sarvam_voice_id, settings.sarvam_tts_model)])
        assert audio
        texts = [message['data']['text'] for socket in wire[0] for message in socket.sent if message['type'] == 'text']
        assert all(any(c.isalnum() for c in part) for part in texts)
        assert '**' not in ''.join(texts) and '₹79,900.50' in ''.join(texts)
    finally:
        await owner.close()


def test_auto_spoken_language_resolves_supported_asr_and_native_scripts_only():
    from studio.voice_config import spoken_language
    assert speech_config({'speech': {'language_code': 'auto'}})['language_code'] == 'auto'
    assert spoken_language('Hello') == 'en-IN'
    assert spoken_language('नमस्ते') == 'hi-IN'
    assert spoken_language('தமிழ்') == 'ta-IN'
    assert spoken_language('Romanised words', 'mr-IN') == 'mr-IN'
    assert spoken_language('hello', 'ur-IN') == 'en-IN'
    assert spoken_language('ନମସ୍କାର', 'or-IN') == 'od-IN'


@pytest.mark.asyncio
async def test_auto_language_reconfigures_synthesis_without_sending_auto(wire):
    owner = sarvam_tts.SarvamCall(speech_config({'speech': {'language_code': 'auto'}}))
    try:
        for language in ('en-IN', 'hi-IN', 'hi-IN'):
            await owner.set_language(language)
            assert b''.join([part async for part in owner.stream(words(), settings.sarvam_voice_id, settings.sarvam_tts_model)])
        sockets, _ = wire
        assert len(sockets) == 2 and sockets[0].closed
        languages = [m['data']['language_code'] for socket in sockets for m in socket.sent if m['type'] == 'config']
        assert languages == ['en-IN', 'hi-IN']
    finally:
        await owner.close()


@pytest.mark.asyncio
async def test_audio_pacing_rebases_after_first_byte_and_chunk_stalls_and_oversleep():
    from studio.media import AudioPacer
    clock = [0.0]
    waits = []
    async def sleep(delay):
        waits.append(delay)
        clock[0] += delay
    pacer = AudioPacer(clock=lambda: clock[0], sleep=sleep)
    clock[0] = 3.0  # First synthesis bytes arrive well after turn startup.
    queue_end = clock[0]
    for group in range(3):
        if group:
            clock[0] += 2.5  # Provider pause: never repay this with a burst.
        for _ in range(100):
            await pacer.wait(.02)
            queue_end = max(clock[0], queue_end) + .02
            assert queue_end - clock[0] <= .181
    assert waits and all(0 < value <= .021 for value in waits)
    async def delayed_sleep(delay):
        clock[0] += delay + 4  # A blocked event loop wakes up very late.
    pacer.sleep = delayed_sleep
    await pacer.wait(.02)
    pacer.sleep = sleep
    queue_end = clock[0]
    for _ in range(100):
        await pacer.wait(.02)
        queue_end = max(clock[0], queue_end) + .02
        assert queue_end - clock[0] <= .181


@pytest.mark.asyncio
async def test_audio_pacing_wait_remains_interruptible():
    from studio.media import AudioPacer
    entered = asyncio.Event()
    async def blocked(delay):
        entered.set()
        await asyncio.Event().wait()
    pacer = AudioPacer(clock=lambda: 0, sleep=blocked)
    pacer.next_send = 5
    task = asyncio.create_task(pacer.wait(.02))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.fixture(autouse=True)
def sarvam_settings(monkeypatch):
    monkeypatch.setattr(settings, 'voice_provider', 'sarvam')
    monkeypatch.setattr(settings, 'sarvam_api_key', 'synthetic-offline-sarvam')
    monkeypatch.setattr(settings, 'voice_greeting_cache_enabled', False)


class Socket:
    def __init__(self, stt=False):
        self.stt, self.closed, self.transcribed = stt, False, False
        self.outputs = asyncio.Queue()
        self.sent = []
        if stt:
            self.outputs.put_nowait(json.dumps({'event':'session.begin','config':{'model':'saaras:v4'}}))

    async def send(self, raw):
        message = json.loads(raw)
        self.sent.append(message)
        if self.stt:
            if message['event'] == 'audio_input' and not self.transcribed:
                self.transcribed = True
                assert base64.b64decode(message['audio'])
                for event in [
                    {'event':'vad.speech_start','utterance_idx':0},
                    {'event':'transcript.partial','utterance_idx':0,'text':'What are'},
                    {'event':'transcript.final','utterance_idx':0,'text':'What are your hours?'},
                ]:
                    self.outputs.put_nowait(json.dumps(event))
            elif message['event'] == 'end':
                self.outputs.put_nowait(json.dumps({'event':'session.end','audio_duration_s':.1}))
        elif message['type'] == 'config':
            assert message['data']['output_audio_codec'] == 'linear16'
            assert message['data']['speech_sample_rate'] == 24000
        elif message['type'] == 'text':
            self.outputs.put_nowait(json.dumps({'type':'audio','data':{'audio':base64.b64encode(b'\0'*1920).decode()}}))
        elif message['type'] == 'flush':
            self.outputs.put_nowait(json.dumps({'type':'event','data':{'event_type':'final'}}))

    async def recv(self):
        value = await self.outputs.get()
        if value is None:
            raise RuntimeError('Synthetic disconnected socket')
        return value

    def __aiter__(self):
        return self

    async def __anext__(self):
        value = await self.outputs.get()
        if value is None:
            raise StopAsyncIteration
        return value

    async def close(self):
        self.closed = True
        self.outputs.put_nowait(None)


def sse(delta=None, finish=None, usage=None):
    body = {'id':'synthetic-turn','object':'chat.completion.chunk','created':0,
            'model':'sarvam-105b-conversations','choices':[]}
    if delta is not None or finish:
        body['choices'] = [{'index':0,'delta':delta or {},'finish_reason':finish}]
    if usage:
        body['usage'] = usage
    return 'data: '+json.dumps(body)+'\n\n'


@pytest.fixture
def wire(monkeypatch):
    sockets, requests = [], []
    async def connect(url, **kwargs):
        parsed = urlsplit(url)
        assert parsed.hostname == 'api.sarvam.ai'
        params = parse_qs(parsed.query)
        stt = parsed.path == '/speech-to-text-realtime/ws'
        assert params['model'] == ['saaras:v4' if stt else 'bulbul:v4-flash']
        if stt:
            assert params['stream_type'] == ['fast'] and params['sample_rate'] == ['16000']
        else:
            assert params['send_completion_event'] == ['true']
        assert kwargs['additional_headers'] == {'api-subscription-key':'synthetic-offline-sarvam'}
        socket = Socket(stt)
        sockets.append(socket)
        return socket
    monkeypatch.setattr(sarvam_stt.websockets, 'connect', connect)

    def handle(request):
        payload = json.loads(request.content)
        requests.append(payload)
        assert str(request.url) == 'https://api.sarvam.ai/v1/chat/completions'
        assert payload['model'] == 'sarvam-105b-conversations'
        assert payload['reasoning_effort'] is None and payload['stream']
        assert 'stream_options' not in payload and 'prompt_cache_options' not in payload
        content = sse({'content':'We are open today.'})+sse(finish='stop')+sse(usage={'prompt_tokens':100,'completion_tokens':10})+'data: [DONE]\n\n'
        return httpx.Response(200,headers={'content-type':'text/event-stream'},content=content)
    async def client(profile):
        return AsyncOpenAI(api_key=profile['api_key'],base_url=profile['base_url'],max_retries=0,
                           http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)))
    monkeypatch.setattr(llm_connections,'create_client',client)
    return sockets, requests


async def words():
    yield 'Hello.'
    yield FlushEvent()
    yield FlushEvent()  # duplicate markers must not create ambiguous empty flushes


@pytest.mark.asyncio
async def test_tts_reuses_completed_socket_and_discards_interrupted_generation(wire):
    sockets, _ = wire
    speech = speech_config({})
    owner = sarvam_tts.SarvamCall(speech)
    try:
        for _ in range(2):
            assert b''.join([chunk async for chunk in owner.stream(words(), speech['voice_id'], speech['model'])]) == b'\0'*1920
        assert len(sockets) == 1 and not sockets[0].closed
        assert len([m for m in sockets[0].sent if m['type']=='flush']) == 2
        producer_closed = asyncio.Event()
        async def pending():
            try:
                yield 'Interrupted text'
                await asyncio.Event().wait()
            finally:
                producer_closed.set()
        async with aclosing(owner.stream(pending(),speech['voice_id'],speech['model'])) as stream:
            assert await anext(stream)
        assert sockets[0].closed and producer_closed.is_set()
        assert [chunk async for chunk in owner.stream(words(),speech['voice_id'],speech['model'])]
        assert len(sockets) == 2
    finally:
        await owner.close()
    assert all(s.closed for s in sockets)


@pytest.mark.asyncio
@pytest.mark.parametrize('event',[
    {'type':'audio','data':{'audio':base64.b64encode(b'x').decode()}},
    {'type':'event','data':{'event_type':'final'}},
    {'type':'error','data':{'message':'private provider text'}},
])
async def test_bad_tts_frames_fail_closed_without_waiting_for_silence(wire,event):
    sockets, _ = wire
    speech = speech_config({})
    owner = sarvam_tts.SarvamCall(speech)
    generation = owner.prepare(speech['voice_id'],speech['model'])
    socket = await generation.task
    socket.outputs.put_nowait(json.dumps(event))
    async def pending():
        await asyncio.Event().wait()
        yield 'not submitted'
    try:
        with pytest.raises(RuntimeError):
            async with aclosing(owner.stream(pending(),speech['voice_id'],speech['model'])) as stream:
                await asyncio.wait_for(anext(stream),1)
        assert socket.closed
    finally:
        await owner.close()


@pytest.mark.asyncio
async def test_close_during_tts_connect_cancels_owned_task(monkeypatch):
    async def connect(*args,**kwargs):
        await asyncio.Event().wait()
    monkeypatch.setattr(sarvam_tts.websockets,'connect',connect)
    speech = speech_config({})
    owner = sarvam_tts.SarvamCall(speech)
    generation = owner.prepare(speech['voice_id'],speech['model'])
    await asyncio.sleep(0)
    await asyncio.wait_for(owner.close(),1)
    assert generation.task.cancelled()


@pytest.mark.asyncio
async def test_stt_partial_revisions_duplicate_finals_and_session_usage(wire):
    session = await sarvam_stt.Recognition.connect('auto')
    try:
        for event in [
            {'event':'vad.speech_start','utterance_idx':0},
            {'event':'transcript.partial','utterance_idx':0,'text':'ice'},
            {'event':'transcript.partial','utterance_idx':0,'text':'ice cream'},
            {'event':'transcript.final','utterance_idx':0,'text':'ice cream.','language_code':'en-IN'},
            {'event':'transcript.final','utterance_idx':0,'text':'ice cream.'},
            {'event':'transcript.partial','utterance_idx':0,'text':'stale'},
            {'event':'session.end','audio_duration_s':1.25},
        ]:
            session.socket.outputs.put_nowait(json.dumps(event))
        messages = [json.loads(raw) async for raw in session]
        assert [m['type'] for m in messages] == ['SpeechStarted','Results','Results','Results']
        assert sum(bool(m.get('speech_final')) for m in messages)==1 and session.billed_ms==1250
        assert messages[-1]['language']=='en-IN'
    finally:
        await session.close()


def test_old_agent_voice_is_normalized_but_text_model_is_preserved(monkeypatch):
    from studio.llm import resolve,live_voice_ready
    original = {'llm':{'model':settings.openai_model},'speech':{'provider':'fish','voice_id':'old-fish-id','live_stt_language':'hi'}}
    speech = speech_config(original)
    assert speech['model']=='bulbul:v4-flash' and speech['live_stt_model']=='saaras:v4'
    assert speech['voice_id']==settings.sarvam_voice_id and speech['live_stt_language']=='hi-IN'
    assert resolve(original)['model']==settings.openai_model
    assert voice_profile()['model']=='sarvam-105b-conversations' and live_voice_ready(original,None)
    monkeypatch.setattr(settings,'sarvam_api_key','')
    assert not live_voice_ready(original,None) and not settings.capabilities()['live_voice']


def test_sarvam_costs_use_characters_and_second_billing():
    from studio.metering import cost_micro,MICRO,effective_rates
    from studio.plans import catalog
    body = catalog()
    rates = body['provider_rates']
    assert cost_micro(rates,'sarvam-stt',{'stt_ms':60000})==49*MICRO
    assert cost_micro(rates,'sarvam-stt',{'stt_ms':1})==cost_micro(rates,'sarvam-stt',{'stt_ms':1000})
    assert cost_micro(rates,'sarvam-tts',{'tts_characters':1000,'tts_utf8_bytes':3000})==100*MICRO
    assert cost_micro(body['model_rates']['sarvam-105b-conversations'],'sarvam-llm',{'input_tokens':1000000,'output_tokens':1000000})==7500*MICRO
    from fastapi import HTTPException
    with pytest.raises(HTTPException):effective_rates({'provider_rates':{}},'sarvam-stt')


def test_delayed_synthesis_is_paced_by_actual_media_websocket(sample, wire, monkeypatch):
    from studio.media import HEADER
    original = Socket.send
    async def delayed_clip(self, raw):
        message = json.loads(raw)
        if not self.stt and message['type'] == 'text':
            self.sent.append(message)
            await asyncio.sleep(1.25)
            self.outputs.put_nowait(json.dumps({'type': 'audio', 'data': {
                'audio': base64.b64encode(b'\0' * 96000).decode()}}))
            return
        await original(self, raw)
    monkeypatch.setattr(Socket, 'send', delayed_clip)
    client, _, base, fixture = sample
    response = client.post(base + '/voice/sessions', json={'agent_id': fixture['agent_id'], 'mode': 'live'})
    assert response.status_code == 201
    stamps = []
    with client.websocket_connect('/v1/media', headers={'Origin': settings.app_origin}) as ws:
        ws.send_json({'type': 'client.start', 'session_token': response.json()['session_token']})
        while True:
            event = ws.receive()
            assert event['type'] != 'websocket.close'
            if event.get('bytes'):
                stamps.append(HEADER.unpack_from(event['bytes'])[-1])
            if event.get('text'):
                message = json.loads(event['text'])
                assert message['type'] != 'server.error', message
                if message.get('state') == 'listening':
                    break
        clips = sum(m['type'] == 'text' for socket in wire[0] for m in socket.sent if not socket.stt)
        assert clips and len(stamps) == 100 * clips  # All PCM retained after text chunking.
        for start in range(0, len(stamps), 100):
            assert (stamps[start + 99] - stamps[start]) / 1_000_000 >= 1.6
        ws.send_json({'type': 'client.stop'})
        while ws.receive_json()['type'] != 'server.ended':
            pass


def test_browser_websocket_sarvam_audio_reply_and_provider_costs(sample,wire):
    from test_media_lifecycle import assert_no_sql_on_running_loop
    client,workspace,base,fixture = sample
    response=client.post(base+'/voice/sessions',json={'agent_id':fixture['agent_id'],'mode':'live'})
    assert response.status_code==201,response.text
    state=response.json()
    with assert_no_sql_on_running_loop(),client.websocket_connect('/v1/media',headers={'Origin':settings.app_origin}) as ws:
        ws.send_json({'type':'client.start','session_token':state['session_token'],'transcript_mode':'delta-v1'})
        assert ws.receive_json()['type']=='server.ready'
        for turn in range(2):
            audio=False
            while True:
                event=ws.receive()
                assert event['type']!='websocket.close'
                if event.get('bytes'):audio=True
                if event.get('text'):
                    message=json.loads(event['text'])
                    assert message['type']!='server.error',message
                    if message.get('state')=='listening':break
            assert audio
            if turn==0:
                from studio.media import HEADER
                payload=b'\0'*3200
                ws.send_bytes(HEADER.pack(b'NTV1',1,1,1,0,16000,0,0,len(payload),0)+payload)
        ws.send_json({'type':'client.stop'})
        while ws.receive_json()['type']!='server.ended':pass
    sockets,requests=wire
    assert requests and all(s.closed for s in sockets)
    assert len([s for s in sockets if not s.stt])==1
    with session_scope() as db:
        costs=list(db.scalars(select(CallCostRecord).where(CallCostRecord.workspace_id==workspace)))
        assert {'sarvam-stt','sarvam-tts','sarvam-llm'} <= {c.provider for c in costs}
        assert not {'fish','deepgram','openai'} & {c.provider for c in costs}
        assert all(c.cost_micro_minor>0 for c in costs if c.provider.startswith('sarvam'))


@pytest.mark.parametrize('provider',['twilio','plivo'])
def test_carrier_sarvam_connection_uses_mulaw_audio_and_cleans_up(sample,wire,monkeypatch,provider):
    from studio import twilio_routes
    from studio.security import capability
    from test_media_lifecycle import assert_no_sql_on_running_loop
    client,workspace,base,fixture=sample
    agent=client.get(base+'/agents/'+fixture['agent_id']).json()
    with session_scope(write=True) as db:
        call=Call(workspace_id=workspace,agent_version_id=agent['published_version_id'],mode='live',
            transport='pstn',state='connecting',provider_call_id='synthetic-leg',
            metadata_data={'provider':provider,'admitted_max_seconds':10})
        db.add(call);db.flush();call_id=call.id
    monkeypatch.setattr(settings,'live_calls_enabled',True)
    monkeypatch.setattr(twilio_routes,'call_credentials',lambda call:{'account_sid':'synthetic-account'})
    token=capability({'aud':'twilio-media' if provider=='twilio' else 'carrier','workspace_id':workspace,
                      'call_id':call_id,'provider_call_id':'synthetic-leg'})
    path='/v1/twilio-media/' if provider=='twilio' else '/v1/carrier-media/'
    with assert_no_sql_on_running_loop(),client.websocket_connect(path+token) as ws:
        ws.send_json({'event':'start','start':{'accountSid':'synthetic-account','callSid':'synthetic-leg',
            'callId':'synthetic-leg','streamSid':'stream','streamId':'stream',
            'mediaFormat':{'encoding':'audio/x-mulaw','sampleRate':8000}}})
        event=ws.receive_json()
        assert event['event'] in {'media','playAudio'}
        assert base64.b64decode(event['media']['payload'])
        ws.send_json({'event':'media','streamSid':'stream','streamId':'stream',
                      'media':{'track':'inbound','payload':base64.b64encode(b'\xff'*800).decode()}})
        while not wire[1]:
            message=ws.receive_json()
            assert message['event'] in {'media','playAudio','clear','clearAudio'}
        ws.send_json({'event':'stop'})
        while ws.receive()['type']!='websocket.close':pass
    assert wire[1] and all(s.closed for s in wire[0])
    with session_scope() as db:
        assert db.get(Call,call_id).state=='completed'
        assert db.scalar(select(StoredTurn.id).where(StoredTurn.call_id==call_id,StoredTurn.speaker=='user'))
        stt=db.scalar(select(CallCostRecord).where(CallCostRecord.call_id==call_id,CallCostRecord.provider=='sarvam-stt'))
        assert stt and stt.units['stt_ms']>0


@pytest.mark.asyncio
async def test_streamed_tool_arguments_and_result_roundtrip(monkeypatch):
    from studio.llm import Turn
    requests=[]
    def handle(request):
        body=json.loads(request.content);requests.append(body)
        if len(requests)==1:
            content=sse({'tool_calls':[{'index':0,'id':'tool-1','type':'function','function':{'name':'lookup','arguments':'{"id":'}}]})
            content+=sse({'tool_calls':[{'index':0,'function':{'arguments':'"123"}'}}]})+sse(finish='tool_calls')
        else:
            assert body['messages'][-1]=={'role':'tool','tool_call_id':'tool-1','content':'{"status": "open"}'}
            content=sse({'content':'Your request is open.'})+sse(finish='stop')
        return httpx.Response(200,headers={'content-type':'text/event-stream'},content=content+'data: [DONE]\n\n')
    async def client(profile):
        return AsyncOpenAI(api_key=profile['api_key'],base_url=profile['base_url'],max_retries=0,
                           http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)))
    monkeypatch.setattr(llm_connections,'create_client',client)
    messages=[{'role':'user','content':'Look up 123'}]
    turn=Turn(voice_profile(),'Use lookup.',messages,tools=[{'name':'lookup','parameters':{'type':'object','properties':{'id':{'type':'string'}}}}])
    assert not [chunk async for chunk in turn.stream()]
    assert turn.calls==[{'id':'tool-1','name':'lookup','arguments':'{"id":"123"}'}]
    turn.append_results([{'status':'open'}])
    assert ''.join([chunk async for chunk in turn.stream()])=='Your request is open.'


@pytest.mark.asyncio
async def test_sarvam_voice_tool_cannot_write_until_later_presented_confirmation(sample,monkeypatch):
    from studio import providers,tool_safety
    from studio.domain import default_agent
    from studio.models import Ticket
    from sqlalchemy import func
    _,workspace,_,_=sample
    with session_scope(write=True) as db:
        call=Call(workspace_id=workspace,mode='live',transport='browser',state='connected')
        db.add(call);db.flush();call_id=call.id
    def handle(request):
        body=json.loads(request.content)
        assert body['model']=='sarvam-105b-conversations' and body['tools']
        content=sse({'tool_calls':[{'index':0,'id':'ticket-1','type':'function',
            'function':{'name':'create_support_ticket','arguments':'{"subject":"Synthetic support request"}'}}]})
        content+=sse(finish='tool_calls')+sse(usage={'prompt_tokens':100,'completion_tokens':20})
        return httpx.Response(200,headers={'content-type':'text/event-stream'},content=content+'data: [DONE]\n\n')
    async def client(profile):
        return AsyncOpenAI(api_key=profile['api_key'],base_url=profile['base_url'],max_retries=0,
                           http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)))
    monkeypatch.setattr(llm_connections,'create_client',client)
    proposals=[]
    async def emit(data):proposals.append(data['confirmation'])
    context={'workspace_id':workspace,'call_id':call_id,'operation_id':'synthetic-ticket','user_text':'Please record my support request.',
             'last_assistant_text':'','voice_stream':True,'emit_safety':emit,'billing_mode':'live'}
    config=default_agent();config['tools']=[{'name':'create_support_ticket'}]
    output=[chunk async for chunk in providers.answer_stream(config,context['user_text'],[],tool_context=context)]
    text=''.join(chunk for chunk in output if isinstance(chunk,str))
    assert len(proposals)==1 and 'Confirm request' in text
    with session_scope() as db:assert db.scalar(select(func.count()).select_from(Ticket))==0
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        await tool_safety.execute_confirmation(config,{**context,'user_text':'Confirm request'},proposals[0]['id'])
    tool_safety.mark_presented(context,proposals[0]['id'],text)
    later={**context,'user_text':'Confirm request','last_assistant_text':text}
    result=await tool_safety.execute_confirmation(config,later,proposals[0]['id'])
    assert result['ticket_id']
    assert await tool_safety.execute_confirmation(config,later,proposals[0]['id'])==result
    with session_scope() as db:assert db.scalar(select(func.count()).select_from(Ticket))==1


@pytest.mark.asyncio
async def test_truncated_model_stream_does_not_authorize_partial_tool(monkeypatch):
    from studio.llm import Turn
    def handle(request):
        return httpx.Response(200,headers={'content-type':'text/event-stream'},content=sse({'tool_calls':[
            {'index':0,'id':'unfinished','type':'function','function':{'name':'create_support_ticket','arguments':'{"subject":'}}]}))
    async def client(profile):
        return AsyncOpenAI(api_key=profile['api_key'],base_url=profile['base_url'],max_retries=0,
                           http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)))
    monkeypatch.setattr(llm_connections,'create_client',client)
    turn=Turn(voice_profile(),'Test.',[{'role':'user','content':'Test'}])
    with pytest.raises(RuntimeError,match='finish reason'):
        _=[chunk async for chunk in turn.stream()]
    assert turn.calls==[]


def test_sarvam_economics_uses_voice_rates_independent_of_text_model():
    from studio.unit_economics import report
    result=report()
    assert result['voice_model']=='sarvam-105b-conversations'
    assert len({row['unit_cost_micro_minor']['browser_voice_minute'] for row in result['models']})==1
    assert len({row['unit_cost_micro_minor']['chat_turn'] for row in result['models']})>1

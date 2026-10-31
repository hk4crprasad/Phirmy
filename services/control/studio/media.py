import asyncio
import contextlib
import json
import logging
import struct
import time
from urllib.parse import urlencode
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException
from sqlalchemy import select, func
import websockets
from .config import settings
from .widget_branding import installation_allows_origin
from .db import session_scope, now, uid
from .models import Call, Turn, AgentVersion, Conversation, Ticket, Installation, Message
from .security import verify_capability
from .domain import owned, settle_call, emit,bind_variables
from .knowledge import retrieve
from .providers import answer_stream
from .fish_stream import FishCall
from .media_lifecycle import locked_call, finalize as finalize_media
from .async_work import durable_await, durable_to_thread
from fishaudio.types import FlushEvent
from .recording import AudioTimeline
from . import voice_latency, voice_greetings
from . import llm_connections
from .llm_events import ModelIncompleteError
from .transcripts import Transcript
from .voice_prefetch import InterimPrefetch,normalize as normalize_query

router = APIRouter()
log = logging.getLogger(__name__)
HEADER = struct.Struct("<4sBBBBIIIIQ")
owners = set()


def decode_frame(frame):
    if len(frame) < HEADER.size:
        raise ValueError("Audio frame header missing")
    magic, version, kind, channels, reserved, rate, sequence, epoch, length, stamp = HEADER.unpack_from(frame)
    payload = frame[HEADER.size:]
    if magic != b"NTV1" or version != 1 or kind != 1 or channels != 1 or reserved or rate != 16000:
        raise ValueError("Unsupported input audio format")
    if length != len(payload) or length % 2 or length > 6400 or not length:
        raise ValueError("Invalid audio frame size")
    return payload, sequence


def encode_frame(audio, sequence, epoch, stamp):
    return HEADER.pack(b"NTV1", 1, 2, 1, 0, 24000, sequence, epoch, len(audio), stamp) + audio


class AudioPacer:
    """Bound queued audio without turning synthesis/event-loop delays into debt."""
    def __init__(self, *, clock=None, sleep=None, ahead=.16):
        self.clock = clock or time.monotonic
        self.sleep = sleep or asyncio.sleep
        self.ahead = ahead
        self.next_send = None

    async def wait(self, seconds):
        now = self.clock()
        scheduled = max(now, self.next_send if self.next_send is not None else now)
        delay = scheduled - now - self.ahead
        if delay > 0:
            await self.sleep(delay)
        # First-byte latency, gaps between chunks and delayed wake-ups must not
        # be repaid by bursting stale frames into a browser's playout queue.
        self.next_send = max(scheduled, self.clock()) + seconds


class VoiceSession:
    def __init__(self, websocket, workspace_id, call_id, config, mode, *, timing_source=None):
        self.ws, self.workspace_id, self.call_id = websocket, workspace_id, call_id
        self.config, self.mode = config, mode
        self.epoch, self.sequence = 0, 0
        self.started = time.monotonic()
        self.task = None
        self.lock = asyncio.Lock()
        self.dg = None
        self.history = []
        self.website_context = {}
        with session_scope() as db:
            call = db.get(Call, call_id)
            self.agent_version_id=call.agent_version_id if call else None
            self.admitted_max_seconds=call.metadata_data.get('admitted_max_seconds',900) if call else 900
            if call and call.metadata_data.get('widget_installation_id'):
                installation = db.get(Installation, call.metadata_data['widget_installation_id'])
                from .widget_branding import widget_config
                self.config=widget_config(config,installation.theme)
                self.website_context = {'installation_id':installation.id, 'website_actions':bool(installation.theme.get('website_actions')),
                                        'page_url':call.metadata_data.get('page_url'), 'conversation_id':call.metadata_data['conversation_id']}
                recent = list(db.scalars(select(Message).where(Message.workspace_id == workspace_id, Message.conversation_id == call.metadata_data['conversation_id']).order_by(Message.created_at.desc(), Message.id.desc()).limit(24)))
                self.history = [{'role':m.role,'text':m.text_content, 'interrupted':bool(m.metadata_data.get('interrupted'))} for m in reversed(recent)]
        self.closed = False
        self.provider_failed = False
        self.provider_failure = asyncio.Event()
        self.stt_samples=0
        self.reply_language = 'en-IN'
        self.recording = AudioTimeline(config) if mode == 'live' else AudioTimeline({})
        self.last_activity = time.monotonic()
        self.checkin_sent = False
        self.timing_source = timing_source or ('live' if mode=='live' else 'development')
        self.llm_clients = llm_connections.CallClients(workspace_id)
        self.transcript_deltas = False
        self.prefetch=InterimPrefetch(self.retrieve_query,self.validate_prefetch)
        from .voice_config import sarvam_enabled, speech_config
        self.sarvam = sarvam_enabled()
        self.config = {**self.config, 'speech': speech_config(self.config)}
        self.tts_provider = 'sarvam-tts' if self.sarvam else 'fish'
        if self.sarvam:
            from .sarvam_tts import SarvamCall
            self.fish = SarvamCall(self.config['speech'])
        else:
            self.fish = FishCall()

    def retrieval_query(self,question):
        query=question
        if self.website_context.get('page_url') and __import__('re').search(r'\b(this|it|its|that)\b',question,__import__('re').I):
            query+=' '+self.website_context['page_url'].rsplit('/',1)[-1].replace('-',' ')
        return normalize_query(query)

    async def retrieve_query(self,query,snapshot_ids):
        from .metering import scope
        with scope(workspace_id=self.workspace_id,call_id=self.call_id,mode=self.mode):
            return await retrieve(self.workspace_id,list(snapshot_ids),query)

    async def validate_prefetch(self,snapshot_ids,result):
        from .knowledge import valid_prefetch
        return await asyncio.to_thread(valid_prefetch,self.workspace_id,list(snapshot_ids),result)

    async def close_providers(self):
        try:
            await self.interrupt()
        finally:
            try:
                await self.prefetch.close()
            finally:
                try:
                    await self.fish.close()
                finally:
                    await self.llm_clients.close()

    async def persist_timing(self, timing):
        try:
            await asyncio.to_thread(voice_latency.persist,timing)
        except Exception:
            # Telemetry failure must not mask billing settlement or transport
            # cleanup. Never log prompts or a provider exception's raw contents.
            log.warning('Voice timing persistence failed for call %s',self.call_id)

    async def event(self, kind, **data):
        async with self.lock:
            await self.ws.send_json({"type": kind, "event_id": uid(), "timestamp": now().isoformat(), "call_id": self.call_id, "epoch": self.epoch, **data})

    async def open_recognition(self):
        if self.sarvam:
            from .sarvam_stt import Recognition
            self.dg = await Recognition.connect(self.config['speech']['live_stt_language'])
        else:
            query = urlencode({'model': 'nova-3', 'language': self.config['speech']['live_stt_language'],
                'encoding': 'linear16', 'sample_rate': 16000, 'channels': 1, 'interim_results': 'true',
                'vad_events': 'true', 'endpointing': 250, 'utterance_end_ms': 1000})
            self.dg = await websockets.connect('wss://api.deepgram.com/v1/listen?' + query,
                additional_headers={'Authorization': 'Token ' + settings.deepgram_api_key},
                max_size=1_000_000, open_timeout=15)

    async def recognition_audio(self,payload):
        if self.stt_samples+len(payload)//2>self.admitted_max_seconds*16000:
            raise HTTPException(429,'This call reached its admitted audio allowance')
        await self.dg.send(payload)
        self.stt_samples+=len(payload)//2

    def record_audio_usage(self,db):
        if self.mode!='live':return
        from .metering import record_cost
        reported = getattr(self.dg, 'billed_ms', None) if self.sarvam else None
        duration = max(self.stt_samples // 16, reported or 0)
        record_cost(db,self.workspace_id,'stt:'+self.call_id,'sarvam-stt' if self.sarvam else 'deepgram','stt',{'stt_ms':duration},
                    call_id=self.call_id,source='provider_usage' if reported is not None else 'measured_pcm',
                    model=self.config['speech']['live_stt_model'] if self.sarvam else None)

    def save_turn(self, speaker, text, epoch, interrupted=False):
        if not text.strip():
            return
        with session_scope(write=True) as db:
            ordinal = db.scalar(select(func.count()).select_from(Turn).where(Turn.workspace_id == self.workspace_id, Turn.call_id == self.call_id))
            db.add(Turn(workspace_id=self.workspace_id, call_id=self.call_id, ordinal=ordinal, speaker=speaker, text_content=text.strip(), epoch=epoch, interrupted=interrupted))
            if self.website_context.get('conversation_id'):
                db.add(Message(workspace_id=self.workspace_id, conversation_id=self.website_context['conversation_id'], client_message_id=uid(), role=speaker, text_content=text.strip(), metadata_data={'channel':'voice','interrupted':interrupted}))
        self.history.append({"role": speaker, "text": text.strip(), "interrupted": interrupted})

    async def interrupt(self):
        task = self.task
        if task:
            self.task = None
            self.epoch += 1
            if not task.done() and not task.cancelling():
                task.cancel()
            # Clear playback before waiting for metering/DB cleanup. Detach the
            # old task first so concurrent interrupt messages cannot cancel its
            # cleanup twice or clear a newer response's task pointer.
            with contextlib.suppress(WebSocketDisconnect, RuntimeError):
                await self.event("server.clear", reason="interruption")
            # Always retrieve the task result, even when a closed socket ended it.
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

    async def user_text(self, text, *, final_received_at=None, input_kind='text',transcript_turn_id=None,language=None):
        timing = voice_latency.Trace(self.workspace_id,self.call_id,self.epoch,self.timing_source,input_kind,
                                     started_at=final_received_at)
        def admit():
            from .usage import admit_turn
            with session_scope(write=True) as db:
                admit_turn(db, self.workspace_id, 'voice-turn:' + self.call_id + ':' + uid())
        try:
            with timing.measure('turn_admission'):
                await asyncio.to_thread(admit)
        except asyncio.CancelledError:
            timing.finish('interrupted')
            await self.persist_timing(timing)
            raise
        except Exception:
            timing.finish('denied')
            await self.persist_timing(timing)
            raise
        self.last_activity=time.monotonic();self.checkin_sent=False
        if not self.config.get('behavior',{}).get('interruptible',True) and self.task and not self.task.done():
            await self.task
        await self.interrupt()
        from .voice_config import spoken_language
        self.reply_language = spoken_language(text, language)
        timing.epoch = self.epoch
        await asyncio.to_thread(self.save_turn,"user", text, self.epoch)
        timing.mark('transcript_saved')
        await self.event("server.transcript", speaker="user", text=text, final=True, turn_id=transcript_turn_id or uid())
        self.task = asyncio.create_task(self.respond(text,timing=timing))

    async def respond(self, question=None,announcement=None,*,timing=None):
        timing = timing or voice_latency.Trace(self.workspace_id,self.call_id,self.epoch,self.timing_source,
                                               'checkin' if announcement else 'greeting' if question is None else 'text')
        timing.mark('response_started')
        timing_token = voice_latency.current.set(timing)
        clients_token = llm_connections.current.set(self.llm_clients)
        outcome = 'failed'
        epoch, generated = self.epoch, ""
        transcript=Transcript(self.event,'assistant',epoch,identity=timing.turn_id,deltas=self.transcript_deltas)
        pending_confirmation = None
        tts_bytes=0;tts_characters=0;tts_utf8_bytes=0;tts_attempted=False
        fish_generation = None
        greeting_key = None
        cached_greeting = None
        greeting_audio = bytearray()
        greeting_complete = True
        previous = self.history[-2] if len(self.history)>1 else {}
        safety_context = {'workspace_id':self.workspace_id,'call_id':self.call_id,
                          'operation_id':self.call_id+':'+str(len(self.history)),'user_text':question or '',
                          'billing_mode':self.mode,
                          'last_assistant_text':previous.get('text','') if previous.get('role')=='assistant' and not previous.get('interrupted') else ''}
        try:
            if self.sarvam:
                from .voice_config import spoken_language
                configured = self.config['speech'].get('language_code')
                language = (self.reply_language if question is not None else spoken_language(
                    announcement or self.config.get('greeting', ''))
                    ) if configured == 'auto' else spoken_language(detected=configured)
                await self.fish.set_language(language)
            if self.mode == 'live' and question is None and announcement is None:
                greeting_text = self.config.get('greeting', 'Hello. How can I help?')
                if self.recording.enabled:
                    greeting_text += ' This call is being recorded.'
                greeting_key = voice_greetings.cache.key(self.workspace_id, self.agent_version_id, self.config, greeting_text)
                cached_greeting = voice_greetings.cache.get(greeting_key)
            if self.mode == 'live' and cached_greeting is None and settings.voice_fish_preconnect_enabled:
                fish_generation = self.fish.prepare(self.config['speech']['voice_id'], self.config['speech']['model'])
            from .handoff import reply as safety_reply
            with timing.measure('safety'):
                safe_response = await safety_reply(self.config,safety_context) if question is not None else None
            await self.event("server.turn_state", state="thinking")
            if question is None:
                initial = announcement or self.config.get("greeting", "Hello. How can I help?")
                if announcement is None and self.recording.enabled:
                    initial+=' This call is being recorded.'
                passages = []
            elif safe_response is not None:
                initial = safe_response['text']
                pending_confirmation = safe_response.get('confirmation')
                passages = []
            else:
                query = self.retrieval_query(question)
                snapshot_ids=self.config.get('knowledge_snapshot_ids',[])
                with timing.measure('retrieval'):
                    cached=await self.prefetch.take(query,snapshot_ids)
                    if cached is not None:
                        result,elapsed=cached
                        timing.spans['retrieval_prefetch']=elapsed
                        timing.mark('retrieval_prefetch_reused')
                    else:result=await self.retrieve_query(query,snapshot_ids)
                passages = result["passages"] if result["answerable"] else []
                initial = None

            website_results = []
            async def text_chunks():
                nonlocal generated, pending_confirmation
                if initial is not None:
                    generated = initial
                    await transcript.write(generated)
                    yield initial
                    yield FlushEvent()
                    return
                async def website_event(data):
                    if epoch == self.epoch: website_results.append({k:v for k,v in data.items() if k in {'actions','products'}})
                async def safety_event(data):
                    nonlocal pending_confirmation
                    pending_confirmation=data.get('confirmation')
                tool_context = {**safety_context,'workspace_id':self.workspace_id,'call_id':self.call_id,'user_text':question,'operation_id':self.call_id+':'+str(len(self.history)),
                                'voice_stream':True,
                                'voice_language':language if self.sarvam else None,
                                'knowledge_snapshot_ids':self.config.get('knowledge_snapshot_ids', []), 'history':self.history[:-1], **self.website_context, 'emit_website':website_event, 'emit_safety':safety_event}
                async for text in answer_stream(self.config, question, passages, self.history[:-1], tool_context):
                    if epoch != self.epoch:
                        return
                    if isinstance(text,FlushEvent):
                        yield text
                        continue
                    generated += text
                    await transcript.write(generated)
                    yield text
                yield FlushEvent()

            if self.mode == "live":
                await self.event("server.turn_state", state="speaking")
                pending = b""
                pacer = AudioPacer()
                tts_operation='tts:'+self.call_id+':'+str(epoch)+':'+uid()
                from .streaming_budget import SpeechBudget
                speech_budget = SpeechBudget({'workspace_id':self.workspace_id,'call_id':self.call_id},tts_operation,provider=self.tts_provider)
                async def measured_text():
                    nonlocal tts_characters,tts_utf8_bytes
                    from .speech_text import speech_chunks
                    async for text in speech_chunks(text_chunks()):
                        if isinstance(text,FlushEvent):
                            yield text
                            continue
                        with timing.measure('tts_admission'):
                            await speech_budget.reserve(len(text) if self.sarvam else len(text.encode()))
                        tts_characters+=len(text);tts_utf8_bytes+=len(text.encode())
                        yield text
                async def cached_audio():
                    # Still emit the same authoritative transcript and playback
                    # frames; replay does not reserve or meter fresh synthesis.
                    async for _ in text_chunks():
                        pass
                    timing.mark('greeting_cache_hit')
                    yield cached_greeting
                if cached_greeting is None:
                    tts_attempted=True
                    audio_source = self.fish.stream(measured_text(), self.config['speech']['voice_id'], self.config['speech']['model'])
                else:
                    audio_source = cached_audio()
                async with contextlib.aclosing(audio_source) as audio_stream:
                    async for audio in audio_stream:
                        if audio:
                            timing.mark('first_tts_byte')
                        tts_bytes+=len(audio)
                        if greeting_key is not None and cached_greeting is None and greeting_complete:
                            if len(greeting_audio) + len(audio) <= voice_greetings.cache.MAX_CLIP_BYTES:
                                greeting_audio.extend(audio)
                            else:
                                greeting_audio.clear()
                                greeting_complete = False
                        if epoch != self.epoch:
                            break
                        pending += audio
                        while len(pending) >= 960:
                            frame, pending = pending[:960], pending[960:]
                            await pacer.wait(len(frame) / 48000)
                            self.recording.add(frame, 24000, 1)
                            packet = encode_frame(frame, self.sequence, epoch, int((time.monotonic() - self.started) * 1_000_000))
                            async with self.lock:
                                await self.ws.send_bytes(packet)
                            timing.mark('first_audio_sent')
                            self.sequence += 1
                if pending and len(pending) % 2 == 0 and epoch == self.epoch:
                    await pacer.wait(len(pending) / 48000)
                    self.recording.add(pending, 24000, 1)
                    async with self.lock:
                        await self.ws.send_bytes(encode_frame(pending, self.sequence, epoch, int((time.monotonic() - self.started) * 1_000_000)))
                    timing.mark('first_audio_sent')
                    self.sequence += 1
            else:
                async for _ in text_chunks():
                    pass
            if epoch == self.epoch:
                await asyncio.to_thread(self.save_turn,"assistant", generated, epoch)
                if pending_confirmation:
                    from .tool_safety import mark_presented
                    await asyncio.to_thread(mark_presented,safety_context,pending_confirmation['id'],generated)
                if announcement is None:self.last_activity=time.monotonic()
                await transcript.write(generated,final=True)
                for result in website_results: await self.event('server.website', **result)
                await self.event("server.turn_state", state="listening")
                outcome = 'completed'
                if greeting_key is not None and cached_greeting is None and greeting_complete:
                    voice_greetings.cache.put(greeting_key, greeting_audio)
        except asyncio.CancelledError:
            outcome = 'interrupted'
            if generated:
                await asyncio.to_thread(self.save_turn,"assistant", generated, epoch, interrupted=True)
            raise
        except HTTPException as error:
            outcome = 'denied' if error.status_code==429 else 'failed'
            with contextlib.suppress(WebSocketDisconnect, RuntimeError):
                await self.event('server.error',code='tool_limit' if error.status_code==429 else 'confirmation_required',
                    message=str(error.detail) if error.status_code==429 else 'The action needs a current confirmation.',retryable=False)
                await self.event('server.turn_state',state='listening')
        except ModelIncompleteError as error:
            outcome='incomplete'
            if generated:
                await asyncio.to_thread(self.save_turn,'assistant',generated,epoch,interrupted=True)
            with contextlib.suppress(WebSocketDisconnect,RuntimeError):
                await self.event('server.error',code='model_incomplete',reason=error.reason,
                    message='That answer stopped early. Please ask a shorter follow-up.',retryable=False)
                await self.event('server.turn_state',state='listening')
        except Exception:
            log.warning("Voice generation failed for call %s", self.call_id)
            with contextlib.suppress(WebSocketDisconnect, RuntimeError):
                await self.event("server.error", code="generation_failed", message="Voice generation failed; inspect provider configuration.", retryable=True)
        finally:
            try:
                if fish_generation is not None:
                    await self.fish.discard(fish_generation)
            finally:
                timing.finish(outcome)
                try:
                    if tts_attempted:
                        from .metering import append_cost
                        await durable_to_thread(append_cost,{'workspace_id':self.workspace_id,'call_id':self.call_id,
                            'model':self.config['speech']['model'] if self.sarvam else None},self.tts_provider,'tts',
                            {'tts_characters':tts_characters,'tts_utf8_bytes':tts_utf8_bytes,'tts_ms':tts_bytes//48},
                            tts_operation,'observed_input')
                finally:
                    try:
                        await durable_await(self.persist_timing(timing))
                    finally:
                        voice_latency.current.reset(timing_token)
                        llm_connections.current.reset(clients_token)

    async def receive(self, operation, *, timeout):
        """Wake a blocked client/carrier receive when recognition has ended."""
        incoming = asyncio.create_task(asyncio.wait_for(operation, timeout))
        failed = asyncio.create_task(self.provider_failure.wait())
        try:
            done, _ = await asyncio.wait((incoming, failed), return_when=asyncio.FIRST_COMPLETED)
            if failed in done:
                raise RuntimeError('Speech recognition disconnected')
            return await incoming
        finally:
            for task in (incoming, failed):
                if not task.done():task.cancel()
            await durable_await(asyncio.gather(incoming, failed, return_exceptions=True))

    async def recognize(self):
        try:
            await self._recognize()
        except asyncio.CancelledError:
            raise
        except Exception:
            # Provider payloads/errors may contain sensitive data. The owner
            # reports a stable error and performs all call/billing cleanup.
            pass
        if not self.closed:
            self.provider_failed = True
            self.provider_failure.set()

    async def _recognize(self):
        final = []
        transcript=None
        async for message in self.dg:
            received_at = time.monotonic()
            event = json.loads(message)
            if event.get("type") == "SpeechStarted":
                self.last_activity=time.monotonic();self.checkin_sent=False
                if self.config.get('behavior',{}).get('interruptible',True):await self.interrupt()
                self.prefetch.reset()
                if self.mode == 'live' and settings.voice_fish_preconnect_enabled and not (self.task and not self.task.done()):
                    self.fish.prepare(self.config['speech']['voice_id'], self.config['speech']['model'])
                transcript=None
            elif event.get("type") == "Results":
                text = event.get("channel", {}).get("alternatives", [{}])[0].get("transcript", "").strip()
                if text:
                    self.last_activity=time.monotonic();self.checkin_sent=False
                    if transcript is None or transcript.epoch!=self.epoch:
                        transcript=Transcript(self.event,'user',self.epoch,deltas=self.transcript_deltas)
                    await transcript.write(' '.join([*final,text]))
                    if not event.get('speech_final'):
                        self.prefetch.observe(self.retrieval_query(' '.join([*final,text])),self.config.get('knowledge_snapshot_ids',[]))
                if event.get("is_final") and text:
                    final.append(text)
                if event.get("speech_final") and final:
                    question, final = " ".join(final), []
                    await self.user_text(question,final_received_at=received_at,input_kind='stt_final',
                                         transcript_turn_id=transcript.identity if transcript else None,
                                         language=event.get('language'))
                    transcript=None
            elif event.get("type") == "UtteranceEnd" and final:
                question, final = " ".join(final), []
                await self.user_text(question,final_received_at=received_at,input_kind='stt_final',
                                     transcript_turn_id=transcript.identity if transcript else None)
                transcript=None

    async def watch_idle(self):
        behavior=self.config.get('behavior',{})
        last_state_check=0
        def stopped():
            with session_scope() as db:
                call=db.get(Call,self.call_id)
                if not call or call.state in {'ending','completed','failed','canceled'}:
                    return True
                from .models import WorkspaceSubscription
                budget=db.scalar(select(WorkspaceSubscription).where(WorkspaceSubscription.workspace_id==self.workspace_id))
                if budget and (budget.operator_paused or budget.billing_blocked):return True
                if call.metadata_data.get('phone_trial_id'):
                    from .phone_trials import call_seconds
                    try:
                        call_seconds(db, call)
                    except HTTPException:
                        return True
                    if call.connected_at and (now() - call.connected_at).total_seconds() >= call.metadata_data['phone_trial_seconds']:
                        return True
                if call.metadata_data.get('widget_installation_id'):
                    conversation = db.get(Conversation, call.metadata_data.get('conversation_id'))
                    if not conversation or conversation.state != 'open': return True
                    installation = db.get(Installation, call.metadata_data['widget_installation_id'])
                    if installation and installation.theme.get('publishable_key') and call.metadata_data.get('widget_key_revision') != __import__('hashlib').sha256(installation.theme['publishable_key'].encode()).hexdigest(): return True
                    return not installation or not installation.enabled or not installation.theme.get('voice_enabled') or not installation_allows_origin(installation,call.metadata_data.get('widget_origin'))
                return False
        while not self.closed:
            await asyncio.sleep(.5)
            if time.monotonic()-last_state_check>=1:
                last_state_check=time.monotonic()
                if await asyncio.to_thread(stopped):
                    await self.ws.close();return
            if self.task and not self.task.done():continue
            elapsed=time.monotonic()-self.last_activity
            if elapsed>=behavior.get('idle_end_seconds',30):
                await self.event('server.idle',reason='idle_timeout')
                await self.ws.close();return
            if not self.checkin_sent and elapsed>=behavior.get('silence_prompt_seconds',8):
                self.checkin_sent=True
                self.task=asyncio.create_task(self.respond(announcement='Are you still there? I’m here if you need a hand.'))


@router.websocket("/v1/media")
async def browser_media(websocket: WebSocket):
    origin = websocket.headers.get("origin")
    if origin not in {settings.app_origin, settings.app_origin.replace("localhost", "127.0.0.1")}:
        await websocket.close(1008)
        return
    await websocket.accept()
    session, recognizer, idle = None, None, None
    call_id, owns_call, failed = None, False, False
    admitted = False
    workspace_id = None
    try:
        hello = await asyncio.wait_for(websocket.receive_json(), timeout=10)
        claims = verify_capability(hello.get("session_token", ""), "media")
        call_id, workspace_id = claims["call_id"], claims["workspace_id"]
        if hello.get("type") != "client.start" or call_id in owners:
            raise ValueError("Session already active or start message invalid")
        # Claim locally before yielding; PostgreSQL also locks the call row.
        owners.add(call_id)
        owns_call = True
        def admit():
            with session_scope(write=True) as db:
                call = locked_call(db, workspace_id, call_id)
                if call.state != "created":
                    raise ValueError("Call session is no longer available")
                if call.metadata_data.get('widget_installation_id'):
                    installation = owned(db, Installation, workspace_id, call.metadata_data['widget_installation_id'])
                    if installation.theme.get('publishable_key') and call.metadata_data.get('widget_key_revision') != __import__('hashlib').sha256(installation.theme['publishable_key'].encode()).hexdigest():
                        raise HTTPException(403, 'This widget key has been rotated; reconnect')
                    if not installation.enabled or not installation.theme.get('voice_enabled') or not installation_allows_origin(installation,call.metadata_data.get('widget_origin')):
                        raise ValueError('Website voice access was disabled')
                config = bind_variables(owned(db, AgentVersion, workspace_id, call.agent_version_id).config,call.metadata_data.get('variables',{}))
                mode = call.mode
                if 'admitted_max_seconds' not in call.metadata_data:
                    from .admission import admit_voice
                    admit_voice(db,call,config)
                from .llm import live_voice_ready
                if mode == "live" and not live_voice_ready(config,workspace_id):
                    raise ValueError("Live voice providers are not configured")
                call.state, call.connected_at = "connected", now()
                installation_seconds=min(call.metadata_data.get('installation_max_duration_ms',900000)/1000,call.metadata_data.get('admitted_max_seconds',900))
            return config, mode, installation_seconds
        async def initialize():
            nonlocal config, mode, installation_seconds, admitted, session
            config, mode, installation_seconds = await asyncio.to_thread(admit)
            admitted = True
            session = await asyncio.to_thread(VoiceSession, websocket, workspace_id, call_id, config, mode)
        config, mode, installation_seconds = None, None, None
        # Observe the committed outcome before propagating cancellation, so the
        # finalizer cannot lose an admitted call or its financial reservation.
        await durable_await(initialize())
        session.transcript_deltas=hello.get('transcript_mode')=='delta-v1'
        audio = {"codec": "pcm_s16le", "sample_rate": 16000, "channels": 1}
        await session.event("server.ready", input_format=audio, output_format={**audio, "sample_rate": 24000}, mode=mode,
                            transcript_mode='delta-v1' if session.transcript_deltas else 'full')
        if mode == "live":
            await session.open_recognition()
            recognizer = asyncio.create_task(session.recognize())
        session.task = asyncio.create_task(session.respond())
        idle=asyncio.create_task(session.watch_idle())
        deadline = time.monotonic() + min(config["behavior"]["max_connected_seconds"],900,installation_seconds)
        input_samples, last_sequence = 0, -1
        while time.monotonic() < deadline:
            message = await session.receive(websocket.receive(), timeout=min(45, max(1, deadline - time.monotonic())))
            if message.get("type") == "websocket.disconnect":
                break
            if message.get("bytes") is not None:
                if mode != "live":
                    raise ValueError("Audio input requires live voice mode")
                payload, sequence = decode_frame(message["bytes"])
                input_samples += len(payload) // 2
                if sequence <= last_sequence or input_samples > 16000 * (time.monotonic() - session.started + 2):
                    raise ValueError('Audio must arrive in order at conversational speed')
                last_sequence = sequence
                session.recording.add(payload, 16000, 0)
                await session.recognition_audio(payload)
            elif message.get("text"):
                data = json.loads(message["text"])
                if data.get("type") == "client.stop":
                    break
                if data.get("type") == "client.text":
                    text = str(data.get("text", "")).strip()
                    if not 1 <= len(text) <= 4000:
                        raise ValueError("Text turn length is invalid")
                    await session.user_text(text)
                elif data.get("type") == "client.interrupt":
                    await session.interrupt()
    except asyncio.CancelledError:
        failed = True
        raise
    except (WebSocketDisconnect, asyncio.TimeoutError):
        pass
    except (ValueError, HTTPException) as exc:
        failed = True
        with contextlib.suppress(Exception):
            await websocket.send_json({"type": "server.error", "code": "session_invalid", "message": str(exc)})
    except Exception:
        failed = True
        log.exception("Media session failed for call %s", call_id)
        with contextlib.suppress(Exception):
            await websocket.send_json({"type": "server.error", "code": "media_failed", "message": "Media session could not continue"})
    finally:
        failed = failed or bool(session and session.provider_failed)
        try:
            await durable_await(finalize_media(session, workspace_id, call_id,
                admitted=admitted, failed=failed, failure_code='media_session_failed', tasks=(idle, recognizer)))
            if session:
                with contextlib.suppress(Exception):
                    await session.event('server.ended', state='failed' if failed else 'completed',
                        reason='session_ended', connected_ms=int((time.monotonic()-session.started)*1000))
        finally:
            if call_id and owns_call:
                owners.discard(call_id)
            with contextlib.suppress(Exception):
                await websocket.close()

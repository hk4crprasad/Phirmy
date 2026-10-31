"""Persistent Bulbul v4 Flash socket; authoritative flush completions and barge-in."""
import asyncio
import base64
import contextlib
import json
import time
from urllib.parse import urlencode

import websockets
from fishaudio.types import FlushEvent

from .async_work import durable_await
from .config import settings
from . import voice_latency


class Generation:
    def __init__(self, owner, voice_id, model):
        self.owner, self.voice_id, self.model = owner, voice_id, model
        self.completed = self.used = False
        self.started = time.monotonic()
        self.task = asyncio.create_task(owner.connect(voice_id, model))
        self.task.add_done_callback(lambda task: task.exception() if not task.cancelled() else None)

    async def stream(self, texts):
        if self.used:
            raise RuntimeError('A speech generation cannot be replayed')
        self.used = True
        socket = await self.task
        voice_latency.mark('tts_connected')
        sent = received = 0
        dirty = False

        async def flush():
            nonlocal sent, dirty
            if dirty:
                sent += 1
                dirty = False
                await socket.send(json.dumps({'type': 'flush'}))

        async def send():
            nonlocal dirty
            async for text in texts:
                if isinstance(text, FlushEvent):
                    await flush()
                else:
                    for offset in range(0, len(text), 500):
                        part = text[offset:offset + 500]
                        voice_latency.mark('tts_first_text_sent')
                        dirty = dirty or bool(part.strip())
                        await socket.send(json.dumps({'type': 'text', 'data': {'text': part}}))
            await flush()

        sender = asyncio.create_task(send())
        receiver = None
        try:
            while True:
                if sender.done():
                    await sender
                    if received == sent:
                        self.completed = True
                        return
                receiver = asyncio.create_task(socket.recv())
                if not sender.done():
                    await asyncio.wait((sender, receiver), return_when=asyncio.FIRST_COMPLETED)
                if sender.done():
                    await sender
                    if received == sent and not receiver.done():
                        receiver.cancel()
                        await asyncio.gather(receiver, return_exceptions=True)
                        self.completed = True
                        return
                raw = await asyncio.wait_for(receiver, 20)
                message = json.loads(raw)
                if message.get('type') == 'error':
                    raise RuntimeError('Sarvam synthesis returned an error')
                if message.get('type') == 'audio':
                    data = base64.b64decode(message['data']['audio'], validate=True)
                    if len(data) % 2 or data.startswith(b'RIFF'):
                        raise RuntimeError('Sarvam returned unexpected PCM audio')
                    yield data
                elif message.get('type') == 'event' and message.get('data', {}).get('event_type') == 'final':
                    received += 1
                    if received > sent:
                        raise RuntimeError('Unexpected synthesis completion')
        finally:
            sender.cancel()
            if receiver is not None:
                receiver.cancel()
            await durable_await(asyncio.gather(sender, *([receiver] if receiver else []), return_exceptions=True))


class SarvamCall:
    def __init__(self, speech):
        self.speech = speech
        from .voice_config import spoken_language
        self.language_code = spoken_language(detected=speech.get('language_code'))
        self.socket = self.generation = self.keepalive = None
        self.closed = False

    async def connect(self, voice_id, model):
        if self.socket is not None:
            return self.socket
        query = urlencode({'model': model, 'send_completion_event': 'true'})
        self.socket = await websockets.connect(
            'wss://api.sarvam.ai/text-to-speech/ws?' + query,
            additional_headers={'api-subscription-key': settings.sarvam_api_key},
            max_size=2_000_000, max_queue=8, open_timeout=15, close_timeout=2)
        await self.socket.send(json.dumps({'type': 'config', 'data': {
            'speaker': voice_id, 'language_code': self.language_code,
            'speech_sample_rate': 24000, 'output_audio_codec': 'linear16',
            'enable_preprocessing': True, 'min_buffer_size': 50, 'max_chunk_length': 200}}))
        self.keepalive = asyncio.create_task(self._ping())
        return self.socket

    async def _ping(self):
        try:
            while True:
                await asyncio.sleep(15)
                await self.socket.send(json.dumps({'type': 'ping'}))
        except asyncio.CancelledError:
            raise
        except Exception:
            await self.socket.close()

    def prepare(self, voice_id, model):
        if self.closed:
            raise RuntimeError('Sarvam call is closed')
        if self.generation is None:
            self.generation = Generation(self, voice_id, model)
        return self.generation

    async def set_language(self, language):
        if language == self.language_code:
            return
        from .voice_config import SPOKEN_LANGUAGES
        if language not in SPOKEN_LANGUAGES.values():
            raise ValueError('Unsupported speech language')
        await self.discard()
        await self._disconnect()
        self.language_code = language

    async def discard(self, generation=None):
        generation = generation or self.generation
        if generation is None:
            return
        if self.generation is generation:
            self.generation = None
        if not generation.task.done():
            generation.task.cancel()
        await durable_await(asyncio.gather(generation.task, return_exceptions=True))
        if not generation.completed:
            await self._disconnect()

    async def _disconnect(self):
        if self.keepalive:
            self.keepalive.cancel()
            await asyncio.gather(self.keepalive, return_exceptions=True)
            self.keepalive = None
        socket, self.socket = self.socket, None
        if socket is not None:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(socket.close(), 3)

    async def stream(self, texts, voice_id, model):
        generation = self.prepare(voice_id, model)
        try:
            async with contextlib.aclosing(generation.stream(texts)) as audio:
                async for chunk in audio:
                    yield chunk
        finally:
            await durable_await(self.discard(generation))

    async def close(self):
        self.closed = True
        try:
            await self.discard()
        finally:
            await self._disconnect()

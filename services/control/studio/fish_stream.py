"""Call-owned, early-opened Fish sessions with authoritative stop/finish boundaries."""
import asyncio
import contextlib
import time

import msgpack
import websockets
from fishaudio.types import FlushEvent

from .async_work import durable_await
from .config import settings
from . import voice_latency


class Generation:
    def __init__(self, voice_id, model):
        self.voice_id, self.model = voice_id, model
        self.socket = None
        self.started = time.monotonic()
        self.connected = None
        self.used = False
        self.close_task = None
        self.task = asyncio.create_task(self.open(), name='fish-connection-setup')
        self.task.add_done_callback(self.observe)

    @staticmethod
    def observe(task):
        if not task.cancelled():
            task.exception()

    async def open(self):
        self.socket = await websockets.connect(
            'wss://api.fish.audio/v1/tts/live',
            additional_headers={'Authorization': 'Bearer ' + settings.fish_api_key,
                                'model': self.model or settings.fish_tts_model},
            max_size=2_000_000, open_timeout=15, close_timeout=3,
        )
        await self.socket.send(msgpack.packb({'event': 'start', 'request': {
            'text': '', 'format': 'pcm', 'sample_rate': 24000,
            'reference_id': self.voice_id, 'latency': 'balanced',
            'chunk_length': 200, 'normalize': True,
        }}, use_bin_type=True))
        self.connected = time.monotonic()
        return self.socket

    async def close(self):
        if self.close_task is None:
            self.close_task = asyncio.create_task(self._close(), name='fish-connection-close')
        await durable_await(self.close_task)

    async def _close(self):
        if not self.task.done() and not self.task.cancelling():
            self.task.cancel()
        await asyncio.gather(self.task, return_exceptions=True)
        if self.socket is not None:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self.socket.close(), timeout=4)

    async def stream(self, texts):
        if self.used:
            raise RuntimeError('A Fish generation cannot be replayed')
        self.used = True
        socket = await self.task
        trace = voice_latency.current.get()
        if trace is not None:
            # Setup can precede final STT. Record actual duration separately;
            # offsets clamp at receipt rather than inventing negative latency.
            for name, stamp in [('tts_setup_started', self.started), ('tts_connected', self.connected)]:
                trace.marks[name] = round(max(0, stamp - trace.started_at) * 1000, 3)
            trace.spans['tts_connect'] = round((self.connected - self.started) * 1000, 3)
            if self.connected <= trace.started_at:
                trace.mark('tts_preconnected')
        stop_intended = asyncio.Event()

        async def send():
            async for text in texts:
                if isinstance(text, FlushEvent):
                    await socket.send(msgpack.packb({'event': 'flush'}, use_bin_type=True))
                else:
                    voice_latency.mark('tts_first_text_sent')
                    await socket.send(msgpack.packb({'event': 'text', 'text': text}, use_bin_type=True))
            stop_intended.set()
            await socket.send(msgpack.packb({'event': 'stop'}, use_bin_type=True))

        sender = asyncio.create_task(send(), name='fish-text-sender')
        receiver = None
        try:
            while True:
                receiver = asyncio.create_task(socket.recv(), name='fish-audio-receiver')
                if not sender.done():
                    await asyncio.wait((sender, receiver), return_when=asyncio.FIRST_COMPLETED)
                if sender.done():
                    await sender
                raw = await asyncio.wait_for(receiver, timeout=15) if sender.done() else await receiver
                if not isinstance(raw, bytes):
                    raise RuntimeError('Fish returned an unexpected transport frame')
                message = msgpack.unpackb(raw, raw=False)
                if message.get('event') == 'audio':
                    data = message.get('audio')
                    if not isinstance(data, bytes) or len(data) % 2:
                        raise RuntimeError('Fish returned invalid PCM audio data')
                    yield data
                elif message.get('event') == 'finish':
                    if message.get('reason') != 'stop' or not stop_intended.is_set():
                        raise RuntimeError('Fish ended before synthesis completed')
                    break
            await sender
        finally:
            sender.cancel()
            if receiver is not None:
                receiver.cancel()
            await durable_await(asyncio.gather(sender, *([receiver] if receiver else []), return_exceptions=True))


class FishCall:
    """One active generation per call; no text is sent during speculative setup.

    Fish closes after stop/finish. Open the next generation during incoming
    speech/retrieval, and never infer readback completion from an audio timeout.
    """
    def __init__(self):
        self.generation = None
        self.closed = False

    def prepare(self, voice_id, model=None):
        if self.closed:
            raise RuntimeError('Fish call is closed')
        if self.generation is None:
            self.generation = Generation(voice_id, model)
        elif (self.generation.voice_id, self.generation.model) != (voice_id, model):
            raise RuntimeError('Speech configuration changed during an active generation')
        return self.generation

    async def discard(self, generation=None):
        generation = generation or self.generation
        if generation is None:
            return
        if self.generation is generation:
            self.generation = None
        await durable_await(generation.close())

    async def stream(self, texts, voice_id, model=None):
        generation = self.prepare(voice_id, model)
        try:
            async with contextlib.aclosing(generation.stream(texts)) as audio:
                async for chunk in audio:
                    yield chunk
        finally:
            await self.discard(generation)

    async def close(self):
        self.closed = True
        await self.discard()

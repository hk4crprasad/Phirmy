"""Saaras v4 realtime recognition; normalize provider events for the media engine."""
import asyncio
import base64
import contextlib
import json
import math
from urllib.parse import urlencode

import websockets

from .config import settings


class Recognition:
    def __init__(self, socket):
        self.socket = socket
        self.finished_utterance = -1
        self.started_utterance = -1
        self.billed_ms = None
        self.closed = False
        self.keepalive = asyncio.create_task(self._ping())

    @classmethod
    async def connect(cls, language, *, manual=False):
        params = {'model': settings.sarvam_stt_model, 'language_code': language,
                  'stream_type': 'fast', 'mode': 'transcribe', 'encoding': 'linear16',
                  'sample_rate': 16000, 'endpointing': 'manual' if manual else 'vad',
                  'silence_duration_ms': settings.sarvam_endpointing_ms,
                  'min_speech_duration_ms': 100, 'threshold': .3}
        socket = await websockets.connect(
            'wss://api.sarvam.ai/speech-to-text-realtime/ws?' + urlencode(params),
            additional_headers={'api-subscription-key': settings.sarvam_api_key},
            max_size=1_000_000, max_queue=8, open_timeout=15, close_timeout=2)
        try:
            event = json.loads(await asyncio.wait_for(socket.recv(), 15))
            if event.get('event') != 'session.begin':
                raise RuntimeError('Sarvam recognition did not start')
            config = event.get('config', {})
            if config.get('model') != settings.sarvam_stt_model:
                raise RuntimeError('Sarvam recognition model mismatch')
            return cls(socket)
        except BaseException:
            await socket.close()
            raise

    async def _ping(self):
        try:
            while True:
                await asyncio.sleep(15)
                await self.socket.send(json.dumps({'event': 'ping'}))
        except asyncio.CancelledError:
            raise
        except Exception:
            await self.socket.close()  # Wake the owner receive on keepalive failure.

    async def send(self, pcm):
        await self.socket.send(json.dumps({'event': 'audio_input', 'audio': base64.b64encode(pcm).decode()}))

    def usage(self, event):
        duration = event.get('audio_duration_s')
        if type(duration) in {int, float} and math.isfinite(duration) and 0 <= duration <= 3600:
            self.billed_ms = math.ceil(duration * 1000)

    async def __aiter__(self):
        async for raw in self.socket:
            event = json.loads(raw)
            kind = event.get('event')
            if kind == 'error':
                raise RuntimeError('Sarvam recognition returned an error')
            if kind == 'session.end':
                self.usage(event)
                return
            if kind not in {'vad.speech_start', 'transcript.partial', 'transcript.final'}:
                continue
            index = event.get('utterance_idx')
            if type(index) is not int or index < 0:
                raise RuntimeError('Invalid recognition utterance identity')
            if index <= self.finished_utterance or index < self.started_utterance:
                continue
            if index > self.started_utterance:
                self.started_utterance = index
                yield json.dumps({'type': 'SpeechStarted'})
            if kind == 'vad.speech_start':
                continue
            text = event.get('text')
            if not isinstance(text, str) or len(text) > 8000:
                raise RuntimeError('Invalid recognition transcript')
            final = kind == 'transcript.final'
            if final:
                self.finished_utterance = index
            yield json.dumps({'type': 'Results', 'is_final': final, 'speech_final': final,
                              'channel': {'alternatives': [{'transcript': text}]},
                              'language': event.get('language') or event.get('language_code')})

    async def close(self):
        if self.closed:
            return
        self.closed = True
        self.keepalive.cancel()
        await asyncio.gather(self.keepalive, return_exceptions=True)
        try:
            if self.billed_ms is None:
                await self.socket.send(json.dumps({'event': 'end'}))
                async with asyncio.timeout(2):
                    async for raw in self.socket:
                        event = json.loads(raw)
                        if event.get('event') == 'session.end':
                            self.usage(event)
                            break
        except Exception:
            pass
        finally:
            with contextlib.suppress(Exception):
                await self.socket.close()


async def transcribe(wav):
    """Bounded widget dictation uses the same latest realtime model in manual mode."""
    import io
    import wave
    with wave.open(io.BytesIO(wav)) as audio:
        if (audio.getframerate(), audio.getnchannels(), audio.getsampwidth()) != (16000, 1, 2):
            raise ValueError('Canonical microphone audio required')
        pcm = audio.readframes(16000 * 30 + 1)
    if len(pcm) > 16000 * 30 * 2:
        raise ValueError('Record up to 30 seconds')
    session = await Recognition.connect(settings.sarvam_language, manual=True)
    try:
        async with asyncio.timeout(40):
            await session.socket.send(json.dumps({'event': 'speech_start'}))
            for offset in range(0, len(pcm), 6400):
                await session.send(pcm[offset:offset + 6400])
            await session.socket.send(json.dumps({'event': 'speech_end'}))
            async for raw in session:
                event = json.loads(raw)
                if event.get('speech_final'):
                    return event['channel']['alternatives'][0]['transcript']
            raise RuntimeError('Sarvam dictation ended without a final transcript')
    finally:
        await session.close()

"""Synthetic SDK/WebSocket boundaries; actual media, admission and codec code run."""
import asyncio
from contextlib import ExitStack, contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import msgpack


class SyntheticVoiceProviders:
    def __init__(self, *, retrieval_delay=.04, model_first_token=.18, token_delay=.05,
                 fish_connect=.04, fish_first_audio=.12, tokens=38):
        self.delays = {'retrieval':retrieval_delay,'model_first_token':model_first_token,'token':token_delay,
                       'fish_connect':fish_connect,'fish_first_audio':fish_first_audio}
        self.chunks = ['word ']*tokens+['done.']
        self.sockets = []
        self.active_model_streams = set()
        self.clients = []
        self.model_requests = 0
        self.text_submissions = []

    async def retrieval(self, *args, **kwargs):
        await asyncio.sleep(self.delays['retrieval'])
        return {'answerable':True,'passages':[]}

    def model_client(self, **kwargs):
        fixture = self
        class Stream:
            async def __aenter__(self):
                fixture.active_model_streams.add(self)
                return self
            async def __aexit__(self, *args):
                fixture.active_model_streams.discard(self)
            async def __aiter__(self):
                for index, chunk in enumerate(fixture.chunks):
                    await asyncio.sleep(fixture.delays['model_first_token' if index==0 else 'token'])
                    yield SimpleNamespace(type='response.output_text.delta',delta=chunk)
                yield SimpleNamespace(type='response.completed',response=SimpleNamespace(output=[],usage=SimpleNamespace(
                    input_tokens=100,output_tokens=50,input_tokens_details=SimpleNamespace(cached_tokens=0,cache_write_tokens=0))))
        class Client:
            def __init__(self):
                self.responses = SimpleNamespace(create=self.create)
                self.closed=False
                fixture.clients.append(self)
            async def create(self, **request):
                assert request['stream'] is True
                fixture.model_requests+=1
                return Stream()
            async def close(self):
                self.closed=True
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                await self.close()
        return Client()

    def fish_socket(self, url, **kwargs):
        assert url == 'wss://api.fish.audio/v1/tts/live'
        fixture = self
        class Socket:
            def __init__(self):
                self.inputs, self.outputs = asyncio.Queue(), asyncio.Queue()
                self.worker = None
                self.closed = False
                self.events = []
            async def connect(self):
                await asyncio.sleep(fixture.delays['fish_connect'])
                self.worker = asyncio.create_task(self.synthesize())
                fixture.sockets.append(self)
                return self
            def __await__(self):
                return self.connect().__await__()
            async def __aenter__(self):
                return await self.connect()
            async def __aexit__(self, *args):
                await self.close()
            async def send(self, data):
                event = msgpack.unpackb(data,raw=False)
                self.events.append(event)
                if event['event']=='start':
                    assert event['request']['text']=='' and event['request']['format']=='pcm'
                    assert event['request']['latency']=='balanced'
                    return
                if event['event']=='text':
                    fixture.text_submissions.append(event['text'])
                assert event['event'] in {'text','flush','stop'}
                await self.inputs.put(event)
            async def synthesize(self):
                first = True
                while True:
                    event = await self.inputs.get()
                    if event['event']=='stop':
                        await self.outputs.put(msgpack.packb({'event':'finish','reason':'stop'},use_bin_type=True))
                        return
                    if event['event']=='text':
                        if first:
                            await asyncio.sleep(fixture.delays['fish_first_audio'])
                            first = False
                        await self.outputs.put(msgpack.packb({'event':'audio','audio':b'\0'*960},use_bin_type=True))
            def __aiter__(self):
                return self
            async def __anext__(self):
                return await self.outputs.get()
            async def recv(self):
                return await self.outputs.get()
            async def close(self):
                self.closed = True
                if self.worker:
                    self.worker.cancel()
                    try:
                        await self.worker
                    except asyncio.CancelledError:
                        pass
        return Socket()

    @contextmanager
    def installed(self):
        from studio.config import settings
        with ExitStack() as stack:
            stack.enter_context(patch('studio.media.retrieve',self.retrieval))
            stack.enter_context(patch('studio.handoff.reply',AsyncMock(return_value=None)))
            stack.enter_context(patch('openai.AsyncOpenAI',self.model_client))
            stack.enter_context(patch('websockets.connect',self.fish_socket))
            for name,value in {'openai_api_key':'synthetic-voice-key','openai_base_url':'https://api.openai.com/v1',
                               'openai_api_style':'responses','openai_token_parameter':'max_output_tokens',
                               'openai_model':'gpt-5.6-luna','fish_api_key':'synthetic-fish-key'}.items():
                stack.enter_context(patch.object(settings,name,value))
            yield self

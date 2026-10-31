import asyncio
from contextlib import suppress
import json

from fastapi import HTTPException
import pytest

from studio import llm, llm_connections
from studio.config import settings
from studio.llm_requests import for_voice
from llm_test_helpers import profile
from test_voice_latency import voice
from voice_latency_fixture import SyntheticVoiceProviders


@pytest.fixture
def clients(monkeypatch):
    entries=[]
    class Client:
        def __init__(self,**kwargs):
            self.options=kwargs
            self.closed=False
            entries.append(self)
        async def close(self):
            self.closed=True
            if self.options.get('http_client'):await self.options['http_client'].aclose()
        async def __aenter__(self):return self
        async def __aexit__(self,*args):await self.close()
    import openai
    monkeypatch.setattr(openai,'AsyncOpenAI',Client)
    return entries


@pytest.mark.asyncio
async def test_two_turns_share_client_but_rotation_and_capacity_close_idle_clients(clients):
    pool=llm_connections.CallClients('workspace',limit=1)
    first=for_voice(profile(),{})
    async with pool.lease(first,'workspace') as a:pass
    async with pool.lease(first,'workspace') as b:pass
    assert a is b and len(clients)==1 and not a.closed
    async with pool.lease({**first,'api_key':'rotated-synthetic-key'},'workspace') as rotated:
        assert rotated is not a and a.closed
    await pool.close()
    assert all(client.closed for client in clients)
    with pytest.raises(RuntimeError,match='closed'):
        async with pool.lease(first,'workspace'):pass


@pytest.mark.asyncio
async def test_pool_never_crosses_workspace_or_evicts_active_connection(clients):
    pool=llm_connections.CallClients('workspace',limit=1)
    selected=for_voice(profile(),{})
    with pytest.raises(HTTPException,match='another workspace'):
        async with pool.lease(selected,'foreign'):pass
    assert not clients
    async with pool.lease(selected,'workspace') as active:
        with pytest.raises(HTTPException,match='connection limit'):
            async with pool.lease({**selected,'api_key':'different-synthetic-key'},'workspace'):pass
        assert not active.closed
    await pool.close()


@pytest.mark.asyncio
async def test_public_endpoint_guard_is_preserved_for_warm_clients(clients):
    from studio.network import PublicTransport
    pool=llm_connections.CallClients('workspace')
    async with pool.lease(for_voice(profile(public_only=True),{}),'workspace') as client:
        transport=client.options['http_client']
        assert isinstance(transport._transport,PublicTransport)
        assert not transport._trust_env and not transport.follow_redirects
    await pool.close()
    assert transport.is_closed


@pytest.mark.asyncio
async def test_disabling_keepalive_closes_every_temporary_client(clients,monkeypatch):
    monkeypatch.setattr(settings,'voice_llm_keepalive_enabled',False)
    pool=llm_connections.CallClients('workspace')
    token=llm_connections.current.set(pool)
    try:
        for _ in range(2):
            async with llm_connections.client_for(for_voice(profile(),{}),'workspace'):pass
    finally:
        llm_connections.current.reset(token)
        await pool.close()
    assert len(clients)==2 and all(client.closed for client in clients)


@pytest.mark.asyncio
async def test_normal_turns_reuse_one_client_and_recheck_profile_every_time(voice,monkeypatch):
    _,_,_,_,session,_=voice
    fixture=SyntheticVoiceProviders(retrieval_delay=0,model_first_token=0,token_delay=0,fish_connect=0,fish_first_audio=0,tokens=1)
    original=llm.resolve
    resolved=[]
    def resolve(*args):
        resolved.append(True)
        if len(resolved)>2:raise ValueError('Synthetic profile was disabled')
        return original(*args)
    monkeypatch.setattr(llm,'resolve',resolve)
    with fixture.installed():
        try:
            for _ in range(3):
                await session.user_text('Synthetic profile resolution')
                await session.task
            assert len(resolved)==3
            assert len(fixture.clients)==1
            assert fixture.model_requests==2
        finally:await session.close_providers()
    assert all(client.closed for client in fixture.clients)


@pytest.mark.asyncio
async def test_barge_in_closes_old_stream_but_reuses_healthy_http_client(voice):
    _,_,_,_,session,_=voice
    fixture=SyntheticVoiceProviders(retrieval_delay=0,model_first_token=10,fish_connect=0)
    with fixture.installed():
        try:
            await session.user_text('Synthetic interrupted question')
            async def entered():
                while not fixture.active_model_streams:await asyncio.sleep(.001)
            await asyncio.wait_for(entered(),2)
            await session.interrupt()
            assert not fixture.active_model_streams
            fixture.delays.update(model_first_token=0,token=0,fish_connect=0,fish_first_audio=0)
            fixture.chunks=['Synthetic next answer.']
            await session.user_text('Synthetic next question')
            await session.task
            assert len(fixture.clients)==1 and fixture.model_requests==2
        finally:await session.close_providers()
    assert all(client.closed for client in fixture.clients)


@pytest.mark.asyncio
async def test_repeated_call_cleanup_cancellation_still_observes_client_close(clients):
    pool=llm_connections.CallClients('workspace')
    async with pool.lease(for_voice(profile(),{}),'workspace') as client:pass
    entered,release=asyncio.Event(),asyncio.Event()
    original=client.close
    async def blocked():
        entered.set()
        await release.wait()
        await original()
    client.close=blocked
    task=asyncio.create_task(pool.close())
    try:
        await asyncio.wait_for(entered.wait(),1)
        task.cancel();await asyncio.sleep(0)
        task.cancel();await asyncio.sleep(0)
        assert not task.done()
    finally:release.set()
    with pytest.raises(asyncio.CancelledError):await task
    assert client.closed


@pytest.mark.asyncio
@pytest.mark.parametrize('send_tail',[True,False])
async def test_real_sdk_reuses_tcp_connection_after_terminal_sse_tail(account,send_tail):
    _,workspace_id,_=account
    connections=[];writers=set();handlers=set()
    async def serve(reader,writer):
        handlers.add(asyncio.current_task());writers.add(writer);connections.append(writer)
        try:
            while True:
                line=await asyncio.wait_for(reader.readline(),3)
                if not line:return
                headers={}
                while (line:=await reader.readline()) not in {b'\r\n',b''}:
                    key,body=line.decode().split(':',1);headers[key.lower()]=body.strip()
                await reader.readexactly(int(headers.get('content-length','0')))
                event={'type':'response.completed','response':{'id':'synthetic-response','object':'response','status':'completed',
                    'model':'gpt-5.6-luna','output':[],
                    'usage':{'input_tokens':100,'output_tokens':5,'input_tokens_details':{'cached_tokens':0,'cache_write_tokens':0}}}}
                content=('event: response.completed\ndata: '+json.dumps(event)+'\n\n').encode()
                tail=b'data: [DONE]\n\n'
                writer.write(('HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nContent-Length: '+str(len(content)+len(tail))+
                              '\r\nConnection: keep-alive\r\n\r\n').encode()+content)
                await writer.drain();await asyncio.sleep(.02)
                if not send_tail:
                    await reader.read(1)
                    return
                writer.write(tail);await writer.drain()
        except (ConnectionError,asyncio.TimeoutError):pass
        finally:
            writer.close()
            with suppress(ConnectionError):await writer.wait_closed()
            writers.discard(writer);handlers.discard(asyncio.current_task())
    server=await asyncio.start_server(serve,'127.0.0.1',0)
    port=server.sockets[0].getsockname()[1]
    selected=for_voice(profile(base_url=f'http://127.0.0.1:{port}/v1',workspace_id=workspace_id),{})
    pool=llm_connections.CallClients(workspace_id)
    token=llm_connections.current.set(pool)
    try:
        async def two_turns():
            for _ in range(2):
                turn=llm.Turn(selected,'Synthetic trusted policy',[])
                assert [part async for part in turn.stream()]==[]
        await asyncio.wait_for(two_turns(),5)
        assert len(connections)==(1 if send_tail else 2),(
            'Drain a valid SSE tail for actual keepalive; discard a stalled connection without replaying generation')
    finally:
        llm_connections.current.reset(token)
        await pool.close()
        server.close();await server.wait_closed()
        for writer in list(writers):writer.close()
        for task in list(handlers):task.cancel()
        await asyncio.gather(*list(handlers),return_exceptions=True)

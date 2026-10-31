"""Call-scoped, bounded HTTP keepalive; model authorization is never cached."""
import asyncio
from collections import OrderedDict
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import hashlib
import logging

from fastapi import HTTPException
from .async_work import durable_await

current=ContextVar('voice_llm_clients',default=None)
log=logging.getLogger(__name__)


async def create_client(profile):
    from openai import AsyncOpenAI
    extra={}
    if profile.get('public_only'):
        import httpx
        from .network import PublicTransport
        extra['http_client']=httpx.AsyncClient(transport=PublicTransport(),follow_redirects=False,timeout=35,trust_env=False)
    try:
        return AsyncOpenAI(api_key=profile['api_key'],base_url=profile['base_url'],timeout=35,max_retries=0,**extra)
    except BaseException:
        if extra.get('http_client'):await extra['http_client'].aclose()
        raise


@dataclass
class Entry:
    client: object
    users: int=0


async def close_client(client):
    try:
        await asyncio.wait_for(client.close(),3)
    except Exception:
        log.warning('voice_llm_client_close_failed')


async def drain_completed(iterator):
    """Read the bounded terminal SSE tail so HTTP keepalive can actually work."""
    from .voice_latency import mark
    try:
        async with asyncio.timeout(.25):
            async for _ in iterator:pass
    except Exception:
        # Completed output/usage is authoritative. A missing terminal tail
        # forfeits this connection; never retry generation or accept more tools.
        mark('llm_tail_unavailable')
    else:mark('llm_response_drained')


class CallClients:
    def __init__(self, workspace_id, *, limit=2):
        self.workspace_id,self.limit=workspace_id,limit
        self.entries=OrderedDict()
        self.lock=asyncio.Lock()
        self.closed=False

    @asynccontextmanager
    async def lease(self,profile,workspace_id):
        if workspace_id!=self.workspace_id:
            raise HTTPException(409,'Voice model connection belongs to another workspace')
        key=(profile['base_url'],hashlib.sha256(profile['api_key'].encode()).hexdigest(),bool(profile.get('public_only')))
        async with self.lock:
            if self.closed:raise RuntimeError('Voice model connections are closed')
            entry=self.entries.get(key)
            if entry is None:
                if len(self.entries)>=self.limit:
                    idle=next((identity for identity,item in self.entries.items() if not item.users),None)
                    if idle is None:raise HTTPException(503,'This call has reached its model connection limit')
                    await durable_await(close_client(self.entries.pop(idle).client))
                entry=Entry(await create_client(profile))
                self.entries[key]=entry
            entry.users+=1
            self.entries.move_to_end(key)
        try:
            yield entry.client
        finally:
            async with self.lock:entry.users-=1

    async def close(self):
        async with self.lock:
            self.closed=True
            entries=list(self.entries.values())
            self.entries.clear()
        await durable_await(asyncio.gather(*(close_client(entry.client) for entry in entries)))


@asynccontextmanager
async def client_for(profile,workspace_id):
    from .config import settings
    pool=current.get()
    if pool is not None and profile.get('voice') and settings.voice_llm_keepalive_enabled:
        async with pool.lease(profile,workspace_id) as client:yield client
    else:
        async with await create_client(profile) as client:yield client

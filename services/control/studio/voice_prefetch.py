"""Bounded, read-only speculation. Only an exact final query may reuse a result."""
import asyncio
from dataclasses import dataclass
import time
import unicodedata

from .async_work import durable_await
from .config import settings


def normalize(query):
    return unicodedata.normalize('NFC',' '.join(query.split()))


@dataclass
class Entry:
    started: float
    task: object=None
    completed: float | None=None
    elapsed_ms: float | None=None


class InterimPrefetch:
    def __init__(self,retrieve,validate,*,clock=time.monotonic):
        self.retrieve,self.validate,self.clock=retrieve,validate,clock
        self.pending=None
        self.candidate=None
        self.entries={}
        self.active=set()
        self.attempts=0
        self.generation=0
        self.closed=False

    def _observe_done(self,task):
        self.active.discard(task)
        if not task.cancelled():task.exception()

    def _cancel_pending(self):
        if self.pending is not None and not self.pending.done() and not self.pending.cancelling():
            self.pending.cancel()
        self.pending=None

    def reset(self):
        self._cancel_pending()
        self.generation+=1
        self.attempts=0
        self.candidate=None
        self.entries.clear()
        # Let already-paid embedding work finish so its actual usage is known.
        # It still counts against the two concurrent tasks across utterances.

    def observe(self,query,snapshot_ids):
        if self.closed or not settings.voice_prefetch_enabled:return
        query=normalize(query)
        if not 16<=len(query)<=4000 or len(query.split())<3:return
        key=(tuple(snapshot_ids),query)
        if key==self.candidate:return
        self._cancel_pending()
        self.candidate=key
        if key in self.entries or self.attempts>=settings.voice_prefetch_max_requests:return
        self.pending=asyncio.create_task(self._delay(key,self.generation),name='voice-retrieval-debounce')
        self.pending.add_done_callback(self._observe_done)

    async def _delay(self,key,generation):
        await asyncio.sleep(settings.voice_prefetch_debounce_ms/1000)
        if (self.closed or not settings.voice_prefetch_enabled or generation!=self.generation or key!=self.candidate or
            self.attempts>=settings.voice_prefetch_max_requests or len(self.active)>=2):return
        self.attempts+=1
        entry=Entry(self.clock())
        task=asyncio.create_task(self._fetch(entry,key),name='voice-retrieval-prefetch')
        entry.task=task
        self.entries[key]=entry
        self.active.add(task)
        task.add_done_callback(self._observe_done)

    async def _fetch(self,entry,key):
        try:return await self.retrieve(key[1],key[0])
        finally:
            entry.completed=self.clock()
            entry.elapsed_ms=round(max(0,entry.completed-entry.started)*1000,3)

    async def take(self,query,snapshot_ids):
        self._cancel_pending()
        if not settings.voice_prefetch_enabled:return None
        entry=self.entries.get((tuple(snapshot_ids),normalize(query)))
        if entry is None:return None
        ttl=settings.voice_prefetch_result_ttl_seconds
        if entry.completed is not None and self.clock()-entry.completed>ttl:return None
        result=await asyncio.shield(entry.task)
        if self.clock()-entry.completed>ttl:return None
        if not await self.validate(tuple(snapshot_ids),result):return None
        return result,entry.elapsed_ms

    async def close(self):
        self.closed=True
        pending=self.pending
        self._cancel_pending()
        tasks=set(self.active)
        if pending is not None:tasks.add(pending)
        for task in tasks:
            if not task.done() and not task.cancelling():task.cancel()
        await durable_await(asyncio.gather(*tasks,return_exceptions=True))
        self.entries.clear()

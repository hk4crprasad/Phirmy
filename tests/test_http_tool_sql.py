import asyncio
import threading

import httpx
import pytest
from sqlalchemy import select

from studio import http_tools
from studio.db import session_scope
from studio.models import ToolExecution
from test_custom_runtime import create_tool
from test_media_lifecycle import assert_no_sql_on_running_loop


@pytest.mark.asyncio
async def test_custom_tool_create_claim_and_completion_run_off_audio_loop(account,monkeypatch):
    _,ws,_=account;tool=create_tool(account,monkeypatch)
    requests=[]
    def endpoint(request):requests.append(request);return httpx.Response(200,json={'status':'ok'})
    monkeypatch.setattr(http_tools,'PublicTransport',lambda:httpx.MockTransport(endpoint))
    with assert_no_sql_on_running_loop():
        result=await http_tools.invoke(ws,tool['id'],1,{'order_id':'safe'},{},'off-loop')
    assert result['state']=='succeeded' and len(requests)==1


@pytest.mark.asyncio
async def test_cancel_during_request_records_unknown_and_replay_never_resends(account,monkeypatch):
    _,ws,_=account;tool=create_tool(account,monkeypatch)
    entered=asyncio.Event();requests=[]
    async def endpoint(request):
        requests.append(request);entered.set();await asyncio.Event().wait()
    monkeypatch.setattr(http_tools,'PublicTransport',lambda:httpx.MockTransport(endpoint))
    with assert_no_sql_on_running_loop():
        task=asyncio.create_task(http_tools.invoke(ws,tool['id'],1,{'order_id':'safe'},{},'interrupted'))
        await asyncio.wait_for(entered.wait(),2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        replay=await http_tools.invoke(ws,tool['id'],1,{'order_id':'safe'},{},'interrupted')
    assert replay['state']=='unknown' and len(requests)==1


@pytest.mark.asyncio
async def test_cancel_during_queue_observes_commit_then_closes_unused_execution(account,monkeypatch):
    _,ws,_=account;tool=create_tool(account,monkeypatch)
    entered,release=threading.Event(),threading.Event()
    original=http_tools._queue_execution
    def slow(*args,**kwargs):
        result=original(*args,**kwargs);entered.set();assert release.wait(3);return result
    monkeypatch.setattr(http_tools,'_queue_execution',slow)
    with assert_no_sql_on_running_loop():
        task=asyncio.create_task(http_tools.invoke(ws,tool['id'],1,{'order_id':'safe'},{},'unused'))
        try:
            assert await asyncio.to_thread(entered.wait,2)
            task.cancel();await asyncio.sleep(0);assert not task.done()
            release.set()
            with pytest.raises(asyncio.CancelledError):await task
        finally:release.set()
    with session_scope() as db:
        row=db.scalar(select(ToolExecution))
        assert row.state=='failed' and 'before external' in row.result['error']


@pytest.mark.asyncio
async def test_concurrent_consumers_submit_one_http_request(account,monkeypatch):
    _,ws,_=account;tool=create_tool(account,monkeypatch)
    queued=await asyncio.to_thread(http_tools._queue_execution,ws,tool['id'],1,{'order_id':'safe'},{},'one-claim')
    entered,release=asyncio.Event(),asyncio.Event();requests=[]
    async def endpoint(request):
        requests.append(request);entered.set();await release.wait();return httpx.Response(200,json={'ok':True})
    monkeypatch.setattr(http_tools,'PublicTransport',lambda:httpx.MockTransport(endpoint))
    with assert_no_sql_on_running_loop():
        first=asyncio.create_task(http_tools.perform(queued['execution_id']))
        await asyncio.wait_for(entered.wait(),2)
        second=await http_tools.perform(queued['execution_id'])
        assert second['state']=='running'
        release.set()
        assert (await first)['state']=='succeeded'
    assert len(requests)==1


@pytest.mark.asyncio
async def test_known_http_result_survives_cancellation_during_client_close(account,monkeypatch):
    _,ws,_=account;tool=create_tool(account,monkeypatch)
    entered=asyncio.Event()
    class Transport(httpx.MockTransport):
        async def aclose(self):entered.set();await asyncio.Event().wait()
    monkeypatch.setattr(http_tools,'PublicTransport',lambda:Transport(lambda request:httpx.Response(200,json={'completed':True})))
    with assert_no_sql_on_running_loop():
        task=asyncio.create_task(http_tools.invoke(ws,tool['id'],1,{'order_id':'safe'},{},'known-result'))
        await asyncio.wait_for(entered.wait(),2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
    with session_scope() as db:
        row=db.scalar(select(ToolExecution))
        assert row.state=='succeeded' and row.result['response']=={'completed':True}

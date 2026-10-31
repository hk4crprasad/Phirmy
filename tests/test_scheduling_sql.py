import asyncio
import threading

import pytest
from sqlalchemy import func,select

from studio import scheduling
from studio.db import session_scope
from studio.models import SchedulingBooking,Appointment
from test_agent_scheduling import scheduler,prepare,confirmed_context
from test_media_lifecycle import assert_no_sql_on_running_loop


@pytest.mark.asyncio
async def test_availability_readback_confirmation_and_reconciliation_have_no_audio_loop_sql(scheduler):
    s=scheduler
    with assert_no_sql_on_running_loop():
        _,proposal=await prepare(s)
        result=await scheduling.agent_action('confirm_scheduling_booking',{'booking_id':proposal['booking_id']},confirmed_context(s,proposal))
        assert result['booking_confirmed'],result
        refreshed=await scheduling.agent_action('get_scheduling_booking',{'booking_id':proposal['booking_id']},s.context)
        assert refreshed['booking_confirmed']
    assert len(s.state['posts'])==1


@pytest.mark.asyncio
async def test_cancel_after_durable_claim_before_http_closes_known_unused_booking(scheduler,monkeypatch):
    s=scheduler;_,proposal=await prepare(s)
    entered,release=threading.Event(),threading.Event()
    original=scheduling.durable_to_thread
    async def observe(function,*args,**kwargs):
        if function.__name__!='claim_submission':return await original(function,*args,**kwargs)
        def slow():
            result=function(*args,**kwargs);entered.set();assert release.wait(3);return result
        return await original(slow)
    monkeypatch.setattr(scheduling,'durable_to_thread',observe)
    with assert_no_sql_on_running_loop():
        task=asyncio.create_task(scheduling.confirm({'booking_id':proposal['booking_id']},confirmed_context(s,proposal)))
        try:
            assert await asyncio.to_thread(entered.wait,2)
            task.cancel();await asyncio.sleep(0);assert not task.done()
            release.set()
            with pytest.raises(asyncio.CancelledError):await task
        finally:release.set()
    assert not s.state['posts']
    with session_scope() as db:
        row=db.get(SchedulingBooking,proposal['booking_id'])
        assert row.state=='failed' and 'before external' in row.result['message']


@pytest.mark.asyncio
async def test_provider_success_survives_canceled_result_commit_and_never_posts_twice(scheduler,monkeypatch):
    s=scheduler;_,proposal=await prepare(s)
    entered,release=threading.Event(),threading.Event()
    original=scheduling.store_result
    def slow(*args):
        result=original(*args);entered.set();assert release.wait(3);return result
    monkeypatch.setattr(scheduling,'store_result',slow)
    with assert_no_sql_on_running_loop():
        task=asyncio.create_task(scheduling.confirm({'booking_id':proposal['booking_id']},confirmed_context(s,proposal)))
        try:
            assert await asyncio.to_thread(entered.wait,3)
            task.cancel();release.set()
            with pytest.raises(asyncio.CancelledError):await task
        finally:release.set()
        result=await scheduling.confirm({'booking_id':proposal['booking_id']},confirmed_context(s,proposal))
    assert result['booking_confirmed'] and len(s.state['posts'])==1
    with session_scope() as db:assert db.scalar(select(func.count()).select_from(Appointment))==1

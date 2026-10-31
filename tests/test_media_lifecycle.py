import asyncio
from contextlib import contextmanager
import threading

import pytest
from sqlalchemy import event

from studio import media, media_lifecycle
from studio.config import settings
from studio.db import engine, session_scope
from studio.models import Call


@contextmanager
def assert_no_sql_on_running_loop():
    violations=[]
    def query(*args):
        try:asyncio.get_running_loop()
        except RuntimeError:return
        violations.append(True)
        raise AssertionError('SQL ran on the media event loop')
    event.listen(engine,'before_cursor_execute',query)
    try:yield
    finally:event.remove(engine,'before_cursor_execute',query)
    assert not violations


def test_browser_handshake_greeting_and_settlement_have_no_event_loop_sql(sample):
    client,_,base,fixture=sample
    state=client.post(base+'/voice/sessions',json={'agent_id':fixture['agent_id'],'mode':'simulation'}).json()
    with assert_no_sql_on_running_loop():
        with client.websocket_connect('/v1/media',headers={'Origin':settings.app_origin}) as ws:
            ws.send_json({'type':'client.start','session_token':state['session_token']})
            assert ws.receive_json()['type']=='server.ready'
            while True:
                response=ws.receive_json()
                if response.get('type')=='server.turn_state' and response['state']=='listening':break
            ws.send_json({'type':'client.stop'})
            while ws.receive_json()['type']!='server.ended':pass


@pytest.mark.asyncio
async def test_cancel_during_committed_setup_observes_result_settles_and_releases_owner(sample,monkeypatch):
    client,_,base,fixture=sample
    state=client.post(base+'/voice/sessions',json={'agent_id':fixture['agent_id'],'mode':'simulation'}).json()
    entered,release=threading.Event(),threading.Event()
    original=media.VoiceSession
    class Session(original):
        def __init__(self,*args,**kwargs):
            entered.set()
            assert release.wait(3)
            super().__init__(*args,**kwargs)
    monkeypatch.setattr(media,'VoiceSession',Session)
    class Socket:
        headers={'origin':settings.app_origin}
        closed=False
        async def accept(self):pass
        async def receive_json(self):return {'type':'client.start','session_token':state['session_token']}
        async def send_json(self,*args):pass
        async def close(self):self.closed=True
    socket=Socket()
    from studio.security import verify_capability
    call_id=verify_capability(state['session_token'],'media')['call_id']
    with assert_no_sql_on_running_loop():
        task=asyncio.create_task(media.browser_media(socket))
        try:
            assert await asyncio.to_thread(entered.wait,2)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done() and call_id in media.owners
            release.set()
            with pytest.raises(asyncio.CancelledError):await asyncio.wait_for(task,3)
        finally:release.set()
    assert call_id not in media.owners and socket.closed
    with session_scope() as db:assert db.get(Call,call_id).state=='failed'


def test_constructor_failure_after_admission_still_settles_call(sample,monkeypatch):
    client,_,base,fixture=sample
    state=client.post(base+'/voice/sessions',json={'agent_id':fixture['agent_id'],'mode':'simulation'}).json()
    def broken(*args,**kwargs):raise RuntimeError('Synthetic initialization failure')
    monkeypatch.setattr(media,'VoiceSession',broken)
    from studio.security import verify_capability
    call_id=verify_capability(state['session_token'],'media')['call_id']
    with client.websocket_connect('/v1/media',headers={'Origin':settings.app_origin}) as ws:
        ws.send_json({'type':'client.start','session_token':state['session_token']})
        assert ws.receive_json()['code']=='media_failed'
        assert ws.receive()['type']=='websocket.close'
    assert call_id not in media.owners
    with session_scope() as db:assert db.get(Call,call_id).state=='failed'


def test_invalid_reused_handshake_cannot_settle_someone_elses_call(sample):
    client,_,base,fixture=sample
    state=client.post(base+'/voice/sessions',json={'agent_id':fixture['agent_id'],'mode':'simulation'}).json()
    from studio.security import verify_capability
    call_id=verify_capability(state['session_token'],'media')['call_id']
    with session_scope(write=True) as db:db.get(Call,call_id).state='connected'
    with client.websocket_connect('/v1/media',headers={'Origin':settings.app_origin}) as ws:
        ws.send_json({'type':'client.start','session_token':state['session_token']})
        assert ws.receive_json()['code']=='session_invalid'
        assert ws.receive()['type']=='websocket.close'
    assert call_id not in media.owners
    with session_scope() as db:assert db.get(Call,call_id).state=='connected'

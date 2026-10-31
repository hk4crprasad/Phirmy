"""Real Chromium regressions for pending-route shutdown, timeout and Stop."""
import asyncio
import time
import base64
import importlib.util
from pathlib import Path
from urllib.robotparser import RobotFileParser
import pytest
from playwright.async_api import BrowserType, Error as PlaywrightError
from studio import knowledge
from studio import website_extraction as renderer

pytestmark = pytest.mark.sandbox

SITE='https://renderer.example'


@pytest.fixture
async def browser_events(monkeypatch,capsys):
    # Exercise the real isolated browser engine with an in-memory IPC adapter so
    # tests can close its page and inject snapshot failures deterministically.
    # Separate container tests verify the production filesystem/network boundary.
    from studio import isolation
    spec=importlib.util.spec_from_file_location('isolated_browser_engine',Path(__file__).resolve().parents[1]/'sandbox_runtime/job.py')
    engine=importlib.util.module_from_spec(spec);spec.loader.exec_module(engine)
    class EngineAdapter:
        async def run(self,request,fetch):
            return {'type':'result','body':base64.b64encode(await engine.render(request,fetch)).decode()}
    monkeypatch.setattr(isolation,'provider',EngineAdapter())
    loop=asyncio.get_running_loop();previous=loop.get_exception_handler()
    errors=[];browsers=[]
    loop.set_exception_handler(lambda loop,context:errors.append(context))
    launch=BrowserType.launch
    async def capture(self,*args,**kwargs):
        # Hosted Ubuntu may expose a slow Snap launcher at /usr/bin/chromium.
        # These host-side lifecycle tests use the browser installed by Playwright;
        # the separate container tests still exercise Debian's production binary.
        kwargs['executable_path']=self.executable_path
        browser=await launch(self,*args,**kwargs);browsers.append(browser);return browser
    monkeypatch.setattr(BrowserType,'launch',capture)
    monkeypatch.setattr(renderer,'RENDER_SETTLE_MILLISECONDS',200)
    try:
        yield browsers,errors
    finally:
        loop.set_exception_handler(previous)
        assert 'Error occurred in event listener' not in capsys.readouterr().err


def robot():
    value=RobotFileParser();value.parse(['User-agent: *','Allow: /']);return value


def assert_closed(events):
    browsers,errors=events
    assert browsers and all(not browser.is_connected() for browser in browsers)
    assert not errors,errors


@pytest.mark.asyncio
async def test_success_cancels_pending_and_queued_fetches_before_return(monkeypatch,browser_events):
    entered=asyncio.Event();finished=asyncio.Event();active=set();requests=[]
    async def fetch(url,*args,**kwargs):
        requests.append(url)
        if url==SITE+'/':
            return url,b'<html><main>Useful rendered business evidence.</main><script src="/app.js"></script></html>','text/html'
        if url==SITE+'/app.js':
            return url,b"fetch('/slow-a');fetch('/slow-b');fetch('/slow-c');",'application/javascript'
        assert url==SITE+'/slow-a'
        active.add(url);entered.set()
        try:await asyncio.Event().wait()
        finally:active.remove(url);finished.set()
    monkeypatch.setattr(knowledge,'safe_fetch',fetch)
    html=await asyncio.wait_for(renderer.rendered_html(SITE+'/',robot(),0),5)
    assert b'Useful rendered business evidence.' in html
    assert entered.is_set() and finished.is_set() and not active
    assert requests==[SITE+'/',SITE+'/app.js',SITE+'/slow-a']
    await asyncio.sleep(.1)
    assert_closed(browser_events)


@pytest.mark.asyncio
@pytest.mark.parametrize('ending',['cancel','timeout','page_closed'])
async def test_interrupted_main_request_is_drained_without_masking_failure(monkeypatch,browser_events,ending):
    entered=asyncio.Event();finished=asyncio.Event()
    async def fetch(url,*args,**kwargs):
        entered.set()
        try:await asyncio.Event().wait()
        finally:finished.set()
    monkeypatch.setattr(knowledge,'safe_fetch',fetch)
    started=time.monotonic();task=asyncio.create_task(renderer.rendered_html(SITE+'/',robot(),0))
    try:
        await asyncio.wait_for(entered.wait(),5)
        if ending=='cancel':
            task.cancel()
            with pytest.raises(asyncio.CancelledError):await task
        elif ending=='timeout':
            with pytest.raises(TimeoutError):await asyncio.wait_for(task,.4)
        else:
            await browser_events[0][0].contexts[0].pages[0].close()
            with pytest.raises(PlaywrightError):await asyncio.wait_for(task,3)
        assert finished.is_set()
        assert time.monotonic()-started<5
        await asyncio.sleep(.1)
        assert_closed(browser_events)
    finally:
        task.cancel();await asyncio.gather(task,return_exceptions=True)


@pytest.mark.asyncio
async def test_real_snapshot_error_is_not_hidden_by_cleanup(monkeypatch,browser_events):
    from playwright.async_api import Page
    async def fetch(url,*args,**kwargs):return url,b'<html><main>Business information</main></html>','text/html'
    async def fail_snapshot(self):raise PlaywrightError('Synthetic snapshot failure')
    monkeypatch.setattr(knowledge,'safe_fetch',fetch)
    monkeypatch.setattr(Page,'content',fail_snapshot)
    with pytest.raises(PlaywrightError,match='Synthetic snapshot failure'):
        await asyncio.wait_for(renderer.rendered_html(SITE+'/',robot(),0),5)
    assert_closed(browser_events)

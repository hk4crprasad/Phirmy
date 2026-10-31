"""Isolated Voice Lab browser regression; synthetic PCM, no provider sessions.

Build web first, then use with_server.py with this --serve on8100 and
API_ORIGIN=http://127.0.0.1:8100 PUBLIC_API_ORIGIN=http://127.0.0.1:18111
next start apps/web -p3300. This harness only
accepts loopback and owns disposable SQLite; never use a production API.
"""
import asyncio
import json
from pathlib import Path
import runpy
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = 'http://127.0.0.1:3300'


def serve():
    sys.path.insert(0, str(ROOT / 'services/control'))
    runpy.run_path(str(ROOT / 'tests/conftest.py'))
    from studio.config import settings
    settings.app_env = 'development'
    settings.app_origin = ORIGIN
    settings.public_api_origin = 'http://127.0.0.1:8100'
    settings.worker_enabled = False
    assert settings.database_url.startswith('sqlite:') and not settings.sarvam_api_key
    from studio.main import create_app
    from studio.media import AudioPacer, encode_frame
    import uvicorn
    from websockets.asyncio.server import serve as websocket_server

    async def stream(socket):
        hello = json.loads(await socket.recv())
        assert hello['session_token'] in {'offline-legacy', 'offline-fixed'}
        legacy = hello['session_token'] == 'offline-legacy'
        async def incoming():
            async for message in socket:
                if isinstance(message, str) and json.loads(message).get('type') == 'client.stop':
                    await socket.send(json.dumps({'type': 'server.ended'}))
                    await socket.close()
                    return
        reader = asyncio.create_task(incoming())
        try:
            await socket.send(json.dumps({'type': 'server.ready'}))
            await socket.send(json.dumps({'type': 'server.turn_state', 'state': 'speaking'}))
            pacer = AudioPacer()
            old_deadline = started = time.monotonic()
            sequence = 0
            for pause, byte_count in [(1.25, 96000), (2.2, 48480)]:
                await asyncio.sleep(pause)
                clip = b'\0' * byte_count
                for offset in range(0, len(clip), 960):
                    frame = clip[offset:offset+960]
                    if not legacy:
                        await pacer.wait(len(frame) / 48000)
                    await socket.send(encode_frame(frame, sequence, 0, int((time.monotonic()-started)*1e6)))
                    sequence += 1
                    if legacy:
                        # Exact preceding timing contract, retained only to prove
                        # that the browser regression fails before the fix.
                        old_deadline += .02
                        await asyncio.sleep(max(0, old_deadline-time.monotonic()-.16))
            await socket.send(json.dumps({'type': 'server.turn_state', 'state': 'listening'}))
            await reader
        except Exception as error:
            from websockets.exceptions import ConnectionClosed
            if not isinstance(error, ConnectionClosed):
                raise
        finally:
            reader.cancel()
            await asyncio.gather(reader, return_exceptions=True)
    async def main():
        async with websocket_server(stream, '127.0.0.1', 18111):
            await uvicorn.Server(uvicorn.Config(create_app(), host='127.0.0.1', port=8100, log_level='warning')).serve()
    asyncio.run(main())


def verify():
    from playwright.sync_api import sync_playwright, expect
    sys.path.insert(0, str(ROOT / 'scripts'))
    from qa_accounts import bootstrap_account
    art = ROOT / 'artifacts/playout'
    art.mkdir(parents=True, exist_ok=True)
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream'])
        for scenario, mobile in [('legacy', False), ('fixed', False), ('fixed', True)]:
            context = browser.new_context(viewport={'width':390,'height':844} if mobile else {'width':1440,'height':1000},
                is_mobile=mobile, has_touch=mobile, permissions=['microphone'], reduced_motion='reduce')
            assert context.request.get(ORIGIN + '/backend/healthz').status == 200
            response = bootstrap_account(context.request, ORIGIN+'/backend/v1/auth/signup', data={
                'name':'Playout QA', 'email':'playout-'+uuid.uuid4().hex[:10]+'@example.test',
                'password':'Local-Synthetic-Password-Only', 'workspace_name':'Playout QA'})
            workspace = response.json()['workspaces'][0]['id']
            csrf = next(c['value'] for c in context.cookies() if c['name']=='studio_csrf')
            fixture = context.request.post(ORIGIN+'/backend/v1/workspaces/'+workspace+'/fixtures', headers={'X-CSRF-Token':csrf})
            assert fixture.status == 201
            page = context.new_page()
            page.set_default_timeout(20000)
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            def capabilities(route):
                response = route.fetch()
                body = response.json()
                caps = body.get('summary', {}).get('capabilities')
                if caps is not None:
                    caps.update(live_voice=True, voice_provider='sarvam')
                route.fulfill(response=response, json=body)
            page.route('**/backend/v1/workspaces/*/bootstrap*', capabilities)
            page.route('**/backend/v1/workspaces/*/voice/sessions', lambda route: route.fulfill(json={
                'call_id':'offline-playout', 'session_token':'offline-'+scenario,
                'media_url':'ws://127.0.0.1:18111/'}))
            page.add_init_script('''
                window.qaAudio={frames:0,maxAhead:0};
                const Native=window.AudioContext;
                window.AudioContext=class extends Native {
                  createBufferSource(){
                    const source=super.createBufferSource(),start=source.start.bind(source),ctx=this;
                    source.start=(at)=>{
                      window.qaAudio.frames++;
                      window.qaAudio.maxAhead=Math.max(window.qaAudio.maxAhead,at+source.buffer.duration-ctx.currentTime);
                      start(at);
                    };
                    return source;
                  }
                };
            ''')
            page.goto(ORIGIN+'/app/voice')
            page.wait_for_load_state('networkidle')
            page.get_by_role('combobox', name='Test mode').select_option('live')
            page.get_by_role('button', name='Start microphone test').click()
            if scenario == 'legacy':
                expect(page.locator('.error[role="alert"]')).to_contain_text('Audio playback couldn’t keep up')
            else:
                deadline = time.monotonic() + 15
                while page.evaluate('window.qaAudio.frames') < 151 and time.monotonic() < deadline:
                    page.wait_for_timeout(100)
                assert page.evaluate('window.qaAudio.frames') == 151
                expect(page.locator('.error[role="alert"]')).to_have_count(0)
                expect(page.get_by_role('button', name='End session')).to_be_enabled()
                assert page.evaluate('window.qaAudio.maxAhead') < .5
                page.get_by_role('button', name='End session').click()
                expect(page.get_by_role('button', name='Start microphone test')).to_be_visible()
            assert not errors, errors
            result = {'scenario':scenario, 'mobile':mobile, **page.evaluate('window.qaAudio'), 'page_errors':errors}
            results.append(result)
            page.screenshot(path=str(art/(scenario+('-mobile' if mobile else '-desktop')+'.png')), full_page=True)
            context.close()
        browser.close()
    (art/'results.json').write_text(json.dumps(results, indent=2))
    print(json.dumps({'playout_browser':results,'provider_requests':0,'production_requests':0}))


if __name__ == '__main__':
    serve() if '--serve' in sys.argv else verify()

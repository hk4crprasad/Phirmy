"""Exercise the real trial UI/admission against an isolated, worker-free API.

Uses a temporary SQLite database, fake provider bindings and synthetic numbers.
Browser backend requests are forwarded to this API without changing responses.
No dispatcher runs, so queued calls never reach a carrier or speech provider.
"""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit
import httpx
from playwright.sync_api import sync_playwright, expect

from qa_accounts import bootstrap_account
ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / 'artifacts' / 'phone-trials'
ART.mkdir(parents=True, exist_ok=True)
ORIGIN = os.environ.get('BROWSER_TEST_ORIGIN', 'http://127.0.0.1:3100')


with tempfile.TemporaryDirectory(prefix='cynerza-phone-browser-') as folder:
    directory = Path(folder)
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0)); port = listener.getsockname()[1]
    api_origin = 'http://127.0.0.1:' + str(port)
    env = os.environ | {'APP_ENV': 'development', 'APP_ORIGIN': ORIGIN, 'DATABASE_URL': 'sqlite:///' + str(directory / 'qa.db'),
        'SUPABASE_DB_PASSWORD': '', 'DATA_DIR': str(directory / 'data'), 'APP_SECRET': 'synthetic-browser-secret-' + 'x' * 32,
        'OBJECT_STORAGE_PROVIDER': 'local', 'AZURE_STORAGE_CONNECTION_STRING': '', 'AZURE_STORAGE_ACCOUNT_URL': '',
        'VECTOR_ENDPOINT': '', 'VECTOR_API_KEY': '', 'EMBEDDING_API_KEY': '', 'OPENAI_API_KEY': 'synthetic-llm-key',
        'FISH_API_KEY': 'synthetic-fish-key', 'FISH_VOICE_ID': 'synthetic-voice', 'DEEPGRAM_API_KEY': 'synthetic-stt-key',
        'TWILIO_ACCOUNT_SID': 'AC-synthetic-browser', 'TWILIO_AUTH_TOKEN': 'synthetic-browser-token',
        'TWILIO_API_KEY': '', 'TWILIO_API_SECRET': '', 'PHONE_NUMBER_PURCHASES_ENABLED': 'false',
        'PHONE_TRIAL_AUTO_ASSIGN_POOL_ID': 'browser-automatic-pool',
        'PLIVO_AUTH_ID': '', 'PLIVO_AUTH_TOKEN': '', 'SMTP_HOST': '', 'GOOGLE_CLIENT_ID': '', 'GOOGLE_CLIENT_SECRET': '',
        'REQUIRE_EMAIL_VERIFICATION': 'false', 'SESSION_SECURE': 'false', 'DEV_SEED_ENABLED': 'true',
        'PHONE_TRIALS_ENABLED': 'true', 'LIVE_CALLS_ENABLED': 'true', 'LIVE_PAYMENTS_ENABLED': 'false',
        'MEDIA_PUBLIC_ORIGIN': 'https://synthetic.example.test'}
    launch = "import sys;sys.path.insert(0,'services/control');import uvicorn;from studio.main import create_app;uvicorn.run(create_app(start_worker=False),host='127.0.0.1',port=" + str(port) + ",log_level='warning')"
    log = open(directory / 'api.log', 'w')
    server = subprocess.Popen([sys.executable, '-c', launch], cwd=ROOT, env=env, stdout=log, stderr=log)
    try:
        with httpx.Client(trust_env=False) as health:
            for _ in range(60):
                if server.poll() is not None:
                    raise RuntimeError('Isolated API exited')
                try:
                    if health.get(api_origin + '/healthz').status_code == 200: break
                except httpx.HTTPError:
                    pass
                time.sleep(.25)
            else: raise RuntimeError('Isolated API did not start')

        def operate(mode, ws):
            code = '''
import sys
from datetime import timedelta
from sqlalchemy import select
sys.path.insert(0,'services/control')
from studio.db import session_scope,now
from studio.models import PhoneTrialPool,PhoneTrial,PhoneNumberInventory,PhoneNumberOrder,Number,Call,Job
from studio.phone_trials import create_pool,grant_trial
from studio.domain import settle_call
if sys.argv[1]=='allocate':
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import MagicMock,patch
    from studio.workers import execute_job
    sdk=MagicMock()
    sdk.incoming_phone_numbers.list.return_value=[SimpleNamespace(phone_number='+12025550110',sid='PN-synthetic-browser',account_sid='AC-synthetic-browser',capabilities={'voice':True})]
    with session_scope() as db:
        job_id=db.scalar(select(Job.id).where(Job.kind=='phone_number_allocate'))
    with patch('studio.carrier_config.twilio_client',return_value=sdk):
        asyncio.run(execute_job(job_id))
    assert not sdk.incoming_phone_numbers.create.called
    with session_scope(write=True) as db:
        trial=db.scalar(select(PhoneTrial).where(PhoneTrial.workspace_id==sys.argv[2]));assert trial
        trial.destinations=['+12025550111']
    sys.exit(0)
with session_scope(write=True) as db:
    if sys.argv[1]=='seed':
        pool=create_pool(db,name='Browser QA',expires_at=now()+timedelta(days=19),alert_email='owner@example.test')
        pool.id='browser-automatic-pool';db.flush()
        pool.balance_minor,pool.balance_state,pool.balance_checked_at=1500,'ready',now()
        db.add(PhoneNumberInventory(pool_id=pool.id,e164='+12025550110',provider_number_id='PN-synthetic-browser'))
    elif sys.argv[1]=='finish':
        for call in db.scalars(select(Call).where(Call.workspace_id==sys.argv[2],Call.mode=='live')):
            settle_call(db,call,0,'completed')
    else:
        for pool in db.scalars(select(PhoneTrialPool)):
            pool.expires_at=now()-timedelta(seconds=1)
'''
            result = subprocess.run([sys.executable, '-c', code, mode, ws], cwd=ROOT, env=env, capture_output=True, text=True)
            if result.returncode: raise RuntimeError('Isolated operator fixture failed')

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(viewport={'width': 1440, 'height': 1000}, reduced_motion='reduce')
            pending, hold_bootstrap = [], True
            def backend(route):
                path = urlsplit(route.request.url)
                if hold_bootstrap and path.path.endswith('/bootstrap'):
                    pending.append(route)
                    return
                target = api_origin + path.path.removeprefix('/backend') + ('?' + path.query if path.query else '')
                response = route.fetch(url=target, max_redirects=0)
                route.fulfill(response=response)
            context.route('**/backend/**', backend)
            signup = bootstrap_account(context.request, api_origin + '/v1/auth/signup', data={'name': 'Phone QA', 'email': 'phone-browser@example.test',
                'password': 'Long-Synthetic-Phone-Password', 'workspace_name': 'Phone browser QA'})
            assert signup.status == 200
            ws = signup.json()['workspaces'][0]['id']
            csrf = next(cookie['value'] for cookie in context.cookies() if cookie['name'] == 'studio_csrf')
            fixture = context.request.post(api_origin + '/v1/workspaces/' + ws + '/fixtures', data={}, headers={'X-CSRF-Token': csrf, 'Origin': ORIGIN})
            assert fixture.status == 201
            operate('seed', ws)
            page = context.new_page(); page.set_default_timeout(20000)
            errors = []; page.on('pageerror', lambda error: errors.append(str(error)))
            def open_numbers():
                with page.expect_response(lambda response: response.url.endswith('/bootstrap') and response.status == 200):
                    page.goto(ORIGIN + '/app/numbers')
                expect(page.get_by_role('heading', name='Your phone trial', exact=True)).to_be_visible()
            with page.expect_request(lambda request: request.url.endswith('/bootstrap')):
                page.goto(ORIGIN + '/app/numbers', wait_until='domcontentloaded')
            expect(page.get_by_role('heading', name='Opening your workspace…', exact=True)).to_be_visible()
            expect(page.get_by_role('button', name='Register owned number', exact=True)).to_have_count(0)
            deadline = time.monotonic() + 10
            while not pending and time.monotonic() < deadline: page.wait_for_timeout(10)
            assert pending, 'Workspace bootstrap was not intercepted'
            hold_bootstrap = False
            with page.expect_response(lambda response: response.url.endswith('/bootstrap') and response.status == 200):
                for route in pending: backend(route)
            expect(page.get_by_role('heading', name='Your seven-day phone trial', exact=True)).to_be_visible()
            page.set_viewport_size({'width': 390, 'height': 844})
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            page.screenshot(path=str(ART / 'automatic-offer-mobile.png'), full_page=True, animations='disabled')
            with page.expect_response(lambda response: response.url.endswith('/phone-trial') and response.status == 202):
                page.get_by_role('button', name='Start free phone trial', exact=True).click()
            expect(page.get_by_role('dialog')).to_have_count(0)
            expect(page.get_by_role('button', name='Start free phone trial', exact=True)).to_have_count(0)
            operate('allocate', ws)
            expect(page.get_by_role('heading', name='Your phone trial', exact=True)).to_be_visible(timeout=20000)
            allowance = page.get_by_label('Phone trial allowance')
            expect(allowance).to_contain_text('3 of 3 calls remaining')
            for theme in ['light', 'dark']:
                page.get_by_role('button', name='Color theme', exact=True).click()
                page.get_by_role('menuitemradio', name=theme.title(), exact=True).click()
                for width, height, size in [(1440, 1000, 'desktop'), (390, 844, 'mobile')]:
                    page.set_viewport_size({'width': width, 'height': height})
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    page.screenshot(path=str(ART / ('active-' + theme + '-' + size + '.png')), full_page=True, animations='disabled')
            page.set_viewport_size({'width': 1440, 'height': 1000})
            for remaining in [2, 1, 0]:
                page.get_by_role('button', name='Make a trial call', exact=True).click()
                dialog = page.get_by_role('dialog', name='Try your agent on the phone')
                expect(dialog).to_contain_text('up to 60 seconds')
                with page.expect_response(lambda response: response.url.endswith('/calls/outbound') and response.status == 202):
                    dialog.get_by_role('button', name='Call my test number', exact=True).click()
                expect(allowance).to_contain_text(str(remaining) + ' of 3 calls remaining')
                operate('finish', ws)
            expect(page.get_by_role('button', name='Make a trial call', exact=True)).to_be_disabled()
            expect(allowance).to_contain_text('You have used your phone trial allowance.')
            page.screenshot(path=str(ART / 'exhausted.png'), full_page=True, animations='disabled')
            operate('expire', ws); open_numbers()
            expect(allowance).to_contain_text('This phone trial has ended.')
            page.screenshot(path=str(ART / 'expired.png'), full_page=True, animations='disabled')
            assert not errors, errors
            browser.close()
        (ART / 'results.json').write_text(json.dumps({'status': 'passed', 'api': 'temporary SQLite, worker disabled',
            'checks': ['bootstrap loading before controls', 'mobile one-click trial request without number picker', 'automatic owned-stock assignment',
                       'automatic status refresh', 'light/dark desktop/mobile', 'no overflow', 'trial dialog', 'three actual API admissions',
                       'allowance refresh', 'exhausted and expired states'], 'provider_calls': 0, 'page_errors': errors}, indent=2) + '\n')
        print('Phone trial browser passed: actual admission, allowance, expiry, desktop/mobile themes; no provider calls or page errors.')
    finally:
        server.terminate()
        try: server.wait(timeout=10)
        except subprocess.TimeoutExpired: server.kill(); server.wait()
        log.close()

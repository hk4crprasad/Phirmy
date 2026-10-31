"""Actual booking UI/WebSocket acceptance using a temporary API and fake providers."""
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit,parse_qs,urlencode

import httpx
from playwright.sync_api import sync_playwright, expect

from qa_accounts import bootstrap_account
ROOT = Path(__file__).resolve().parents[1]
OAUTH = os.environ.get('QA_SCHEDULING_OAUTH') == '1'
ART = ROOT / 'artifacts' / ('scheduling-oauth' if OAUTH else 'scheduling')
ART.mkdir(parents=True, exist_ok=True)
ORIGIN = os.environ.get('BROWSER_TEST_ORIGIN', 'http://127.0.0.1:3100')

with tempfile.TemporaryDirectory(prefix='cynerza-scheduling-browser-') as folder:
    directory = Path(folder)
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0)); port = listener.getsockname()[1]
    api_origin = 'http://127.0.0.1:' + str(port)
    env = os.environ | {'APP_ENV': 'development', 'APP_ORIGIN': ORIGIN, 'PUBLIC_API_ORIGIN': api_origin,
        'DATABASE_URL': 'sqlite:///' + str(directory / 'qa.db'), 'SUPABASE_DB_PASSWORD': '',
        'DATA_DIR': str(directory / 'data'), 'APP_SECRET': 'synthetic-scheduling-secret-' + 'x' * 32,
        'OBJECT_STORAGE_PROVIDER': 'local', 'AZURE_STORAGE_CONNECTION_STRING': '', 'AZURE_STORAGE_ACCOUNT_URL': '',
        'VECTOR_ENDPOINT': '', 'VECTOR_API_KEY': '', 'EMBEDDING_API_KEY': '', 'OPENAI_API_KEY': '',
        'FISH_API_KEY': '', 'FISH_VOICE_ID': '', 'DEEPGRAM_API_KEY': '', 'SMTP_HOST': '',
        'GOOGLE_CLIENT_ID': '', 'GOOGLE_CLIENT_SECRET': '', 'REQUIRE_EMAIL_VERIFICATION': 'false',
        'SESSION_SECURE': 'false', 'DEV_SEED_ENABLED': 'true', 'LIVE_CALLS_ENABLED': 'false',
        'PHONE_TRIALS_ENABLED': 'false', 'PHONE_NUMBER_PURCHASES_ENABLED': 'false', 'LIVE_PAYMENTS_ENABLED': 'false',
        'TWILIO_ACCOUNT_SID': '', 'TWILIO_AUTH_TOKEN': '', 'TWILIO_API_KEY': '', 'TWILIO_API_SECRET': '',
        'PLIVO_AUTH_ID': '', 'PLIVO_AUTH_TOKEN': ''}
    env.update({'CALCOM_CLIENT_ID':'synthetic-client' if OAUTH else '', 'CALCOM_CLIENT_SECRET':'synthetic-secret' if OAUTH else '', 'CALCOM_OAUTH_MODE':'confidential', 'CALENDLY_CLIENT_ID':'synthetic-client' if OAUTH else '', 'CALENDLY_CLIENT_SECRET':'synthetic-secret' if OAUTH else ''})
    with (directory / 'api.log').open('w') as log:
        server = subprocess.Popen([sys.executable, 'scripts/scheduling_browser_fixture.py', str(port)], cwd=ROOT,
                                  env=env, stdout=log, stderr=log)
        try:
            with httpx.Client(trust_env=False) as health:
                for _ in range(80):
                    if server.poll() is not None: raise RuntimeError('Synthetic API exited')
                    try:
                        if health.get(api_origin + '/healthz').status_code == 200: break
                    except httpx.HTTPError: pass
                    time.sleep(.25)
                else: raise RuntimeError('Synthetic API not ready')
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                context = browser.new_context(viewport={'width': 1440, 'height': 1000}, reduced_motion='reduce')
                def backend(route):
                    path = urlsplit(route.request.url)
                    target = api_origin + path.path.removeprefix('/backend') + ('?' + path.query if path.query else '')
                    route.fulfill(response=route.fetch(url=target, max_redirects=0))
                context.route('**/backend/**', backend)
                authorizations=[]
                def consent(route):
                    parsed=urlsplit(route.request.url);query=parse_qs(parsed.query)
                    assert query['client_id']==['synthetic-client'] and query.get('state')
                    if parsed.hostname=='auth.calendly.com':assert query['code_challenge_method']==['S256']
                    authorizations.append(parsed.hostname)
                    destination=query['redirect_uri'][0]+'?'+urlencode({'state':query['state'][0],'code':'synthetic-approval'})
                    import html
                    route.fulfill(status=200,content_type='text/html',body='<h1>Synthetic provider consent</h1><a href="'+html.escape(destination,quote=True)+'">Allow fixture access</a>')
                if OAUTH:
                    context.route('https://app.cal.com/auth/oauth2/authorize?**',consent)
                    context.route('https://auth.calendly.com/oauth/authorize?**',consent)
                signup = bootstrap_account(context.request, api_origin + '/v1/auth/signup', data={'name': 'Scheduling QA',
                    'email': 'scheduling-browser@example.test', 'password': 'Long-Synthetic-Booking-Password', 'workspace_name': 'Scheduling QA'})
                assert signup.status == 200
                ws = signup.json()['workspaces'][0]['id']
                csrf = next(cookie['value'] for cookie in context.cookies() if cookie['name'] == 'studio_csrf')
                fixture = context.request.post(api_origin + '/v1/workspaces/' + ws + '/fixtures', data={},
                                               headers={'X-CSRF-Token': csrf, 'Origin': ORIGIN})
                assert fixture.status == 201
                agent_id = fixture.json()['agent_id']
                page = context.new_page(); page.set_default_timeout(20000)
                errors = []; page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(ORIGIN + '/app/integrations')
                for name, key_label, key, url in [
                    ('Cal.com', 'Cal.com API key', 'synthetic-cal-token', 'https://cal.com/fixture/meeting'),
                    ('Calendly', 'Calendly personal access token', 'synthetic-calendly-token', 'https://calendly.com/fixture/meeting')]:
                    card = page.locator('.integration-card').filter(has=page.get_by_role('heading', name=name, exact=True))
                    if OAUTH:
                        card.get_by_role('button',name='Connect with '+name,exact=True).click()
                        expect(page.get_by_role('heading',name='Synthetic provider consent')).to_be_visible()
                        page.get_by_role('link',name='Allow fixture access').click()
                        page.wait_for_url(ORIGIN+'/app/integrations**')
                        expect(page.get_by_text('Account authorized.',exact=False)).to_be_visible()
                    else:
                        card.get_by_role('button', name='Connect', exact=True).click()
                        dialog = page.get_by_role('dialog', name='Connect ' + name)
                        dialog.get_by_label(key_label, exact=True).fill(key)
                        dialog.get_by_label('Your ' + name + ' scheduling link', exact=True).fill(url)
                        dialog.get_by_role('button', name='Verify connection', exact=True).click()
                    card.get_by_role('button', name='Set up call booking', exact=True).click()
                    dialog = page.get_by_role('dialog', name='Call booking · ' + name)
                    dialog.get_by_label('Meeting type', exact=True).select_option(label=name + ' consultation · 30 min')
                    dialog.get_by_role('button', name='Enable call booking', exact=True).click()
                    expect(card.get_by_text('Call booking configured', exact=True)).to_be_visible()
                    card_box, disconnect_box = card.bounding_box(), card.get_by_role('button', name='Disconnect', exact=True).bounding_box()
                    assert card_box and disconnect_box and disconnect_box['x'] + disconnect_box['width'] <= card_box['x'] + card_box['width']
                page.screenshot(path=str(ART / 'integrations-desktop.png'), full_page=True)
                page.goto(ORIGIN + '/app/agents/' + agent_id)
                page.get_by_role('button', name='Actions', exact=True).click()
                page.get_by_label('Book meetings through Cal.com or Calendly', exact=True).check()
                expect(page.get_by_label('Book meetings through Cal.com or Calendly', exact=True)).to_be_checked()
                page.get_by_label('Booking platform', exact=True).select_option('calcom')
                page.get_by_role('button', name='Publish agent', exact=True).click()
                expect(page.locator('.toast')).to_contain_text('Agent published')
                page.screenshot(path=str(ART / 'agent-actions.png'), full_page=True)
                for index, name in enumerate(['Cal.com', 'Calendly']):
                    if index:
                        page.goto(ORIGIN + '/app/agents/' + agent_id)
                        page.get_by_role('button', name='Actions', exact=True).click()
                        page.get_by_label('Booking platform', exact=True).select_option('calendly')
                        page.get_by_role('button', name='Publish agent', exact=True).click()
                        expect(page.locator('.toast')).to_contain_text('Agent published')
                    page.goto(ORIGIN + '/app/voice?agent=' + agent_id)
                    page.get_by_role('button', name='Start simulation', exact=True).click()
                    entry = page.get_by_label('Voice lab text turn', exact=True)
                    expect(entry).to_be_enabled()
                    entry.fill('I would like a ' + name + ' meeting. My name is Jane Doe and my email is jane@example.test.')
                    page.get_by_role('button', name='Send test turn', exact=True).click()
                    preview = page.get_by_text(re.compile('^Please confirm:')).last
                    expect(preview).to_be_visible()
                    expect(preview).to_contain_text('Asia/Kolkata')
                    count = context.request.get(api_origin + '/qa-booking-count').json()
                    assert len(count['simulated_posts']) == index
                    entry.fill('Yes, please book it')
                    page.get_by_role('button', name='Send test turn', exact=True).click()
                    expect(page.get_by_text(re.compile('^Your booking is confirmed')).last).to_be_visible()
                    page.screenshot(path=str(ART / ('voice-' + name.lower().replace('.', '') + '.png')), full_page=True)
                    page.get_by_role('button', name='End session', exact=True).click()
                    expect(page.get_by_role('button', name='Start simulation', exact=True)).to_be_visible()
                page.goto(ORIGIN + '/app/appointments')
                expect(page.get_by_role('heading', name='Agent booking requests', exact=True)).to_be_visible()
                expect(page.get_by_text('Cal.com consultation', exact=True)).to_be_visible()
                expect(page.get_by_text('Calendly consultation', exact=True)).to_be_visible()
                expect(page.get_by_role('link', name='Manage at provider')).to_have_count(2)
                for theme in ['Light', 'Dark']:
                    page.get_by_role('button', name='Color theme', exact=True).click()
                    page.get_by_role('menuitemradio', name=theme, exact=True).click()
                    for width, height, size in [(1440, 1000, 'desktop'), (390, 844, 'mobile')]:
                        page.set_viewport_size({'width': width, 'height': height})
                        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                        if size == 'mobile':
                            for link in page.get_by_role('link', name='Manage at provider').all():
                                box = link.bounding_box()
                                assert box and box['x'] >= 0 and box['x'] + box['width'] <= width
                        page.screenshot(path=str(ART / ('bookings-' + theme.lower() + '-' + size + '.png')), full_page=True)
                if OAUTH: assert authorizations==['app.cal.com','auth.calendly.com']
                count = context.request.get(api_origin + '/qa-booking-count').json()
                assert count['simulated_posts'] == ['calcom', 'calendly'] and not errors, errors
                browser.close()
            result = {'status': 'passed', 'oauth_redirect_consent_callbacks': 'synthetic provider consent with real app routes' if OAUTH else 'not exercised', 'checks': ['real signup, encrypted connection and meeting selection UI',
                'agent scheduling bundle and publication', 'actual WebSocket call simulation with readback then yes',
                'both provider adapters, one simulated POST each', 'booking history, desktop/mobile, light/dark'],
                'page_errors': errors, 'external_provider_requests': 0, 'paid_calls': 0}
            (ART / 'browser-results.json').write_text(json.dumps(result, indent=2) + '\n')
            print(json.dumps(result))
        finally:
            server.terminate()
            try: server.wait(timeout=10)
            except subprocess.TimeoutExpired: server.kill(); server.wait()

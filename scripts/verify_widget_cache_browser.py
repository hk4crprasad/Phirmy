"""Built Next + real isolated API/Redis: headers, warm hits and revocation.

Uses disposable SQLite/objects, synthetic ownership evidence and no provider
credentials. Does not stop or replace the primary development services.
"""
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time
from datetime import timedelta

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'services/control'), str(ROOT/'scripts')]
redis_url = os.environ.get('STUDIO_TEST_REDIS_URL')
assert redis_url, 'Provide a disposable STUDIO_TEST_REDIS_URL'
folder = Path(tempfile.mkdtemp(prefix='widget-cache-browser-'))
os.environ.update(
    APP_ENV='test', DATABASE_URL='sqlite:///'+str(folder/'qa.db'), SUPABASE_DB_PASSWORD='',
    DATA_DIR=str(folder/'data'), APP_SECRET=secrets.token_urlsafe(48), OBJECT_STORAGE_PROVIDER='local',
    AZURE_STORAGE_CONNECTION_STRING='', AZURE_STORAGE_ACCOUNT_URL='', AZURE_STORAGE_PREFIX='',
    REDIS_URL=redis_url, WIDGET_FRAME_CACHE_NAMESPACE='test:browser:frame:'+secrets.token_hex(8),
    VECTOR_ENDPOINT='', VECTOR_API_KEY='', OPENAI_API_KEY='', EMBEDDING_API_KEY='', FISH_API_KEY='',
    FISH_VOICE_ID='', DEEPGRAM_API_KEY='', SMTP_HOST='', PLIVO_AUTH_ID='', PLIVO_AUTH_TOKEN='',
    TWILIO_ACCOUNT_SID='', TWILIO_AUTH_TOKEN='', TWILIO_API_KEY='', TWILIO_API_SECRET='',
    LIVE_CALLS_ENABLED='false', PHONE_TRIALS_ENABLED='false', PHONE_NUMBER_PURCHASES_ENABLED='false',
    RAZORPAY_KEY_ID='', RAZORPAY_KEY_SECRET='', RAZORPAY_TEST_KEY_ID='', RAZORPAY_TEST_KEY_SECRET='',
    RAZORPAY_LIVE_KEY_ID='', RAZORPAY_LIVE_KEY_SECRET='', RAZORPAY_WEBHOOK_SECRET='',
    LIVE_PAYMENTS_ENABLED='false', PAID_ACTIVATION_ENABLED='false', BILLING_OPERATOR_EMAILS='',
    BILLING_OPERATOR_REFUNDS_ENABLED='false', BILLING_DEVELOPMENT_ALLOWANCES_ENABLED='true',
    GOOGLE_CLIENT_ID='', GOOGLE_CLIENT_SECRET='', REQUIRE_EMAIL_VERIFICATION='false', SESSION_SECURE='false',
    CIPHER_KEY_PROVIDER='local', CIPHER_KEYS_JSON='', CIPHER_ACTIVE_KEY_ID='app-v1', CIPHER_VAULT_URL='',
    TURNSTILE_SITE_KEY='', TURNSTILE_SECRET_KEY='', WIDGET_BOT_CHALLENGE_ENABLED='false', WORKER_ENABLED='false',
)

from fastapi.testclient import TestClient
from fastapi.responses import JSONResponse
import httpx
from playwright.sync_api import sync_playwright
import uvicorn
from qa_accounts import bootstrap_account
from studio import widget_frame_cache as cache
from studio.config import settings
from studio.db import now, session_scope
from studio.main import create_app
from studio.models import Installation, OriginVerification
from studio.secrets import encrypt


def port():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        return listener.getsockname()[1]


api_origin = 'http://127.0.0.1:'+str(port())
web_origin = 'http://127.0.0.1:'+str(port())
settings.app_origin = web_origin
settings.public_api_origin = api_origin
app = create_app(start_worker=False)
counts = {'policy_requests':0}
unavailable = False


@app.middleware('http')
async def policy_evidence(request, call_next):
    if request.url.path.endswith('/frame-policy'):
        counts['policy_requests'] += 1
        if unavailable:
            return JSONResponse({'detail':'synthetic policy API outage'}, status_code=503)
    return await call_next(request)


with TestClient(app) as client:
    account = bootstrap_account(client, '/v1/auth/signup', json={
        'name':'Cache browser QA', 'email':'cache-ui@example.test', 'password':'Long-Synthetic-Cache-Password',
        'workspace_name':'Cache browser QA',
    }).json()
    workspace_id = account['workspaces'][0]['id']
    client.headers.update({'Origin':web_origin, 'X-CSRF-Token':client.cookies['studio_csrf']})
    response = client.post('/v1/workspaces/'+workspace_id+'/fixtures', json={})
    assert response.status_code == 201, response.text
    fixture = response.json()
    origin = 'https://verified-cache.example'
    with session_scope(write=True) as db:
        installation = db.get(Installation, fixture['installation_id'])
        installation.allowed_origins = [origin, web_origin]
        public_id = installation.public_id
        proof = OriginVerification(workspace_id=workspace_id, origin=origin, encrypted_token=encrypt('synthetic-proof'),
            expires_at=now()+timedelta(days=1), verified_at=now(), verified_until=now()+timedelta(days=90))
        db.add(proof)
        db.flush()
        proof_id = proof.id

server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=int(api_origin.rsplit(':',1)[1]), log_level='warning'))
thread = threading.Thread(target=server.run, daemon=True)
thread.start()
web_log = (folder/'web.log').open('w')
web = subprocess.Popen([
    'node', str(ROOT/'node_modules/next/dist/bin/next'), 'start', str(ROOT/'apps/web'),
    '--hostname', '127.0.0.1', '--port', web_origin.rsplit(':',1)[1],
], cwd=ROOT, env=os.environ | {'API_ORIGIN':api_origin, 'PUBLIC_API_ORIGIN':api_origin, 'NODE_ENV':'production'},
    stdout=web_log, stderr=subprocess.STDOUT)
try:
    deadline = time.monotonic()+30
    while True:
        try:
            if httpx.get(web_origin+'/widget.js', timeout=.5).status_code == 200:
                break
        except httpx.HTTPError:
            pass
        assert time.monotonic() < deadline and web.poll() is None, 'Isolated Next server did not start'
        time.sleep(.1)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path='/usr/bin/chromium', headless=True)
        context = browser.new_context()
        assets = ['/widget.js', '/bot-challenge.js', '/pcm-capture.js', '/widget-designs.css']
        for asset in assets:
            response = context.request.get(web_origin+asset)
            assert response.status == 200
            assert response.headers['cache-control'] == 'public, max-age=60, must-revalidate', (asset, response.headers['cache-control'])
            assert response.headers.get('etag')
            conditional = context.request.get(web_origin+asset, headers={'If-None-Match':response.headers['etag']})
            assert conditional.status == 304, (asset, conditional.status)
        for path in ['/signin', '/legal/privacy']:
            assert 'no-store' in context.request.get(web_origin+path).headers['cache-control']
        url = web_origin+'/widget/'+public_id
        first = context.request.get(url)
        assert origin in first.headers['content-security-policy'] and counts['policy_requests'] == 1
        second = context.request.get(url)
        assert origin in second.headers['content-security-policy'] and counts['policy_requests'] == 1, counts
        assert first.headers['content-security-policy'] != second.headers['content-security-policy']
        assert 'no-store' in second.headers['cache-control']
        with session_scope(write=True) as db:
            db.get(OriginVerification, proof_id).verified_until = now()-timedelta(seconds=1)
        revoked = context.request.get(url)
        assert origin not in revoked.headers['content-security-policy'] and counts['policy_requests'] == 2, counts
        unavailable = True
        # A guard forces authoritative fallback, and an unavailable API denies external framing.
        cache.connection().eval(cache.GUARD, 1, cache.key(public_id), 'guard:synthetic-outage')
        denied = context.request.get(url)
        framing = next(part.strip() for part in denied.headers['content-security-policy'].split(';') if part.strip().startswith('frame-ancestors'))
        assert framing == "frame-ancestors 'self'", framing
        assert counts['policy_requests'] == 3
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(web_origin+'/legal/privacy')
        page.get_by_role('heading', name='Privacy Notice', exact=True).wait_for()
        assert not errors
        browser.close()
        result = {'assets_cacheable':len(assets), 'conditional_304':len(assets), 'html':'no-store',
            'warm_page_policy_api_calls':0, 'revocation':'immediate invalidation',
            'outage':'self framing only', 'page_errors':len(errors), 'status':'passed'}
        artifacts = ROOT/'artifacts/widget-cache'
        artifacts.mkdir(parents=True, exist_ok=True)
        (artifacts/'results.json').write_text(json.dumps(result, indent=2))
        print(json.dumps(result))
finally:
    web.terminate()
    try:
        web.wait(timeout=10)
    except subprocess.TimeoutExpired:
        web.kill()
        web.wait(timeout=5)
    web_log.close()
    server.should_exit = True
    thread.join(timeout=10)
    connection = cache.connection()
    keys = list(connection.scan_iter(match=settings.widget_frame_cache_namespace+':*'))
    if keys:
        connection.delete(*keys)

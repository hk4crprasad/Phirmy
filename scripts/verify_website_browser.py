"""URL-to-widget browser acceptance against an isolated DB and actual local website."""
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
def email_gate(page):
    email=page.get_by_label("Email address",exact=True)
    try: email.wait_for(state="visible",timeout=2500)
    except Exception: return
    email.fill("widget-qa@example.test");page.get_by_role("button",name="Continue",exact=True).click()
ROOT=Path(__file__).resolve().parents[1]; WEB='http://127.0.0.1:3100'
ART=ROOT/'artifacts/website';ART.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory(prefix='cynerza-website-browser-') as folder:
    directory=Path(folder)
    with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    API='http://127.0.0.1:'+str(port);SITE=API+'/fixture-site/'
    env=os.environ|{'APP_ENV':'development','APP_ORIGIN':WEB,'PUBLIC_API_ORIGIN':API,'QA_WEBSITE_ORIGIN':API,
        'DATABASE_URL':'sqlite:///'+str(directory/'qa.db'),'SUPABASE_DB_PASSWORD':'','DATA_DIR':str(directory/'data'),
        'APP_SECRET':'synthetic-website-secret-'+'x'*32,'OBJECT_STORAGE_PROVIDER':'local','AZURE_STORAGE_CONNECTION_STRING':'','AZURE_STORAGE_ACCOUNT_URL':'',
        'REDIS_URL':'','VECTOR_ENDPOINT':'','VECTOR_API_KEY':'','EMBEDDING_API_KEY':'','OPENAI_API_KEY':'','FISH_API_KEY':'','FISH_VOICE_ID':'','DEEPGRAM_API_KEY':'','SMTP_HOST':'',
        'GOOGLE_CLIENT_ID':'','GOOGLE_CLIENT_SECRET':'','REQUIRE_EMAIL_VERIFICATION':'false','SESSION_SECURE':'false','DEV_SEED_ENABLED':'true',
        'LIVE_CALLS_ENABLED':'false','PHONE_TRIALS_ENABLED':'false','PHONE_NUMBER_PURCHASES_ENABLED':'false','LIVE_PAYMENTS_ENABLED':'false',
        'TWILIO_ACCOUNT_SID':'','TWILIO_AUTH_TOKEN':'','TWILIO_API_KEY':'','TWILIO_API_SECRET':'','PLIVO_AUTH_ID':'','PLIVO_AUTH_TOKEN':''}
    with (directory/'api.log').open('w') as log:
        server=subprocess.Popen([sys.executable,'scripts/website_browser_fixture.py',str(port)],cwd=ROOT,env=env,stdout=log,stderr=log)
        try:
            with httpx.Client(trust_env=False) as client:
                for _ in range(80):
                    if server.poll() is not None:raise RuntimeError('Fixture API exited')
                    try:
                        if client.get(API+'/healthz').status_code==200:break
                    except httpx.HTTPError:pass
                    time.sleep(.25)
                else:raise RuntimeError('Fixture not ready')
            with sync_playwright() as p:
                browser=p.chromium.launch(headless=True)
                context=browser.new_context(viewport={'width':1440,'height':1100},reduced_motion='reduce')
                def backend(route):
                    path=urlsplit(route.request.url)
                    target=API+path.path.removeprefix('/backend')+('?' + path.query if path.query else '')
                    route.fulfill(response=route.fetch(url=target,max_redirects=0))
                context.route('**/backend/**',backend)
                signup=bootstrap_account(context.request, API+'/v1/auth/signup',data={'name':'Website QA','email':'website-browser@example.test','password':'Long-Synthetic-Website-Password','workspace_name':'Website QA'})
                assert signup.status==200;ws=signup.json()['workspaces'][0]['id']
                csrf=next(c['value'] for c in context.cookies() if c['name']=='studio_csrf')
                page=context.new_page();page.set_default_timeout(30000)
                errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(WEB+'/app/widget')
                page.get_by_label('Assistant website URL').fill(SITE)
                page.get_by_role('button',name='Create website assistant',exact=True).click()
                expect(page.get_by_text('Your website knowledge is connected',exact=True)).to_be_visible(timeout=45000)
                expect(page.get_by_text('3 pages collected',exact=False)).to_be_visible()
                page.screenshot(path=str(ART/'dashboard-desktop.png'),full_page=True)
                # Verify the saved appearance is returned by normal installation APIs.
                page.get_by_role('button',name='Customize widget',exact=True).click()
                dialog=page.get_by_role('dialog',name='Your assistant’s appearance')
                dialog.get_by_label('Assistant name',exact=True).fill('Market guide')
                dialog.get_by_label('Launcher label',exact=True).fill('Ask Market')
                dialog.get_by_role('tab',name='Messages & tone',exact=True).click()
                dialog.get_by_label('Welcome message',exact=True).fill('Welcome to Market Studio. What can I help you find?')
                dialog.get_by_role('button',name='Save widget',exact=True).click()
                expect(dialog).not_to_be_visible()
                page.get_by_role('button',name='Test agent',exact=True).click()
                email_gate(page)
                page.get_by_label('Chat message',exact=True).fill('What is the Amber cream price?')
                page.get_by_role('button',name='Send chat message',exact=True).click()
                expect(page.get_by_text('Amber hand cream is USD 12.5.',exact=False)).to_be_visible()
                page.get_by_role('button',name='Indexed pages',exact=True).click()
                expect(page.locator('.website-page')).to_have_count(3)
                page.screenshot(path=str(ART/'pages-desktop.png'),full_page=True)
                page.set_viewport_size({'width':390,'height':844})
                page.evaluate('document.activeElement?.blur()')
                page.evaluate('window.scrollTo(0,0)')
                for control in page.locator('.website-start input, .website-start select, .website-start button').all():
                    box=control.bounding_box();assert box and box['x'] >= 0 and box['x']+box['width'] <= 391,box
                page.screenshot(path=str(ART/'dashboard-mobile.png'),full_page=True)
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
                page.get_by_role('button',name='Color theme',exact=True).click()
                page.get_by_role('menuitemradio',name='Dark',exact=True).click()
                page.screenshot(path=str(ART/'dashboard-dark-mobile.png'),full_page=True)
                rows=context.request.get(API+'/v1/workspaces/'+ws+'/website-assistants').json()['items']
                row=rows[0];inst=row['installation']
                assert inst['theme']['assistant_name']=='Market guide'
                context.request.post(API+'/qa-install',data={'id':inst['public_id'],'key':inst['theme']['publishable_key']})
                # Independent website visitor; no workspace cookies or dashboard API identity.
                visitor=browser.new_context(viewport={'width':390,'height':844},reduced_motion='reduce')
                visitor.route('**/backend/**',backend)
                site=visitor.new_page();site.on('pageerror',lambda e:errors.append(str(e)))
                site.goto(SITE)
                site.get_by_role('button',name='Ask Market',exact=True).click()
                expect(site.get_by_role('button',name='Ask Market',exact=True)).to_be_visible()
                email_gate(site)
                expect(site.get_by_text('Welcome to Market Studio.',exact=False)).to_be_visible()
                site.get_by_label('Chat message',exact=True).fill('What is the Amber cream price?')
                site.get_by_role('button',name='Send',exact=True).click()
                expect(site.get_by_text('Amber hand cream is USD 12.5.',exact=False)).to_be_visible()
                site.get_by_label('Chat message',exact=True).fill('Open the Amber hand cream page')
                site.get_by_role('button',name='Send',exact=True).click()
                site.wait_for_url(API+'/fixture-site/products/amber')
                expect(site.get_by_role('dialog',name='Business support chat')).to_be_visible()
                expect(site.get_by_label('Chat message',exact=True)).to_be_enabled()
                expect(site.get_by_text('What is the Amber cream price?',exact=True)).to_be_visible()
                site.get_by_label('Chat message',exact=True).fill('What are the benefits of this product?')
                site.get_by_role('button',name='Send',exact=True).click()
                expect(site.get_by_text('50 ml tube costs USD 12.50',exact=False).last).to_be_visible()
                site.screenshot(path=str(ART/'embedded-product-mobile.png'),full_page=True)
                assert not visitor.cookies()
                assert site.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
                site.set_viewport_size({'width':1440,'height':1000});site.emulate_media(color_scheme='dark')
                site.screenshot(path=str(ART/'embedded-product-dark-desktop.png'),full_page=True)
                assert not errors,errors
                stats=context.request.get(API+'/v1/workspaces/'+ws+'/website-assistants').json()['items'][0]['usage']
                assert stats['conversations']==2 and stats['visitor_turns']==4,stats
                # Stop through the actual dashboard while a controlled fetch is in flight.
                page.bring_to_front()
                context.request.post(API+'/qa-slow', data={'enabled':True})
                page.get_by_role('button', name='Recrawl', exact=True).click()
                expect(page.get_by_role('button', name='Stop crawl', exact=True)).to_be_visible()
                page.get_by_role('button', name='Stop crawl', exact=True).click()
                expect(page.get_by_role('button', name='Recrawl', exact=True)).to_be_enabled(timeout=10000)
                stopped=context.request.get(API+'/v1/workspaces/'+ws+'/website-assistants').json()['items'][0]
                assert stopped['job']['state']=='canceled',stopped['job']
                assert stopped['knowledge']['active_snapshot_id']==row['knowledge']['active_snapshot_id']
                page.screenshot(path=str(ART/'crawl-stopped-mobile.png'),full_page=True)
                result={'crawl_stop_and_preserved_knowledge':'passed','url_onboarding':'passed','background_crawl_and_products':'passed','indexed_page_management':'passed','appearance':'passed','dashboard_agent_test':'passed','separate_origin_widget':'passed','page_navigation_and_history':'passed','current_product_context':'passed','mobile_and_dark':'passed','no_visitor_cookies':'passed','usage':stats,'page_errors':errors,'real_provider_requests':0}
                (ART/'browser-results.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
                browser.close()
        finally:
            server.terminate()
            try:server.wait(timeout=10)
            except subprocess.TimeoutExpired:server.kill();server.wait()

"""Progressive loading with real local API data and deliberately held requests.

Provider-free synthetic QA accounts only. Responses are real API responses;
only the retry test injects an explicit HTTP503. No private data is cached on disk.
"""
import json
import os
from pathlib import Path
import time
import uuid
from urllib.parse import urlsplit, parse_qs
from playwright.sync_api import sync_playwright, expect

from qa_accounts import bootstrap_account
ORIGIN=os.environ.get('BROWSER_TEST_ORIGIN','http://127.0.0.1:3100')
ART=Path(__file__).resolve().parents[1]/'artifacts/dashboard'
ART.mkdir(parents=True,exist_ok=True)
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    context=browser.new_context(viewport={'width':1440,'height':1000},reduced_motion='reduce')
    assert context.request.get(ORIGIN+'/backend/healthz').json()['environment']=='development'
    signup=bootstrap_account(context.request, ORIGIN+'/backend/v1/auth/signup',data={'name':'Loading QA','email':'loading-'+uuid.uuid4().hex[:8]+'@example.test','password':'Long-Synthetic-Password','workspace_name':'Loading QA'})
    assert signup.status==200
    ws=signup.json()['workspaces'][0]['id'];base='/backend/v1/workspaces/'+ws
    csrf=next(c['value'] for c in context.cookies() if c['name']=='studio_csrf')
    headers={'X-CSRF-Token':csrf}
    assert context.request.post(ORIGIN+base+'/fixtures',headers=headers).status==201
    held=[];requests=[];errors=[]
    page=context.new_page();page.set_default_timeout(15000)
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.on('request',lambda r:requests.append(r.url) if '/backend/' in r.url else None)
    context.route('**/bootstrap?view=*',lambda route:held.append(route))
    started=time.monotonic();page.goto(ORIGIN+'/app')
    expect(page.get_by_role('navigation')).to_be_visible()
    shell_ms=round((time.monotonic()-started)*1000)
    expect(page.get_by_label('Workspace',exact=True)).to_have_value(ws)
    expect(page.get_by_role('heading',name='Opening your workspace…')).to_have_count(0)
    expect(page.locator('main')).to_have_attribute('aria-busy','true')
    page.wait_for_function('document.querySelector(".sidebar") !== null')
    # Deliver summary first. Real counts appear while recent activity stays pending.
    summary=[r for r in held if parse_qs(urlsplit(r.request.url).query).get('view')==['summary']]
    assert len(summary)==1
    summary[0].continue_()
    expect(page.get_by_role('heading',name='A little more connected, Loading.')).to_be_visible()
    expect(page.get_by_text('Loading recent activity…',exact=True)).to_be_visible()
    expect(page.get_by_text('Your first conversation starts the story.',exact=True)).to_have_count(0)
    page.screenshot(path=str(ART/'summary-before-activity.png'))
    for r in held:
        if r not in summary:r.continue_()
    context.unroute('**/bootstrap?view=*')
    expect(page.get_by_role('heading',name='Recent conversations',exact=True)).to_be_visible()
    initial_bytes=page.evaluate("performance.getEntriesByType('resource').filter(x=>x.name.includes('/_next/')&&x.name.split('?')[0].endsWith('.js')).reduce((n,x)=>n+x.encodedBodySize,0)")
    page.locator('.sidebar').evaluate("e=>e.dataset.loadingTest='retained'")
    agent_requests=[]
    context.route('**/bootstrap?view=agents',lambda r:agent_requests.append(r))
    page.get_by_role('link',name='Agents',exact=True).first.click()
    expect(page.get_by_role('heading',name='Loading agents…',exact=True)).to_be_visible()
    assert page.locator('.sidebar').get_attribute('data-loading-test')=='retained'
    # Leave the in-flight page; cached Overview is immediately usable.
    page.get_by_role('link',name='Overview',exact=True).first.click()
    expect(page.get_by_role('heading',name='Recent conversations',exact=True)).to_be_visible()
    for r in agent_requests:r.continue_()
    context.unroute('**/bootstrap?view=agents')
    page.get_by_role('link',name='Agents',exact=True).first.click()
    expect(page.get_by_role('button',name='Create agent',exact=True)).to_be_visible()
    page.get_by_role('link',name='Overview',exact=True).first.click()
    expect(page.get_by_role('heading',name='Recent conversations',exact=True)).to_be_visible()
    assert sum(u.endswith('/v1/auth/me') for u in requests)==1,requests
    assert sum(parse_qs(urlsplit(u).query).get('view')==['overview'] for u in requests)==1
    assert sum(parse_qs(urlsplit(u).query).get('view')==['agents'] for u in requests)==1
    assert not any(urlsplit(u).path.endswith('/bootstrap') and not urlsplit(u).query for u in requests)
    # Failure of a new page preserves navigation and the previously working page.
    context.route('**/bootstrap?view=contacts',lambda r:r.fulfill(status=503,json={'detail':'Synthetic loading outage'}))
    page.get_by_role('link',name='Contacts',exact=True).first.click()
    expect(page.get_by_role('button',name='Retry loading',exact=True)).to_be_visible()
    expect(page.locator('.sidebar')).to_be_visible()
    context.unroute('**/bootstrap?view=contacts')
    page.get_by_role('button',name='Retry loading',exact=True).click()
    expect(page.get_by_role('heading',name='Keep the right people close.',exact=True)).to_be_visible()
    expect(page.get_by_role('button',name='Retry loading',exact=True)).to_have_count(0)
    # A stalled read becomes a page-level retry, without blocking navigation.
    stalled=[]
    context.route('**/bootstrap?view=models',lambda r:stalled.append(r))
    timed=context.new_page();timed.clock.install()
    timed.goto(ORIGIN+'/app/models')
    expect(timed.get_by_role('heading',name='Loading models…',exact=True)).to_be_visible()
    timed.clock.fast_forward(16000)
    expect(timed.get_by_role('button',name='Retry loading',exact=True)).to_be_visible()
    expect(timed.locator('.sidebar')).to_be_visible()
    for request in stalled:
        try:request.abort()
        except Exception:pass
    context.unroute('**/bootstrap?view=models')
    timed.get_by_role('button',name='Retry loading',exact=True).click()
    expect(timed.locator('main')).to_have_attribute('aria-busy','false')
    expect(timed.locator('.workspace-page-loading')).to_have_count(0)
    timed.close()
    # An independent profile page does not wait for dashboard statistics.
    delayed=[];other=context.new_page()
    other.on('pageerror',lambda e:errors.append(str(e)))
    context.route('**/bootstrap?view=summary',lambda r:delayed.append(r))
    other.goto(ORIGIN+'/app/profile')
    expect(other.get_by_role('heading',name='Make yourself at home.',exact=True)).to_be_visible()
    assert delayed
    for r in delayed:r.continue_()
    context.unroute('**/bootstrap?view=summary');other.close()
    # Switching workspaces must discard old data and ignore an old pending read.
    created=context.request.post(ORIGIN+'/backend/v1/workspaces',data={'name':'Different QA workspace'},headers=headers)
    assert created.status==201
    ws2=created.json()['id'];stale=[]
    context.route('**/'+ws+'/bootstrap?view=agents',lambda r:stale.append(r))
    other=context.new_page();other.on('pageerror',lambda e:errors.append(str(e)))
    other.goto(ORIGIN+'/app/agents')
    expect(other.get_by_label('Workspace',exact=True)).to_be_visible()
    expect(other.get_by_role('heading',name='Loading agents…',exact=True)).to_be_visible()
    other.get_by_label('Workspace',exact=True).select_option(ws2)
    expect(other.get_by_role('button',name='Create agent',exact=True)).to_be_visible()
    expect(other.get_by_role('link',name='Gift studio assistant',exact=False)).to_have_count(0)
    for r in stale:
        try:r.continue_()
        except Exception:pass # The workspace switch aborts the obsolete request.
    context.unroute('**/'+ws+'/bootstrap?view=agents')
    expect(other.get_by_label('Workspace',exact=True)).to_have_value(ws2)
    expect(other.get_by_role('link',name='Gift studio assistant',exact=False)).to_have_count(0)
    assert not errors,errors
    result={'shell_before_data':True,'summary_before_activity':True,'shell_ms_local':shell_ms,
            'initial_javascript_bytes':initial_bytes,'auth_me_requests_for_navigation':1,'full_bootstrap_requests':0,
            'overview_requests_after_revisit':1,'agents_requests_after_revisit':1,
            'cached_pages_stay_usable':True,'page_failure_retry':'passed','timeout_retry':'passed','profile_independent_of_summary':True,
            'workspace_switch_and_stale_response':'passed','page_errors':errors,
            'measurement_note':'Local production frontend; real isolated API; requests deliberately held for ordering checks. Not public network latency.'}
    (ART/'loading-results.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result));browser.close()

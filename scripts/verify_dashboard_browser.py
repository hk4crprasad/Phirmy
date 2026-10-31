"""Workspace layout acceptance on actual local API data; no paid provider calls."""
import json
import os
from pathlib import Path
import uuid
from playwright.sync_api import sync_playwright, expect

from qa_accounts import bootstrap_account
ORIGIN = os.environ.get('BROWSER_TEST_ORIGIN', 'http://127.0.0.1:3100')
ART = Path(__file__).resolve().parents[1] / 'artifacts/dashboard'
ART.mkdir(parents=True, exist_ok=True)
ROUTES = ['', 'agents', 'knowledge', 'templates', 'tools', 'models', 'voice', 'calls', 'campaigns', 'inbox', 'contacts', 'leads', 'appointments', 'products', 'widget', 'numbers', 'integrations', 'team', 'operations', 'billing', 'developers', 'settings', 'profile']

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(viewport={'width':1440, 'height':1000}, reduced_motion='reduce')
    assert context.request.get(ORIGIN+'/backend/healthz').json()['environment'] == 'development'
    response = bootstrap_account(context.request, ORIGIN+'/backend/v1/auth/signup', data={'name':'Alex Morgan', 'email':'dashboard-'+uuid.uuid4().hex[:10]+'@example.test', 'password':'Long-Synthetic-Password', 'workspace_name':'A very long workspace name for the dashboard layout check'})
    assert response.status == 200
    ws = response.json()['workspaces'][0]['id']
    csrf = next(c['value'] for c in context.cookies() if c['name']=='studio_csrf')
    fixture = context.request.post(ORIGIN+'/backend/v1/workspaces/'+ws+'/fixtures', headers={'X-CSRF-Token':csrf})
    assert fixture.status == 201
    agent = fixture.json()['agent_id']
    page = context.new_page(); page.set_default_timeout(20000)
    errors = []; page.on('pageerror', lambda e: errors.append(str(e)))
    def goto(route):
        page.goto(ORIGIN+'/app'+('/'+route if route else ''))
        expect(page.locator('main h1')).to_be_visible()
        expect(page.locator('main')).to_have_attribute('aria-busy','false')
        expect(page.locator('.workspace-page-loading')).to_have_count(0)
    def overflow():
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), page.url
    def theme(name):
        page.get_by_role('button', name='Color theme', exact=True).click()
        page.get_by_role('menuitemradio', name=name, exact=True).click()
    goto('')
    assert page.locator('.nav-link').first.evaluate('e=>parseFloat(getComputedStyle(e).fontSize)') >= 14
    assert page.locator('.page-heading p').evaluate('e=>parseFloat(getComputedStyle(e).fontSize)') >= 16
    for width, mode in [(1440, 'desktop'), (390, 'mobile')]:
        page.set_viewport_size({'width':width, 'height':1000 if width==1440 else 844})
        for color in ['Light','Dark']:
            theme(color)
            for route in ROUTES + ['agents/'+agent]:
                goto(route); overflow()
                if route in ['', 'agents', 'integrations', 'contacts', 'profile']:
                    page.screenshot(animations='disabled', path=str(ART/(mode+'-'+color.lower()+'-'+(route or 'overview')+'.png')), full_page=mode=='desktop')
            print(mode+' '+color+': 24 dashboard pages passed', flush=True)
    # A delayed/failed notification request must not claim an empty inbox.
    pending = []
    context.route('**/notifications', lambda route: pending.append(route))
    page.reload(); expect(page.locator('main h1')).to_be_visible()
    page.get_by_role('button', name='Notifications', exact=True).click()
    expect(page.get_by_text('Loading notifications…', exact=True)).to_be_visible()
    page.wait_for_timeout(200)
    for request in pending:
        request.fulfill(status=503, json={'detail':'Synthetic notification outage'})
    expect(page.get_by_role('button', name='Retry notifications', exact=True)).to_be_visible()
    expect(page.get_by_text('You’re all caught up.', exact=True)).to_have_count(0)
    context.unroute('**/notifications')
    page.get_by_role('button', name='Retry notifications', exact=True).click()
    expect(page.get_by_role('button', name='Retry notifications', exact=True)).to_have_count(0)
    page.get_by_role('button', name='Close notifications', exact=True).click()
    expect(page.get_by_role('button', name='Notifications', exact=False)).to_be_focused()
    # Mobile navigation: readable close control, focus containment and restoration.
    page.get_by_role('button', name='Open navigation', exact=True).click()
    close = page.locator('.mobile-nav-close')
    expect(close).to_be_visible()
    assert close.evaluate("e=>{const probe=document.createElement('span');probe.style.color='var(--ink)';e.append(probe);const expected=getComputedStyle(probe).color;probe.remove();return getComputedStyle(e).color===expected;}")
    page.keyboard.press('Escape')
    expect(page.get_by_role('button', name='Open navigation', exact=True)).to_be_focused()
    # A smaller viewport and long form retain the dialog heading/close controls.
    page.set_viewport_size({'width':360,'height':560})
    goto('agents'); page.get_by_role('button',name='Create agent',exact=True).click()
    dialog = page.get_by_role('dialog')
    expect(dialog).to_be_visible()
    body = dialog.locator('.modal-body')
    body.evaluate('e=>e.scrollTop=e.scrollHeight')
    expect(dialog.get_by_role('button',name='Close dialog',exact=True)).to_be_in_viewport()
    assert dialog.bounding_box()['height'] <= 560-20
    page.keyboard.press('Escape')
    expect(page.get_by_role('button',name='Create agent',exact=True)).to_be_focused()
    overflow()
    # Desktop rail remains retractable with the new larger navigation.
    page.set_viewport_size({'width':1024,'height':768}); goto('')
    page.get_by_role('button',name='Toggle navigation',exact=True).click()
    page.wait_for_function('document.querySelector(".sidebar").getBoundingClientRect().width < 90')
    page.reload(); expect(page.get_by_role('button',name='Expand navigation',exact=True)).to_be_visible()
    assert page.locator('.sidebar').bounding_box()['width'] < 90
    page.get_by_role('button',name='Expand navigation',exact=True).click()
    overflow()
    page.set_viewport_size({'width':844,'height':390}); goto('profile'); overflow()
    page.locator('.sidebar').evaluate('e=>e.scrollTop=e.scrollHeight')
    expect(page.get_by_role('button',name='Sign out',exact=True)).to_be_in_viewport()
    assert page.locator('.main-shell').evaluate('e=>parseFloat(getComputedStyle(e).transitionDuration)') < .01
    assert not errors, errors
    result={'dashboard_routes':24, 'viewports':[1440,390], 'themes':['light','dark'], 'horizontal_overflow':False, 'modal_small_viewport':'passed', 'sidebar_collapse_persistence':'passed', 'landscape_navigation':'passed', 'reduced_motion':'passed', 'notification_loading_error_retry':'passed', 'page_errors':errors}
    (ART/'results.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result)); browser.close()

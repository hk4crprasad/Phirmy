"""Local beta acceptance: real UI, synthetic accounts, no calls or paid providers.

Run with the system-Chromium wrapper documented in BETA_DEPLOYMENT.md.
The development server must explicitly allow isolated QA signup/fixtures.
"""
import json
import os
from pathlib import Path
import re
import uuid
import httpx
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / 'artifacts' / 'beta'
ART.mkdir(parents=True, exist_ok=True)
ORIGIN = os.environ.get('BROWSER_TEST_ORIGIN', 'http://127.0.0.1:3100')
with httpx.Client(trust_env=False, timeout=10) as client:
    health = client.get(ORIGIN + '/backend/healthz').json()
    if health.get('environment') != 'development':
        raise SystemExit('Run this verifier against isolated development services only.')

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context(viewport={'width': 1440, 'height': 1000}, reduced_motion='reduce')
    page = context.new_page()
    page.set_default_timeout(20000)
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    suffix = uuid.uuid4().hex[:8]
    page.goto(ORIGIN + '/signin')
    expect(page.get_by_role('button', name='Continue with Google')).to_be_visible()
    page.get_by_role('button', name='Create a workspace', exact=True).click()
    page.get_by_label('Your name').fill('Beta QA')
    page.get_by_label('Work email').fill('beta-browser-' + suffix + '@example.test')
    page.get_by_label('Password', exact=True).fill('Long-Local-Beta-QA-Password')
    page.get_by_label('Workspace name').fill('Beta QA ' + suffix)
    page.get_by_role('button', name='Create workspace', exact=True).click()
    page.wait_for_url('**/app')
    expect(page.get_by_role('heading', name='See your website answer back.')).to_be_visible()
    page.screenshot(path=str(ART / 'first-win-desktop.png'), full_page=True)
    page.get_by_role('button', name='Load sample workspace', exact=True).click()
    expect(page.get_by_role('link', name=re.compile('^Gift studio assistant'))).to_be_visible()
    page.get_by_role('link', name='Agents', exact=True).first.click()
    page.wait_for_url('**/app/agents')
    expect(page.get_by_role('heading', name='Meet your team of agents.')).to_be_visible()
    page.get_by_role('button', name='Create agent', exact=True).click()
    dialog = page.get_by_role('dialog')
    expect(dialog.get_by_role('textbox', name='Name', exact=True)).to_be_visible()
    dialog.get_by_label('Name', exact=True).fill('Beta assistant')
    dialog.get_by_label('What should this agent help people do?').fill('Answer questions about engraving from the connected knowledge.')
    dialog.get_by_label('Knowledge to connect').select_option(label='Gift studio · sample knowledge')
    dialog.get_by_role('button', name='Generate draft', exact=True).click()
    page.wait_for_url('**/app/agents/*')
    page.get_by_role('button', name='Add variable', exact=True).click()
    page.get_by_label('Variable name 1').fill('customer_name')
    page.get_by_label('Default value', exact=True).fill('Alex')
    page.get_by_label('First words', exact=True).fill('Hello {{customer_name}}. How can I help?')
    page.get_by_role('button', name='Publish agent', exact=True).click()
    expect(page.locator('.toast')).to_contain_text('Agent published')
    expect(page.get_by_role('button', name='Copy agent ID')).to_be_visible()
    page.screenshot(path=str(ART / 'agent-variables-desktop.png'), full_page=True)

    page.get_by_role('button', name=re.compile('^Notifications')).click()
    expect(page.get_by_label('Notifications', exact=True).get_by_text('Your agent is published', exact=True)).to_be_visible()
    page.get_by_role('button', name='Mark all as read').click()
    expect(page.locator('.notification-item.unread')).to_have_count(0)
    page.get_by_role('button', name='Close notifications').click()
    page.get_by_role('button', name='Toggle navigation').click()
    page.wait_for_function("document.querySelector('.sidebar').getBoundingClientRect().width < 90")
    page.reload()
    page.wait_for_function("document.querySelector('.sidebar')?.getBoundingClientRect().width < 90")
    page.get_by_role('button', name='Expand navigation').click()
    page.wait_for_function("document.querySelector('.sidebar').getBoundingClientRect().width > 150")

    page.get_by_role('link', name='Contacts', exact=True).click()
    page.get_by_role('button', name='Add contact', exact=True).click()
    dialog = page.get_by_role('dialog')
    dialog.get_by_label('Full name').fill('Alex Example')
    dialog.get_by_label('Phone · +country code').fill('+12025550123')
    dialog.get_by_label('Permission to call', exact=True).select_option('granted')
    dialog.get_by_label('How was permission obtained?').fill('Synthetic QA contact requested a callback.')
    dialog.get_by_role('button', name='Save', exact=True).click()
    expect(page.get_by_text('Alex Example', exact=True)).to_be_visible()
    page.get_by_label('Import contacts CSV').set_input_files({'name': 'contacts.csv', 'mimeType': 'text/csv', 'buffer': b'phone,name\n+12025550124,CSV Example\n'})
    dialog = page.get_by_role('dialog', name='Review your contact import')
    expect(dialog.get_by_text('CSV Example', exact=True)).to_be_visible()
    dialog.get_by_role('button', name='Import 1 contacts').click()
    expect(page.get_by_text('CSV Example', exact=True)).to_be_visible()
    with page.expect_download() as download:
        page.get_by_role('button', name='Export', exact=True).click()
    download.value.save_as(str(ART / 'contacts.csv'))
    page.get_by_label('Select Alex Example', exact=True).check()
    page.get_by_role('button', name=re.compile('Create campaign')).click()
    dialog = page.get_by_role('dialog')
    dialog.get_by_label('Campaign name').fill('Beta draft ' + suffix)
    dialog.get_by_label('Published agent').select_option(label='Beta assistant')
    dialog.get_by_role('button', name='Create draft', exact=True).click()
    page.wait_for_url('**/app/campaigns')
    expect(page.get_by_text('Beta draft ' + suffix, exact=True)).to_be_visible()

    page.goto(ORIGIN + '/app/profile')
    page.get_by_label('Your name', exact=True).fill('Beta Builder')
    page.get_by_label('Timezone', exact=True).fill('Europe/London')
    page.get_by_role('button', name='Save profile', exact=True).click()
    expect(page.locator('.user-row strong')).to_have_text('Beta Builder')
    expect(page.get_by_text('This device', exact=True)).to_be_visible()
    cookies = {cookie['name']: cookie for cookie in context.cookies()}
    assert cookies['studio_session']['httpOnly'] and cookies['studio_refresh']['httpOnly']
    original_access = cookies['studio_session']['value']
    context.add_cookies([{'name': 'studio_session', 'value': 'expired.fixture.token', 'url': ORIGIN, 'httpOnly': True, 'sameSite': 'Lax'}])
    page.reload()
    expect(page.get_by_role('heading', name='Make yourself at home.')).to_be_visible()
    assert next(cookie['value'] for cookie in context.cookies() if cookie['name'] == 'studio_session') not in (original_access, 'expired.fixture.token')
    page.screenshot(path=str(ART / 'profile-desktop.png'), full_page=True)

    # Two tabs share refresh cookies. Release both expired access requests at
    # once and require one rotation rather than triggering replay revocation.
    peer = context.new_page()
    peer.goto(ORIGIN + '/app/profile')
    expect(peer.get_by_role('heading', name='Make yourself at home.')).to_be_visible()
    waiting, rotations = [], []
    def expire_together(route):
        if len(waiting) < 2:
            waiting.append(route)
            if len(waiting) == 2:
                for pending in waiting:
                    pending.fulfill(status=401, content_type='application/json', body='{"detail":"Expired access fixture"}')
        else:
            route.continue_()
    def count_rotation(route):
        rotations.append(True)
        route.continue_()
    context.route('**/backend/v1/auth/me', expire_together)
    context.route('**/backend/v1/auth/refresh', count_rotation)
    context.add_cookies([{'name': 'studio_session', 'value': 'expired.concurrent.fixture', 'url': ORIGIN, 'httpOnly': True, 'sameSite': 'Lax'}])
    page.reload(wait_until='commit')
    peer.reload(wait_until='commit')
    expect(page.get_by_role('heading', name='Make yourself at home.')).to_be_visible()
    expect(peer.get_by_role('heading', name='Make yourself at home.')).to_be_visible()
    assert len(rotations) == 1, 'Concurrent tabs must share one refresh rotation'
    context.unroute('**/backend/v1/auth/me', expire_together)
    context.unroute('**/backend/v1/auth/refresh', count_rotation)
    peer.close()

    page.set_viewport_size({'width': 390, 'height': 844})
    page.get_by_role('button', name='Open navigation').click()
    expect(page.get_by_role('dialog', name='Main navigation')).to_be_visible()
    assert page.evaluate("document.querySelector('.main-shell').inert")
    page.keyboard.press('Shift+Tab')
    assert page.evaluate("document.querySelector('.sidebar').contains(document.activeElement)")
    page.screenshot(path=str(ART / 'navigation-mobile.png'), full_page=True)
    page.keyboard.press('Escape')
    expect(page.get_by_role('dialog', name='Main navigation')).to_have_count(0)
    assert not page.evaluate("document.querySelector('.main-shell').inert")
    for route in ('profile', 'contacts', 'integrations', 'agents', 'developers', 'voice'):
        page.goto(ORIGIN + '/app/' + route)
        expect(page.locator('main h1')).to_be_visible()
        expect(page.locator('main')).to_have_attribute('aria-busy','false')
        expect(page.locator('.workspace-page-loading')).to_have_count(0)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), route
        if route in ('profile', 'integrations', 'contacts'):
            page.screenshot(path=str(ART / (route + '-mobile.png')), full_page=True)
    assert not errors, errors
    result = {'signup': 'passed', 'google_button': 'present; activation requires credentials', 'agent_create_publish': 'passed',
              'structured_variables': 'passed', 'notifications_and_read_state': 'passed', 'sidebar_persistence': 'passed',
              'contacts_csv_preview_export': 'passed', 'campaign_from_contacts': 'passed; no calls placed',
              'profile_and_devices': 'passed', 'expired_access_refresh': 'passed', 'concurrent_tab_refresh': 'passed', 'mobile_drawer_focus_escape': 'passed',
              'mobile_overflow': 'none across six routes', 'page_errors': errors}
    (ART / 'browser-results.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))
    browser.close()

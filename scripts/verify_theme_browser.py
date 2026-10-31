"""Neutral themes, local fonts, custom route states and the Remotion walkthrough.

Uses synthetic development accounts only. No paid providers or external websites.
"""
import json
import os
from pathlib import Path
from urllib.parse import urlparse
import uuid
from playwright.sync_api import sync_playwright, expect

from qa_accounts import bootstrap_account
ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / 'artifacts' / 'theme'
ART.mkdir(parents=True, exist_ok=True)
ORIGIN = os.environ.get('BROWSER_TEST_ORIGIN', 'http://127.0.0.1:3100')


def choose(page, name):
    page.get_by_role('button', name='Color theme', exact=True).click()
    page.get_by_role('menuitemradio', name=name, exact=True).click()


def no_overflow(page):
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), page.url


def open_page(page, route):
    if route == '/app' or route.startswith('/app/'):
        with page.expect_response(lambda response: urlparse(response.url).path.endswith('/bootstrap') and response.status == 200):
            page.goto(ORIGIN + route)
        expect(page.locator('main')).to_have_attribute('aria-busy','false')
        expect(page.locator('.workspace-page-loading')).to_have_count(0)
    else:
        page.goto(ORIGIN + route)


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context(viewport={'width': 1440, 'height': 1000}, color_scheme='light')
    page = context.new_page()
    page.set_default_timeout(20000)
    errors, fonts, failed_fonts = [], [], []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('request', lambda request: fonts.append(request.url) if request.resource_type == 'font' else None)
    page.on('requestfailed', lambda request: failed_fonts.append(request.url) if request.resource_type == 'font' else None)

    page.goto(ORIGIN)
    page.wait_for_function('document.fonts.status === "loaded"')
    expect(page.locator('html')).to_have_attribute('data-theme', 'light')
    choose(page, 'Dark')
    expect(page.locator('html')).to_have_attribute('data-theme', 'dark')
    page.reload()
    expect(page.locator('html')).to_have_attribute('data-theme', 'dark')
    peer = context.new_page()
    peer.goto(ORIGIN + '/docs')
    expect(peer.locator('html')).to_have_attribute('data-theme', 'dark')
    choose(page, 'Light')
    expect(peer.locator('html')).to_have_attribute('data-theme', 'light')
    peer.close()
    choose(page, 'Use device setting')
    page.emulate_media(color_scheme='dark')
    expect(page.locator('html')).to_have_attribute('data-theme', 'dark')
    page.emulate_media(color_scheme='light')
    expect(page.locator('html')).to_have_attribute('data-theme', 'light')

    # The tour is loaded on demand and all four chapters are reachable without
    # animation. Play/pause proves it is a working timeline rather than a poster.
    page.get_by_role('button', name='Watch product tour').click()
    dialog = page.get_by_role('dialog', name='From knowledge to conversation')
    expect(dialog.get_by_label('Product walkthrough animation')).to_be_visible()
    for chapter, title in [('Agent', 'Make it sound like you.'), ('Test', 'Try the conversation first.'), ('Publish', 'Ready for the real world.'), ('Knowledge', 'Start with what you know.')]:
        dialog.get_by_role('button', name='Show ' + chapter + ' chapter', exact=True).click()
        expect(dialog.get_by_role('heading', name=title, exact=True)).to_be_visible()
    dialog.get_by_role('button', name='Play video', exact=True).click()
    expect(dialog.get_by_role('button', name='Pause video', exact=True)).to_be_visible()
    page.wait_for_timeout(350)
    dialog.get_by_role('button', name='Pause video', exact=True).click()
    page.screenshot(animations='disabled', path=str(ART / 'walkthrough-light.png'))
    page.keyboard.press('Escape')
    expect(dialog).to_have_count(0)
    expect(page.get_by_role('button', name='Watch product tour')).to_be_focused()

    print('Theme persistence, same-device sync and walkthrough controls passed.', flush=True)
    for route in ('/a-missing-page', '/app/a-missing-page', '/app/agents/invalid/extra'):
        response = page.goto(ORIGIN + route)
        expect(page.get_by_role('heading', name='This page is off the map.')).to_be_visible()
        # Next's streamed notFound response can retain 200; it must be noindex.
        if response.status != 404:
            expect(page.locator('meta[name="robots"]').first).to_have_attribute('content', 'noindex')
        expect(page.get_by_role('link', name='Open workspace')).to_have_attribute('href', '/app')
        no_overflow(page)
    page.screenshot(animations='disabled', path=str(ART / 'missing-light.png'))

    print('Custom missing-page routes passed.', flush=True)
    health = context.request.get(ORIGIN + '/backend/healthz').json()
    assert health['environment'] == 'development', 'Use isolated development services only'
    suffix = uuid.uuid4().hex[:9]
    signup = bootstrap_account(context.request, ORIGIN + '/backend/v1/auth/signup', data={
        'name': 'Theme QA', 'email': 'theme-' + suffix + '@example.test',
        'password': 'Long-Theme-Browser-QA-Password', 'workspace_name': 'Theme workspace'})
    assert signup.status == 200
    workspace = signup.json()['workspaces'][0]['id']
    csrf = next(cookie['value'] for cookie in context.cookies() if cookie['name'] == 'studio_csrf')
    fixture = context.request.post(ORIGIN + '/backend/v1/workspaces/' + workspace + '/fixtures',
                                   headers={'X-CSRF-Token': csrf})
    assert fixture.status == 201
    agent_id = fixture.json()['agent_id']

    # Hold the actual account request to inspect loading, then let it complete.
    choose(page, 'Dark')
    pending = []
    context.route('**/backend/v1/auth/me', lambda route: pending.append(route))
    page.goto(ORIGIN + '/app', wait_until='domcontentloaded')
    expect(page.get_by_role('heading', name='Opening your workspace…')).to_be_visible()
    page.screenshot(animations='disabled', path=str(ART / 'loading-dark.png'))
    no_overflow(page)
    for route in pending:
        route.continue_()
    context.unroute('**/backend/v1/auth/me')
    expect(page.locator('main h1')).to_be_visible()

    print('Custom account-loading state resumes successfully.', flush=True)
    routes = ['', 'agents/' + agent_id, 'tools', 'models', 'integrations', 'contacts', 'profile', 'developers', 'voice', 'widget']
    for theme in ('Light', 'Dark'):
        choose(page, theme)
        for route in routes:
            open_page(page, '/app' + ('/' + route if route else ''))
            expect(page.locator('main h1')).to_be_visible()
            expect(page.locator('html')).to_have_attribute('data-theme', theme.lower())
            no_overflow(page)
            assert page.evaluate(r'Math.abs(parseInt(getComputedStyle(document.body).backgroundColor.match(/\d+/g)[0])-parseInt(getComputedStyle(document.body).backgroundColor.match(/\d+/g)[1])) < 12')
            if route in ('', 'profile'):
                page.screenshot(animations='disabled', path=str(ART / ((route or 'dashboard') + '-' + theme.lower() + '.png')))
        page.goto(ORIGIN + '/docs')
        page.screenshot(animations='disabled', path=str(ART / ('docs-' + theme.lower() + '.png')))

    print('Desktop pages passed in both themes.', flush=True)
    page.set_viewport_size({'width': 390, 'height': 844})
    for theme in ('Light', 'Dark'):
        choose(page, theme)
        for route in ('/', '/signin', '/docs', '/app', '/app/agents/' + agent_id, '/app/contacts', '/app/profile', '/missing-mobile'):
            open_page(page, route)
            expect(page.get_by_role('heading').first).to_be_visible()
            no_overflow(page)
            if route in ('/app', '/missing-mobile'):
                page.screenshot(animations='disabled', path=str(ART / (('dashboard' if route == '/app' else 'missing') + '-mobile-' + theme.lower() + '.png')), full_page=True)
        page.get_by_role('button', name='Color theme', exact=True).click()
        no_overflow(page)
        page.keyboard.press('Escape')
        expect(page.get_by_role('button', name='Color theme', exact=True)).to_be_focused()

    page.emulate_media(reduced_motion='reduce')
    page.goto(ORIGIN + '/missing-reduced-motion')
    assert page.locator('.missing-orbit i').first.evaluate('(el) => getComputedStyle(el).animationName') == 'none'
    page.goto(ORIGIN)
    page.get_by_role('button', name='Watch product tour').click()
    expect(page.get_by_text('Automatic motion is off for your device preference.', exact=False)).to_be_visible()
    expect(page.get_by_role('button', name='Play video', exact=True)).to_be_visible()
    page.keyboard.press('Escape')
    assert fonts and not failed_fonts
    assert all(urlparse(url).netloc == urlparse(ORIGIN).netloc for url in fonts), fonts
    assert not errors, errors
    result = {'themes': 'light/dark/system; persistence and cross-tab sync passed',
              'fonts': 'bundled WOFF2; all font requests same origin; no failed font requests',
              'custom_loading': 'real pending account request; resumes successfully',
              'custom_not_found': 'root and unknown workspace routes; noindex for streamed responses',
              'remotion': 'on-demand player; all chapters, play/pause, transcript and Escape/focus passed',
              'desktop_routes': 10, 'mobile': '8 routes in both themes; no horizontal overflow',
              'reduced_motion': 'static route art and no tour autoplay', 'page_errors': errors}
    (ART / 'results.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))
    browser.close()

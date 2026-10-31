"""Real preview UI/API with synthetic website/model boundaries, no paid requests.

Run through the system Chromium wrapper. --fixture-api is an internal subprocess
mode; its settings are isolated by the parent, never the user's main database.
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

ROOT = Path(__file__).resolve().parents[1]
SITE = 'https://preview-shop.example'


def fixture_api(port):
    sys.path.insert(0, str(ROOT / 'services/control'))
    import uvicorn
    from studio import preview_routes, preview_answers
    from studio.main import create_app
    page = b'''<html><head><title>Preview care shop</title></head><body>
        <nav><a href="/collections/all">Shop all</a><a href="/products/argan-serum">Argan serum</a></nav>
        <main><p>We sell hair and skin care with argan oil and vitamin E for everyday use.</p>
        <p>Are our products safe during pregnancy? Please consult your doctor.</p>
        <p>Argan serum contains vitamin E. Shipping takes four business days.</p></main></body></html>'''
    async def fetch(url, **kwargs):
        if url == SITE + '/robots.txt':
            return url, b'User-agent: *\nAllow: /', 'text/plain'
        if url.rstrip('/') == SITE:
            return SITE + '/', page, 'text/html'
        raise ValueError('Only the synthetic preview website is permitted in QA')
    class Model:
        def __init__(self, profile, instructions, messages, **kwargs):
            assert messages[-1]['content'] == 'What is argan serum made with?'
            self.text = json.dumps({'text': 'Argan serum contains vitamin E.', 'supported': True, 'link_ids': [1]})
        async def stream(self):
            yield self.text
    preview_routes.safe_fetch = fetch
    preview_answers.Turn = Model
    uvicorn.run(create_app(start_worker=False), host='127.0.0.1', port=port, log_level='warning')


def verify():
    import httpx
    from playwright.sync_api import sync_playwright, expect
    origin = os.environ.get('BROWSER_TEST_ORIGIN', 'http://127.0.0.1:3100')
    artifact = ROOT / 'artifacts/preview'
    artifact.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='cynerza-preview-browser-') as folder:
        directory = Path(folder)
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0)); port = listener.getsockname()[1]
        api = 'http://127.0.0.1:' + str(port)
        env = os.environ | {'APP_ENV': 'test', 'APP_ORIGIN': origin, 'DATABASE_URL': 'sqlite:///' + str(directory / 'qa.db'),
            'SUPABASE_DB_PASSWORD': '', 'DATA_DIR': str(directory / 'data'), 'APP_SECRET': 'synthetic-preview-' + 'x' * 40,
            'OBJECT_STORAGE_PROVIDER': 'local', 'AZURE_STORAGE_CONNECTION_STRING': '', 'AZURE_STORAGE_ACCOUNT_URL': '',
            'VECTOR_ENDPOINT': '', 'VECTOR_API_KEY': '', 'EMBEDDING_API_KEY': '', 'OPENAI_API_KEY': 'synthetic-model-key',
            'FISH_API_KEY': '', 'DEEPGRAM_API_KEY': '', 'SMTP_HOST': '', 'LIVE_CALLS_ENABLED': 'false', 'LIVE_PAYMENTS_ENABLED': 'false',
            'PHONE_TRIALS_ENABLED': 'false', 'PHONE_NUMBER_PURCHASES_ENABLED': 'false'}
        with (directory / 'api.log').open('w') as log:
            server = subprocess.Popen([sys.executable, str(Path(__file__)), '--fixture-api', str(port)], cwd=ROOT, env=env, stdout=log, stderr=log)
            try:
                with httpx.Client(trust_env=False) as client:
                    for _ in range(80):
                        if server.poll() is not None:
                            raise RuntimeError('Preview fixture exited')
                        try:
                            if client.get(api + '/healthz').status_code == 200:
                                break
                        except httpx.HTTPError:
                            pass
                        time.sleep(.25)
                    else:
                        raise RuntimeError('Preview fixture did not start')
                errors = []
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(headless=True)
                    context = browser.new_context(viewport={'width': 1440, 'height': 1000}, reduced_motion='reduce')
                    def backend(route):
                        parsed = urlsplit(route.request.url)
                        route.fulfill(response=route.fetch(url=api + parsed.path.removeprefix('/backend'), max_redirects=0))
                    context.route('**/backend/**', backend)
                    page = context.new_page()
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto(origin)
                    page.get_by_label('Your website', exact=True).fill(SITE)
                    page.get_by_role('button', name='Try my website', exact=True).click()
                    expect(page.get_by_role('heading', name='That’s your business. Already helping.')).to_be_visible()
                    entry = page.get_by_label('Ask your assistant', exact=True)
                    entry.fill('what all products give me one link')
                    page.get_by_role('button', name='Send question', exact=True).click()
                    catalog = page.get_by_role('link', name='Browse products', exact=False)
                    expect(catalog).to_be_visible()
                    assert catalog.get_attribute('href') == SITE + '/collections/all'
                    assert 'pregnancy' not in page.locator('.fm-message.assistant').last.inner_text()
                    entry.fill('What is argan serum made with?')
                    page.get_by_role('button', name='Send question', exact=True).click()
                    expect(page.get_by_text('Argan serum contains vitamin E.', exact=True)).to_be_visible()
                    expect(page.get_by_role('link', name='Argan serum', exact=False)).to_be_visible()
                    for width, name in [(1440, 'desktop'), (390, 'mobile')]:
                        page.set_viewport_size({'width': width, 'height': 1000 if width == 1440 else 844})
                        for theme in ['Light', 'Dark']:
                            page.get_by_role('button', name='Color theme', exact=True).click()
                            page.get_by_role('menuitemradio', name=theme, exact=True).click()
                            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                            assert page.locator('.fm-compose button').evaluate('el => getComputedStyle(el).color !== getComputedStyle(el).backgroundColor')
                            assert page.locator('.fm-compose button svg').bounding_box()['width'] >= 16
                            page.screenshot(path=str(artifact / f'{name}-{theme.lower()}.png'), full_page=True)
                    assert not errors, errors
                    browser.close()
                result = {'status': 'passed', 'question': 'what all products give me one link', 'catalog_url': SITE + '/collections/all',
                          'configured_model_path': 'passed with synthetic model boundary', 'themes': ['light', 'dark'],
                          'viewports': ['desktop', 'mobile'], 'page_errors': errors, 'external_website_requests': 0, 'paid_provider_requests': 0}
                (artifact / 'browser-results.json').write_text(json.dumps(result, indent=2) + '\n')
                print(json.dumps(result))
            finally:
                server.terminate()
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    server.kill(); server.wait(timeout=5)


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--fixture-api':
        fixture_api(int(sys.argv[2]))
    else:
        verify()

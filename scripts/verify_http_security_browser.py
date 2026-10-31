"""Actual production frontend nonce/CSP acceptance against an isolated QA API."""
import json
import os
from pathlib import Path
import re
import uuid
from playwright.sync_api import sync_playwright, expect
from qa_accounts import bootstrap_account

origin = os.environ.get('BROWSER_TEST_ORIGIN', 'http://127.0.0.1:3100')
with sync_playwright() as p:
    browser = p.chromium.launch(executable_path='/usr/bin/chromium', headless=True)
    context = browser.new_context()
    first = context.request.get(origin+'/signin')
    second = context.request.get(origin+'/signin')
    csp = first.headers['content-security-policy']
    script_policy = next(part for part in csp.split(';') if part.strip().startswith('script-src'))
    assert "'unsafe-inline'" not in script_policy and "'unsafe-eval'" not in script_policy
    assert "'strict-dynamic'" in script_policy
    assert re.search(r"nonce-([^']+)", csp)[1] != re.search(r"nonce-([^']+)", second.headers['content-security-policy'])[1]
    assert "frame-ancestors 'none'" in csp
    assert 'includeSubDomains' in first.headers['strict-transport-security']
    bootstrap_account(context.request, origin+'/backend/v1/auth/signup', data={
        'name':'CSP QA', 'email':'csp-'+uuid.uuid4().hex[:12]+'@example.test',
        'password':'Private-Synthetic-CSP-Password', 'workspace_name':'CSP QA'})
    page = context.new_page()
    errors = []
    blocked = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('console', lambda message: blocked.append(True) if 'inline script' in message.text.lower() and 'security policy' in message.text.lower() else None)
    def inject_untrusted_html(route):
        response = route.fetch()
        html = response.text()
        assert '</head>' in html
        html = html.replace('</head>', '<script>window.untrustedInlineExecuted = true</script></head>', 1)
        route.fulfill(response=response, body=html)
    page.route('**/app/developers', inject_untrusted_html)
    page.goto(origin+'/app/developers')
    page.get_by_role('button',name='Create API key',exact=True).click()
    expect(page.get_by_role('heading',name='Create a scoped API key',exact=True)).to_be_visible()
    assert page.locator('script').evaluate_all('(nodes) => nodes.some(node => !!node.nonce)')
    assert blocked, 'Untrusted parser-inserted script did not produce a CSP violation'
    assert page.evaluate('() => window.untrustedInlineExecuted === undefined')
    assert not errors, 'Production application raised a page error'
    widget = context.request.get(origin+'/widget/unknown-policy-check')
    assert "frame-ancestors 'self'" in widget.headers['content-security-policy']
    assert 'x-frame-options' not in widget.headers
    artifact = Path('artifacts/http-security')
    artifact.mkdir(parents=True,exist_ok=True)
    results = {'unique_nonces':True,'strict_script_policy':True,'dashboard_interaction':True,
               'injected_inline_script_blocked':True,'widget_external_framing_closed':True,'page_errors':0}
    (artifact/'browser.json').write_text(json.dumps(results,indent=2)+'\n')
    print(json.dumps(results))
    browser.close()

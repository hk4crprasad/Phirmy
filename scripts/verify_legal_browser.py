"""Actual local production web build and isolated development API legal flow."""
import json
import os
from pathlib import Path
import secrets
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

origin = os.environ.get('BROWSER_TEST_ORIGIN', 'http://127.0.0.1:3100')
assert urlparse(origin).hostname in {'127.0.0.1', 'localhost'}, 'Use the isolated local development environment'
artifacts = Path('artifacts/legal')
artifacts.mkdir(parents=True, exist_ok=True)
documents = {'terms':'Terms of Service', 'privacy':'Privacy Notice', 'cookies':'Cookie Notice',
             'acceptable-use':'Acceptable Use Policy', 'dpa':'Data Processing Addendum'}

with sync_playwright() as playwright:
    chromium_path = os.environ.get('CHROMIUM_PATH', '/usr/bin/chromium')
    launch_kwargs = {'headless': True}
    if os.path.exists(chromium_path):
        launch_kwargs['executable_path'] = chromium_path
    browser = playwright.chromium.launch(**launch_kwargs)
    context = browser.new_context(viewport={'width':1280,'height':1000})
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    for path, title in documents.items():
        response = page.goto(origin+'/legal/'+path)
        assert response.status == 200
        assert "'strict-dynamic'" in response.headers['content-security-policy']
        expect(page.get_by_role('heading', name=title, exact=True)).to_be_visible()
        expect(page.get_by_text('DRAFT FOR LAWYER REVIEW.', exact=False)).to_be_visible()
        assert page.title() == title+' · Phirmy'
    assert page.goto(origin+'/legal/unknown-document').status == 404
    page.goto(origin+'/signin')
    page.get_by_role('button',name='Create a workspace',exact=True).click()
    page.get_by_label('Your name',exact=True).fill('Legal browser QA')
    page.get_by_label('Work email',exact=True).fill('legal-browser-'+secrets.token_hex(5)+'@example.test')
    page.get_by_label('Password',exact=True).fill('Long-Synthetic-Browser-Password')
    page.get_by_label('Workspace name',exact=True).fill('Legal browser QA')
    posts = []
    page.on('request',lambda request: posts.append(request.post_data_json) if request.method=='POST' and request.url.endswith('/v1/auth/signup') else None)
    checkbox = page.get_by_role('checkbox',name='I accept',exact=False)
    expect(checkbox).not_to_be_checked()
    page.get_by_role('button',name='Create workspace',exact=True).click()
    assert page.evaluate('document.querySelector("input[name=legal_accepted]").validity.valueMissing')
    assert not posts
    checkbox.check()
    page.screenshot(path=str(artifacts/'signup-acceptance.png'),full_page=True)
    page.get_by_role('button',name='Create workspace',exact=True).click()
    page.wait_for_url('**/app',timeout=30000)
    assert len(posts)==1 and posts[0]['legal_accepted'] is True
    response = context.request.get(origin+'/backend/v1/auth/legal-acceptances')
    assert response.status==200
    records=response.json()['items']
    assert len(records)==1 and records[0]['version']==posts[0]['legal_version'] and records[0]['source']=='password_signup'
    assert not errors
    browser.close()
    print(json.dumps({'legal_documents':len(documents),'invalid_document':'404','unchecked_signup':'no request',
                      'accepted_signup':'versioned server record','page_errors':len(errors),'status':'passed'}))

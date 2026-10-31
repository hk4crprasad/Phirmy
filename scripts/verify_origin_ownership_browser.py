"""Ownership dashboard with a fake DNS provider only in a separate QA test process.

Requires the explicit isolated SQLite environment used by the running QA API.
The product server retains its real verifier; no production bypass is installed.
"""
import json
import logging
import os
from pathlib import Path
import sys
from unittest.mock import patch
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'services/control'))
from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright, expect
from studio import origin_ownership
from studio.config import settings
from studio.db import engine
from studio.main import create_app
from qa_accounts import bootstrap_account

assert engine.dialect.name == 'sqlite' and settings.app_env != 'production', 'Only isolated local QA is permitted'
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpx2').setLevel(logging.WARNING)
web = os.environ.get('BROWSER_TEST_ORIGIN','http://127.0.0.1:3100')
origin = 'https://ownership-qa.example'
with sync_playwright() as p:
    browser = p.chromium.launch(executable_path='/usr/bin/chromium',headless=True)
    context = browser.new_context()
    me = bootstrap_account(context.request,web+'/backend/v1/auth/signup',data={
        'name':'Ownership QA','email':'origin-'+uuid.uuid4().hex[:10]+'@example.test',
        'password':'Private-Synthetic-Origin-Password','workspace_name':'Ownership QA'}).json()
    base = '/v1/workspaces/'+me['workspaces'][0]['id']
    csrf = next(cookie['value'] for cookie in context.cookies() if cookie['name']=='studio_csrf')
    headers = {'Origin':web,'X-CSRF-Token':csrf}
    fixture = context.request.post(web+'/backend'+base+'/fixtures',data={},headers=headers)
    assert fixture.status == 201
    created = context.request.post(web+'/backend'+base+'/installations',headers=headers,data={
        'agent_id':fixture.json()['agent_id'],'name':'Ownership QA widget','allowed_origins':[origin,web]})
    assert created.status == 201
    widget = created.json()
    public_url = web+'/backend/v1/public/installations/'+widget['public_id']
    public_options = {'headers':{'Origin':origin},'params':{'public_key':widget['theme']['publishable_key']}}
    assert context.request.post(public_url,**public_options).status == 403
    page = context.new_page(); errors=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    page.goto(web+'/app/widget')
    details = page.locator('details').filter(has=page.get_by_text('Other agent installations',exact=True))
    details.locator('summary').click()
    card = details.locator('.stack').filter(has=page.get_by_text('Ownership QA widget',exact=True)).first
    card.get_by_role('button',name='Customize widget',exact=True).click()
    dialog = page.get_by_role('dialog',name='Your assistant’s appearance')
    dialog.get_by_role('tab',name='Website',exact=True).click()
    dialog.get_by_role('button',name='Create ownership challenge',exact=True).click()
    dialog.get_by_text('DNS TXT record',exact=True).click()
    record = context.request.get(web+'/backend'+base+'/origins').json()['items'][0]
    class FakeDNS:
        async def verify(self,candidate,method,token):
            return candidate==origin and method=='dns' and origin_ownership.PREFIX+token==record['dns']['value']
    def check_with_fake_dns(route):
        request=route.request
        forwarded={name:value for name,value in request.all_headers().items() if name not in {'host','content-length','connection'}}
        with patch.object(origin_ownership,'provider',FakeDNS()):
            result=TestClient(create_app(start_worker=False)).post(
                request.url.split('/backend',1)[1],headers=forwarded,json=request.post_data_json)
        route.fulfill(status=result.status_code,body=result.content,headers={'Content-Type':'application/json'})
    page.route('**/origins/*/verify',check_with_fake_dns)
    dialog.get_by_role('button',name='Check DNS proof',exact=True).click()
    expect(dialog.get_by_text('Verified until',exact=False)).to_be_visible()
    assert context.request.post(public_url,**public_options).status==200
    csp=context.request.get(web+'/widget/'+widget['public_id']).headers['content-security-policy']
    assert origin in csp
    dialog.get_by_role('button',name='Revoke website verification',exact=True).click()
    expect(dialog.get_by_text('Verified until',exact=False)).not_to_be_visible()
    assert context.request.post(public_url,**public_options).status==403
    assert origin not in context.request.get(web+'/widget/'+widget['public_id']).headers['content-security-policy']
    assert not errors
    results={'challenge_ui':True,'fake_dns_through_real_verification_endpoint':True,
             'unverified_origin_denied':True,'verified_origin_allowed':True,'frame_policy_updated':True,
             'revocation_enforced':True,'page_errors':0}
    folder=Path('artifacts/origin-ownership');folder.mkdir(parents=True,exist_ok=True)
    (folder/'browser.json').write_text(json.dumps(results,indent=2)+'\n')
    print(json.dumps(results));browser.close()

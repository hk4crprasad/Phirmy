"""Production UI and real routes, fake Turnstile only in this separate QA process."""
import json
import logging
import os
from pathlib import Path
import re
from unittest.mock import patch
from urllib.parse import urlsplit
import uuid

from fastapi.testclient import TestClient
from playwright.sync_api import expect,sync_playwright
from sqlalchemy import select

from qa_accounts import bootstrap_account
from studio import bot_challenge
from studio.config import settings
from studio.db import session_scope
from studio.main import create_app
from studio.models import EmailOutbox
from studio.secrets import decrypt

logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpx2').setLevel(logging.WARNING)
web=os.environ.get('BROWSER_TEST_ORIGIN','http://127.0.0.1:3100')
expect.set_options(timeout=30000)
class FakeTurnstile:
    calls=0
    async def verify(self,token,remote_ip,hostname):
        assert remote_ip=='testclient' and hostname==urlsplit(web).hostname
        self.calls+=1
        return token=='synthetic-browser-bot-proof' and self.calls==1

fake=FakeTurnstile();latest={}
with sync_playwright() as playwright:
    browser=playwright.chromium.launch(executable_path='/usr/bin/chromium',headless=True)
    context=browser.new_context()
    me=bootstrap_account(context.request,web+'/backend/v1/auth/signup',data={
        'name':'Protection QA','email':'protection-'+uuid.uuid4().hex[:10]+'@example.test',
        'password':'Private-Synthetic-Protection-Password','workspace_name':'Protection QA'}).json()
    base='/v1/workspaces/'+me['workspaces'][0]['id']
    csrf=next(cookie['value'] for cookie in context.cookies() if cookie['name']=='studio_csrf')
    headers={'Origin':web,'X-CSRF-Token':csrf}
    fixture=context.request.post(web+'/backend'+base+'/fixtures',data={},headers=headers)
    assert fixture.status==201
    created=context.request.post(web+'/backend'+base+'/installations',headers=headers,data={
        'agent_id':fixture.json()['agent_id'],'name':'Protection QA widget','allowed_origins':[web]})
    assert created.status==201
    widget=created.json();page=context.new_page();errors=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    def fake_route(route):
        request=route.request
        forwarded={name:value for name,value in request.all_headers().items() if name not in {'host','content-length','connection'}}
        with patch.object(bot_challenge,'provider',fake),patch.object(settings,'widget_bot_challenge_enabled',True),\
             patch.object(settings,'turnstile_site_key','synthetic-browser-site'),\
             patch.object(settings,'turnstile_secret_key','synthetic-browser-secret'),\
             patch.object(settings,'widget_marketing_consent_enabled',True):
            with TestClient(create_app(start_worker=False)) as client:
                result=client.request(request.method,request.url.split('/backend',1)[1],headers=forwarded,
                                      content=request.post_data)
        if request.url.endswith('/email/request') and result.status_code==202:latest.update(result.json())
        route.fulfill(status=result.status_code,body=result.content,headers={'Content-Type':'application/json'})
    page.route('**/backend/v1/public/installations/**',fake_route)
    page.route('**/backend/v1/public/sessions',fake_route)
    page.route('**/backend/v1/public/email/*',fake_route)
    page.route('https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit',lambda route:route.fulfill(
        content_type='application/javascript',body='''window.turnstile={ready:fn=>fn(),render:(root,options)=>{
          let button=document.createElement('button');button.type='button';button.textContent='Complete bot check';
          button.onclick=()=>options.callback('synthetic-browser-bot-proof');root.append(button);return 'qa-bot';
        },remove:()=>document.querySelectorAll('[aria-label="Bot verification"] button').forEach(button=>button.remove())};'''))
    page.goto(web+'/widget/'+widget['public_id']+'?public_key='+widget['theme']['publishable_key'])
    expect(page.get_by_role('button',name='Complete bot check',exact=True)).to_be_visible()
    assert not page.get_by_label('Email address',exact=True).is_visible()
    page.get_by_role('button',name='Complete bot check',exact=True).click()
    expect(page.get_by_label('Chat message',exact=True)).to_be_enabled()
    assert fake.calls==1
    page.get_by_text('Verify email for follow-up',exact=True).click()
    page.get_by_label('Email for verification',exact=True).fill('verified-visitor@example.test')
    page.get_by_role('button',name='Send verification code',exact=True).click()
    expect(page.get_by_label('Email verification code',exact=True)).to_be_visible()
    with session_scope() as db:
        mail=db.scalar(select(EmailOutbox).where(EmailOutbox.operation_key=='widget-otp:'+latest['challenge_id']))
        code=re.search(r'code is (\d{6})',json.loads(decrypt(mail.encrypted_payload))['body'])[1]
    assert code not in json.dumps(latest)
    page.get_by_label('Email verification code',exact=True).fill(code)
    page.get_by_role('checkbox').check()
    page.get_by_role('button',name='Verify email',exact=True).click()
    expect(page.get_by_text('Email verified',exact=True)).to_be_visible()
    lead=context.request.get(web+'/backend'+base+'/leads').json()['items'][0]
    assert lead['email_verified'] and lead['marketing_opt_in']
    page.goto(web+'/app/widget')
    details=page.locator('details').filter(has=page.get_by_text('Other agent installations',exact=True))
    details.locator('summary').click()
    card=details.locator('.stack').filter(has=page.get_by_text('Protection QA widget',exact=True)).first
    card.get_by_role('button',name='Customize widget',exact=True).click()
    dialog=page.get_by_role('dialog',name='Your assistant’s appearance')
    dialog.get_by_role('tab',name='Website',exact=True).click()
    dialog.get_by_text('Visitor quotas and spending limit',exact=True).click()
    cap=dialog.get_by_label('Monthly spending limit · paise (0 pauses requests)',exact=True)
    expect(cap).to_be_visible();cap.fill('0')
    dialog.get_by_role('button',name='Save visitor protection',exact=True).click()
    expect(dialog.get_by_role('button',name='Save visitor protection',exact=True)).to_be_enabled()
    public=context.request.post(web+'/backend/v1/public/sessions',headers={'Origin':web},data={
        'installation_public_id':widget['public_id'],'public_key':widget['theme']['publishable_key']})
    assert public.status==429
    with session_scope() as db:
        assert db.scalar(select(EmailOutbox.id).where(EmailOutbox.operation_key.like('widget-cap:'+widget['id']+':%')))
    assert not errors,errors
    result={'production_ui_fake_turnstile_real_server_contract':True,'email_optional_by_default':True,
            'otp_via_encrypted_outbox':True,'consent_after_verification_only':True,
            'owner_cap_ui_blocks_admission_and_queues_email':True,'page_errors':0}
    folder=Path('artifacts/widget-protection');folder.mkdir(parents=True,exist_ok=True)
    (folder/'browser.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result));browser.close()

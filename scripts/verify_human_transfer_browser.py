"""Local browser acceptance for prepared staff destinations and manual callbacks.

Requires isolated development API/local objects with all paid providers disabled.
No carrier request is made. BROWSER_TEST_ORIGIN selects the existing local frontend.
"""
import json
import os
from pathlib import Path
import uuid

from playwright.sync_api import expect, sync_playwright
from qa_accounts import bootstrap_account

web=os.environ.get('BROWSER_TEST_ORIGIN','http://127.0.0.1:3100')
expect.set_options(timeout=30000)
with sync_playwright() as playwright:
    browser=playwright.chromium.launch(executable_path='/usr/bin/chromium',headless=True)
    context=browser.new_context()
    me=bootstrap_account(context.request,web+'/backend/v1/auth/signup',data={
        'name':'Handoff QA','email':'handoff-'+uuid.uuid4().hex[:10]+'@example.test',
        'password':'Private-Synthetic-Handoff-Password','workspace_name':'Handoff QA'}).json()
    base=web+'/backend/v1/workspaces/'+me['workspaces'][0]['id']
    csrf=next(cookie['value'] for cookie in context.cookies() if cookie['name']=='studio_csrf')
    headers={'Origin':web,'X-CSRF-Token':csrf}
    fixture=context.request.post(base+'/fixtures',headers=headers,data={})
    assert fixture.status==201
    page=context.new_page();errors=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    page.goto(web+'/app/integrations')
    expect(page.get_by_text('Human transfer',exact=True)).to_be_visible()
    page.get_by_role('button',name='Set staff destination',exact=True).click()
    page.get_by_label('Staff phone with country code').fill('+12025550124')
    page.get_by_label('Team name read to the caller').fill('Synthetic support team')
    page.get_by_label('Maximum staff-leg duration in seconds').fill('30')
    page.get_by_role('button',name='Save for approval',exact=True).click()
    expect(page.get_by_text('Synthetic support team · ending 0124 · up to 30s',exact=True)).to_be_visible()
    expect(page.get_by_text('Live transfer activation is off.',exact=False)).to_be_visible()
    policy=context.request.get(base+'/transfer-policy').json()
    assert policy['approved'] is False and not policy['live_activation_enabled']
    assert 'destination' not in policy
    assert context.request.get(base+'/call-transfers').json()['items']==[]
    created=context.request.post(base+'/installations',headers=headers,data={
        'agent_id':fixture.json()['agent_id'],'name':'Handoff QA widget','allowed_origins':[web]})
    assert created.status==201
    installation=created.json()
    page.goto(web+'/widget/'+installation['public_id']+'?public_key='+installation['theme']['publishable_key'])
    email=page.get_by_label('Email address',exact=True)
    message=page.get_by_label('Chat message',exact=True)
    for _ in range(100):
        if email.is_visible() or (message.count() and message.is_enabled()):break
        page.wait_for_timeout(50)
    if email.is_visible():
        email.fill('visitor@example.test');page.get_by_role('button',name='Continue',exact=True).click()
    expect(message).to_be_enabled()
    message.fill('Please call me back at +12025550123')
    page.get_by_role('button',name='Send chat message').click()
    confirm=page.get_by_role('button',name='Confirm request',exact=True)
    expect(confirm).to_be_visible()
    assert context.request.get(base+'/tickets').json()['items']==[]
    confirm.click()
    expect(page.get_by_text('Your callback request is in the team inbox.',exact=False)).to_be_visible()
    tickets=context.request.get(base+'/tickets').json()['items']
    assert len(tickets)==1 and 'unverified' in tickets[0]['description']
    page.goto(web+'/app/inbox')
    page.get_by_role('button',name='Support tickets',exact=True).click()
    expect(page.get_by_text('Callback request',exact=True)).to_be_visible()
    page.get_by_label('Ticket state Callback request').select_option('resolved')
    expect(page.get_by_label('Ticket state Callback request')).to_have_value('resolved')
    assert context.request.get(base+'/tickets').json()['items'][0]['state']=='resolved'
    assert not errors,errors
    folder=Path('artifacts/human-transfers');folder.mkdir(parents=True,exist_ok=True)
    result={'staff_destination_form':'passed','masked_destination':'passed','approval_required':True,
            'live_activation_enabled':False,'callback_readback_and_confirmation':'passed',
            'owner_inbox_resolution':'passed','page_errors':errors,'carrier_calls_made':0}
    (folder/'browser.json').write_text(json.dumps(result,indent=2))
    page.screenshot(path=str(folder/'inbox.png'),full_page=True)
    print(json.dumps(result))
    browser.close()

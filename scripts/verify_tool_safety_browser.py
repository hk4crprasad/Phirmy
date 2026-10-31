"""Real local browser/chat/WebSocket confirmation acceptance; providers are disabled."""
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
        'name':'Safety QA','email':'safety-'+uuid.uuid4().hex[:10]+'@example.test',
        'password':'Private-Synthetic-Safety-Password','workspace_name':'Safety QA'}).json()
    base=web+'/backend/v1/workspaces/'+me['workspaces'][0]['id']
    csrf=next(cookie['value'] for cookie in context.cookies() if cookie['name']=='studio_csrf')
    response=context.request.post(base+'/fixtures',data={},headers={'Origin':web,'X-CSRF-Token':csrf})
    assert response.status==201
    page=context.new_page();page.set_default_timeout(30000);errors=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    created=context.request.post(base+'/installations',headers={'Origin':web,'X-CSRF-Token':csrf},data={
        'agent_id':response.json()['agent_id'],'name':'Safety QA widget','allowed_origins':[web]})
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
    message.fill('What does human hair mean?');page.get_by_role('button',name='Send chat message').click()
    expect(message).to_be_enabled()
    assert context.request.get(base+'/tickets').json()['items']==[]
    message.fill('Please create a support ticket for follow-up.');page.get_by_role('button',name='Send chat message').click()
    confirm=page.get_by_role('button',name='Confirm request',exact=True)
    expect(confirm).to_be_visible()
    assert context.request.get(base+'/tickets').json()['items']==[]
    confirm.click()
    expect(page.get_by_text("I've recorded your request as a support ticket.",exact=False)).to_be_visible()
    assert len(context.request.get(base+'/tickets').json()['items'])==1
    expect(confirm).not_to_be_visible()
    page.goto(web+'/app/voice')
    events=[]
    def socket_open(socket):
        def frame(payload):
            if isinstance(payload,str):
                try:events.append(json.loads(payload))
                except ValueError:pass
        socket.on('framereceived',frame)
    page.on('websocket',socket_open)
    page.get_by_role('button',name='Start simulation',exact=True).click()
    expect(page.get_by_label('Voice lab text turn')).to_be_enabled()
    expect(page.get_by_text('Hello, this is your AI support assistant. How can I help?',exact=True)).to_be_visible()
    turn=page.get_by_label('Voice lab text turn')
    turn.fill('Please create a support ticket for follow-up.');page.get_by_role('button',name='Send test turn').click()
    expect(page.get_by_text('Confirm request',exact=False)).to_be_visible()
    # Wait for the actual turn-completed receipt before sending the next turn.
    for _ in range(100):
        if events and events[-1].get('type')=='server.turn_state' and events[-1].get('state')=='listening':break
        page.wait_for_timeout(50)
    assert len(context.request.get(base+'/tickets').json()['items'])==1
    turn.fill('Confirm request');page.get_by_role('button',name='Send test turn').click()
    expect(page.get_by_text("I've recorded your request as a support ticket.",exact=False)).to_be_visible()
    assert len(context.request.get(base+'/tickets').json()['items'])==2
    page.get_by_role('button',name='End session',exact=True).click()
    expect(page.get_by_role('button',name='Start simulation',exact=True)).to_be_visible()
    assert not errors,errors
    result={'unrelated_human_word_no_ticket':True,'chat_confirmation_required':True,
            'chat_confirmation_persists_once':True,'voice_confirmation_required':True,
            'voice_confirmation_persists_once':True,'page_errors':0}
    folder=Path('artifacts/tool-safety');folder.mkdir(parents=True,exist_ok=True)
    (folder/'browser.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result));browser.close()

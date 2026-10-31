"""Actual dashboard deletion flow, isolated local API/objects only, no providers."""
import json,uuid
from pathlib import Path
from playwright.sync_api import sync_playwright,expect
from qa_accounts import bootstrap_account
WEB='http://127.0.0.1:3100';ART=Path('artifacts/agent-deletion');ART.mkdir(parents=True,exist_ok=True)
with sync_playwright() as p:
 browser=p.chromium.launch(headless=True,executable_path='/usr/bin/chromium');context=browser.new_context(viewport={'width':1440,'height':1080},reduced_motion='reduce');request=context.request
 assert request.get(WEB+'/backend/healthz').json()['environment']=='development'
 account=bootstrap_account(request, WEB+'/backend/v1/auth/signup',data={'name':'Deletion QA','email':'delete-'+uuid.uuid4().hex[:10]+'@example.test','password':'Long-Local-Delete-Password','workspace_name':'Deletion QA'});assert account.status==200
 base=WEB+'/backend/v1/workspaces/'+account.json()['workspaces'][0]['id'];headers={'Origin':WEB,'X-CSRF-Token':next(c['value'] for c in context.cookies() if c['name']=='studio_csrf')}
 fixture=request.post(base+'/fixtures',headers=headers,data={});assert fixture.status==201
 agent=request.get(base+'/agents/'+fixture.json()['agent_id']).json()
 other=request.post(base+'/agents',headers=headers,data={'name':'Keep shared knowledge'}).json()
 config=other['draft_config'];config['knowledge_snapshot_ids']=agent['draft_config']['knowledge_snapshot_ids']
 assert request.put(base+'/agents/'+other['id']+'/draft',headers=headers,data={'expected_revision':1,'config':config}).status==200
 page=context.new_page();page.set_default_timeout(20000);errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
 page.goto(WEB+'/app/agents');page.get_by_role('button',name='Delete agent '+agent['name'],exact=True).click()
 dialog=page.get_by_role('dialog',name='Delete agent and data');expect(dialog.get_by_label('Agent name to confirm deletion')).to_be_visible()
 expect(dialog.get_by_role('button',name='Delete permanently',exact=True)).to_be_disabled()
 dialog.get_by_label('Agent name to confirm deletion').fill('incorrect');expect(dialog.get_by_role('button',name='Delete permanently',exact=True)).to_be_disabled()
 dialog.get_by_role('button',name='Cancel',exact=True).click();expect(dialog).not_to_be_visible()
 assert request.get(base+'/agents/'+agent['id']).status==200
 page.goto(WEB+'/app/agents/'+agent['id']);page.get_by_role('button',name='Delete agent '+agent['name'],exact=True).click();expect(dialog.get_by_label('Agent name to confirm deletion')).to_be_visible()
 dialog.get_by_label('Agent name to confirm deletion').fill(agent['name']);page.screenshot(path=str(ART/'01-confirmation-desktop.png'))
 page.set_viewport_size({'width':390,'height':844});page.screenshot(path=str(ART/'02-confirmation-mobile.png'))
 assert dialog.bounding_box()['width']<=390 and page.evaluate('document.documentElement.scrollWidth<=innerWidth')
 with page.expect_response(lambda response:response.url.endswith('/agents/'+agent['id']+'/delete') and response.request.method=='POST') as response:
  dialog.get_by_role('button',name='Delete permanently',exact=True).click()
 assert response.value.status==202;job=response.value.json()
 expect(page.get_by_text('Agent and owned data deleted.',exact=True)).to_be_visible(timeout=20000)
 page.set_viewport_size({'width':1440,'height':1080});page.screenshot(path=str(ART/'03-completed-operations.png'),full_page=True)
 assert request.get(base+'/agents/'+agent['id']).status==404
 assert request.get(base+'/agents/'+other['id']).status==200
 assert request.get(base+'/knowledge/'+fixture.json()['kb_id']).status==200
 page.goto(WEB+'/app/agents');page.get_by_role('button',name='Delete agent '+other['name'],exact=True).click();expect(dialog).to_be_visible();dialog.get_by_role('button',name='Archive instead',exact=True).click()
 expect(page.get_by_role('button',name='Delete agent '+other['name'],exact=True)).to_have_count(0)
 assert request.get(base+'/agents/'+other['id']).json()['archived'] is True
 assert not errors,errors
 result={'cancel_and_typed_confirmation':'passed','list_and_editor_actions':'passed','mobile_dialog':'passed','worker_completion_and_status':'passed','shared_knowledge_and_other_agent':'passed','archive_alternative':'passed','page_errors':errors}
 (ART/'browser-results.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result));browser.close()

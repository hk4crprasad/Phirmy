"""Same-origin polling regression through the real Next rewrite and local API."""
import json,uuid,tempfile,html,os
from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
from functools import partial
from threading import Thread
from pathlib import Path
from playwright.sync_api import sync_playwright,expect
from qa_accounts import bootstrap_account
WEB='http://127.0.0.1:3100';ART=Path('artifacts/widget-polling');ART.mkdir(parents=True,exist_ok=True)
with sync_playwright() as p:
 browser=p.chromium.launch(headless=True,executable_path='/usr/bin/chromium')
 admin=browser.new_context();request=admin.request
 account=bootstrap_account(request, WEB+'/backend/v1/auth/signup',data={'name':'Polling QA','email':'poll-'+uuid.uuid4().hex[:12]+'@example.test','password':'Long-Local-Testing-Password','workspace_name':'Polling QA'})
 assert account.status==200
 base=WEB+'/backend/v1/workspaces/'+account.json()['workspaces'][0]['id']
 headers={'Origin':WEB,'X-CSRF-Token':next(c['value'] for c in admin.cookies() if c['name']=='studio_csrf')}
 assert request.post(base+'/fixtures',headers=headers,data={}).status==201
 original=request.get(base+'/installations').json()['items'][0]
 results=json.loads((ART/'results.json').read_text()) if os.environ.get('WIDGET_POLL_CASES') and (ART/'results.json').exists() else {};errors=[]
 for mode in os.environ.get('WIDGET_POLL_CASES','react_tester,embed,html_http,html_file').split(','):
  embedded=mode != 'react_tester'
  # Independent installation for each client; both use the app's own origin.
  row=request.post(base+'/installations',headers=headers,data={'name':'Polling QA widget','agent_id':original['agent_id'],'allowed_origins':[WEB]}).json()
  visitor=browser.new_context();page=visitor.new_page();page.set_default_timeout(15000);page.on('pageerror',lambda e:errors.append(str(e)))
  polls=[];page.on('response',lambda r:polls.append(r) if r.url.endswith('/v1/public/conversation') else None)
  server=None;folder=None;surface=page;file_policy=None
  if mode in ('html_http','html_file'):
   folder=tempfile.TemporaryDirectory(prefix='widget-embed-')
   file=Path(folder.name)/'index.html'
   file.write_text('<!doctype html><title>Independent HTML</title><h1>My test website</h1><script defer src="'+WEB+'/widget.js" data-widget-id="'+html.escape(row['public_id'],quote=True)+'" data-public-key="'+html.escape(row['theme']['publishable_key'],quote=True)+'"></script>')
   if mode=='html_http':
    server=ThreadingHTTPServer(('127.0.0.1',0),partial(SimpleHTTPRequestHandler,directory=folder.name));Thread(target=server.serve_forever,daemon=True).start();destination='http://127.0.0.1:'+str(server.server_port)
   else:destination=file.as_uri()
   try:page.goto(destination)
   except Exception as error:
    if mode!='html_file' or 'ERR_BLOCKED_BY_ADMINISTRATOR' not in str(error):raise
    file_policy='file:// blocked by managed browser; real opaque-origin sandbox HTML used instead'
    page.close();page=visitor.new_page();page.set_default_timeout(15000);page.on('pageerror',lambda e:errors.append(str(e)));page.on('response',lambda r:polls.append(r) if r.url.endswith('/v1/public/conversation') else None)
    page.goto(WEB+'/')
    page.evaluate('content=>{const f=document.createElement("iframe");f.dataset.filePreview="true";f.setAttribute("sandbox","allow-scripts allow-forms");f.style.cssText="width:460px;height:900px;border:0";f.srcdoc=content;document.body.prepend(f)}',file.read_text())
    surface=page.frame_locator('iframe[data-file-preview]')
   surface.get_by_role('button',name='Let’s talk',exact=True).click()
  elif embedded:
   page.goto(WEB+'/')
   page.evaluate('row=>{const s=document.createElement("script");s.src="/widget.js";s.setAttribute("data-widget-id",row.public_id);s.setAttribute("data-public-key",row.theme.publishable_key);document.body.append(s)}',row)
   page.get_by_role('button',name='Let’s talk',exact=True).click()
  else:page.goto(WEB+'/widget/'+row['public_id']+'?public_key='+row['theme']['publishable_key'])
  surface.get_by_label('Email address',exact=True).fill('visitor@example.test')
  with page.expect_response(lambda r:r.url.endswith('/v1/public/sessions') and r.request.method=='POST') as response:
   surface.get_by_role('button',name='Continue',exact=True).click()
  state=response.value.json();assert response.value.status==201
  page.wait_for_timeout(2500)
  assert polls and all(r.status==200 and r.request.method=='POST' for r in polls)
  # Reproduce the original failure: a same-origin GET naturally has no Origin.
  status=surface.locator('body').evaluate('(body,token)=>fetch("http://127.0.0.1:3100/backend/v1/public/conversation",{credentials:"omit",headers:{Authorization:"Bearer "+token}}).then(r=>r.status)',state['session_token'])
  assert status==(403 if mode in ('react_tester','embed') else 200)
  polls.clear()
  path=base+'/conversations/'+state['id']
  assert request.patch(path+'/mode',headers=headers,data={'mode':'human'}).status==200
  assert request.post(path+'/messages',headers=headers,data={'text':'This operator reply arrives through same-origin polling.','client_message_id':str(uuid.uuid4())}).status==201
  expect(surface.get_by_text('Support team · This operator reply arrives through same-origin polling.',exact=True)).to_be_visible(timeout=10000)
  assert request.delete(base+'/installations/'+row['id'],headers=headers).status==200
  expect(surface.get_by_text('Chat session is unavailable. Reconnect to continue.',exact=False).first).to_be_visible(timeout=10000)
  count=len(polls);page.wait_for_timeout(4500);assert len(polls)==count,'Rejected session kept polling'
  key=mode
  page.screenshot(path=str(ART/(key+'.png')))
  results[key]={'same_origin_post':'passed','diagnostic_get_status':status,'operator_reply':'passed','terminal_rejection_stops_polling':'passed','file_policy':file_policy}
  (ART/'results.json').write_text(json.dumps(results,indent=2)+'\n')
  visitor.close()
  if server:server.shutdown();server.server_close()
  if folder:folder.cleanup()
 assert not errors,errors
 results['page_errors']=errors;(ART/'results.json').write_text(json.dumps(results,indent=2)+'\n');print(json.dumps(results));browser.close()

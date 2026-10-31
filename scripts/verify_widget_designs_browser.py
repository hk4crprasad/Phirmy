"""Save and test every design through the dashboard and real Aurely HTML embed.

Uses only the retained local QA workspace. Captures actual screenshots per style;
no mocked network, preset injection, generated widget images or trust exceptions.
"""
import json,secrets,sys,uuid
from pathlib import Path
from qa_accounts import bootstrap_account
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'services/control'))
from sqlalchemy import select
from studio.db import session_scope,engine
from studio.models import Membership,Conversation,Message
from playwright.sync_api import sync_playwright,expect
def email_gate(page):
    email=page.get_by_label("Email address",exact=True)
    try: email.wait_for(state="visible",timeout=2500)
    except Exception: return
    email.fill("widget-qa@example.test");page.get_by_role("button",name="Continue",exact=True).click()
ROOT=Path(__file__).resolve().parents[1];ART=ROOT/'artifacts/widget-designs';ART.mkdir(parents=True,exist_ok=True)
WEB='http://127.0.0.1:3100';DEMO='http://127.0.0.1:3200';WS='632f4e20-9134-4efa-8842-5e60144f2e8e';BASE='/v1/workspaces/'+WS
DESIGNS=[('minimal','Minimalism'),('glassmorphism','Glassmorphism'),('claymorphism','Claymorphism'),('skeuomorphism','Skeuomorphism'),('neobrutalism','Neobrutalism'),('bento','Bento grid'),('neumorphism','Neumorphism'),('aurora','Aurora'),('editorial','Editorial'),('monochrome','Monochrome')]
if engine.dialect.name!='sqlite':raise RuntimeError('Use the explicit local QA database')
with sync_playwright() as p:
 browser=p.chromium.launch(headless=True,executable_path='/usr/bin/chromium')
 admin=browser.new_context(viewport={'width':1500,'height':1120},reduced_motion='reduce')
 signup=bootstrap_account(admin.request, WEB+'/backend/v1/auth/signup',headers={'Origin':WEB},data={'name':'Design gallery QA','email':'design-gallery-'+uuid.uuid4().hex[:10]+'@example.test','password':secrets.token_urlsafe(24),'workspace_name':'Design gallery QA'})
 assert signup.status==200,signup.status
 with session_scope(write=True) as db:db.add(Membership(workspace_id=WS,user_id=signup.json()['user']['id'],role='owner'))
 admin.add_init_script('localStorage.setItem("studio.workspace",'+json.dumps(WS)+')')
 page=admin.new_page();page.set_default_timeout(30000);errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
 original=next(x for x in admin.request.get(WEB+'/backend'+BASE+'/installations').json()['items'] if x['name']=='Aurely demo HTML widget')
 page.goto(WEB+'/app/widget')
 details=page.locator('details').filter(has=page.get_by_text('Other agent installations',exact=True));details.locator('summary').click()
 card=details.locator('.stack').filter(has=page.get_by_text('Aurely demo HTML widget',exact=True)).first
 results=[]
 for preset,label in DESIGNS:
  card.get_by_role('button',name='Customize widget',exact=True).click()
  dialog=page.get_by_role('dialog',name='Your assistant’s appearance')
  dialog.get_by_role('tab',name='Style',exact=True).click()
  dialog.get_by_label('Widget style',exact=True).select_option(preset)
  preview=dialog.locator('.wd-root')
  assert preview.get_attribute('data-widget-design')==preset
  assert preview.evaluate('(root)=>getComputedStyle(root).getPropertyValue("--wd-style").trim()')==preset
  dialog.screenshot(path=str(ART/(preset+'-dashboard.png')))
  dialog.get_by_role('button',name='Save widget',exact=True).click();expect(dialog).not_to_be_visible()
  row=next(x for x in admin.request.get(WEB+'/backend'+BASE+'/installations').json()['items'] if x['id']==original['id'])
  assert row['theme']['preset']==preset and row['theme']['publishable_key']==original['theme']['publishable_key']
  assert row['theme']['assistant_name']==original['theme']['assistant_name'] and row['theme']['tone']==original['theme']['tone']
  visitor=browser.new_context(viewport={'width':1440,'height':1040},reduced_motion='reduce')
  site=visitor.new_page();site.set_default_timeout(30000);site.on('pageerror',lambda e:errors.append(str(e)))
  site.goto(DEMO+'/',wait_until='networkidle')
  launcher=site.get_by_role('button',name=row['theme'].get('launcher_label','Let’s talk'),exact=True);expect(launcher).to_be_visible();launcher.click();email_gate(site)
  expect(site.get_by_label('Chat message',exact=True)).to_be_enabled()
  host=site.locator('[data-voice-studio-widget]');root=host.locator('.wd-root')
  assert root.evaluate('(node)=>getComputedStyle(node).getPropertyValue("--wd-style").trim()')==preset
  question='What is the price of the Premium Silver-Tone Designer Bangle?'
  site.get_by_label('Chat message',exact=True).fill(question)
  with site.expect_response(lambda r:r.url.endswith('/v1/public/chat') and r.request.method=='POST',timeout=90000) as chat:
   site.get_by_role('button',name=row['theme'].get('send_button_label','Send'),exact=True).click()
  assert chat.value.status==200
  expect(site.get_by_role('button',name=row['theme'].get('send_button_label','Send'),exact=True)).to_be_enabled(timeout=90000)
  assert host.locator('.error').inner_text()==''
  with session_scope() as db:
   stored=db.scalar(select(Message).join(Conversation,Conversation.id==Message.conversation_id).where(Conversation.workspace_id==WS,Conversation.installation_id==row['id'],Message.role=='assistant').order_by(Message.created_at.desc()).limit(1))
   assert stored and '699' in stored.text_content;answer=stored.text_content
  host.evaluate("host=>{const root=host.shadowRoot,log=root.querySelector('.log'),answer=[...root.querySelectorAll('.message')].find(x=>x.textContent.includes('699'));if(answer)log.scrollTop=answer.offsetTop-log.offsetTop;}")
  site.wait_for_timeout(300)
  material=host.locator('.wd-panel').evaluate('(node)=>{const s=getComputedStyle(node);return {shadow:s.boxShadow,background:s.backgroundImage,border:s.borderWidth,filter:s.backdropFilter,radius:s.borderRadius}}')
  site.screenshot(path=str(ART/(preset+'-desktop.png')))
  bounds=host.bounding_box();clip={'x':max(0,bounds['x']-20),'y':max(0,bounds['y']-20),'width':min(bounds['width']+40,1440-max(0,bounds['x']-20)),'height':min(bounds['height']+40,1040-max(0,bounds['y']-20))}
  site.screenshot(path=str(ART/(preset+'-widget.png')),clip=clip)
  site.set_viewport_size({'width':390,'height':844})
  box=site.get_by_role('dialog',name='Business support chat').bounding_box()
  assert box and box['x']>=0 and box['x']+box['width']<=390 and box['y']>=0 and box['y']+box['height']<=844
  assert site.evaluate('document.documentElement.scrollWidth<=innerWidth')
  site.screenshot(path=str(ART/(preset+'-mobile.png')))
  site.emulate_media(color_scheme='dark')
  assert site.get_by_role('dialog',name='Business support chat').bounding_box()['x']>=0
  assert not visitor.cookies([WEB,DEMO])
  results.append({'id':preset,'label':label,'saved_and_reopened':'passed','preview_matches_embed':'passed','real_chat':answer,'mobile_and_dark':'passed','material':material})
  print(json.dumps({'style':label,'status':'passed'}),flush=True)
  visitor.close()
 assert len({json.dumps(r['material'],sort_keys=True) for r in results})==len(DESIGNS),'Design materials were not distinct'
 # Leave the example in the premium minimal design through the same dashboard.
 card.get_by_role('button',name='Customize widget',exact=True).click();dialog=page.get_by_role('dialog',name='Your assistant’s appearance');dialog.get_by_role('tab',name='Style',exact=True).click();dialog.get_by_label('Widget style',exact=True).select_option('minimal');dialog.get_by_role('button',name='Save widget',exact=True).click();expect(dialog).not_to_be_visible()
 assert not errors,errors
 (ART/'results.json').write_text(json.dumps({'styles':results,'page_errors':errors,'final_demo_style':'minimal'},indent=2)+'\n')
 cards=''.join('<article><h2>'+r['label']+'</h2><img src="'+r['id']+'-widget.png" alt="Actual '+r['label']+' widget screenshot"><p><a href="'+r['id']+'-desktop.png">Desktop</a> · <a href="'+r['id']+'-mobile.png">Mobile</a> · <a href="'+r['id']+'-dashboard.png">Dashboard</a></p></article>' for r in results)
 gallery='<!doctype html><html><head><meta charset="utf-8"><title>Widget design gallery</title><style>body{margin:0;padding:36px;background:#eeece7;color:#252823;font:16px system-ui}h1{margin:0;font:42px Georgia}header p{color:#666;margin:10px 0 30px}.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:24px}article{background:#f9f8f4;border:1px solid #dcd9d2;border-radius:14px;padding:20px}h2{font:23px Georgia;margin:0 0 18px}img{width:100%;height:620px;object-fit:contain;object-position:top}a{color:inherit;font-size:14px}</style></head><body><header><h1>Ten expressions. One connected assistant.</h1><p>Actual dashboard-selected designs, real Aurely answers. Each tested on desktop and mobile.</p></header><main class="grid">'+cards+'</main></body></html>'
 (ART/'index.html').write_text(gallery)
 # Local file gallery contains only the screenshots produced above.
 from functools import partial
 from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
 from threading import Thread
 server=ThreadingHTTPServer(('127.0.0.1',0),partial(SimpleHTTPRequestHandler,directory=str(ART)))
 thread=Thread(target=server.serve_forever,daemon=True);thread.start()
 try:
  gallery_page=admin.new_page();gallery_page.set_viewport_size({'width':1320,'height':1000});gallery_page.goto('http://127.0.0.1:'+str(server.server_port)+'/index.html');gallery_page.screenshot(path=str(ART/'all-designs.png'),full_page=True)
 finally:server.shutdown();server.server_close();thread.join()
 print(json.dumps({'styles_tested':len(results),'page_errors':errors,'gallery':str(ART/'index.html')}),flush=True)
 admin.close();browser.close()

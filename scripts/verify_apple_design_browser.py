"""Apple-design interaction audit with actual isolated local API data, no providers."""
import json,uuid
from pathlib import Path
from playwright.sync_api import sync_playwright,expect
from qa_accounts import bootstrap_account
WEB='http://127.0.0.1:3100';ART=Path('artifacts/apple-design');ART.mkdir(parents=True,exist_ok=True)
with sync_playwright() as p:
 browser=p.chromium.launch(headless=True,executable_path='/usr/bin/chromium')
 context=browser.new_context(viewport={'width':1440,'height':1000},reduced_motion='reduce')
 request=context.request
 account=bootstrap_account(request, WEB+'/backend/v1/auth/signup',data={'name':'Design audit','email':'design-'+uuid.uuid4().hex[:12]+'@example.test','password':'Long-Local-Audit-Password','workspace_name':'Design audit'})
 assert account.status==200
 base=WEB+'/backend/v1/workspaces/'+account.json()['workspaces'][0]['id']
 csrf=next(x['value'] for x in context.cookies() if x['name']=='studio_csrf');headers={'Origin':WEB,'X-CSRF-Token':csrf}
 fixture=request.post(base+'/fixtures',headers=headers,data={});assert fixture.status==201
 widget=request.get(base+'/installations').json()['items'][0]
 state=request.post(WEB+'/backend/v1/public/sessions',headers={'Origin':WEB},data={'installation_public_id':widget['public_id'],'visitor_email':'visitor-audit@example.test'}).json()
 path=base+'/conversations/'+state['id'];assert request.patch(path+'/mode',headers=headers,data={'mode':'human'}).status==200
 for i in range(12):
  assert request.post(path+'/messages',headers=headers,data={'text':f'Reply {i+1}. We can help you find the right piece, understand delivery, and choose your next step.','client_message_id':str(uuid.uuid4())}).status==201
 page=context.new_page();page.set_default_timeout(20000);errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
 page.goto(WEB+'/');expect(page.locator('h1')).to_be_visible();page.screenshot(path=str(ART/'landing-desktop.png'))
 page.goto(WEB+'/app/inbox?conversation='+state['id']);expect(page.get_by_label('Reply to visitor')).to_be_enabled()
 selected=page.locator('.live-conversation[aria-pressed=true]');expect(selected).to_have_count(1)
 assert selected.evaluate('e=>getComputedStyle(e).backgroundColor')!='rgba(0, 0, 0, 0)'
 thread=page.locator('.live-thread-messages');thread.evaluate('e=>e.scrollTop=0');page.wait_for_timeout(200)
 assert request.post(path+'/messages',headers=headers,data={'text':'A new message while you read earlier replies.','client_message_id':str(uuid.uuid4())}).status==201
 expect(thread.get_by_text('A new message while you read earlier replies.',exact=True)).to_be_attached(timeout=10000)
 assert thread.evaluate('e=>e.scrollTop')<10
 # New replies must not pull the whole document or the reading position away.
 assert page.evaluate('scrollY')<10
 page.locator('.live-inbox-thread button').first.focus()
 assert page.locator('.live-inbox-thread button').first.evaluate('e=>getComputedStyle(e).outlineColor')=='rgb(22, 123, 103)'
 page.screenshot(path=str(ART/'inbox-desktop.png'),full_page=True)
 # Held notification responses complete in reverse order; only the latest may render.
 pending=[];context.route('**/notifications',lambda route:pending.append(route))
 trigger=page.get_by_role('button',name='Notifications',exact=False).first;trigger.click()
 page.wait_for_function('true');page.wait_for_timeout(5500)
 assert len(pending)>=2
 pending[-1].fulfill(status=200,json={'items':[],'unread':0})
 pending[0].fulfill(status=200,json={'items':[{'id':'stale','title':'Stale notification','description':'Older request','href':'/app/inbox','created_at':'2026-10-24T00:00:00Z','read':False}],'unread':1})
 expect(page.get_by_text('You’re all caught up.',exact=True)).to_be_visible()
 expect(page.get_by_text('Stale notification',exact=True)).to_have_count(0)
 for route in pending[1:-1]:route.fulfill(status=200,json={'items':[],'unread':0})
 context.unroute('**/notifications');page.keyboard.press('Escape')
 for width,theme in [(390,'Light'),(390,'Dark')]:
  page.set_viewport_size({'width':width,'height':844})
  page.get_by_role('button',name='Color theme',exact=True).click();page.get_by_role('menuitemradio',name=theme,exact=True).click()
  assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
  for element in page.locator('.topbar .icon-button').all():
   if element.is_visible():
    box=element.bounding_box();assert box['width']>=44 and box['height']>=44
  page.screenshot(path=str(ART/('inbox-mobile-'+theme.lower()+'.png')),full_page=True)
 page.emulate_media(contrast='more');assert page.locator('.topbar').evaluate('e=>getComputedStyle(e).backdropFilter')=='none'
 page.emulate_media(contrast='no-preference',reduced_motion='reduce')
 page.goto(WEB+'/app/agents');page.get_by_role('button',name='Create agent',exact=True).click()
 dialog=page.get_by_role('dialog');assert dialog.evaluate('e=>getComputedStyle(e).animationName')=='none'
 page.screenshot(path=str(ART/'mobile-dialog.png'));page.keyboard.press('Escape')
 page.set_viewport_size({'width':1440,'height':1000});page.goto(WEB+'/app/widget')
 page.get_by_text('Other agent installations',exact=True).click()
 page.get_by_role('button',name='Customize widget',exact=True).first.click()
 editor=page.get_by_role('dialog',name='Your assistant’s appearance');editor.get_by_role('tab',name='Style',exact=True).click()
 editor.get_by_label('Widget style',exact=True).select_option('glassmorphism')
 expect(editor.locator('.wd-root')).to_have_attribute('data-widget-design','glassmorphism')
 panel=editor.locator('.wd-panel');assert panel.evaluate('e=>getComputedStyle(e).backdropFilter')!='none'
 page.emulate_media(contrast='more');assert panel.evaluate('e=>getComputedStyle(e).backdropFilter')=='none'
 page.screenshot(path=str(ART/'glass-high-contrast.png'));page.keyboard.press('Escape')
 assert not errors,errors
 results={'selected_conversation':'passed','read_position_and_document_scroll':'passed','focus_ring':'passed','notification_ordering':'passed','mobile_touch_targets_and_overflow':'passed','high_contrast_material':'passed','reduced_motion_dialog':'passed','glass_contrast_fallback':'passed','page_errors':errors}
 (ART/'results.json').write_text(json.dumps(results,indent=2)+'\n');print(json.dumps(results));browser.close()

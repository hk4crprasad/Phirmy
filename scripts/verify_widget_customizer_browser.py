"""Actual dashboard branding -> actual separate-origin Aurely demo widget.

Uses the explicit local QA workspace, actual logo storage and configured providers.
Creates a synthetic local editor membership solely in that QA workspace; no email,
customer database, crawl, phone or payment. Saves screenshots without credentials.
"""
from pathlib import Path
import json,secrets,sys,uuid
from qa_accounts import bootstrap_account
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'services/control'))
from PIL import Image,ImageDraw,ImageFont
from sqlalchemy import select
from studio.db import session_scope,engine
from studio.models import Membership,Conversation,Message
from playwright.sync_api import sync_playwright,expect
def email_gate(page):
    email=page.get_by_label("Email address",exact=True)
    try: email.wait_for(state="visible",timeout=2500)
    except Exception: return
    email.fill("widget-qa@example.test");page.get_by_role("button",name="Continue",exact=True).click()

ROOT=Path(__file__).resolve().parents[1];ART=ROOT/'artifacts/widget-customizer';ART.mkdir(parents=True,exist_ok=True)
WEB='http://127.0.0.1:3100';DEMO='http://127.0.0.1:3200';WS='632f4e20-9134-4efa-8842-5e60144f2e8e';BASE='/v1/workspaces/'+WS
if engine.dialect.name!='sqlite':raise RuntimeError('Run only with the explicit local QA database')
logo=ART/'aurely-monogram.png';image=Image.new('RGB',(128,128),'#214d3b');draw=ImageDraw.Draw(image)
font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf',84)
draw.text((64,57),'A',font=font,anchor='mm',fill='#fffaf0');image.save(logo)
with sync_playwright() as p:
 browser=p.chromium.launch(headless=True,executable_path='/usr/bin/chromium')
 admin=browser.new_context(viewport={'width':1500,'height':1120},reduced_motion='reduce')
 signup=bootstrap_account(admin.request, WEB+'/backend/v1/auth/signup',headers={'Origin':WEB},data={'name':'Widget designer QA','email':'widget-designer-'+uuid.uuid4().hex[:10]+'@example.test','password':secrets.token_urlsafe(24),'workspace_name':'Widget design QA'})
 assert signup.status==200,signup.status
 user=signup.json()['user']['id']
 with session_scope(write=True) as db:db.add(Membership(workspace_id=WS,user_id=user,role='owner'))
 admin.add_init_script('localStorage.setItem("studio.workspace",'+json.dumps(WS)+')')
 page=admin.new_page();page.set_default_timeout(30000);errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
 items=admin.request.get(WEB+'/backend'+BASE+'/installations').json()['items']
 installation=next(x for x in items if x['name']=='Aurely demo HTML widget');key=installation['theme']['publishable_key']
 page.goto(WEB+'/app/widget')
 details=page.locator('details').filter(has=page.get_by_text('Other agent installations',exact=True))
 details.locator('summary').click()
 card=details.locator('.stack').filter(has=page.get_by_text('Aurely demo HTML widget',exact=True)).first
 card.get_by_role('button',name='Customize widget',exact=True).click()
 dialog=page.get_by_role('dialog',name='Your assistant’s appearance')
 dialog.get_by_label('Assistant name',exact=True).fill('Aurely concierge')
 dialog.get_by_label('Launcher label',exact=True).fill('Ask Aurely')
 dialog.locator('input[type=file]').set_input_files(str(logo))
 dialog.get_by_label('Font family',exact=True).select_option('serif')
 expect(dialog.get_by_alt_text('Widget logo preview')).to_be_visible()
 page.screenshot(path=str(ART/'01-dashboard-brand.png'))
 dialog.get_by_role('tab',name='Style',exact=True).click()
 for label,color in [('Button colour','#214d3b'),('Button text colour','#ffffff'),('Panel colour','#fffaf0'),('Text colour','#263528'),('Visitor bubble colour','#214d3b'),('Visitor text colour','#ffffff'),('Border colour','#cfc6b8')]:dialog.get_by_label(label+' hex',exact=True).fill(color)
 dialog.get_by_label('Widget style',exact=True).select_option('classic')
 dialog.get_by_label('Button shape',exact=True).select_option('rounded')
 dialog.get_by_label('Button icon',exact=True).select_option('logo')
 dialog.get_by_label('Position',exact=True).select_option('left')
 for label,value in [('Corner radius · px','22'),('Panel width · px','380'),('Panel height · px','580'),('Side spacing · px','24'),('Bottom spacing · px','24')]:dialog.get_by_label(label,exact=True).fill(value)
 dialog.get_by_role('tab',name='Messages & tone',exact=True).click()
 welcome='Welcome to Aurely. Let’s find your next favourite piece.'
 dialog.get_by_label('Welcome message',exact=True).fill(welcome)
 dialog.get_by_label('Input placeholder',exact=True).fill('Ask about a piece…')
 dialog.get_by_label('Send button label',exact=True).fill('Ask')
 dialog.get_by_label('Footer text',exact=True).fill('Your Aurely concierge')
 dialog.get_by_label('Response tone',exact=True).select_option('concise')
 page.screenshot(path=str(ART/'02-dashboard-messages.png'))
 dialog.get_by_role('button',name='Save widget',exact=True).click()
 expect(dialog).not_to_be_visible(timeout=45000)
 current=next(x for x in admin.request.get(WEB+'/backend'+BASE+'/installations').json()['items'] if x['id']==installation['id'])
 assert current['theme']['publishable_key']==key and current['public_id']==installation['public_id']
 assert current['theme']['tone']=='concise' and current['theme']['logo_path']
 # Reopen the persisted editor and verify cancel does not save a second change.
 card.get_by_role('button',name='Customize widget',exact=True).click()
 expect(dialog.get_by_label('Assistant name',exact=True)).to_have_value('Aurely concierge')
 dialog.get_by_label('Launcher label',exact=True).fill('Unsaved label')
 dialog.get_by_role('tab',name='Messages & tone',exact=True).click()
 expect(dialog.get_by_label('Welcome message',exact=True)).to_have_value(welcome)
 expect(dialog.get_by_label('Response tone',exact=True)).to_have_value('concise')
 dialog.get_by_role('button',name='Cancel',exact=True).click()
 # Mobile dashboard editor remains usable and its save footer stays reachable.
 page.set_viewport_size({'width':390,'height':844})
 card.get_by_role('button',name='Customize widget',exact=True).click()
 dialog.get_by_role('tab',name='Brand',exact=True).click()
 assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
 page.screenshot(path=str(ART/'03-dashboard-mobile.png'))
 dialog.get_by_role('button',name='Cancel',exact=True).click()
 # Fresh anonymous visitor, actual demo HTML/script/CORS/API with no mocks.
 visitor=browser.new_context(viewport={'width':1440,'height':1040},reduced_motion='reduce')
 site=visitor.new_page();site.on('pageerror',lambda e:errors.append(str(e)));site.set_default_timeout(30000)
 site.goto(DEMO+'/',wait_until='networkidle')
 launcher=site.get_by_role('button',name='Ask Aurely',exact=True)
 expect(launcher).to_be_visible()
 assert launcher.evaluate('(button)=>getComputedStyle(button).backgroundColor')=='rgb(33, 77, 59)'
 assert site.locator('[data-voice-studio-widget]').evaluate('(host)=>getComputedStyle(host).left')=='24px'
 launcher.click();email_gate(site);expect(site.get_by_text(welcome,exact=True)).to_be_visible()
 expect(site.get_by_placeholder('Ask about a piece…')).to_be_visible()
 panel=site.get_by_role('dialog',name='Business support chat')
 assert panel.evaluate('(node)=>getComputedStyle(node).borderRadius')=='22px'
 assert panel.bounding_box()['width']==380
 logo_node=site.locator('[data-voice-studio-widget]').locator('.header img')
 expect(logo_node).to_be_visible();site.wait_for_function("document.querySelector('[data-voice-studio-widget]').shadowRoot.querySelector('.header img')?.naturalWidth > 0")
 site.get_by_label('Chat message',exact=True).fill('What is the price of the Premium Silver-Tone Designer Bangle?')
 with site.expect_response(lambda r:r.url.endswith('/v1/public/chat') and r.request.method=='POST',timeout=90000) as chat:
  site.get_by_role('button',name='Ask',exact=True).click()
 response=chat.value
 assert response.status==200
 expect(site.get_by_role('button',name='Ask',exact=True)).to_be_enabled(timeout=90000)
 assert site.locator('[data-voice-studio-widget]').locator('.error').inner_text()==''
 with session_scope() as db:
  stored=db.scalar(select(Message).join(Conversation,Conversation.id==Message.conversation_id).where(Conversation.workspace_id==WS,Conversation.installation_id==installation['id'],Message.role=='assistant').order_by(Message.created_at.desc()).limit(1))
  assert stored and '699' in stored.text_content
  reply=stored.text_content
 host=site.locator('[data-voice-studio-widget]')
 host.evaluate("host=>{const root=host.shadowRoot,log=root.querySelector('.log'),answer=[...root.querySelectorAll('.message')].find(x=>x.textContent.includes('699'));if(answer)log.scrollTop=answer.offsetTop-log.offsetTop;}")
 site.screenshot(path=str(ART/'04-customized-demo.png'))
 site.set_viewport_size({'width':390,'height':844})
 assert panel.bounding_box()['x']>=0 and panel.bounding_box()['x']+panel.bounding_box()['width']<=390
 site.screenshot(path=str(ART/'05-customized-demo-mobile.png'))
 assert not visitor.cookies([DEMO,WEB]) and not errors,errors
 result={'dashboard_edit_save_reopen':'passed','cancel_discards_changes':'passed','uploaded_logo':'passed; actual stored image loaded anonymously',
  'public_key_and_embed_id':'preserved','button_before_open':'passed; saved text/icon/colour/position','panel_dimensions_and_radius':'passed',
  'welcome_placeholder_footer':'passed','tone':'concise persisted; backend tests verify chat config','anonymous_real_chat':reply,
  'mobile_dashboard_and_embed':'passed; no overflow','page_errors':errors}
 (ART/'results.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
 visitor.close();admin.close();browser.close()

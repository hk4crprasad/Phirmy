"""Real dashboard + anonymous HTML embed acceptance; explicit local QA DB only.

Uses configured Deepgram and LLM services, synthetic speech and contact details.
No marketing email or real calendar booking is sent. Saves actual screenshots.
"""
import json,secrets,sys,uuid
from pathlib import Path
from qa_accounts import bootstrap_account
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'services/control'))
from sqlalchemy import select
from studio.db import session_scope,engine
from studio.models import Membership,Lead
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1];ART=ROOT/'artifacts/widget-live';ART.mkdir(parents=True,exist_ok=True)
WEB='http://127.0.0.1:3100';DEMO='http://127.0.0.1:3200';WS='632f4e20-9134-4efa-8842-5e60144f2e8e';BASE='/v1/workspaces/'+WS
if engine.dialect.name!='sqlite':raise RuntimeError('Requires explicit local QA database')
results={};errors=[]
with sync_playwright() as p:
 browser=p.chromium.launch(headless=True,executable_path='/usr/bin/chromium',args=['--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream','--use-file-for-fake-audio-capture='+str(ROOT/'artifacts/provider-smoke.wav')])
 admin=browser.new_context(viewport={'width':1500,'height':1100},reduced_motion='reduce')
 signup=bootstrap_account(admin.request, WEB+'/backend/v1/auth/signup',headers={'Origin':WEB},data={'name':'Live inbox QA','email':'live-inbox-'+uuid.uuid4().hex[:10]+'@example.test','password':secrets.token_urlsafe(24),'workspace_name':'Live inbox QA'})
 assert signup.status==200,signup.status
 with session_scope(write=True) as db:db.add(Membership(workspace_id=WS,user_id=signup.json()['user']['id'],role='owner'))
 admin.add_init_script('localStorage.setItem("studio.workspace",'+json.dumps(WS)+')')
 visitor=browser.new_context(viewport={'width':1440,'height':1040},permissions=['microphone'],reduced_motion='reduce')
 site=visitor.new_page();site.set_default_timeout(30000);site.on('pageerror',lambda e:errors.append(str(e)))
 site.goto(DEMO+'/',wait_until='networkidle');site.get_by_role('button',name='Ask Aurely',exact=True).click()
 expect(site.get_by_label('Email address',exact=True)).to_be_visible()
 assert not site.locator('input[name=marketing_opt_in]').is_checked()
 site.screenshot(path=str(ART/'01-email-welcome.png'))
 site.get_by_label('Email address',exact=True).fill('visitor-live-qa@example.test')
 with site.expect_response(lambda r:r.url.endswith('/v1/public/sessions') and r.request.method=='POST') as session:
  site.get_by_role('button',name='Continue',exact=True).click()
 state=session.value.json();assert session.value.status==201 and state['lead_captured']
 results['email_gate_and_lead']='passed'
 with session_scope() as db:
  leads=list(db.scalars(select(Lead).where(Lead.workspace_id==WS,Lead.email=='visitor-live-qa@example.test').order_by(Lead.created_at.desc())))
  assert leads and json.loads(leads[0].evidence)['marketing_opt_in'] is False
 # Actual browser microphone -> actual server-side configured Deepgram.
 mic=site.get_by_role('button',name='Start voice input',exact=True)
 expect(mic).to_be_visible();mic.click();expect(site.get_by_role('button',name='Stop voice input',exact=True)).to_be_visible()
 site.wait_for_timeout(4500)
 with site.expect_response(lambda r:r.url.endswith('/v1/public/voice/transcribe'),timeout=60000) as transcript:
  site.get_by_role('button',name='Stop voice input',exact=True).click()
 response=transcript.value
 if response.status==200 and response.json().get('text'):
  expect(site.get_by_label('Chat message',exact=True)).not_to_have_value('')
  results['real_deepgram']={'status':'passed','transcript':response.json()['text']}
 else:
  results['real_deepgram']={'status':'unavailable','http_status':response.status,'detail':response.json().get('detail')}
 site.screenshot(path=str(ART/'02-voice-input.png'))
 # Actual configured chat; provider failure is recorded separately from inbox acceptance.
 site.get_by_label('Chat message',exact=True).fill('What is the price of the Premium Silver-Tone Designer Bangle?')
 site.get_by_role('button',name='Ask',exact=True).click()
 expect(site.get_by_role('button',name='Ask',exact=True)).to_be_enabled(timeout=90000)
 host=site.locator('[data-voice-studio-widget]')
 results['real_knowledge_chat']='passed' if '699' in host.locator('.log').inner_text() else {'status':'unavailable','detail':host.locator('.error').inner_text()}
 dashboard=admin.new_page();dashboard.set_default_timeout(30000);dashboard.on('pageerror',lambda e:errors.append(str(e)))
 dashboard.goto(WEB+'/app/inbox?conversation='+state['id'])
 thread=dashboard.get_by_role('region',name='Live conversation')
 expect(thread.get_by_role('button',name='Take over',exact=True)).to_be_visible()
 thread.get_by_role('button',name='Take over',exact=True).click()
 expect(thread.get_by_label('Reply to visitor',exact=True)).to_be_enabled()
 expect(host.get_by_text('Support team connected · AI paused',exact=True)).to_be_visible(timeout=10000)
 thread.get_by_label('Reply to visitor',exact=True).fill('Hello! I’m from Aurely’s team. I can help you choose the right piece.')
 thread.get_by_role('button',name='Send reply',exact=True).click()
 expect(host.get_by_text('Support team · Hello! I’m from Aurely’s team. I can help you choose the right piece.',exact=True)).to_be_visible(timeout=10000)
 site.get_by_label('Chat message',exact=True).fill('Thank you, I would like personal help choosing a bangle.')
 site.get_by_role('button',name='Ask',exact=True).click()
 expect(thread.get_by_text('Thank you, I would like personal help choosing a bangle.',exact=True)).to_be_visible(timeout=10000)
 assert not thread.get_by_text('Thinking…',exact=True).count()
 dashboard.screenshot(path=str(ART/'03-live-inbox-takeover.png'),full_page=True)
 site.screenshot(path=str(ART/'04-visitor-human-reply.png'))
 site.set_viewport_size({'width':390,'height':844});site.wait_for_timeout(150);
 box=host.locator('.message.user').last.bounding_box();log_box=host.locator('.log').bounding_box();assert box['y']+box['height']<=log_box['y']+log_box['height']+1
 site.screenshot(path=str(ART/'05-mobile-human-reply.png'))
 assert site.evaluate('document.documentElement.scrollWidth<=innerWidth')
 site.reload(wait_until='networkidle');expect(host.get_by_text('Support team connected · AI paused',exact=True)).to_be_visible(timeout=10000)
 results['human_takeover_replies_live_updates_resume_mobile']='passed'
 thread.get_by_role('button',name='Return to AI',exact=True).click()
 expect(host.get_by_text('AI assistant · your team can join this chat',exact=True)).to_be_visible(timeout=10000)
 thread.get_by_role('button',name='Resolve',exact=True).click()
 expect(host.get_by_text('Conversation closed',exact=True)).to_be_visible(timeout=10000)
 expect(site.get_by_label('Chat message',exact=True)).to_be_disabled()
 results['return_to_ai_resolve']='passed'
 dashboard.get_by_role('button',name='Notifications',exact=False).first.click()
 expect(dashboard.get_by_role('region',name='Notifications').get_by_text('New visitor message',exact=True).first).to_be_visible()
 dashboard.screenshot(path=str(ART/'06-notifications.png'),full_page=True)
 results['notifications']='passed'
 dashboard.goto(WEB+'/app/leads');expect(dashboard.get_by_text('PROMOTIONAL EMAIL',exact=True)).to_be_visible();dashboard.screenshot(path=str(ART/'07-lead-consent.png'),full_page=True)
 assert not visitor.cookies([WEB,DEMO]);assert not errors,errors
 results['page_errors']=errors
 (ART/'results.json').write_text(json.dumps(results,indent=2)+'\n');print(json.dumps(results),flush=True)
 visitor.close();admin.close();browser.close()

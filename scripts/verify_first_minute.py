"""Real first-use timing and responsive acceptance; starts with no account/cookies."""
from pathlib import Path
import json,time,uuid,os
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1];ART=ROOT/'artifacts';ART.mkdir(exist_ok=True)
with sync_playwright() as p:
 browser=p.chromium.launch(headless=True)
 page=browser.new_page(viewport={'width':1440,'height':900})
 errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
 page.goto('http://127.0.0.1:3100');page.wait_for_load_state('networkidle')
 expect(page.get_by_role('heading',name='Your website. Answering customers.')).to_be_visible()
 assert page.locator('main').get_by_role('button').count()==1
 assert page.get_by_role('button',name='Try my website').bounding_box()['y']<800
 page.screenshot(path=str(ART/'hero-desktop.png'),full_page=True)
 page.set_viewport_size({'width':390,'height':844})
 assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
 assert page.get_by_role('button',name='Try my website').bounding_box()['y']<750
 page.screenshot(path=str(ART/'hero-mobile.png'),full_page=True)
 page.set_viewport_size({'width':1440,'height':900})
 page.get_by_label('Your website',exact=True).fill(os.environ.get('FIRST_MINUTE_WEBSITE','https://palsona.in'))
 started=time.monotonic();page.get_by_role('button',name='Try my website').click()
 expect(page.get_by_text('Your website, understood.',exact=True)).to_be_visible(timeout=35000)
 elapsed=time.monotonic()-started
 assert elapsed<60,elapsed
 expect(page.get_by_role('link',name='Read the source')).to_be_visible()
 assert '/signin' not in page.url
 assert not any(c['name']=='studio_session' for c in page.context.cookies())
 page.screenshot(path=str(ART/'first-answer-desktop.png'),full_page=True)
 page.get_by_label('Ask your assistant').fill('What can I buy?')
 page.get_by_role('button',name='Send question').click()
 expect(page.get_by_role('link',name='Read the source')).to_have_count(2,timeout=15000)
 for question,reply,label in [
  ('hi','Hi! What would you like to know about this business?','Assistant'),
  ('Thank you!',"You're welcome!",'Assistant'),
  ('Explain quantum teleportation',"I couldn't verify that",'Not found on this page'),
 ]:
  page.get_by_label('Ask your assistant').fill(question)
  page.get_by_role('button',name='Send question').click()
  last=page.locator('.fm-message.assistant').last
  expect(last).to_contain_text(reply,timeout=15000)
  expect(last.locator('.fm-message-label')).to_have_text(label)
  assert last.locator('a').count()==0
  expect(page.get_by_role('link',name='Read the source')).to_have_count(2)
  page.wait_for_function("(()=>{const e=document.querySelector('.fm-messages');return e.scrollHeight-e.clientHeight-e.scrollTop<2})()")
 page.set_viewport_size({'width':390,'height':844})
 assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
 page.screenshot(path=str(ART/'first-answer-mobile.png'),full_page=True)
 page.get_by_role('link',name='Keep my assistant').click()
 expect(page.get_by_role('heading',name='Your assistant is ready to keep.')).to_be_visible()
 assert not errors,errors
 result={'website':os.environ.get('FIRST_MINUTE_WEBSITE','https://palsona.in'),'first_result_seconds':round(elapsed,2),'no_signup_before_value':'passed','single_primary_button':'passed','source_citation':'passed','followup_question':'passed','greeting_and_thanks':'passed without false source citations','missing_evidence':'correct label, no citation','latest_reply_scroll':'passed','mobile_overflow':'none','keep_handoff':'passed','page_errors':errors}
 (ART/'first-minute-results.json').write_text(json.dumps(result,indent=2))
 print(json.dumps(result));browser.close()

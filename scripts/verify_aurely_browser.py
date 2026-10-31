"""Live Aurely acceptance through the actual app UI and configured providers.

Requires local API/web plus Redis/Qdrant. Retains a named synthetic QA workspace,
actual site knowledge and ignored screenshots/results. No phone/email/payment
or source-site mutation. Crawling and model/embedding requests may incur credits.
"""
from pathlib import Path
import json,os,secrets,time,uuid
import httpx
from playwright.sync_api import sync_playwright,expect
from qa_accounts import bootstrap_account
WEB='http://127.0.0.1:3100'; SITE='https://aurelyjewellers.in/'
ART=Path('artifacts/aurely-app');ART.mkdir(exist_ok=True)
with sync_playwright() as p:
 browser=p.chromium.launch(headless=True,executable_path='/usr/bin/chromium')
 context=browser.new_context(viewport={'width':1440,'height':1100},reduced_motion='reduce')
 page=context.new_page();page.set_default_timeout(30000)
 errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
 account=bootstrap_account(context.request, WEB+'/backend/v1/auth/signup',headers={'Origin':WEB},data={'name':'Aurely crawl test','email':'aurely-'+uuid.uuid4().hex[:10]+'@example.test','password':secrets.token_urlsafe(24),'workspace_name':'Aurely Jewellers crawl test'})
 assert account.status==200,account.status
 ws=account.json()['workspaces'][0]['id'];base=WEB+'/backend/v1/workspaces/'+ws
 csrf=next(c['value'] for c in context.cookies() if c['name']=='studio_csrf')
 headers={'Origin':WEB,'X-CSRF-Token':csrf}
 page.goto(WEB+'/app/widget')
 page.get_by_label('Assistant website URL').fill(SITE)
 with page.expect_response(lambda r:r.url==base+'/website-assistants' and r.request.method=='POST') as created:
  page.get_by_role('button',name='Create website assistant',exact=True).click()
 response=created.value
 assert response.status==202, response.status
 row=response.json();job_id=row['job']['id']
 expect(page.get_by_role('button',name='Stop crawl',exact=True)).to_be_visible()
 page.screenshot(path=str(ART/'01-crawling.png'),full_page=True)
 print(json.dumps({'state':'started','workspace_id':ws,'website_id':row['id'],'job_id':job_id,'screenshot':str(ART/'01-crawling.png')}),flush=True)
 started=time.monotonic();last=None
 while time.monotonic()-started<300:
  status=context.request.get(base+'/jobs/'+job_id).json()
  progress=(status['state'],status['phase'],status['completed_items'])
  if progress!=last:
   print(json.dumps({'state':progress[0],'phase':progress[1],'pages':progress[2],'elapsed_seconds':round(time.monotonic()-started)}),flush=True);last=progress
  if status['state'] in ['completed','failed','canceled']:break
  page.wait_for_timeout(1500)
 else: raise RuntimeError('Crawl did not complete within 300 seconds; left running for inspection')
 rows=context.request.get(base+'/website-assistants').json()['items'];row=next(x for x in rows if x['id']==row['id'])
 products=context.request.get(base+'/products').json()['items']
 pages=context.request.get(base+'/website-assistants/'+row['id']+'/pages').json()['items']
 result={'website':SITE,'workspace_id':ws,'website_id':row['id'],'job':status,'knowledge':row['knowledge'],'products':products,'pages':pages,'page_errors':errors,'elapsed_seconds':round(time.monotonic()-started,2),'crawler':'actual app crawler; live site; no network mocks; no Firecrawl import'}
 (ART/'results.json').write_text(json.dumps(result,indent=2)+'\n')
 page.wait_for_timeout(4500)
 page.screenshot(path=str(ART/'02-crawl-result.png'),full_page=True)
 if status['state']=='completed':
  page.get_by_role('button',name='Indexed pages',exact=True).click()
  expect(page.locator('.website-page').first).to_be_visible()
  page.screenshot(path=str(ART/'03-indexed-pages.png'),full_page=True)
  query=context.request.post(base+'/knowledge/'+row['kb_id']+'/query',headers=headers,data={'query':'What is the price of the Premium Silver Tone Designer Bangle and what material is it made of?','limit':4})
  result['knowledge_query']={'status':query.status,'result':query.json()}
  (ART/'results.json').write_text(json.dumps(result,indent=2)+'\n')
  page.get_by_role('button',name='Test agent',exact=True).click()
  page.get_by_label('Chat message',exact=True).fill('What is the price of the Premium Silver Tone Designer Bangle and what material is it made of?')
  with page.expect_response(lambda r:r.url.endswith('/v1/public/chat') and r.request.method=='POST',timeout=90000) as chat_response:
   page.get_by_role('button',name='Send chat message',exact=True).click()
  response=chat_response.value
  events=[json.loads(x.split('data: ',1)[1]) for x in response.text().split('\n\n') if x.startswith('event: chat.completed')]
  result['agent_test']={'status':response.status,'completed':events}
  page.wait_for_timeout(1000)
  page.screenshot(path=str(ART/'04-grounded-answer.png'),full_page=True)
  (ART/'results.json').write_text(json.dumps(result,indent=2)+'\n')
 print(json.dumps({'state':status['state'],'pages':row['knowledge']['pages_indexed'],'chunks':row['knowledge']['chunks_indexed'],'products':len(products),'errors':errors,'result_file':str(ART/'results.json')}),flush=True)
 context.close()
 browser.close()

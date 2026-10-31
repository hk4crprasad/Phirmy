"""Test the actual cross-origin HTML embed with real Aurely knowledge/providers.

Requires the local API/web and demo static server. No request/response mocks.
Saves screenshots and public chat evidence, never cookies or resume tokens.
"""
import json
import os
from pathlib import Path
from urllib.parse import urlsplit,unquote
import httpx
from playwright.sync_api import sync_playwright,expect
def email_gate(page):
    email=page.get_by_label("Email address",exact=True)
    try: email.wait_for(state="visible",timeout=2500)
    except Exception: return
    email.fill("widget-qa@example.test");page.get_by_role("button",name="Continue",exact=True).click()

ROOT=Path(__file__).resolve().parents[1]
DEMO=ROOT/'examples/aurely-widget-demo'
ART=ROOT/'artifacts/aurely-widget-demo';ART.mkdir(parents=True,exist_ok=True)
config=json.loads((DEMO/'widget-config.json').read_text())
origin=config['demo_origin'];app=config['app_origin'];public_id=config['installation_public_id'];key=config['public_key']
question='What is the price of the Premium Silver-Tone Designer Bangle, and is it solid silver?'
product_url='https://aurelyjewellers.in/product/premium-silver-tone-designer-bangle-for-women'

with httpx.Client(trust_env=False,timeout=15) as metadata_client:
    metadata=metadata_client.post(app+'/backend/v1/public/installations/'+public_id,params={'public_key':key},headers={'Origin':origin})
    metadata.raise_for_status();theme=metadata.json()['theme']
launcher_label=theme.get('launcher_label') or 'Let’s talk'
send_label=theme.get('send_button_label') or 'Send'
welcome=theme.get('welcome_message') or 'Hello!'

with sync_playwright() as p:
    launch={'headless':True,'executable_path':'/usr/bin/chromium'}
    proxy_url=os.environ.get('HTTPS_PROXY') or os.environ.get('https_proxy')
    if proxy_url:
        parsed=urlsplit(proxy_url)
        proxy={'server':parsed.scheme+'://'+parsed.hostname+(':'+str(parsed.port) if parsed.port else ''),'bypass':'127.0.0.1,localhost'}
        if parsed.username:proxy.update(username=unquote(parsed.username),password=unquote(parsed.password or ''))
        launch['proxy']=proxy
    browser=p.chromium.launch(**launch)
    context=browser.new_context(viewport={'width':1440,'height':1040},reduced_motion='reduce')
    page=context.new_page();page.set_default_timeout(30000)
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    public_requests=[]
    navigation_requests=[]
    remote_failures=[]
    context.on('request',lambda request:navigation_requests.append(request.url) if request.is_navigation_request() else None)
    context.on('requestfailed',lambda request:remote_failures.append({'url':request.url.split('?')[0],'failure':request.failure}) if request.url.startswith('https://aurelyjewellers.in/') else None)
    def observe(request):
        if '/v1/public/' in request.url:public_requests.append({'method':request.method,'path':urlsplit(request.url).path})
    page.on('request',observe)
    page.goto(origin+'/',wait_until='networkidle')
    expect(page.get_by_role('heading',name='Small details. Lasting impressions.')).to_be_visible()
    page.screenshot(path=str(ART/'01-demo-page.png'))
    page.get_by_role('button',name=launcher_label,exact=True).click()
    email_gate(page)
    expect(page.get_by_role('button',name=launcher_label,exact=True)).to_be_visible()
    expect(page.get_by_text(welcome,exact=False)).to_be_visible()
    expect(page.get_by_label('Chat message',exact=True)).to_be_enabled()
    page.get_by_label('Chat message',exact=True).fill(question)
    with page.expect_response(lambda r:r.url.endswith('/v1/public/chat') and r.request.method=='POST',timeout=90000) as response_info:
        page.get_by_role('button',name=send_label,exact=True).click()
    response=response_info.value
    events=[json.loads(x.split('data: ',1)[1]) for x in response.text().split('\n\n') if x.startswith('event: chat.completed')]
    assert response.status==200 and events,'Chat did not complete'
    answer=events[-1]
    assert '699' in answer['text'] and ('imitation' in answer['text'].lower() or 'not solid' in answer['text'].lower()),answer['text']
    assert any(p['canonical_url']==product_url for p in answer.get('products',[]))
    assert answer.get('citations'), 'Expected source evidence'
    widget=page.locator('[data-voice-studio-widget]')
    widget.evaluate("host => {const root=host.shadowRoot, log=root.querySelector('.log'), answer=[...root.querySelectorAll('.message')].find(x=>x.textContent.includes('699'));if(answer)log.scrollTop=answer.offsetTop-log.offsetTop;}")
    page.wait_for_timeout(1200)
    assert widget.locator('img').evaluate_all('(images)=>images.every(img=>!img.complete||img.naturalWidth>0)'), 'Broken product image remained visible'
    page.screenshot(path=str(ART/'02-desktop-answer.png'))
    assert not context.cookies([app,origin]), 'Visitor received dashboard/demo cookies'
    # The real product card requests its source URL in another tab. Record TLS failures separately.
    link=widget.locator('a.product').filter(has=page.get_by_text('Premium Silver-Tone Designer Bangle for Women',exact=True)).first
    expect(link).to_have_attribute('href',product_url)
    expect(link).to_have_attribute('target','_blank')
    with page.expect_popup() as popup_info:link.click()
    popup=popup_info.value
    popup.wait_for_timeout(2000)
    assert product_url in navigation_requests, 'The product link did not request its source URL'
    source_page_loaded=popup.url==product_url and popup.locator('h1').count()>0
    if source_page_loaded:
        source_page_result='passed; source page opened'
    else:
        assert any(x['url']==product_url and x['failure']=='net::ERR_CERT_AUTHORITY_INVALID' for x in remote_failures), 'Unexpected source page loading failure'
        source_page_result='correct source URL requested in new tab; cloud browser TLS trust prevented loading'
    popup.close();page.bring_to_front()
    # Same-tab reload resumes the saved public conversation rather than creating one.
    creations_before=sum(x['path'].endswith('/public/sessions') for x in public_requests)
    page.reload(wait_until='networkidle')
    expect(page.get_by_role('dialog',name='Business support chat')).to_be_visible()
    expect(page.get_by_text(question,exact=True)).to_be_visible()
    expect(page.get_by_label('Chat message',exact=True)).to_be_enabled()
    assert any(x['path'].endswith('/public/sessions/resume') for x in public_requests)
    assert sum(x['path'].endswith('/public/sessions') for x in public_requests)==creations_before
    # Close/reopen works and mobile stays inside the viewport in both color modes.
    page.get_by_role('button',name='Close chat',exact=True).click()
    expect(page.get_by_role('dialog',name='Business support chat')).not_to_be_visible()
    page.get_by_role('button',name=launcher_label,exact=True).click()
    page.set_viewport_size({'width':390,'height':844})
    page.evaluate('window.scrollTo(0,0)')
    panel=page.get_by_role('dialog',name='Business support chat')
    box=panel.bounding_box();assert box and box['x']>=0 and box['x']+box['width']<=390
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    widget.evaluate("host=>{const root=host.shadowRoot,log=root.querySelector('.log'),answer=[...root.querySelectorAll('.message')].find(x=>x.textContent.includes('699'));if(answer)log.scrollTop=answer.offsetTop-log.offsetTop;}")
    page.screenshot(path=str(ART/'03-mobile-answer.png'))
    page.emulate_media(color_scheme='dark')
    page.screenshot(path=str(ART/'04-mobile-dark.png'))
    # Origin and key enforcement use the real public endpoint, not a browser mock.
    with httpx.Client(trust_env=False,timeout=15) as client:
        url=app+'/backend/v1/public/installations/'+public_id
        denied=client.post(url,params={'public_key':key},headers={'Origin':'http://127.0.0.1:3999'})
        wrong_key=client.post(url,params={'public_key':'invalid-key'},headers={'Origin':origin})
        assert denied.status_code==(403 if theme.get('restrict_origins') else 200) and wrong_key.status_code==403
    assert not errors,errors
    result={'demo_origin':origin,'app_origin':app,'public_id':public_id,'embed':'actual widget.js on a separate HTML origin',
        'chat':'passed; real configured LLM/Qdrant','question':question,'answer':answer['text'],
        'product_link':source_page_result,'source_citations':len(answer['citations']),
        'reload_resume':'passed; no duplicate session','close_reopen':'passed','mobile_light_dark':'passed; no horizontal overflow',
        'dashboard_cookies':'none','unlisted_origin_status':denied.status_code,'invalid_key_rejection':wrong_key.status_code,'page_errors':errors,'remote_browser_failures':remote_failures,'broken_image_fallback':'passed'}
    (ART/'results.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result),flush=True)
    context.close();browser.close()

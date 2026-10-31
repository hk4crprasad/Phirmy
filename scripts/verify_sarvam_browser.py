"""Focused UI check against an isolated development API; no provider requests."""
import json
import os
from pathlib import Path
import sys
import uuid
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from qa_accounts import bootstrap_account
origin=os.environ.get('BROWSER_TEST_ORIGIN','http://127.0.0.1:3100')
art=ROOT/'artifacts/sarvam';art.mkdir(exist_ok=True,parents=True)
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    context=browser.new_context(viewport={'width':1440,'height':1000},reduced_motion='reduce')
    assert context.request.get(origin+'/backend/healthz').status==200
    response=bootstrap_account(context.request,origin+'/backend/v1/auth/signup',data={
        'name':'Sarvam QA','email':'sarvam-'+uuid.uuid4().hex[:10]+'@example.test','password':'Local-Synthetic-Password-Only',
        'workspace_name':'Sarvam QA'})
    workspace=response.json()['workspaces'][0]['id']
    base=origin+'/backend/v1/workspaces/'+workspace
    csrf=next(c['value'] for c in context.cookies() if c['name']=='studio_csrf')
    fixture=context.request.post(base+'/fixtures',headers={'X-CSRF-Token':csrf})
    assert fixture.status==201
    agent=fixture.json()['agent_id']
    initial=context.request.get(base+'/agents/'+agent).json()['draft_config']
    page=context.new_page();page.set_default_timeout(20000)
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(origin+'/app/agents/'+agent);page.wait_for_load_state('networkidle')
    page.get_by_role('button',name='voice & behavior',exact=False).click()
    expect(page.get_by_text('Browser voice and phone calls use Sarvam',exact=False)).to_be_visible()
    expect(page.get_by_role('combobox',name='Speech model',exact=True)).to_have_value('bulbul:v4-flash')
    expect(page.get_by_role('combobox',name='Recognition language',exact=True)).to_have_value('auto')
    page.get_by_role('combobox',name='Spoken language',exact=True).select_option('hi-IN')
    page.get_by_role('textbox',name='Sarvam speaker',exact=False).fill('simran_enhi_customer')
    page.get_by_role('button',name='Save draft',exact=True).click()
    expect(page.get_by_text('Draft saved',exact=True)).to_be_visible()
    saved=context.request.get(base+'/agents/'+agent).json()['draft_config']
    assert saved['llm']==initial['llm']
    assert saved['speech']['language_code']=='hi-IN' and saved['speech']['live_stt_model']=='saaras:v4'
    page.get_by_role('combobox',name='Spoken language',exact=True).select_option('auto')
    page.get_by_role('button',name='Save draft',exact=True).click()
    expect(page.get_by_text('Draft saved',exact=True)).to_be_visible()
    saved=context.request.get(base+'/agents/'+agent).json()['draft_config']
    assert saved['speech']['language_code']=='auto' and saved['llm']==initial['llm']
    page.screenshot(path=str(art/'voice-editor-desktop.png'),full_page=True)
    page.set_viewport_size({'width':390,'height':844})
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
    page.screenshot(path=str(art/'voice-editor-mobile.png'),full_page=True)
    page.goto(origin+'/app/voice');page.wait_for_load_state('networkidle')
    expect(page.get_by_role('option',name='Live microphone · Sarvam')).to_have_count(1)
    assert not errors,errors
    (art/'browser.json').write_text(json.dumps({'desktop':True,'mobile':True,'saved_sarvam_speech':True,'text_model_preserved':True,'page_errors':errors},indent=2))
    browser.close()
print('Sarvam editor desktop/mobile, save, voice label and GPT preservation passed.')

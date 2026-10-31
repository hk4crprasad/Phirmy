"""Cross-origin microphone lifecycle QA. Synthetic device/API; no provider calls.

Run with isolated dev API :8100 and production web :3100. Does not send email.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from pathlib import Path
import json
import uuid
import httpx
from playwright.sync_api import sync_playwright, expect
from qa_accounts import bootstrap_account

ROOT = Path(__file__).resolve().parents[1]
WEB, API, HOST = 'http://127.0.0.1:3100', 'http://127.0.0.1:8100', 'http://127.0.0.1:3201'
PROBE = """(() => {
  const real = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
  window.micProbe = {calls:0, tracks:[], mode:'real'};
  navigator.mediaDevices.getUserMedia = async (...args) => {
    const p=window.micProbe; p.calls++;
    if(p.mode==='denied') throw new DOMException('Synthetic denial','NotAllowedError');
    if(p.mode==='missing') throw new DOMException('Synthetic missing device','NotFoundError');
    if(p.mode==='pending') await new Promise(resolve=>p.resolve=resolve);
    try { const stream=await real(...args); p.tracks.push(...stream.getTracks()); return stream; } catch(e) { p.failure=e.name; throw e; }
  };
})();"""

def main():
    with httpx.Client(base_url=API, timeout=30) as client:
        assert client.get('/healthz').status_code==200
        signup=bootstrap_account(client,'/v1/auth/signup',json={'name':'Microphone QA','email':f'mic-{uuid.uuid4().hex[:10]}@example.test','password':uuid.uuid4().hex,'workspace_name':'Microphone QA'})
        ws=signup.json()['workspaces'][0]['id']
        client.headers['X-CSRF-Token']=client.cookies['studio_csrf']
        base='/v1/workspaces/'+ws
        fixture=client.post(base+'/fixtures').json()
        installation=client.get(base+'/installations').json()['items'][0]
        result=client.put(base+'/installations/'+installation['id'],json={'agent_id':fixture['agent_id'],'name':'Mic QA','allowed_origins':[HOST],'theme':{'preset':'minimal','voice_enabled':True}})
        assert result.status_code==200, result.status_code
        proof=client.post(base+'/origins',json={'origin':HOST})
        assert proof.status_code==201
        verified=client.post(base+'/origins/'+proof.json()['id']+'/verify',json={'method':'dns'})
        assert verified.status_code==200, 'Use scripts/run_sarvam_browser_qa.py with its isolated loopback proof boundary'
        public_id=installation['public_id']
        class Host(BaseHTTPRequestHandler):
            def do_GET(self):
                body=f"<!doctype html><html><head><meta name='viewport' content='width=device-width, initial-scale=1'></head><body><h1>Independent website</h1><script defer src='{WEB}/widget.js' data-installation='{public_id}'></script></body></html>".encode()
                self.send_response(200)
                self.send_header('Content-Type','text/html')
                if self.path=='/blocked': self.send_header('Permissions-Policy','microphone=()')
                self.end_headers(); self.wfile.write(body)
            def log_message(self,*args): pass
        server=ThreadingHTTPServer(('127.0.0.1',3201),Host)
        Thread(target=server.serve_forever,daemon=True).start()
        try:
            with sync_playwright() as p:
                browser=p.chromium.launch(executable_path=p.chromium.executable_path,headless=True,args=['--use-fake-device-for-media-stream'])
                context=browser.new_context(viewport={'width':390,'height':844})
                context.add_init_script(PROBE)
                def session(route):
                    response=route.fetch(); data=response.json()
                    data.update(voice_available=True,voice_input_available=True)
                    route.fulfill(response=response,json=data)
                context.route('**/v1/public/sessions',session)
                context.route('**/v1/public/voice/transcribe',lambda route:route.fulfill(json={'text':'Synthetic microphone transcript.'}))
                voice_requests=[]; pcm=[]
                def voice_session(route):
                    voice_requests.append(True)
                    route.fulfill(json={'call_id':'synthetic-call','session_token':'synthetic-session','media_url':'ws://127.0.0.1:8100/qa-media'})
                context.route('**/v1/public/voice/sessions',voice_session)
                context.route('**/v1/public/voice/sessions/*/stop',lambda route:route.fulfill(json={}))
                def socket(ws):
                    def receive(message):
                        if isinstance(message,bytes): pcm.append(len(message))
                        elif json.loads(message).get('type')=='client.start': ws.send(json.dumps({'type':'server.ready'}))
                    ws.on_message(receive)
                context.route_web_socket('**/qa-media',socket)
                page=context.new_page(); errors=[]
                page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(HOST)
                page.locator('[data-voice-studio-widget] .launcher').click()
                mic=page.get_by_role('button',name='Start voice input',exact=True)
                expect(mic).to_be_visible(timeout=30000)
                assert page.evaluate('micProbe.calls')==0
                assert page.evaluate("async()=> (await navigator.permissions.query({name:'microphone'})).state")=='prompt'
                page.evaluate("micProbe.mode='denied'")
                mic.click(); expect(page.get_by_text('Microphone access is blocked.',exact=False)).to_be_visible()
                page.evaluate("micProbe.mode='missing'")
                mic.click(); expect(page.get_by_text('No microphone was found.',exact=False)).to_be_visible()
                context.grant_permissions(['microphone'])
                page.evaluate("micProbe.mode='pending'")
                mic.click(); expect(mic).to_be_disabled()
                page.get_by_role('button',name='Close chat',exact=True).click()
                page.evaluate('micProbe.resolve()')
                page.wait_for_function("micProbe.tracks.length>0 && micProbe.tracks.every(t=>t.readyState==='ended')")
                page.locator('[data-voice-studio-widget] .launcher').click()
                page.evaluate("micProbe.mode='real'")
                mic.click(); expect(page.get_by_role('button',name='Stop voice input')).to_be_visible()
                page.get_by_role('button',name='Stop voice input').click()
                expect(page.get_by_label('Chat message')).to_have_value('Synthetic microphone transcript.')
                assert page.evaluate("micProbe.tracks.every(t=>t.readyState==='ended')")
                # Opening the delegated iframe must not itself capture audio.
                page.get_by_role('button',name='Talk to this agent',exact=True).click()
                frame=page.frame_locator('iframe[title="Voice assistant"]')
                start=frame.get_by_role('button',name='Start voice conversation',exact=True)
                expect(start).to_be_enabled(timeout=15000)
                child=next(f for f in page.frames if '/widget/' in f.url)
                assert child.evaluate('micProbe.calls')==0
                assert child.evaluate("document.featurePolicy.allowsFeature('microphone')")
                child.evaluate("micProbe.mode='denied'")
                start.click(); expect(frame.locator('.error[role=alert]')).to_contain_text('site settings')
                assert not voice_requests
                child.evaluate("micProbe.mode='real'")
                start.click(); expect(frame.get_by_role('heading',name='Listening…')).to_be_visible()
                page.wait_for_timeout(150)
                assert pcm, 'Real browser capture must send PCM to the synthetic media boundary'
                frame.get_by_role('button',name='End conversation').click()
                expect(start).to_be_visible()
                assert child.evaluate("micProbe.tracks.length>0 && micProbe.tracks.every(t=>t.readyState==='ended')")
                art=ROOT/'artifacts/sarvam'; art.mkdir(parents=True,exist_ok=True)
                page.screenshot(path=str(art/'widget-microphone-mobile.png'),full_page=True)
                page.evaluate('sessionStorage.clear()')
                page.goto(HOST+'/blocked')
                page.locator('[data-voice-studio-widget] .launcher').click()
                expect(page.get_by_role('button',name='Start voice input',exact=True)).to_be_visible(timeout=30000)
                page.get_by_role('button',name='Start voice input',exact=True).click()
                expect(page.get_by_text('This website blocks microphone access.',exact=False)).to_be_visible()
                assert page.evaluate('micProbe.calls')==0
                assert not errors, errors
                result={'cross_origin_iframe':True,'no_prompt_on_load':True,'permission_denied_retry':True,'missing_device':True,'close_during_permission':True,'dictation':True,'browser_pcm_capture':True,'tracks_stopped':True,'blocked_host_policy':True,'page_errors':errors,'real_provider_requests':0}
                (art/'microphone.json').write_text(json.dumps(result,indent=2)); print(json.dumps(result))
                browser.close()
        finally: server.shutdown(); server.server_close()

if __name__=='__main__': main()

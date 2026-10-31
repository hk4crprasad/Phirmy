"""Real PCM/STT/reply/recording acceptance using synthetic input, no phone call.

Default checks the explicit support-ticket path. --llm asks a synthetic knowledge
question through the actual LLM. Uses paid speech/model APIs.
"""
import asyncio,io,json,logging,sys,time,uuid,wave,argparse,re
from pathlib import Path
from qa_accounts import bootstrap_account_async
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'services/control'))
logging.disable(logging.CRITICAL)
import httpx,numpy as np,soxr,websockets
from studio.config import settings
from studio.domain import default_agent
from studio.providers import speech_stream
from studio.media import HEADER

ART=Path(__file__).resolve().parents[1]/'artifacts';ART.mkdir(exist_ok=True)
diagnostics={'phase':'synthesize_test_input','errors':[]}

def input_frame(pcm,sequence,stamp):
    return HEADER.pack(b'NTV1',1,1,1,0,16000,sequence,0,len(pcm),stamp)+pcm

async def main(llm=False):
    async def words():yield 'What is the engraving character limit?' if llm else 'Please create a support ticket for a follow up.'
    input_audio=b''.join([part async for part in speech_stream(words(),settings.fish_voice_id,settings.fish_tts_model)])
    pcm=soxr.resample(np.frombuffer(input_audio,dtype='<i2'),24000,16000).astype('<i2').tobytes()
    diagnostics['phase']='create_test_agent'
    async with httpx.AsyncClient(base_url='http://127.0.0.1:8100',timeout=60,headers={'Origin':settings.app_origin}) as client:
        response=await bootstrap_account_async(client, '/v1/auth/signup',json={'name':'Live Voice QA','email':'live-voice-'+uuid.uuid4().hex[:12]+'@example.test','password':'Synthetic-QA-Password-2026','workspace_name':'Live provider acceptance · QA'})
        response.raise_for_status();ws_id=response.json()['workspaces'][0]['id'];base='/v1/workspaces/'+ws_id
        client.headers['X-CSRF-Token']=client.cookies['studio_csrf']
        config=default_agent('Live speech acceptance')
        if llm:
            response=await client.post(base+'/fixtures',json={});response.raise_for_status();fixture=response.json()
            response=await client.get(base+'/knowledge/'+fixture['kb_id']);response.raise_for_status()
            config['knowledge_snapshot_ids']=[response.json()['active_snapshot_id']]
        config['greeting']='Hello. Your voice assistant is ready.'
        config['recording']={'enabled':True,'retention_days':1}
        config['behavior'].update(silence_prompt_seconds=30,idle_end_seconds=60,max_connected_seconds=90)
        response=await client.post(base+'/agents',json={'name':config['name'],'config':config});response.raise_for_status();agent=response.json()
        response=await client.post(base+'/agents/'+agent['id']+'/publish',json={'expected_draft_revision':agent['draft_revision']});response.raise_for_status()
        response=await client.post(base+'/voice/sessions',json={'agent_id':agent['id'],'mode':'live'});response.raise_for_status();session=response.json()
        transcripts=[];audio=[];errors=[];greeting_done=asyncio.Event();ticket_done=asyncio.Event();ended=asyncio.Event();started=time.monotonic();first_audio=None;user_final_at=None;reply_audio_ms=None
        async with websockets.connect(session['media_url'],origin=settings.app_origin,open_timeout=20,max_size=2000000) as socket:
            await socket.send(json.dumps({'type':'client.start','session_token':session['session_token']}))
            async def read():
                nonlocal first_audio,user_final_at,reply_audio_ms
                async for message in socket:
                    if isinstance(message,bytes):
                        if message[:4]!=b'NTV1':raise RuntimeError('Unexpected PCM frame')
                        if first_audio is None:first_audio=round((time.monotonic()-started)*1000)
                        if user_final_at is not None and reply_audio_ms is None:reply_audio_ms=round((time.monotonic()-user_final_at)*1000)
                        audio.append(message[32:]);continue
                    event=json.loads(message)
                    if event.get('type')=='server.error':
                        errors.append(event.get('code'));diagnostics['errors']=errors;greeting_done.set();ticket_done.set();ended.set()
                    if event.get('type')=='server.ended':ended.set()
                    if event.get('type')=='server.transcript' and event.get('final'):
                        transcripts.append({'speaker':event['speaker'],'text':event['text']})
                        if event['speaker']=='user':user_final_at=time.monotonic()
                        if event['speaker']=='assistant':
                            if (llm and user_final_at is not None) or (not llm and 'support ticket' in event['text'].lower()):ticket_done.set()
                            else:greeting_done.set()
            reader=asyncio.create_task(read())
            try:
                diagnostics['phase']='await_greeting'
                await asyncio.wait_for(greeting_done.wait(),45)
                if errors:raise RuntimeError('Greeting failed')
                diagnostics['phase']='stream_test_speech'
                for sequence,offset in enumerate(range(0,len(pcm),3200)):
                    await socket.send(input_frame(pcm[offset:offset+3200],sequence,int((time.monotonic()-started)*1000000)))
                    await asyncio.sleep(.1)
                for i in range(15):
                    await socket.send(input_frame(b'\0'*3200,1000+i,int((time.monotonic()-started)*1000000)));await asyncio.sleep(.1)
                diagnostics['phase']='await_llm_answer' if llm else 'await_ticket_confirmation'
                await asyncio.wait_for(ticket_done.wait(),45)
                if errors:raise RuntimeError('Ticket turn failed')
                diagnostics['phase']='stop_and_save_recording'
                await socket.send(json.dumps({'type':'client.stop'}))
                await asyncio.wait_for(ended.wait(),45)
            finally:
                await socket.close();reader.cancel()
                try:await reader
                except asyncio.CancelledError:pass
        if errors:raise RuntimeError('Media provider errors occurred')
        if llm:
            replies=[x['text'] for x in transcripts if x['speaker']=='assistant'][1:]
            if not replies or not re.search(r'\b(20|twenty)\b',replies[0],re.I) or 'character' not in replies[0].lower() or reply_audio_ms is None:
                raise RuntimeError('The spoken reply did not confirm the grounded character limit')
        diagnostics['phase']='verify_persisted_resources'
        if not llm:
            response=await client.get(base+'/tickets');response.raise_for_status()
            if not response.json()['items']:raise RuntimeError('Ticket was not persisted')
        response=await client.get(base+'/recordings');response.raise_for_status();recordings=response.json()['items']
        if len(recordings)!=1:raise RuntimeError('Recording was not persisted')
        response=await client.get(base+'/recordings/'+recordings[0]['id']+'/audio');response.raise_for_status()
        with wave.open(io.BytesIO(response.content),'rb') as recorded:
            if recorded.getnchannels()!=2 or recorded.getframerate()!=16000:raise RuntimeError('Invalid recording layout')
            samples=np.frombuffer(recorded.readframes(recorded.getnframes()),dtype='<i2').reshape(-1,2)
            if not all(samples[:,channel].any() for channel in [0,1]):raise RuntimeError('A recording channel is silent')
        prefix='live-llm-session' if llm else 'live-session'
        (ART/(prefix+'-recording.wav')).write_bytes(response.content)
        result={'state':'passed','workspace_id':ws_id,'call_id':session['call_id'],'fish_model':settings.fish_tts_model,'llm_model':settings.openai_model if llm else None,'first_audio_ms':first_audio,'reply_audio_after_final_transcript_ms':reply_audio_ms,'deepgram_recognition':True,'durable_ticket':not llm,'azure_recording_download':True,'recording_channels':2,'microphone':'synthetic input; no physical microphone tested','llm_turn':'passed' if llm else 'not exercised by this ticket path','knowledge':'synthetic fixture; lexical retrieval' if llm else 'not exercised','transcripts':transcripts,'errors':errors}
        (ART/(prefix+'-results.json')).write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--llm',action='store_true');args=parser.parse_args()
    try:asyncio.run(main(args.llm))
    except Exception as exc:
        failure={'state':'failed','error_type':type(exc).__name__,'http_status':getattr(getattr(exc,'response',None),'status_code',None),**diagnostics}
        (ART/('live-llm-session-results.json' if args.llm else 'live-session-results.json')).write_text(json.dumps(failure,indent=2)+'\n');print(json.dumps(failure));raise SystemExit(1)

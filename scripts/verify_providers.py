"""Explicit live acceptance: tiny provider requests, no phone calls or secret output.

Uses configured services and may consume a small amount of provider credit.
Stores only synthetic test audio and redacted results in ignored artifacts/.
"""
import asyncio,sys,json,logging,time,uuid,wave
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'services/control'))
logging.disable(logging.CRITICAL)
import httpx,numpy as np,soxr,websockets
from studio.config import settings
from studio.storage import get_store
from studio.retrieval import embed
from studio.llm import Turn,environment_profile
from studio.providers import speech_stream

ART=Path(__file__).resolve().parents[1]/'artifacts'
ART.mkdir(exist_ok=True)
results={};speech=b''

def failure(exc):
    result={'state':'failed','error_type':type(exc).__name__}
    status=getattr(exc,'status_code',None) or getattr(getattr(exc,'response',None),'status_code',None)
    if status:result['http_status']=status
    code=getattr(exc,'code',None)
    if isinstance(code,str) and code.replace('_','').isalnum() and len(code)<70:result['code']=code
    return result

async def run(name,fn):
    try:results[name]=await asyncio.wait_for(fn(),90)
    except Exception as exc:results[name]=failure(exc)
    print(json.dumps({name:results[name]}),flush=True)

async def storage():
    def check():
        store=get_store();ws='provider-qa-'+uuid.uuid4().hex
        body=b'Voice Studio synthetic Azure round-trip acceptance.'
        key=store.put(ws,'exports',body,'text/plain')
        try:
            if store.get(ws,key)!=body:raise RuntimeError('Storage content mismatch')
            try:store.get('another-workspace',key)
            except PermissionError:pass
            else:raise RuntimeError('Workspace guard failed')
        finally:store.delete(ws,key)
        return {'state':'passed','container':settings.azure_storage_container,'upload_read_delete':True,'workspace_guard':True}
    return await asyncio.to_thread(check)

async def model():
    profile=environment_profile()
    tools=[{'type':'function','name':'connection_probe','description':'Return the synthetic readiness marker.','parameters':{'type':'object','properties':{},'additionalProperties':False}}]
    messages=[{'role':'user','content':'Call connection_probe exactly once, then repeat the returned marker.'}]
    turn=Turn(profile,'Connection test. Use the required tool before responding. Only synthetic test data is involved.',messages,tools,limit=256)
    async for _ in turn.stream():pass
    if len(turn.calls)!=1 or turn.calls[0]['name']!='connection_probe':raise RuntimeError('Expected function call was not returned')
    turn.append_results([{'marker':'voice_probe_ready'}])
    follow=Turn(profile,'Report the returned marker.',messages,limit=256)
    output=''.join([s async for s in follow.stream()])
    if 'voice_probe_ready' not in output:raise RuntimeError('Tool result was not reflected')
    return {'state':'passed','model':profile['model'],'api_style':profile['api_style'],'token_cap':profile['token_parameter'],'temperature':'omitted','streaming':True,'tool_round_trip':True,'first_token_ms':follow.first_token_ms}

async def embeddings():
    vectors=await embed(['A customer asks about order delivery.','A business assistant answers from verified knowledge.'])
    return {'state':'passed','model':settings.embedding_model,'dimensions':len(vectors[0]),'vectors':len(vectors)}


async def qdrant():
    if not settings.vector_endpoint:
        return {'state':'not_configured'}
    from verify_qdrant import verify
    return await verify()

async def fish():
    global speech
    async with httpx.AsyncClient(timeout=25) as client:
        r=await client.get('https://api.fish.audio/model/'+settings.fish_voice_id,headers={'Authorization':'Bearer '+settings.fish_api_key})
        r.raise_for_status()
    async def words():yield 'Hello. Your business voice assistant is ready to help.'
    started=time.monotonic();first=None;chunks=[]
    async for chunk in speech_stream(words(),settings.fish_voice_id,settings.fish_tts_model):
        if first is None:first=round((time.monotonic()-started)*1000)
        chunks.append(chunk)
        if sum(map(len,chunks))>24000*2*20:raise RuntimeError('Unexpectedly long test audio')
    speech=b''.join(chunks)
    if len(speech)<4800 or len(speech)%2 or not np.frombuffer(speech,dtype='<i2').any():raise RuntimeError('No usable PCM audio')
    with wave.open(str(ART/'provider-smoke.wav'),'wb') as out:
        out.setnchannels(1);out.setsampwidth(2);out.setframerate(24000);out.writeframes(speech)
    return {'state':'passed','model':settings.fish_tts_model,'voice_access':True,'pcm_sample_rate':24000,'audio_seconds':round(len(speech)/48000,2),'first_audio_ms':first}

async def deepgram():
    if not speech:return {'state':'blocked','reason':'Fish test audio unavailable'}
    pcm=soxr.resample(np.frombuffer(speech,dtype='<i2'),24000,16000).astype('<i2').tobytes()
    url='wss://api.deepgram.com/v1/listen?model=nova-3&language=en&encoding=linear16&sample_rate=16000&channels=1&interim_results=true&endpointing=250'
    transcripts=[];started=time.monotonic()
    async with websockets.connect(url,additional_headers={'Authorization':'Token '+settings.deepgram_api_key},open_timeout=20,close_timeout=3) as ws:
        async def receive():
            async for message in ws:
                event=json.loads(message)
                if event.get('type')=='Error':raise RuntimeError('Recognition provider returned an error')
                if event.get('type')=='Results' and event.get('is_final'):
                    text=event.get('channel',{}).get('alternatives',[{}])[0].get('transcript','')
                    if text:transcripts.append(text)
        reader=asyncio.create_task(receive())
        try:
            for offset in range(0,len(pcm),3200):
                await ws.send(pcm[offset:offset+3200]);await asyncio.sleep(.1)
            await ws.send(b'\0'*16000)
            await ws.send(json.dumps({'type':'CloseStream'}))
            await asyncio.wait_for(reader,25)
        finally:
            reader.cancel()
            try:await reader
            except asyncio.CancelledError:pass
    text=' '.join(transcripts)
    if not text or not {'voice','assistant'}.intersection(text.lower().split()):raise RuntimeError('Expected test speech was not transcribed')
    return {'state':'passed','model':'nova-3','streaming':True,'transcript':text,'elapsed_ms':round((time.monotonic()-started)*1000)}

async def main():
    await asyncio.gather(run('azure_blob',storage),run('azure_llm',model),run('azure_embeddings',embeddings),run('fish_tts',fish),run('qdrant',qdrant))
    await run('deepgram_stt',deepgram)
    (ART/'provider-results.json').write_text(json.dumps(results,indent=2)+'\n')
    required=['azure_blob','azure_llm','azure_embeddings','fish_tts','deepgram_stt']+(['qdrant'] if settings.vector_endpoint else [])
    return all(results[name]['state']=='passed' for name in required)

if __name__=='__main__':raise SystemExit(0 if asyncio.run(main()) else 1)

"""Generate a long synthetic voice evaluation MP3 with the configured Fish voice.

Uses the paid Fish TTS API. Resumes completed sections; --refresh regenerates them.
The finished MP3 and transcript are also copied to private Azure object storage.
"""
import argparse,hashlib,json,logging,subprocess,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'services/control'))
logging.disable(logging.CRITICAL)
import httpx
from studio.config import settings
from studio.storage import get_store

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/voice-demo'
SECTIONS=[
('Welcome',"""Hello, and welcome. This is a longer voice preview, made so you can hear how I sound beyond a single sentence. You will hear a friendly greeting, a calm customer support conversation, a product explanation, an appointment reminder, and a little storytelling. All names, prices, and situations in this recording are fictional examples. Listen for the pace, the warmth, and the small pauses between thoughts. You can try this on your phone, through headphones, or on a speaker. Let's begin."""),
('A natural first conversation',"""Hi! Thanks for calling. I'm your business's AI assistant, and I'm here to help. Are you looking for something specific, or would you like a little guidance? Take your time. There's no rush. If you're buying a gift, we can start with the person you have in mind. Is it for a birthday, an anniversary, a celebration, or simply a thoughtful surprise? Tell me a little about them, and we'll narrow things down together. And if I don't know an answer, I'll say so."""),
('Helping someone choose',"""That sounds like a lovely idea. If you want something personal without making it complicated, an engraved gift could be a good place to start. The details matter: a name, a short date, or a few words that mean something to both of you. Before you decide, let's check the available space and make sure the wording fits. Would you prefer a clean, understated style, or something a little more expressive? We can compare the options, one at a time, until you find the right fit."""),
('Calm customer support',"""I understand. You expected an update, and not knowing what's happening is frustrating. Let's take this one step at a time. First, I'll need the order reference you received when you placed the order. Please share only that reference, rather than any payment details. I'll check the available information before giving you an answer. If I can't confirm the status, I'll help record the issue for the team. You deserve a clear update, and I don't want to make a promise that hasn't been verified."""),
('Dates and numbers',"""Here is a fictional appointment example. Your appointment is on Thursday, the twenty-second of October, at three thirty in the afternoon, India Standard Time. Please allow about fifteen minutes for the conversation. In another example, the item costs nine hundred and ninety-nine rupees, and the reference is A B seven four two nine. Let me repeat that slowly: A, B, seven, four, two, nine. The requested name has eighteen characters, which fits within a twenty-character limit. Would you like me to read any of those details again?"""),
('A thoughtful booking conversation',"""Of course. Let's find a time that works for you. What day would you prefer, and which time zone should I use? Morning or afternoon? Great. Before anything is booked, I'll check the calendar and repeat the details back to you. If that time is unavailable, we can look at the next suitable option. I won't treat a suggested time as a confirmed appointment. Once the booking system confirms it, I'll give you the result clearly, so you know exactly what has been arranged."""),
('Warmth and reassurance',"""That's wonderful news. Congratulations! I hope the celebration is full of the people and moments that matter most to you. And if today has been a little overwhelming, that's okay too. We can keep this simple. You don't need to remember everything at once. We can go over the important details again, slowly, and make sure nothing feels confusing. Sometimes a helpful conversation is just a small moment of calm in a busy day. I'm glad I could be part of that moment."""),
('Hindi and Hinglish',"""नमस्ते! मैं आपकी एआई असिस्टेंट हूँ। बताइए, मैं आपकी कैसे मदद कर सकती हूँ? अगर आपको किसी प्रोडक्ट के बारे में जानकारी चाहिए, तो उसका नाम बता दीजिए। अगर कोई बात साफ़ नहीं हुई, तो कोई परेशानी नहीं। हम आराम से दोबारा समझ सकते हैं। आपका समय हमारे लिए ज़रूरी है। Main pehle details check karungi, phir aapko clear update dungi. Agar information available nahi hai, toh main guess nahi karungi. Aap chahein toh hum English mein bhi baat kar sakte hain."""),
('A little story',"""On a quiet morning, a small shop opened its doors a few minutes earlier than usual. The first customer came in carrying an old photograph and a very particular idea for a gift. It wasn't expensive or elaborate. It was simply meant to say, I remember. The shopkeeper listened, asked a few careful questions, and helped turn that idea into something real. By the time the customer left, the room felt a little brighter. Sometimes, the smallest details carry the biggest meaning."""),
('Closing the conversation',"""Before we finish, is there anything else you'd like to go over? We can revisit a detail, clarify a question, or simply take a moment. Thank you for listening to this voice preview. You've heard conversational speech, reassurance, dates, numbers, Hindi, Hinglish, and a short story. Notice how comfortable the voice feels over a longer recording, and whether any words sound rushed or unclear. That will help you decide what to adjust. I hope this sounded clear, natural, and easy to listen to. Have a lovely day!"""),
]

def run(*args):
    return subprocess.run(args,check=True,capture_output=True,text=True).stdout

def probe(path):
    return json.loads(run('ffprobe','-v','error','-show_format','-show_streams','-of','json',str(path)))

def main(refresh=False):
    if not settings.fish_api_key or not settings.fish_voice_id:raise RuntimeError('Fish key and voice must be configured')
    OUT.mkdir(parents=True,exist_ok=True)
    manifest={'model':settings.fish_tts_model,'sections':[],'synthetic_demo':True}
    inputs=[];timeline=0
    silence=OUT/'pause.wav'
    run('ffmpeg','-y','-v','error','-f','lavfi','-i','anullsrc=r=44100:cl=mono','-t','0.65',str(silence))
    with httpx.Client(timeout=httpx.Timeout(180,connect=20),follow_redirects=False) as client:
        for i,(name,text) in enumerate(SECTIONS,1):
            target=OUT/f'{i:02}.mp3';wav=OUT/f'{i:02}.wav';stamp=OUT/f'{i:02}.json'
            fingerprint=hashlib.sha256((settings.fish_tts_model+settings.fish_voice_id+text).encode()).hexdigest()
            cached=not refresh and target.exists() and stamp.exists() and json.loads(stamp.read_text()).get('fingerprint')==fingerprint
            if not cached:
                with client.stream('POST','https://api.fish.audio/v1/tts',headers={'Authorization':'Bearer '+settings.fish_api_key,'model':settings.fish_tts_model},json={'text':text,'reference_id':settings.fish_voice_id,'format':'mp3','mp3_bitrate':192,'sample_rate':44100,'latency':'normal','chunk_length':200,'normalize':True,'prosody':{'speed':1,'volume':0}}) as response:
                    response.raise_for_status()
                    with target.with_suffix('.part').open('wb') as output:
                        for data in response.iter_bytes():output.write(data)
                target.with_suffix('.part').replace(target)
                stamp.write_text(json.dumps({'fingerprint':fingerprint}))
            metadata=probe(target);duration=float(metadata['format']['duration'])
            if duration<5:raise RuntimeError('A demo section is unexpectedly short')
            run('ffmpeg','-y','-v','error','-i',str(target),'-ar','44100','-ac','1',str(wav))
            wav_duration=float(probe(wav)['format']['duration'])
            manifest['sections'].append({'title':name,'start_seconds':round(timeline,2),'duration_seconds':round(wav_duration,2)})
            inputs.append(wav);timeline+=wav_duration
            if i<len(SECTIONS):inputs.append(silence);timeline+=.65
            print(json.dumps({'section':i,'of':len(SECTIONS),'title':name,'seconds':round(wav_duration,1)}),flush=True)
    concat=OUT/'concat.txt';concat.write_text('\n'.join("file '"+str(p)+"'" for p in inputs)+'\n')
    output=OUT/'voice-demo-drama-3.mp3'
    run('ffmpeg','-y','-v','error','-f','concat','-safe','0','-i',str(concat),'-af','loudnorm=I=-16:TP=-1.5:LRA=11','-ar','44100','-ac','1','-c:a','libmp3lame','-b:a','192k','-metadata','title=Voice Studio — Extended Voice Demo','-metadata','artist=Voice Studio','-metadata','comment=Synthetic voice evaluation; all scenarios fictional',str(output))
    metadata=probe(output);manifest['duration_seconds']=round(float(metadata['format']['duration']),2);manifest['size_bytes']=output.stat().st_size
    manifest['mp3_bitrate']=192000;manifest['sample_rate']=44100
    if manifest['duration_seconds']<180:raise RuntimeError('Extended demo is shorter than three minutes')
    # Decode the whole file to catch corruption before delivery.
    run('ffmpeg','-v','error','-i',str(output),'-f','null','-')
    transcript=OUT/'voice-demo-transcript.txt';transcript.write_text('\n\n'.join(name+'\n'+text for name,text in SECTIONS)+'\n')
    if settings.object_storage_provider=='azure':
        store=get_store();manifest['azure_objects']={}
        for file,content_type in [(output,'audio/mpeg'),(transcript,'text/plain; charset=utf-8')]:
            data=file.read_bytes();key=store.put('voice-demos','exports',data,content_type)
            if store.get('voice-demos',key)!=data:raise RuntimeError('Azure demo copy mismatch')
            manifest['azure_objects'][file.name]=key
    (OUT/'voice-demo-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'state':'passed','mp3':str(output),'duration_seconds':manifest['duration_seconds'],'size_mb':round(manifest['size_bytes']/1000000,2),'private_azure_copy':bool(manifest.get('azure_objects'))}),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--refresh',action='store_true');args=parser.parse_args()
    try:main(args.refresh)
    except Exception as exc:
        print(json.dumps({'state':'failed','error_type':type(exc).__name__,'http_status':getattr(getattr(exc,'response',None),'status_code',None)}));raise SystemExit(1)

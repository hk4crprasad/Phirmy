"""Opt-in live Sarvam check using synthetic speech and a local read-only demo tool.

Run: .venv/bin/python scripts/verify_sarvam_voice.py --live
No database, carrier call, customer data, or external tool action is used.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import wave

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'services/control'))


async def verify(output):
    import numpy as np
    import soxr
    from fishaudio.types import FlushEvent
    from studio.config import settings
    from studio.sarvam_stt import Recognition
    from studio.sarvam_tts import SarvamCall
    from studio.voice_config import speech_config, voice_profile
    from studio.llm import Turn
    from studio.llm_connections import CallClients, current

    speech = speech_config({})
    owner = SarvamCall(speech)
    recognition = None
    clients = CallClients(None)
    token = current.set(clients)
    phase = 'input synthesis'
    try:
        async def prompt():
            yield 'Please check my booking status.'
            yield FlushEvent()
        source = b''.join([audio async for audio in owner.stream(prompt(),speech['voice_id'],speech['model'])])
        assert source
        pcm = soxr.resample(np.frombuffer(source,dtype='<i2'),24000,16000).astype('<i2').tobytes()
        phase = 'realtime recognition'
        recognition = await Recognition.connect('en-IN')
        final_at = None
        transcript = None
        partials = 0
        async def send():
            # Silence gives server VAD a genuine end-of-turn; input is paced at 20 ms.
            data = b'\0'*6400 + pcm + b'\0'*32000
            started = time.monotonic()
            for offset in range(0,len(data),640):
                await recognition.send(data[offset:offset+640])
                await asyncio.sleep(max(0,started+(offset+640)/32000-time.monotonic()))
        sender = asyncio.create_task(send())
        try:
            async with asyncio.timeout(30):
                async for raw in recognition:
                    event=json.loads(raw)
                    if event.get('type')=='Results':
                        if event.get('speech_final'):
                            transcript=event['channel']['alternatives'][0]['transcript']
                            final_at=time.monotonic()
                            break
                        partials+=1
            assert transcript
        finally:
            sender.cancel()
            await asyncio.gather(sender,return_exceptions=True)
        phase = 'streamed model, tool and speech'
        messages=[{'role':'user','content':transcript}]
        tools=[{'name':'lookup_demo_booking','description':'Read the synthetic test booking status.',
                'parameters':{'type':'object','properties':{},'additionalProperties':False}}]
        instructions='This is a synthetic integration test. Call lookup_demo_booking exactly once to check the booking. After its result, give one brief sentence. Do not invent its status.'
        turn=Turn(voice_profile(),instructions,messages,tools=tools,limit=128)
        reply=[]
        used=[]
        usages=[]
        async def answer():
            for _ in range(2):
                async for delta in turn.stream():
                    reply.append(delta)
                    yield delta
                    if any(mark in delta for mark in '.!?'):
                        yield FlushEvent()
                usages.append({'complete':turn.usage_complete,**(turn.usage or {})})
                if not turn.calls:
                    yield FlushEvent()
                    return
                if len(turn.calls)!=1 or turn.calls[0]['name']!='lookup_demo_booking' or used:
                    raise RuntimeError('Unexpected demo tool call')
                assert json.loads(turn.calls[0]['arguments'])=={}
                used.append('lookup_demo_booking')
                turn.append_results([{'booking':'synthetic demo','status':'confirmed'}])
                yield FlushEvent()
            raise RuntimeError('Demo tool round limit exceeded')
        first_audio = None
        audio = bytearray()
        async for chunk in owner.stream(answer(),speech['voice_id'],speech['model']):
            if chunk and first_audio is None:
                first_audio = time.monotonic()
            audio.extend(chunk)
        assert audio and used and all(item['complete'] for item in usages)
        output.mkdir(parents=True,exist_ok=True)
        with wave.open(str(output/'reply.wav'),'wb') as wav:
            wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(24000);wav.writeframes(audio)
        result={'source':'live Sarvam providers; synthetic input; local read-only fixture tool',
                'stt_model':settings.sarvam_stt_model,'voice_model':settings.sarvam_voice_model,'tts_model':settings.sarvam_tts_model,
                'transcript':transcript,'partials':partials,'tool_calls':used,'reply':''.join(reply),
                'final_transcript_to_first_audio_ms':round((first_audio-final_at)*1000,1),
                'reply_audio_ms':round(len(audio)/48,1),'usage':usages}
        (output/'result.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result,indent=2))
    except Exception as error:
        # Provider exceptions can embed headers or arbitrary provider text.
        raise RuntimeError('Sarvam verification failed during '+phase+' ('+type(error).__name__+')') from None
    finally:
        if recognition is not None:
            await recognition.close()
        await owner.close()
        await clients.close()
        current.reset(token)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true',help='Make bounded billed Sarvam requests with synthetic speech')
    args=parser.parse_args()
    if not args.live:
        parser.error('Pass --live to authorize provider requests')
    key=os.environ.get('SARVAM_API_KEY') or dotenv_values(ROOT/'.env').get('SARVAM_API_KEY')
    if not key:
        raise SystemExit('Set SARVAM_API_KEY in .env first.')
    with tempfile.TemporaryDirectory(prefix='sarvam-verify-') as isolated:
        os.environ.update(SARVAM_API_KEY=key,VOICE_PROVIDER='sarvam',DATABASE_URL='sqlite:///'+isolated+'/unused.db',
                          SUPABASE_DB_PASSWORD='',DATA_DIR=isolated,APP_ENV='test')
        try:
            asyncio.run(verify(ROOT/'artifacts/sarvam'))
        except Exception as error:
            raise SystemExit(str(error)) from None


if __name__=='__main__':
    main()

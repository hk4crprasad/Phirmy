import json

import pytest
from sqlalchemy import select

from studio.config import settings
from studio.db import session_scope
from studio.models import VoiceTimingRecord
from studio.transcripts import Transcript
from test_voice_latency import voice
from voice_latency_fixture import SyntheticVoiceProviders


@pytest.mark.asyncio
async def test_unicode_append_and_revised_hypothesis_share_stable_identity():
    events=[]
    async def send(kind,**data):events.append({'type':kind,**data})
    stream=Transcript(send,'user',3,deltas=True)
    for text in ['Hello 🌿','Hello 🌿!','Hello world','Hello world']:
        await stream.write(text)
    await stream.write('Hello world',final=True)
    current=''
    for expected,event in zip(['Hello 🌿','Hello 🌿!','Hello world'],events[:-1]):
        current=current[:event['retain']]+event['delta']
        assert current==expected
    assert [event['seq'] for event in events[:-1]]==[0,1,2]
    assert len({event['turn_id'] for event in events})==1
    assert events[-1]['text']==current and events[-1]['final']
    assert all(event['epoch']==3 for event in events)


@pytest.mark.asyncio
async def test_legacy_full_frames_keep_the_same_turn_id():
    events=[]
    async def send(kind,**data):events.append({'type':kind,**data})
    stream=Transcript(send,'assistant',0)
    await stream.write('First')
    await stream.write('First second')
    await stream.write('First second',final=True)
    assert all(event['type']=='server.transcript' for event in events)
    assert [event['text'] for event in events]==['First','First second','First second']
    assert len({event['turn_id'] for event in events})==1


@pytest.mark.asyncio
async def test_incremental_transcript_wire_size_does_not_repeat_the_whole_answer():
    async def size(deltas):
        events=[]
        async def send(kind,**data):events.append({'type':kind,**data})
        transcript=Transcript(send,'assistant',0,deltas=deltas)
        for count in range(1,101):await transcript.write('word '*8*count)
        await transcript.write('word '*800,final=True)
        return sum(len(json.dumps(event).encode()) for event in events)
    assert await size(True)<await size(False)//3


@pytest.mark.asyncio
async def test_actual_pipeline_sends_deltas_and_one_final_without_repeating_prefix(voice):
    client,base,_,call_id,session,transport=voice
    session.transcript_deltas=True
    fixture=SyntheticVoiceProviders(retrieval_delay=0,model_first_token=0,token_delay=0,fish_connect=0,fish_first_audio=0)
    fixture.chunks=['Here is a streaming answer ','🌿',' with a suffix.']
    with fixture.installed():
        await session.user_text('Synthetic transcript patch query',input_kind='stt_final')
        await session.task
    deltas=[event for event in transport.events if event['type']=='server.transcript.delta' and event['speaker']=='assistant']
    full=[event for event in transport.events if event['type']=='server.transcript' and event['speaker']=='assistant']
    assert deltas and len(full)==1 and full[0]['final']
    current=''
    for seq,event in enumerate(deltas):
        assert event['seq']==seq and event['retain']==len(current)
        current=current[:event['retain']]+event['delta']
        assert event['turn_id']==full[0]['turn_id']
    assert current==full[0]['text']==''.join(fixture.chunks)
    with session_scope() as db:
        assert db.scalar(select(VoiceTimingRecord).where(VoiceTimingRecord.call_id==call_id)).turn_id==full[0]['turn_id']
    assert client.get(base+'/calls/'+call_id).status_code==200


@pytest.mark.parametrize('requested',[None,'delta-v1'])
def test_real_browser_socket_negotiates_delta_support_and_keeps_legacy_clients(sample,requested):
    client,_,base,fixture=sample
    response=client.post(base+'/voice/sessions',json={'agent_id':fixture['agent_id'],'mode':'simulation'})
    assert response.status_code==201,response.text
    state=response.json()
    events=[]
    with client.websocket_connect('/v1/media',headers={'Origin':settings.app_origin}) as socket:
        hello={'type':'client.start','session_token':state['session_token']}
        if requested:hello['transcript_mode']=requested
        socket.send_json(hello)
        ready=socket.receive_json()
        assert ready['type']=='server.ready' and ready['transcript_mode']==(requested or 'full')
        while True:
            message=socket.receive_json();events.append(message)
            if message['type']=='server.turn_state' and message['state']=='listening':break
        socket.send_json({'type':'client.stop'})
        while socket.receive_json()['type']!='server.ended':pass
    partials=[event for event in events if event['type']=='server.transcript.delta' or (event['type']=='server.transcript' and not event['final'])]
    assert partials and all(event['type']==('server.transcript.delta' if requested else 'server.transcript') for event in partials)


@pytest.mark.asyncio
async def test_deepgram_revisions_accumulate_final_segments_without_changing_turn_id(voice):
    _,_,_,_,session,transport=voice
    session.transcript_deltas=True
    class Deepgram:
        async def __aiter__(self):
            yield json.dumps({'type':'SpeechStarted'})
            for text,final,end in [('We need eyes',False,False),('We need ice',True,False),('cream',False,False),('cream.',True,True)]:
                yield json.dumps({'type':'Results','channel':{'alternatives':[{'transcript':text}]},'is_final':final,'speech_final':end})
    session.dg=Deepgram()
    received=[]
    async def final_text(text,**values):received.append((text,values))
    session.user_text=final_text
    fixture=SyntheticVoiceProviders(fish_connect=0)
    with fixture.installed():
        try:await session._recognize()
        finally:await session.fish.close()
    events=[event for event in transport.events if event['type']=='server.transcript.delta']
    current=''
    for event in events:current=current[:event['retain']]+event['delta']
    assert current=='We need ice cream.' and received[0][0]==current
    assert len({event['turn_id'] for event in events})==1
    assert received[0][1]['transcript_turn_id']==events[0]['turn_id']

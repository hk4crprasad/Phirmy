"""Twilio signed call webhooks and bidirectional Media Streams adapter."""
import asyncio
import base64
import contextlib
import hashlib
import json
import logging
import time
from urllib.parse import urlencode
from xml.etree.ElementTree import Element,SubElement,tostring
import numpy as np
import soxr
import websockets
from fastapi import APIRouter,Request,WebSocket,WebSocketDisconnect,HTTPException
from fastapi.responses import Response
from sqlalchemy import select,text
from twilio.request_validator import RequestValidator
from .config import settings
from .db import session_scope,now
from .models import Call,Number,Agent,AgentVersion
from .domain import owned,settle_call,bind_variables
from .security import capability,verify_capability
from .media import VoiceSession,owners
from .async_work import durable_await
from .media_lifecycle import locked_call, finalize as finalize_media
from .carrier import mulaw_decode,mulaw_encode
from .llm import live_voice_ready
from .carrier_config import call_credentials, callback_credentials

router=APIRouter();log=logging.getLogger(__name__)


async def form_verified(request):
    if not settings.live_calls_enabled:raise HTTPException(503,'Twilio live callbacks are not configured')
    if not settings.media_public_origin.startswith('https://'):raise HTTPException(503,'Set an HTTPS MEDIA_PUBLIC_ORIGIN')
    form={k:str(v) for k,v in (await request.form()).items()}
    carrier = callback_credentials('twilio', form, request.query_params.get('call_id'))
    if not carrier.get('auth_token'):raise HTTPException(503, 'Connect Twilio first')
    url=settings.media_public_origin.rstrip('/')+request.url.path+('?' +request.url.query if request.url.query else '')
    if not RequestValidator(carrier['auth_token']).validate(url,form,request.headers.get('X-Twilio-Signature','')):raise HTTPException(401,'Invalid Twilio signature')
    if form.get('AccountSid')!=carrier.get('account_sid'):raise HTTPException(403,'Twilio account identity mismatch')
    return form


def xml(root):return Response(tostring(root,encoding='unicode'),media_type='application/xml')


@router.post('/v1/provider-webhooks/twilio/answer')
async def answer(request:Request,call_id:str|None=None):
    form=await form_verified(request);sid=form.get('CallSid','')
    if not sid or len(sid)>100:raise HTTPException(422,'CallSid missing')
    with session_scope(write=True) as db:
        if db.bind.dialect.name=='postgresql':db.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:key,0))'),{'key':'twilio:'+sid})
        if call_id:
            call=db.scalar(select(Call).where(Call.id==call_id).with_for_update())
            if not call or call.mode!='live' or call.metadata_data.get('provider')!='twilio':raise HTTPException(404,'Call not found')
            if call.destination!=form.get('To') or call.provider_call_id and call.provider_call_id!=sid:raise HTTPException(403,'Call identity mismatch')
            call.provider_call_id=sid
        else:
            call=db.scalar(select(Call).where(Call.provider_call_id==sid,Call.mode=='live'))
            if not call:
                number=db.scalar(select(Number).where(Number.provider=='twilio',Number.e164==form.get('To'),Number.status=='active',Number.can_inbound.is_(True)))
                if not number or not number.agent_id:
                    root=Element('Response');SubElement(root,'Hangup');return xml(root)
                from .phone_trials import for_number
                if for_number(db, number.id):
                    root=Element('Response');SubElement(root,'Hangup');return xml(root)
                agent=owned(db,Agent,number.workspace_id,number.agent_id)
                if not agent.published_version_id:raise HTTPException(409,'Publish the inbound agent first')
                config=owned(db,AgentVersion,number.workspace_id,agent.published_version_id).config
                if not live_voice_ready(config,number.workspace_id):raise HTTPException(409,'Voice pipeline is not ready')
                call=Call(workspace_id=number.workspace_id,agent_version_id=agent.published_version_id,agent_name=agent.name,mode='live',transport='pstn',direction='inbound',provider_call_id=sid,metadata_data={'provider':'twilio','number_id':number.id,'variables':{'caller_number':form.get('From','')}})
                db.add(call);db.flush()
                from .admission import admit_voice
                admit_voice(db,call,config)
        if call.state in {'ending','completed','failed','canceled','busy','no_answer'}:
            root=Element('Response');SubElement(root,'Hangup');return xml(root)
        if 'admitted_max_seconds' not in call.metadata_data:
            from .admission import admit_voice
            admit_voice(db,call,owned(db,AgentVersion,call.workspace_id,call.agent_version_id).config)
        if call.metadata_data.get('phone_trial_id'):
            from .phone_trials import call_seconds
            try:
                call_seconds(db, call)
            except HTTPException:
                call.failure_code = 'phone_trial_unavailable'
                settle_call(db, call, 0, 'failed')
                root=Element('Response');SubElement(root,'Hangup');return xml(root)
        if call.state in {'created','ringing'}:call.state='connecting'
        token=capability({'aud':'twilio-media','workspace_id':call.workspace_id,'call_id':call.id,'provider_call_id':sid},ttl=180)
        from .carrier_config import remaining_seconds
        remaining=remaining_seconds(call)
    if remaining==0:
        root=Element('Response');SubElement(root,'Hangup');return xml(root)
    if call.direction=='inbound':
        try:
            from .carrier_config import twilio_client
            await asyncio.to_thread(twilio_client(call_credentials(call)).calls(sid).update,time_limit=remaining)
        except Exception:
            # No stream starts unless the carrier accepted a bounded duration.
            root=Element('Response');SubElement(root,'Hangup');return xml(root)
    root=Element('Response');connect=SubElement(root,'Connect');SubElement(connect,'Stream',{'url':settings.media_public_origin.replace('https://','wss://').rstrip('/')+'/v1/twilio-media/'+token});SubElement(root,'Hangup')
    return xml(root)


@router.post('/v1/provider-webhooks/twilio/status')
async def status(request:Request,call_id:str|None=None):
    form=await form_verified(request)
    if form.get('CallStatus') not in {'completed','busy','no-answer','failed','canceled'}:return {'status':'acknowledged'}
    with session_scope(write=True) as db:
        call=db.get(Call,call_id) if call_id else db.scalar(select(Call).where(Call.provider_call_id==form.get('CallSid'),Call.mode=='live'))
        if not call or call.metadata_data.get('provider')!='twilio' or call.provider_call_id and call.provider_call_id!=form.get('CallSid'):raise HTTPException(404,'Call leg not found')
        duration=int((now()-call.connected_at).total_seconds()*1000) if call.connected_at else 0
        outcome={'no-answer':'no_answer'}.get(form['CallStatus'],form['CallStatus'])
        settle_call(db,call,duration,outcome)
    return {'status':'acknowledged'}


class Transport:
    def __init__(self,ws,sid):self.ws=ws;self.sid=sid;self.resampler=soxr.ResampleStream(24000,8000,1,dtype='int16',quality='LQ')
    async def send_json(self,event):
        if event.get('type')=='server.clear':self.resampler.clear();await self.ws.send_json({'event':'clear','streamSid':self.sid})
    async def send_bytes(self,frame):
        converted=self.resampler.resample_chunk(np.frombuffer(frame[32:],dtype='<i2'))
        if len(converted):await self.ws.send_json({'event':'media','streamSid':self.sid,'media':{'payload':base64.b64encode(mulaw_encode(converted)).decode()}})
    async def close(self):await self.ws.close()


@router.websocket('/v1/twilio-media/{token}')
async def media(ws:WebSocket,token:str):
    try:claims=verify_capability(token,'twilio-media')
    except HTTPException:await ws.close(1008);return
    call_id,workspace_id=claims['call_id'],claims['workspace_id']
    if not settings.live_calls_enabled or call_id in owners:await ws.close(1008);return
    owners.add(call_id);session=None;recognize=None;idle=None;failed=False;admitted=False
    try:
        await ws.accept()
        message=await asyncio.wait_for(ws.receive_json(),10)
        if message.get('event')=='connected':message=await asyncio.wait_for(ws.receive_json(),10)
        start=message.get('start',{});fmt=start.get('mediaFormat',{})
        def admit():
            with session_scope() as db:
                bound_call = owned(db, Call, workspace_id, call_id)
                carrier = call_credentials(bound_call)
            if message.get('event')!='start' or start.get('accountSid')!=carrier.get('account_sid') or start.get('callSid')!=claims['provider_call_id'] or fmt.get('encoding')!='audio/x-mulaw' or fmt.get('sampleRate')!=8000:raise ValueError('Stream identity or format mismatch')
            with session_scope(write=True) as db:
                call=locked_call(db,workspace_id,call_id)
                if call.provider_call_id!=claims['provider_call_id'] or call.state not in {'connecting','ringing'}:raise ValueError('Call unavailable')
                config=bind_variables(owned(db,AgentVersion,workspace_id,call.agent_version_id).config,call.metadata_data.get('variables',call.metadata_data.get('contact',{})))
                if call.metadata_data.get('phone_trial_id'):
                    from .phone_trials import call_seconds
                    config['behavior'] = {**config['behavior'], 'max_connected_seconds': min(config['behavior']['max_connected_seconds'], call_seconds(db, call))}
                if not live_voice_ready(config,workspace_id):raise ValueError('Voice pipeline not configured')
                call.state='connected';call.connected_at=call.connected_at or now()
            return config
        async def initialize():
            nonlocal config, admitted, session
            config = await asyncio.to_thread(admit)
            admitted = True
            session = await asyncio.to_thread(VoiceSession, Transport(ws,start['streamSid']), workspace_id, call_id, config, 'live')
        config = None
        await durable_await(initialize())
        stream_sid=start['streamSid']
        await session.open_recognition()
        recognize=asyncio.create_task(session.recognize());session.task=asyncio.create_task(session.respond());idle=asyncio.create_task(session.watch_idle())
        resampler=soxr.ResampleStream(8000,16000,1,dtype='int16',quality='LQ');deadline=time.monotonic()+min(config['behavior']['max_connected_seconds'],900,session.admitted_max_seconds)
        while time.monotonic()<deadline:
            message=await session.receive(ws.receive_json(),timeout=30)
            if message.get('event')=='stop':break
            if message.get('event')=='media':
                if message.get('streamSid')!=stream_sid:raise ValueError('Stream mismatch')
                raw=base64.b64decode(message.get('media',{}).get('payload',''),validate=True)
                if not 1<=len(raw)<=1600:raise ValueError('Invalid media length')
                pcm=resampler.resample_chunk(mulaw_decode(raw)).astype('<i2',copy=False).tobytes()
                if pcm:session.recording.add(pcm,16000,0);await session.recognition_audio(pcm)
    except asyncio.CancelledError:
        failed = True
        raise
    except (WebSocketDisconnect,asyncio.TimeoutError):pass
    except Exception:failed=True;log.exception('Twilio media failed for internal call %s',call_id)
    finally:
        try:
            await durable_await(finalize_media(session, workspace_id, call_id, admitted=admitted,
                failed=failed, failure_code='twilio_media_failed', tasks=(idle, recognize)))
        finally:
            owners.discard(call_id)
            with contextlib.suppress(Exception):
                await ws.close()

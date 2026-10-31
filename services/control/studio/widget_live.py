"""Widget lead capture, operator handover and server-side voice dictation."""
import asyncio
import json
from typing import Literal
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field
from sqlalchemy import select
from .config import settings
from .widget_branding import installation_allows_origin
from .db import session_scope, as_dict, now, uid
from .domain import owned, emit
from .models import Conversation, ConversationContext, Message, Installation, Agent, AgentVersion, Lead
from .schemas import Input
from .security import principal, db_dependency, audit, verify_capability, limiter

router = APIRouter()


class OperatorMode(Input):
    mode: Literal['human', 'open', 'resolved']


class OperatorReply(Input):
    text: str = Field(min_length=1, max_length=8000)
    client_message_id: str = Field(min_length=1, max_length=36)


def visitor_context(request, db):
    from .chat_routes import check_widget_claims
    claims = verify_capability(request.headers.get('authorization', '').removeprefix('Bearer '), 'widget')
    if request.headers.get('origin') != claims['origin']:
        raise HTTPException(403, 'Widget session origin does not match')
    installation = owned(db, Installation, claims['workspace_id'], claims['installation_id'])
    if not installation.enabled or not installation_allows_origin(installation,claims['origin']):
        raise HTTPException(403, 'This widget is disabled')
    check_widget_claims(installation, claims)
    agent = owned(db, Agent, claims['workspace_id'], installation.agent_id)
    version = owned(db, AgentVersion, claims['workspace_id'], claims['agent_version_id'])
    if agent.archived or version.agent_id != installation.agent_id: raise HTTPException(403, 'This assistant is unavailable')
    conversation = owned(db, Conversation, claims['workspace_id'], claims['conversation_id'])
    from .bot_challenge import enforce_session
    context=db.scalar(select(ConversationContext).where(ConversationContext.workspace_id==claims['workspace_id'],ConversationContext.conversation_id==conversation.id))
    enforce_session(context)
    if conversation.installation_id != installation.id: raise HTTPException(403, 'Conversation does not match')
    return claims, installation, conversation


def lead_details(db, conversation):
    context = db.scalar(select(ConversationContext).where(ConversationContext.workspace_id == conversation.workspace_id, ConversationContext.conversation_id == conversation.id))
    return (context.variables or {}).get('_widget_lead', {}) if context else {}


def history(db, conversation):
    rows = list(db.scalars(select(Message).where(Message.workspace_id == conversation.workspace_id, Message.conversation_id == conversation.id).order_by(Message.created_at.desc(), Message.id.desc()).limit(100)))
    return [as_dict(row) for row in reversed(rows)]


def ai_active(workspace_id, conversation_id):
    with session_scope() as db:
        row = db.get(Conversation, conversation_id)
        return bool(row and row.workspace_id == workspace_id and row.state == 'open')


@router.get('/v1/public/conversation')
@router.post('/v1/public/conversation')
def visitor_conversation(request: Request):
    with session_scope() as db:
        claims, installation, conversation = visitor_context(request, db)
        return {'state': conversation.state, 'items': history(db, conversation)}


@router.patch('/v1/workspaces/{workspace_id}/conversations/{conversation_id}/mode')
def operator_mode(workspace_id: str, conversation_id: str, body: OperatorMode, actor=Depends(principal), db=Depends(db_dependency, scope='function')):
    actor.require('inbox:write')
    if not actor.user_id: raise HTTPException(403, 'An operator account is required')
    row = db.scalar(select(Conversation).where(Conversation.workspace_id == workspace_id, Conversation.id == conversation_id).with_for_update())
    if not row: raise HTTPException(404, 'Conversation not found')
    if body.mode == 'human' and row.assigned_user_id and row.assigned_user_id != actor.user_id:
        raise HTTPException(409, 'Another operator is handling this conversation')
    if row.assigned_user_id and row.assigned_user_id != actor.user_id and actor.role not in {'owner', 'admin'}:
        raise HTTPException(403, 'Only the assigned operator can change this conversation')
    row.state = body.mode
    row.assigned_user_id = actor.user_id if body.mode == 'human' else None
    for message in db.scalars(select(Message).where(Message.workspace_id == workspace_id, Message.conversation_id == row.id, Message.role == 'assistant')):
        if message.metadata_data.get('streaming'):
            message.metadata_data = {**message.metadata_data, 'streaming': False, 'interrupted': True}
    audit(db, actor, 'conversation.' + body.mode, row.id)
    emit(db, workspace_id, 'conversation.mode_changed', {'conversation_id': row.id, 'state': row.state})
    return as_dict(row)


@router.post('/v1/workspaces/{workspace_id}/conversations/{conversation_id}/messages', status_code=201)
def operator_reply(workspace_id: str, conversation_id: str, body: OperatorReply, actor=Depends(principal), db=Depends(db_dependency, scope='function')):
    actor.require('inbox:write')
    row = db.scalar(select(Conversation).where(Conversation.workspace_id == workspace_id, Conversation.id == conversation_id).with_for_update())
    if not row: raise HTTPException(404, 'Conversation not found')
    if row.state != 'human' or not actor.user_id or row.assigned_user_id != actor.user_id:
        raise HTTPException(409, 'Take over this conversation before replying')
    previous = db.scalar(select(Message).where(Message.workspace_id == workspace_id, Message.conversation_id == row.id, Message.role == 'operator', Message.client_message_id == body.client_message_id))
    if previous:
        if previous.text_content != body.text: raise HTTPException(409, 'Reply identity already used')
        return as_dict(previous)
    message = Message(workspace_id=workspace_id, conversation_id=row.id, role='operator', client_message_id=body.client_message_id, text_content=body.text, metadata_data={'operator_id': actor.user_id, 'display_name': 'Support team'})
    db.add(message); db.flush()
    audit(db, actor, 'conversation.replied', row.id)
    return as_dict(message)


@router.post('/v1/public/voice/transcribe')
async def voice_transcribe(request: Request):
    with session_scope() as db:
        claims, installation, conversation = visitor_context(request, db)
        if conversation.state == 'resolved': raise HTTPException(409, 'This conversation is closed')
        if not installation.theme.get('voice_input_enabled', True) or not settings.capabilities()['stt']:
            raise HTTPException(409, 'Voice input is temporarily unavailable')
    limiter.check('widget-dictation:' + claims['conversation_id'], 10, 60)
    mime = request.headers.get('content-type', '').split(';')[0]
    if mime not in {'audio/webm', 'audio/ogg', 'audio/mp4', 'audio/wav', 'audio/x-wav'}:
        raise HTTPException(415, 'Use supported microphone audio')
    audio = bytearray()
    async for chunk in request.stream():
        audio.extend(chunk)
        if len(audio) > 5 * 1024 * 1024: raise HTTPException(413, 'Record up to 30 seconds at a time')
    if not audio: raise HTTPException(422, 'No audio was recorded')
    from .isolation import canonical_audio
    try:audio,duration_ms=await canonical_audio(bytes(audio))
    except ValueError as error:raise HTTPException(422,str(error))
    from .voice_config import stt_provider, sarvam_enabled
    provider = stt_provider()
    operation_key='dictation:'+uid()
    with session_scope(write=True) as db:
        claims,installation,conversation=visitor_context(request,db)
        from .widget_protection import require_admission
        require_admission(db,installation,request.client.host if request.client else '', 'transcribe','transcribe:'+uid())
        from .admission import provider_hold
        provider_hold({'workspace_id':claims['workspace_id'],'db':db,'installation_id':installation.id},operation_key,provider,{'stt_ms':duration_ms})
    try:
        if sarvam_enabled():
            from .sarvam_stt import transcribe
            text = await transcribe(bytes(audio))
        else:
            async with httpx.AsyncClient(timeout=40) as client:
                response = await client.post('https://api.deepgram.com/v1/listen', params={'model': 'nova-3', 'smart_format': 'true', 'language': settings.deepgram_language}, headers={'Authorization': 'Token ' + settings.deepgram_api_key, 'Content-Type': 'audio/wav'}, content=bytes(audio))
                response.raise_for_status()
                text = response.json()['results']['channels'][0]['alternatives'][0]['transcript']
    except Exception:
        from .metering import append_cost
        await asyncio.to_thread(append_cost,{'workspace_id':claims['workspace_id']},provider,'dictation',{},operation_key,'unreported')
        raise HTTPException(502, 'Voice transcription failed. Please retry or type your message.')
    from .metering import append_cost
    await asyncio.to_thread(append_cost,{'workspace_id':claims['workspace_id']},provider,'dictation',{'stt_ms':duration_ms},
                           operation_key,'measured_pcm')
    return {'text': text[:8000], 'provider': 'sarvam' if sarvam_enabled() else 'deepgram', 'model': settings.sarvam_stt_model if sarvam_enabled() else 'nova-3'}

import asyncio
import json
import re
import secrets
from datetime import timedelta
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse, Response
from sqlalchemy import select
from .config import settings
from .db import session_scope, as_dict, now, uid
from .models import *
from .schemas import PublicSession, ChatRequest, PublicVoiceSession
from .security import capability, verify_capability, limiter
from .domain import owned, emit, bind_variables
from .knowledge import retrieve
from .providers import answer_stream
from .llm import resolve
from .widget_branding import public_theme,widget_config,installation_allows_origin
from .usage import admit_turn, admit_voice
from .widget_live import ai_active, lead_details
from . import bot_challenge,widget_protection

router = APIRouter(prefix="/v1/public")


@router.get('/widgets/{public_id}/frame-policy')
def frame_policy(public_id: str):
    from .widget_frame_cache import lookup
    return lookup(public_id)


def check_public_key(installation, key):
    expected = installation.theme.get('publishable_key')
    if expected and not secrets.compare_digest(str(key or ''), expected):
        raise HTTPException(403, 'The widget publishable key is invalid')


def check_widget_claims(installation, claims):
    if installation.theme.get('publishable_key') and claims.get('key_revision') != __import__('hashlib').sha256(installation.theme['publishable_key'].encode()).hexdigest():
        raise HTTPException(403, 'This widget key has been rotated; reconnect')


def session_response(db, installation, claims, config):
    from .llm import live_voice_ready
    history = list(db.scalars(select(Message).where(Message.workspace_id == installation.workspace_id, Message.conversation_id == claims['conversation_id']).order_by(Message.created_at.desc(), Message.id.desc()).limit(50)))
    return {'id':claims['conversation_id'], 'session_token':capability({**claims, 'aud':'widget'},ttl=1800),
            'resume_token':capability({**claims, 'aud':'widget-resume'},ttl=86400 * 7),
            'expires_at':(now()+timedelta(minutes=30)).isoformat(),
            'state':db.get(Conversation, claims['conversation_id']).state,
            'lead_captured':bool(lead_details(db, db.get(Conversation, claims['conversation_id']))),
            'voice_input_available':bool(settings.capabilities()['stt'] and installation.theme.get('voice_input_enabled',True)),
            'greeting':installation.theme.get('welcome_message') or config.get('greeting','How can I help?'), 'theme':public_theme(installation),
            'history':[{'role':x.role,'text':x.text_content, **x.metadata_data} for x in reversed(history)],
            'voice_available':bool(installation.theme.get('voice_enabled') and live_voice_ready(config, installation.workspace_id)),
            'mode':'live-llm' if resolve(config,installation.workspace_id)['api_key'] else 'deterministic-development'}


@router.post('/sessions/resume')
def resume_session(request: Request):
    claims = verify_capability(request.headers.get('authorization','').removeprefix('Bearer '), 'widget-resume')
    if claims['origin'] != request.headers.get('origin'): raise HTTPException(403, 'Widget session origin does not match')
    with session_scope() as db:
        installation = owned(db, Installation, claims['workspace_id'], claims['installation_id'])
        if not installation.enabled or not installation_allows_origin(installation,claims['origin']): raise HTTPException(403, 'This widget is disabled')
        check_widget_claims(installation, claims)
        agent = owned(db, Agent, installation.workspace_id, installation.agent_id)
        if agent.archived: raise HTTPException(403, 'This agent is unavailable')
        owned(db, Conversation, claims['workspace_id'], claims['conversation_id'])
        version = owned(db, AgentVersion, claims['workspace_id'], claims['agent_version_id'])
        if version.agent_id != installation.agent_id: raise HTTPException(403, 'This widget agent has changed; reconnect')
        context = db.scalar(select(ConversationContext).where(ConversationContext.workspace_id == claims['workspace_id'], ConversationContext.conversation_id == claims['conversation_id']))
        bot_challenge.enforce_session(context)
        config = widget_config(bind_variables(version.config, context.variables if context else {}),installation.theme)
        return session_response(db, installation, claims, config)



@router.get('/installations/{public_id}')
@router.post('/installations/{public_id}')
def public_configuration(public_id: str, request: Request, public_key: str | None = None):
    with session_scope() as db:
        installation = db.scalar(select(Installation).where(Installation.public_id == public_id, Installation.enabled.is_(True)))
        if not installation or not installation_allows_origin(installation,request.headers.get('origin', '')):
            raise HTTPException(403, 'This assistant is unavailable for this website')
        check_public_key(installation, public_key)
        agent = owned(db, Agent, installation.workspace_id, installation.agent_id)
        if agent.archived or not agent.published_version_id:
            raise HTTPException(409, 'This assistant is unavailable')
        config = owned(db, AgentVersion, installation.workspace_id, agent.published_version_id).config
        preview_user=bot_challenge.dashboard_preview_user(request,installation,db)
        return {'name': config['name'], 'variables': config.get('variables', []), 'theme': public_theme(installation),
                'challenge':{**bot_challenge.public_configuration(),'required':bot_challenge.required() and not preview_user}}


@router.get('/installations/{public_id}/logo')
async def widget_logo(public_id:str,public_key:str=''):
    with session_scope() as db:
        installation=db.scalar(select(Installation).where(Installation.public_id==public_id,Installation.enabled.is_(True)))
        if not installation:raise HTTPException(404,'Logo unavailable')
        check_public_key(installation,public_key)
        key=installation.theme.get('logo_object_key')
        mime=installation.theme.get('logo_content_type')
        if not key or mime not in {'image/png','image/jpeg','image/webp'}:raise HTTPException(404,'Logo unavailable')
        workspace_id=installation.workspace_id
    from .storage import get_store
    try:body=await asyncio.to_thread(get_store().get,workspace_id,key)
    except FileNotFoundError:raise HTTPException(404,'Logo unavailable')
    return Response(body, media_type=mime, headers={'Cache-Control': 'public, max-age=86400, stale-while-revalidate=604800'})


@router.post("/sessions", status_code=201)
async def public_session(body: PublicSession, request: Request):
    limiter.check("widget-session:" + (request.client.host if request.client else "unknown"), 30, 60)
    origin = request.headers.get("origin", "")
    if sum(len(key) + len(value) for key, value in body.variables.items()) > 8000:
        raise HTTPException(413, 'Conversation context is too large')
    with session_scope() as proof_db:
        candidate=proof_db.scalar(select(Installation).where(Installation.public_id==body.installation_public_id,Installation.enabled.is_(True)))
        if not candidate or not installation_allows_origin(candidate,origin):raise HTTPException(403,'Installation is unavailable for this origin')
        check_public_key(candidate,body.public_key)
        limiter.check('widget-install-session:'+candidate.id,60,60)
        preview_user=bot_challenge.dashboard_preview_user(request,candidate,proof_db)
    remote_ip=request.client.host if request.client else ''
    if not preview_user:await bot_challenge.enforce(body.bot_token,remote_ip,origin)
    with session_scope(write=True) as db:
        installation = db.scalar(select(Installation).where(Installation.public_id == body.installation_public_id, Installation.enabled.is_(True)))
        if not installation or not installation_allows_origin(installation,origin):
            raise HTTPException(403, "Installation is unavailable for this origin")
        check_public_key(installation, body.public_key)
        agent = owned(db, Agent, installation.workspace_id, installation.agent_id)
        if agent.archived or not agent.published_version_id:
            raise HTTPException(409, "This widget agent is not published")
        version = owned(db, AgentVersion, installation.workspace_id, agent.published_version_id)
        if installation.theme.get('collect_email', False) and not body.visitor_email:
            raise HTTPException(422, 'Enter your email address to start the conversation')
        widget_protection.require_admission(db,installation,remote_ip,'session','session:'+uid())
        bound = widget_config(bind_variables(version.config, body.variables),installation.theme)
        conversation = Conversation(workspace_id=installation.workspace_id, installation_id=installation.id)
        db.add(conversation); db.flush()
        from .metering import record_usage
        record_usage(db,installation.workspace_id,'conversation:'+conversation.id,'conversations',1,scope_id=conversation.id)
        visitor = {}
        if body.visitor_email:
            proof = {'source':'widget_email_form','conversation_id':conversation.id,'installation_id':installation.id,
                     'origin':origin,'captured_at':now().isoformat(),'email_verified':False}
            lead = Lead(workspace_id=installation.workspace_id, name=body.visitor_email.split('@')[0], email=body.visitor_email, stage='new', evidence=json.dumps(proof))
            db.add(lead); db.flush()
            visitor = {'_widget_lead':{'email':body.visitor_email,'lead_id':lead.id, **proof}}
            emit(db, installation.workspace_id, 'lead.created', {'lead_id':lead.id})
        emit(db, installation.workspace_id, 'conversation.started', {'conversation_id':conversation.id})
        db.add(ConversationContext(workspace_id=installation.workspace_id, conversation_id=conversation.id,
                                   variables={**{k: v for k, v in bound['_runtime_variables'].items()
                                              if k in {x['name'] for x in version.config.get('variables', [])}}, **visitor,
                                              '_bot_verified':bool(bot_challenge.required()),
                                              **({'_dashboard_preview_user_id':preview_user} if preview_user else {})}))
        claims = {"workspace_id": installation.workspace_id, "conversation_id": conversation.id, "installation_id": installation.id, "agent_version_id": agent.published_version_id, "origin": origin,
                  'key_revision':__import__('hashlib').sha256(installation.theme.get('publishable_key','').encode()).hexdigest()}
        return session_response(db, installation, claims, bound)



def widget_voice_context(request, db):
    token = request.headers.get('authorization', '').removeprefix('Bearer ')
    claims = verify_capability(token, 'widget')
    origin = request.headers.get('origin', '')
    if origin not in {claims['origin'], settings.app_origin, settings.app_origin.replace('localhost', '127.0.0.1')}:
        raise HTTPException(403, 'Voice session origin does not match')
    installation = owned(db, Installation, claims['workspace_id'], claims['installation_id'])
    if not installation.enabled or not installation_allows_origin(installation,claims['origin']) or not installation.theme.get('voice_enabled'):
        raise HTTPException(403, 'Voice is unavailable for this website')
    check_widget_claims(installation, claims)
    agent = owned(db, Agent, claims['workspace_id'], installation.agent_id)
    if agent.archived:
        raise HTTPException(403, 'This agent is unavailable')
    return claims, installation


@router.post('/voice/sessions', status_code=201)
def widget_voice_start(body: PublicVoiceSession, request: Request):
    with session_scope(write=True) as db:
        claims, installation = widget_voice_context(request, db)
        if installation.public_id != body.installation_public_id:
            raise HTTPException(403, 'Voice installation does not match')
        version = owned(db, AgentVersion, claims['workspace_id'], claims['agent_version_id'])
        if version.agent_id != installation.agent_id: raise HTTPException(403, 'This widget agent has changed; reconnect')
        context = db.scalar(select(ConversationContext).where(ConversationContext.workspace_id == claims['workspace_id'],
                            ConversationContext.conversation_id == claims['conversation_id']))
        bot_challenge.enforce_session(context)
        if db.get(Conversation, claims['conversation_id']).state != 'open':
            raise HTTPException(409, 'AI voice is paused while the team handles this conversation')
        config = widget_config(bind_variables(version.config, context.variables if context else {}),installation.theme)
        from .llm import live_voice_ready
        if not live_voice_ready(config, claims['workspace_id']):
            raise HTTPException(409, 'Voice is temporarily unavailable. You can still chat with this agent.')
        widget_protection.require_admission(db,installation,request.client.host if request.client else '',
                                            'voice','voice:'+uid())
        admit_voice(db, claims['workspace_id'])
        call = Call(workspace_id=claims['workspace_id'], agent_version_id=version.id,
                    agent_name=config['name'], transport='browser', mode='live',
                    metadata_data={'widget_installation_id': installation.id, 'widget_origin': claims['origin'],
                                   'conversation_id': claims['conversation_id'], 'variables': context.variables if context else {},
                                   'widget_key_revision':claims.get('key_revision'),
                                   'page_url': __import__('studio.website_actions', fromlist=['clean_page_url']).clean_page_url(body.page_url, installation.allowed_origins),
                                   'installation_max_duration_ms':widget_protection.policy(db,installation)['voice_max_seconds']*1000})
        db.add(call); db.flush()
        from .admission import admit_voice as admit_plan_voice
        admit_plan_voice(db,call,config)
        admit_turn(db, claims['workspace_id'], 'voice-start:' + call.id)
        token = capability({'aud': 'media', 'workspace_id': claims['workspace_id'], 'call_id': call.id, 'nonce': uid()}, ttl=120)
        origin = settings.public_api_origin.replace('https://', 'wss://').replace('http://', 'ws://')
        return {'call_id': call.id, 'session_token': token, 'media_url': origin + '/v1/media'}


@router.post('/voice/sessions/{call_id}/stop')
def widget_voice_stop(call_id: str, request: Request):
    with session_scope(write=True) as db:
        claims = verify_capability(request.headers.get('authorization', '').removeprefix('Bearer '), 'widget')
        if request.headers.get('origin', '') not in {claims['origin'], settings.app_origin, settings.app_origin.replace('localhost', '127.0.0.1')}:
            raise HTTPException(403, 'Voice session origin does not match')
        call = owned(db, Call, claims['workspace_id'], call_id)
        if call.metadata_data.get('conversation_id') != claims['conversation_id'] or call.metadata_data.get('widget_installation_id') != claims['installation_id']:
            raise HTTPException(403, 'Call is outside this widget session')
        from .domain import settle_call
        elapsed = int((now() - call.connected_at).total_seconds() * 1000) if call.connected_at else 0
        settle_call(db, call, elapsed)
        return {'status': 'ended'}


@router.post("/chat")
async def public_chat(body: ChatRequest, request: Request):
    token = request.headers.get("authorization", "").removeprefix("Bearer ")
    claims = verify_capability(token, "widget")
    if claims.get("origin") != request.headers.get("origin"):
        raise HTTPException(403, "Widget session origin does not match")
    if body.session_id != claims["conversation_id"]:
        raise HTTPException(403, "Conversation is outside this widget session")
    limiter.check("widget-chat:" + claims["conversation_id"], 30, 60)
    workspace_id = claims["workspace_id"]
    with session_scope(write=True) as db:
        installation = owned(db, Installation, workspace_id, claims["installation_id"])
        if not installation.enabled or not installation_allows_origin(installation,claims['origin']):
            raise HTTPException(403, "Widget installation was disabled")
        check_widget_claims(installation, claims)
        agent = owned(db, Agent, workspace_id, installation.agent_id)
        if agent.archived: raise HTTPException(403, "This agent is unavailable")
        conversation = db.scalar(select(Conversation).where(Conversation.workspace_id == workspace_id, Conversation.id == body.session_id).with_for_update())
        if not conversation or conversation.installation_id != installation.id: raise HTTPException(403, 'Conversation is unavailable')
        if conversation.state == 'resolved': raise HTTPException(409, 'This conversation is closed')
        human_mode = conversation.state == 'human'
        version = owned(db, AgentVersion, workspace_id, claims["agent_version_id"])
        if version.agent_id != installation.agent_id: raise HTTPException(403, "This widget agent has changed; reconnect")
        context = db.scalar(select(ConversationContext).where(ConversationContext.workspace_id == workspace_id,
                            ConversationContext.conversation_id == conversation.id))
        bot_challenge.enforce_session(context)
        config = widget_config(bind_variables(version.config, context.variables if context else {}),installation.theme)
        existing = db.scalar(select(Message).where(Message.workspace_id == workspace_id, Message.conversation_id == body.session_id, Message.client_message_id == body.client_message_id, Message.role == "assistant"))
        user_message = db.scalar(select(Message).where(Message.workspace_id == workspace_id, Message.conversation_id == body.session_id, Message.client_message_id == body.client_message_id, Message.role == "user"))
        if user_message and (user_message.text_content != body.message or user_message.metadata_data.get('confirmation_id') != body.confirmation_id):
            raise HTTPException(409, "Message identity was used with different text")
        if existing and existing.metadata_data.get('streaming'):
            raise HTTPException(409, 'This reply is already being generated')
        generation_id = uid()
        if existing:
            existing_data = as_dict(existing)
        else:
            existing_data = None
            if not user_message:
                widget_protection.require_admission(db,installation,request.client.host if request.client else '',
                    'turn','chat:'+body.session_id+':'+body.client_message_id)
                admit_turn(db, workspace_id, 'widget:' + body.session_id + ':' + body.client_message_id)
                from .metering import record_usage
                record_usage(db,workspace_id,'chat-turn:'+body.session_id+':'+body.client_message_id,'chat_turns',1,scope_id=body.session_id)
                db.add(Message(workspace_id=workspace_id, conversation_id=body.session_id, client_message_id=body.client_message_id, role="user", text_content=body.message, metadata_data={'confirmation_id':body.confirmation_id}))
                emit(db, workspace_id, 'conversation.message', {'conversation_id':conversation.id})
                db.flush()
            if not human_mode:
                db.add(Message(id=generation_id, workspace_id=workspace_id, conversation_id=body.session_id, client_message_id=body.client_message_id, role='assistant', text_content='', metadata_data={'streaming':True}))
        recent = list(db.scalars(select(Message).where(Message.workspace_id == workspace_id,
                                 Message.conversation_id == body.session_id,
                                 Message.client_message_id != body.client_message_id)
                                 .order_by(Message.created_at.desc(), Message.id.desc()).limit(24)))
        history = [{"role": x.role, "text": x.text_content, "interrupted":bool(x.metadata_data.get("interrupted"))} for x in reversed(recent) if x.role in {"user", "assistant", "operator"}]
        for turn in history:
            if turn["role"] == "operator": turn["role"] = "assistant"
        from .website_actions import corpus, clean_page_url
        sources, product_rows = corpus(db, workspace_id, config.get('knowledge_snapshot_ids', []))
        page_url = clean_page_url(body.page_url, installation.allowed_origins)
        page_source = next((as_dict(s) for s in sources if s.canonical_url == page_url), None)
        website_enabled = bool(installation.theme.get('website_actions'))
        installation_id = installation.id


    def event(kind, data):
        return "event: " + kind + "\ndata: " + json.dumps(data, ensure_ascii=False) + "\n\n"

    async def stream():
        if human_mode:
            yield event('chat.human_queued', {'state':'human'})
            return
        if existing_data:
            yield event("chat.text.delta", {"text": existing_data["text_content"]})
            yield event("chat.completed", {"message_id": existing_data["id"], "text": existing_data["text_content"], **existing_data["metadata_data"]})
            return
        message_id, text, metadata = generation_id, "", {"products": [], "citations": []}
        yield event("chat.message.started", {"conversation_id": body.session_id, "message_id": message_id})
        previous = history[-1] if history else {}
        safety_context = {'workspace_id':workspace_id,'conversation_id':body.session_id,
                          'installation_id':installation_id,'operation_id':body.session_id+':'+body.client_message_id,'user_text':body.message,
                          'last_assistant_text':previous.get('text','') if previous.get('role')=='assistant' and not previous.get('interrupted') else ''}
        try:
            from .handoff import reply as safety_reply
            safe_response = await safety_reply(config, safety_context, body.confirmation_id)
            if safe_response is not None:
                text = safe_response['text']
                metadata.update({key:value for key,value in safe_response.items() if key != 'text'})
                if metadata.get('ticket_id'):
                    yield event('chat.ticket.created', {'ticket_id':metadata['ticket_id']})
                if metadata.get('confirmation'):
                    yield event('chat.confirmation.required', metadata['confirmation'])
                yield event('chat.text.delta', {'text':text})
            else:
                from .website_actions import ranked_products, execute as website_execute
                search_query = body.message
                if page_source and re.search(r'\b(this|that|it|its)\b', body.message, re.I): search_query += ' ' + page_source['title']
                result = await retrieve(workspace_id, config.get("knowledge_snapshot_ids", []), search_query)
                passages = result["passages"] if result["answerable"] else []
                if page_source and re.search(r'\b(this|that|it|its)\b', body.message, re.I):
                    passages = [{'url':page_url,'text':page_source['text_content'][:10000],'title':page_source['title']}, *[p for p in passages if p['url'] != page_url]][:6]
                from .prompt_safety import public_passages, sanitized
                passages = public_passages(passages)
                matches = sanitized(ranked_products(product_rows, body.message, page_url, history), private_endpoint=True)
                requested_terms = set(re.findall(r"\w+", body.message.lower()))
                price_query = bool(requested_terms.intersection({"price", "cost", "engraving", "engrave", "customization", "personalised", "personalized"}))

                live_model = bool(resolve(config, workspace_id)['api_key'])
                tool_events = []
                async def website_event(data):
                    if data.get('actions'): metadata.setdefault('actions', []).extend(data['actions'])
                    if data.get('products'): metadata['products'] = data['products']
                    tool_events.append(data)
                async def safety_event(data):
                    metadata.update(data)
                tool_context = {**safety_context,'workspace_id':workspace_id,'conversation_id':body.session_id,'user_text':body.message,
                                'operation_id':body.session_id+':'+body.client_message_id,'installation_id':installation_id,
                                'knowledge_snapshot_ids':config.get('knowledge_snapshot_ids',[]),'website_actions':website_enabled,
                                'page_url':page_url,'history':history,'emit_website':website_event,'emit_safety':safety_event}
                if not live_model and matches and website_enabled and re.search(r'\b(open|show|take|navigate|visit|go)\b',body.message,re.I):
                    from .tool_safety import admit_attempt
                    await asyncio.to_thread(admit_attempt,tool_context,'website_open_page','development-navigation')
                    action_result = await asyncio.to_thread(website_execute,'website_open_page', {'url':matches[0]['canonical_url']}, tool_context)
                    await website_event(action_result)
                if not live_model and price_query and matches:
                    selected = matches[:3]
                    metadata["products"] = selected
                    product = selected[0]
                    text = f"{product['title']} is {product['currency']} {product['price_minor']/100:g}."
                    if product["customization_max_chars"] is not None:
                        text += f" The engraving limit is {product['customization_max_chars']} characters."
                    if product["availability"] == "unknown":
                        text += " Current stock has not been verified."
                    yield event("chat.products", {"products": selected})
                    yield event("chat.text.delta", {"text": text})
                else:
                    async for delta in answer_stream(config, body.message, passages, history, tool_context):
                        text += delta
                        yield event("chat.text.delta", {"text": delta})
                if matches and not metadata['products']: metadata['products'] = matches[:3]
                for data in tool_events:
                    if data.get('actions'): yield event('chat.actions', {'actions':data['actions']})
                if metadata['products']: yield event('chat.products', {'products':metadata['products']})
                metadata["citations"] = passages
                yield event("chat.citations", {"citations": passages})
            with session_scope(write=True) as db:
                existing = db.scalar(select(Message).where(Message.workspace_id == workspace_id, Message.conversation_id == body.session_id, Message.client_message_id == body.client_message_id, Message.role == "assistant"))
                row = db.scalar(select(Conversation).where(Conversation.workspace_id == workspace_id, Conversation.id == body.session_id).with_for_update())
                if row.state != 'open': return
                if existing and not existing.metadata_data.get('streaming'):
                    message_id, text, metadata = existing.id, existing.text_content, existing.metadata_data
                elif existing:
                    existing.text_content, existing.metadata_data = text.strip(), metadata
                else:
                    db.add(Message(id=message_id, workspace_id=workspace_id, conversation_id=body.session_id, client_message_id=body.client_message_id, role="assistant", text_content=text.strip(), metadata_data=metadata))
            if metadata.get('confirmation'):
                from .tool_safety import mark_presented
                await asyncio.to_thread(mark_presented,safety_context,metadata['confirmation']['id'],text.strip())
            yield event("chat.completed", {"message_id": message_id, "text": text.strip(), **metadata})
        except asyncio.CancelledError:
            raise
        except HTTPException as error:
            limit = error.status_code == 429
            yield event('chat.failed', {'code':'tool_limit' if limit else 'confirmation_required',
                'message':str(error.detail) if limit else 'The action needs a current confirmation and permission check.',
                'retryable':False})
        except Exception:
            import logging
            logging.getLogger(__name__).exception("Widget generation failed")
            yield event("chat.failed", {"code": "generation_failed", "message": "The response could not be completed. Please retry.", "retryable": True})
    async def monitored():
        # A separate DB read notices takeover even while retrieval/model generation awaits.
        import contextlib
        source = stream()
        pending = None
        partial_id, partial_text, last_save = (generation_id if not existing_data else None), '', 0.0
        completed = False
        async def save_partial(interrupted=False):
            if not partial_id: return
            with session_scope(write=True) as db:
                row = db.scalar(select(Conversation).where(Conversation.workspace_id == workspace_id, Conversation.id == body.session_id).with_for_update())
                existing = db.get(Message, partial_id)
                if existing and not existing.metadata_data.get('streaming'): return
                stopped = interrupted or row.state != 'open'
                data = {'streaming':not stopped, 'interrupted':stopped}
                if existing:
                    existing.text_content = partial_text
                    existing.metadata_data = data
                elif row.state == 'open' or interrupted:
                    db.add(Message(id=partial_id, workspace_id=workspace_id, conversation_id=body.session_id, client_message_id=body.client_message_id, role='assistant', text_content=partial_text, metadata_data=data))
        try:
            while True:
                if not pending: pending = asyncio.create_task(anext(source))
                done, _ = await asyncio.wait({pending}, timeout=.25)
                if not await asyncio.to_thread(ai_active, workspace_id, body.session_id):
                    await save_partial(True)
                    yield event('chat.interrupted', {'state':'human' if human_mode else 'paused'})
                    return
                if not done: continue
                try: packet = pending.result()
                except StopAsyncIteration: break
                pending = None
                data = json.loads(packet.split('data: ',1)[1])
                if packet.startswith('event: chat.message.started'): partial_id = data['message_id']
                if packet.startswith('event: chat.text.delta'):
                    partial_text += data['text']
                    clock = asyncio.get_running_loop().time()
                    if clock - last_save > .5:
                        await save_partial(); last_save = clock
                if packet.startswith('event: chat.completed'): completed = True
                yield packet
        finally:
            if pending:
                pending.cancel()
                with contextlib.suppress(asyncio.CancelledError, StopAsyncIteration): await pending
            await source.aclose()
            if not completed: await save_partial(True)
    return StreamingResponse(stream() if human_mode else monitored(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import asyncio
import hashlib
import io
import json
import secrets
from fastapi import APIRouter, Depends, Request, HTTPException, UploadFile, File
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select, func
from .config import settings
from .db import as_dict, now, uid
from .models import *
from .schemas import *
from .security import principal, Principal, db_dependency, audit, capability, digest
from .domain import *
from .knowledge import canonical_url, validate_public_url, retrieve, add_source
from .storage import get_store,put_checked

router = APIRouter(prefix="/v1/workspaces/{workspace_id}")


# A closed page vocabulary limits reads without changing the legacy full bootstrap.
BOOTSTRAP_VIEWS = {
    'overview': ['agents', 'knowledge', 'calls', 'jobs'],
    'agents': ['agents', 'knowledge', 'models', 'tools', 'connections', 'jobs'],
    'knowledge': ['knowledge', 'jobs'], 'calls': ['calls', 'agents', 'numbers'],
    'voice': ['agents'], 'products': ['stores', 'products', 'jobs'],
    'widget': ['agents', 'installations'], 'campaigns': ['campaigns', 'agents', 'numbers'],
    'inbox': ['tickets', 'conversations'], 'leads': ['leads'], 'contacts': ['agents'],
    'billing': ['ledger'], 'developers': ['keys', 'webhooks', 'deliveries'],
    'integrations': ['connections', 'leads', 'appointments'], 'operations': [],
    'tools': ['tools', 'tool-executions', 'agents'], 'models': ['models'],
    'appointments': ['appointments', 'leads', 'connections'], 'numbers': ['numbers', 'agents'],
    'team': ['members'], 'settings': [], 'templates': [], 'profile': [], 'summary': [],
}


@router.get("/bootstrap")
def bootstrap(workspace_id: str, view: str | None = None, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    # Reuse the resource handlers so their scope checks and secret redaction stay
    # identical, with one authenticated request/connection for dashboard refresh.
    from . import operations_routes as ops
    from .http_tools import tools,executions
    from .model_routes import models
    handlers = {
        "agents": agents, "knowledge": knowledge_list, "calls": calls,
        "stores": ops.stores, "products": ops.products, "campaigns": ops.campaigns,
        "conversations": ops.conversations, "tickets": ops.tickets, "leads": ops.leads,
        "numbers": ops.numbers, "connections": ops.connections, "appointments": ops.appointments,
        "keys": keys, "webhooks": ops.webhooks, "deliveries": ops.deliveries,
        "jobs": jobs, "members": members, "ledger": ledger, "installations": ops.installations,
        'tools':tools,'models':models,'tool-executions':executions,
    }
    output = {"summary": {}, "data": {}, "denied": []}
    if view is not None and view not in BOOTSTRAP_VIEWS:
        raise HTTPException(422, 'Unknown workspace view')
    selected = {'summary': summary, **handlers} if view is None else (
        {'summary': summary} if view == 'summary' else {name: handlers[name] for name in BOOTSTRAP_VIEWS[view]})
    for name, handler in selected.items():
        try:
            result = handler(workspace_id, actor=actor, db=db)
        except HTTPException as exc:
            if exc.status_code != 403:
                raise
            output["denied"].append(name)
            continue
        if name == "summary":
            output["summary"] = result
        else:
            output["data"][name] = result["items"]
    return output


@router.get("/summary")
def summary(workspace_id: str, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("dashboard:read")
    from .phone_trials import trial_status
    phone_trial = {'status': 'not_assigned'}
    try:
        actor.require('calls:read')
        phone_trial = trial_status(db, workspace_id)
    except HTTPException as exc:
        if exc.status_code != 403:
            raise
    today = now().date()
    call_count, connected_ms = db.execute(select(func.count(Call.id), func.coalesce(func.sum(Call.connected_ms), 0)).where(Call.workspace_id == workspace_id)).one()
    # Aggregate in SQL; never hydrate the entire call history for dashboard totals.
    dates = db.execute(select(func.date(Call.created_at), func.count(Call.id)).where(
        Call.workspace_id == workspace_id, func.date(Call.created_at) >= today - timedelta(days=13),
        func.date(Call.created_at) <= today).group_by(func.date(Call.created_at))).all()
    daily = {str(date): count for date, count in dates}
    return {
        "phone_trial": phone_trial,
        "calls": call_count, "connected_seconds": connected_ms // 1000,
        "agents": db.scalar(select(func.count()).select_from(Agent).where(Agent.workspace_id == workspace_id, Agent.archived.is_(False))),
        "published_agents": db.scalar(select(func.count()).select_from(Agent).where(Agent.workspace_id == workspace_id, Agent.published_version_id.is_not(None))),
        "knowledge_bases": db.scalar(select(func.count()).select_from(KnowledgeBase).where(KnowledgeBase.workspace_id == workspace_id)),
        "open_tickets": db.scalar(select(func.count()).select_from(Ticket).where(Ticket.workspace_id == workspace_id, Ticket.state != "resolved")),
        "new_leads": db.scalar(select(func.count()).select_from(Lead).where(Lead.workspace_id == workspace_id, Lead.stage == "new")),
        "wallet": wallet_state(db, workspace_id),
        "daily_calls": [{"date": (today - timedelta(days=i)).isoformat(), "count": daily.get((today - timedelta(days=i)).isoformat(), 0)} for i in reversed(range(14))],
        "capabilities": workspace_capabilities(db,workspace_id),
    }


def workspace_capabilities(db,workspace_id):
    caps=settings.capabilities()
    from .carrier_config import telephony_ready, credentials as carrier_credentials
    caps['telephony_providers'] = [provider for provider in ['plivo', 'twilio'] if carrier_credentials(provider, workspace_id).get('auth_token')]
    caps['telephony'] = telephony_ready(workspace_id)
    from .phone_trials import trial_status
    trial = trial_status(db, workspace_id)
    if trial['status'] != 'not_assigned' and 'twilio' not in caps['telephony_providers']:
        caps['telephony_providers'].append('twilio')
    from .scheduling_oauth import configured
    caps['scheduling_oauth'] = {provider:configured(provider) for provider in ['calcom','calendly']}
    caps['google_calendar_oauth'] = bool(settings.google_client_id and settings.google_client_secret)
    if db.scalar(select(LLMProfile.id).where(LLMProfile.workspace_id==workspace_id,LLMProfile.enabled.is_(True)).limit(1)):
        caps['llm']=True
        if settings.voice_provider == 'legacy':
            caps['live_voice']=bool(settings.fish_api_key and settings.fish_voice_id and settings.deepgram_api_key)
    return caps


@router.get("/capabilities")
def capabilities(workspace_id: str, actor=Depends(principal),db=Depends(db_dependency,scope='function')):
    actor.require("settings:read")
    return workspace_capabilities(db,workspace_id)


@router.get("/knowledge")
def knowledge_list(workspace_id: str, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("kb:read")
    return {"items": page(db, KnowledgeBase, workspace_id)}


@router.post("/knowledge", status_code=202)
async def knowledge_create(workspace_id: str, body: KBCreate, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("kb:write")
    await validate_public_url(body.website_url)
    kb = KnowledgeBase(workspace_id=workspace_id, name=body.name, website_url=canonical_url(body.website_url))
    db.add(kb)
    db.flush()
    job = enqueue(db, workspace_id, "crawl", {"kb_id": kb.id, "max_pages": body.max_pages})
    audit(db, actor, "kb.created", kb.id)
    return {**as_dict(job), "kb_id": kb.id}


@router.get("/knowledge/{kb_id}")
def kb_get(workspace_id: str, kb_id: str, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("kb:read")
    return as_dict(owned(db, KnowledgeBase, workspace_id, kb_id))


@router.patch("/knowledge/{kb_id}")
def kb_update(workspace_id: str, kb_id: str, body: KBUpdate, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("kb:write")
    kb = owned(db, KnowledgeBase, workspace_id, kb_id)
    if kb.status=="deleting":raise HTTPException(409,"This knowledge is being deleted")
    for key, value in body.model_dump(exclude_none=True).items():
        setattr(kb, key, value)
    audit(db, actor, "kb.updated", kb.id)
    return as_dict(kb)


@router.get("/knowledge/{kb_id}/sources")
def kb_sources(workspace_id: str, kb_id: str, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("kb:read")
    owned(db, KnowledgeBase, workspace_id, kb_id)
    return {"items": [{k: v for k, v in row.items() if k != "text_content"} for row in page(db, Source, workspace_id, kb_id=kb_id)]}


@router.post("/knowledge/{kb_id}/recrawls", status_code=202)
def recrawl(workspace_id: str, kb_id: str, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("kb:write")
    kb = owned(db, KnowledgeBase, workspace_id, kb_id)
    if kb.status=="deleting":raise HTTPException(409,"This knowledge is being deleted")
    active = db.scalar(select(Job).where(Job.workspace_id == workspace_id, Job.kind == "crawl", Job.state.in_(["queued", "running"])))
    if active and active.payload.get("kb_id") == kb_id:
        return as_dict(active)
    kb.status = "processing"
    return as_dict(enqueue(db, workspace_id, "crawl", {"kb_id": kb.id, "max_pages": 20}))


@router.post("/knowledge/{kb_id}/query")
async def query(workspace_id: str, kb_id: str, body: Query, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("kb:read")
    kb = owned(db, KnowledgeBase, workspace_id, kb_id)
    if kb.status=="deleting":raise HTTPException(409,"This knowledge is being deleted")
    snapshots = [kb.active_snapshot_id] if kb.active_snapshot_id else []
    db.commit()
    return await retrieve(workspace_id, snapshots, body.query, body.limit)


@router.post("/knowledge/{kb_id}/documents", status_code=202)
async def document(workspace_id: str, kb_id: str, file: UploadFile = File(...), actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("kb:write")
    kb=owned(db, KnowledgeBase, workspace_id, kb_id)
    if kb.status=="deleting":raise HTTPException(409,"This knowledge is being deleted")
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".txt", ".pdf", ".docx"}:
        raise HTTPException(422, "Upload TXT, PDF or DOCX")
    body = await file.read(20_000_001)
    if len(body) > 20_000_000:
        raise HTTPException(413, "Document limit is 20 MB")
    if not body:
        raise HTTPException(422, "Document is empty")
    if suffix == ".pdf" and not body.startswith(b"%PDF"):
        raise HTTPException(422, "File contents are not a PDF")
    if suffix == ".docx" and not body.startswith(b"PK"):
        raise HTTPException(422, "File contents are not a DOCX")
    db.commit()
    key = await asyncio.to_thread(put_checked, workspace_id, "documents", body, file.content_type or "application/octet-stream")
    from .metering import stored
    stored(db,workspace_id,key,len(body))
    return as_dict(enqueue(db, workspace_id, "document", {"kb_id": kb_id, "object_key": key, "filename": file.filename, "suffix": suffix}))


@router.get("/jobs")
def jobs(workspace_id: str, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("kb:read")
    return {"items": page(db, Job, workspace_id)}


@router.get("/jobs/{job_id}")
def job_get(workspace_id: str, job_id: str, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("kb:read")
    return as_dict(owned(db, Job, workspace_id, job_id))


@router.post("/jobs/{job_id}/cancel")
def job_cancel(workspace_id: str, job_id: str, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("kb:write")
    job = db.scalar(select(Job).where(Job.workspace_id == workspace_id, Job.id == job_id).with_for_update())
    if not job: raise HTTPException(404, "Resource not found")
    if job.kind.startswith('billing_') or job.kind=='invoice_pdf':actor.require('billing:write')
    if job.kind=='agent_delete':raise HTTPException(409,'Permanent deletion cannot be canceled after confirmation')
    if job.state not in {"completed", "failed", "canceled"}:
        job.cancel_requested = True
        if job.state == "queued":
            job.state, job.phase = "canceled", "canceled"
            if job.kind == "crawl":
                kb = owned(db, KnowledgeBase, workspace_id, job.payload["kb_id"])
                kb.status = "ready" if kb.active_snapshot_id else "canceled"
        else:
            job.phase = "stopping"
    return as_dict(job)


@router.post("/jobs/{job_id}/retry", status_code=202)
def job_retry(workspace_id: str, job_id: str, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("kb:write")
    job = owned(db, Job, workspace_id, job_id)
    if job.kind.startswith('billing_') or job.kind=='invoice_pdf':actor.require('billing:write')
    if job.kind=='agent_delete' and (not actor.user_id or actor.role not in {'owner','admin'}):raise HTTPException(403,'Only an owner or admin can retry permanent deletion')
    if job.state not in {"failed", "canceled"}:
        raise HTTPException(409, "Only failed or canceled jobs may be retried")
    job.state, job.error, job.cancel_requested, job.lease_until = "queued", None, False, None
    return as_dict(job)


@router.get("/agents")
def agents(workspace_id: str, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("agents:read")
    return {"items": page(db, Agent, workspace_id, archived=False)}


@router.post("/agents/generate")
async def generate_agent(workspace_id: str, body: Brief, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("agents:write")
    from .security import limiter
    limiter.check("agent-generation:" + workspace_id, 10, 3600)
    from .llm import resolve
    generation_config={}
    if not settings.openai_api_key:
        profile=db.scalar(select(LLMProfile).where(LLMProfile.workspace_id==workspace_id,LLMProfile.enabled.is_(True)).limit(1))
        if profile:generation_config={'llm':{'profile_id':profile.id}}
    generation_profile=resolve(generation_config,workspace_id)
    db.commit()
    async def stream():
        def packet(kind, data):
            return "event: " + kind + "\ndata: " + json.dumps(data) + "\n\n"
        yield packet("generation.started", {"stage": "brief", "mode": "compatible-model" if generation_profile['api_key'] else "development-template"})
        yield packet("generation.stage", {"stage": "business_profile", "status": "completed", "source": "user-supplied-goal"})
        yield packet("generation.stage", {"stage": "script", "status": "running"})
        script = ""
        try:
            if generation_profile['api_key']:
                from .llm import Turn,environment_profile
                turn=Turn(generation_profile,"Write original instructions for a concise AI business assistant. Use the goal as a goal, not verified business facts. Do not invent prices, policies, names, connected tools or completed actions. Include grounding, missing-information handling and escalation only after a real ticket result.",[{'role':'user','content':'Goal: '+body.goal+'\nLanguage: '+body.language+'\nBusiness URL (not fetched here): '+body.business_url}],limit=1600)
                async for delta in turn.stream():
                    script+=delta
                    yield packet('generation.text.delta',{'text':delta})
            else:
                script = (
                    "ROLE AND GOAL\nYou are an AI business assistant. Your goal is: " + body.goal
                    + "\n\nCONVERSATION\nIntroduce yourself as an AI assistant. Ask one question at a time. Listen to the caller and keep replies concise. Let the caller interrupt.\n\n"
                    "GROUNDED ANSWERS\nUse only connected knowledge and verified product/tool results. Do not invent prices, stock, delivery promises or policies. If evidence is missing, explain what is unknown.\n\n"
                    "ACTIONS AND HANDOFF\nNever claim that a booking, message, refund or transfer completed without a successful tool result. If the caller requests follow-up, record a support ticket before confirming the request.\n\n"
                    "ENDING\nConfirm the useful next step, then close politely. No engagement does not qualify a lead."
                )
                yield packet("generation.text.delta", {"text": script})
            yield packet("generation.stage", {"stage": "validation", "status": "completed"})
            yield packet("generation.completed", {"instructions": script, "mode": "compatible-model" if generation_profile['api_key'] else "development-template"})
        except asyncio.CancelledError:
            raise
        except Exception:
            import logging
            logging.getLogger(__name__).exception("Agent generation failed")
            yield packet("generation.failed", {"message": "The draft could not be generated. Check provider configuration and retry."})
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/agents", status_code=201)
async def agent_create(workspace_id: str, body: AgentCreate, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("agents:write")
    from .agent_deletion import lock_knowledge_for_write
    lock_knowledge_for_write(db,workspace_id,body.config or {})
    item = Agent(workspace_id=workspace_id, name=body.name, draft_config=body.config or default_agent(body.name))
    db.add(item)
    db.flush()
    audit(db, actor, "agent.created", item.id)
    if body.website_url:
        from .website_routes import create_website, WebsiteCreate
        website = await create_website(workspace_id, WebsiteCreate(website_url=body.website_url, name=body.name, agent_id=item.id), actor, db)
        return {**as_dict(item), 'website_assistant': website}
    return as_dict(item)


@router.get("/agents/{agent_id}")
def agent_get(workspace_id: str, agent_id: str, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("agents:read")
    return as_dict(owned(db, Agent, workspace_id, agent_id))


@router.put("/agents/{agent_id}/draft")
def agent_draft(workspace_id: str, agent_id: str, body: AgentDraft, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("agents:write")
    agent = owned(db, Agent, workspace_id, agent_id)
    db.refresh(agent,with_for_update=True)
    from .agent_deletion import lock_knowledge_for_write
    lock_knowledge_for_write(db,workspace_id,body.config)
    if agent.archived:raise HTTPException(409,'This agent is archived or being deleted')
    if agent.archived:raise HTTPException(409,'This agent is archived or being deleted')
    if agent.draft_revision != body.expected_revision:
        raise HTTPException(409, "Draft was changed in another tab; reload before saving")
    if not isinstance(body.config.get("name"), str) or not body.config["name"].strip():
        raise HTTPException(422, "An agent name is required")
    agent.draft_config = body.config
    agent.name = body.config["name"][:160]
    agent.draft_revision += 1
    audit(db, actor, "agent.draft_saved", agent.id, {"revision": agent.draft_revision})
    return as_dict(agent)


@router.post("/agents/{agent_id}/validate")
def agent_validate(workspace_id: str, agent_id: str, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("agents:read")
    agent = owned(db, Agent, workspace_id, agent_id)
    if agent.archived:raise HTTPException(409,'This agent is archived or being deleted')
    errors = validate_agent(db, workspace_id, agent.draft_config)
    return {"valid": not errors, "errors": errors}


@router.post("/agents/{agent_id}/publish", status_code=201)
def agent_publish(workspace_id: str, agent_id: str, body: Publish, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("agents:write")
    agent = owned(db, Agent, workspace_id, agent_id)
    db.refresh(agent,with_for_update=True)
    from .agent_deletion import lock_knowledge_for_write
    lock_knowledge_for_write(db,workspace_id,agent.draft_config)
    if agent.archived:raise HTTPException(409,'This agent is archived or being deleted')
    version = publish_agent(db, workspace_id, agent, body.expected_draft_revision)
    audit(db, actor, "agent.published", agent.id, {"version": version.version})
    return as_dict(version)


@router.get("/agents/{agent_id}/versions")
def versions(workspace_id: str, agent_id: str, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("agents:read")
    owned(db, Agent, workspace_id, agent_id)
    return {"items": page(db, AgentVersion, workspace_id, agent_id=agent_id)}


@router.get("/calls")
def calls(workspace_id: str, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("calls:read")
    return {"items": page(db, Call, workspace_id)}


@router.get("/calls/{call_id}")
def call_get(workspace_id: str, call_id: str, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("calls:read")
    call = owned(db, Call, workspace_id, call_id)
    turns = [as_dict(x) for x in db.scalars(select(Turn).where(Turn.workspace_id == workspace_id, Turn.call_id == call_id).order_by(Turn.ordinal))]
    from .voice_latency import detail as timing_detail
    return {**as_dict(call), "turns": turns, 'voice_timing':timing_detail(db,workspace_id,call_id)}


@router.post("/calls/{call_id}/stop")
def stop_call(workspace_id: str, call_id: str, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("calls:write")
    call = owned(db, Call, workspace_id, call_id)
    if call.transport == "pstn" and call.mode == "live" and call.provider_call_id:
        enqueue(db, workspace_id, "hangup", {"call_id": call.id})
        call.state = "ending"
    else:
        duration = int((now() - call.connected_at.replace(tzinfo=now().tzinfo)).total_seconds() * 1000) if call.connected_at else 0
        settle_call(db, call, duration)
    return as_dict(call)


@router.post("/voice/sessions", status_code=201)
def voice_session(workspace_id: str, body: BrowserSession, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("calls:write")
    agent = owned(db, Agent, workspace_id, body.agent_id)
    if agent.archived or not agent.published_version_id:
        raise HTTPException(409, "Publish the agent before starting a session")
    from .llm import live_voice_ready
    if body.mode == "live" and not live_voice_ready(owned(db,AgentVersion,workspace_id,agent.published_version_id).config,workspace_id):
        raise HTTPException(409, "Configure OpenAI, Fish voice and Deepgram credentials for live voice")
    bind_variables(owned(db,AgentVersion,workspace_id,agent.published_version_id).config,body.variables)
    from .usage import admit_voice, admit_turn
    admit_voice(db, workspace_id)
    call = Call(workspace_id=workspace_id, agent_version_id=agent.published_version_id, agent_name=agent.name, transport="browser", mode=body.mode,
                metadata_data={'variables':body.variables})
    db.add(call)
    db.flush()
    from .admission import admit_voice as admit_plan_voice
    admit_plan_voice(db,call,owned(db,AgentVersion,workspace_id,agent.published_version_id).config)
    admit_turn(db, workspace_id, 'voice-start:' + call.id)
    token = capability({"aud": "media", "workspace_id": workspace_id, "call_id": call.id, "nonce": secrets.token_urlsafe(12)}, ttl=120)
    origin = settings.public_api_origin.replace("https://", "wss://").replace("http://", "ws://")
    return {"id": uid(), "call_id": call.id, "session_token": token, "media_url": origin + "/v1/media", "expires_at": (now() + timedelta(seconds=120)).isoformat(), "mode": body.mode}


@router.get("/wallet")
def wallet(workspace_id: str, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("billing:read")
    return {**wallet_state(db, workspace_id), "development_credit": settings.dev_seed_enabled}


@router.get("/ledger")
def ledger(workspace_id: str, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("billing:read")
    return {"items": page(db, Ledger, workspace_id)}


@router.get("/members")
def members(workspace_id: str, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("team:read")
    return {"items": [{**as_dict(x), "name": db.get(User, x.user_id).name, "email": db.get(User, x.user_id).email} for x in db.scalars(select(Membership).where(Membership.workspace_id == workspace_id))]}


@router.get("/keys")
def keys(workspace_id: str, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("developer:read")
    return {"items": [{k: v for k, v in row.items() if k != "secret_hash"} for row in page(db, APIKey, workspace_id)]}


@router.post("/keys", status_code=201)
def create_key(workspace_id: str, body: KeyWrite, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("developer:write")
    allowed = {f"{module}:{action}" for module in ["kb", "agents", "calls", "products", "widget", "inbox", "leads", "campaigns", "appointments", "settings", "billing", "developer", "team", "dashboard"] for action in ["read", "write"]}
    if not set(body.scopes) <= allowed:
        raise HTTPException(422, "Unknown API permission scope")
    if set(body.scopes) & {"developer:write", "team:write", "billing:write"}:
        raise HTTPException(422, "Keys, team and billing changes require a dashboard session")
    if body.expires_at is not None and body.expires_at <= now():
        raise HTTPException(422, "API key expiry must be in the future")
    secret = "vs_" + secrets.token_urlsafe(32)
    item = APIKey(workspace_id=workspace_id, name=body.name, prefix=secret[:11], secret_hash=digest(secret), scopes=body.scopes,
                  expires_at=body.expires_at, requests_per_minute=body.requests_per_minute)
    db.add(item)
    db.flush()
    audit(db, actor, "api_key.created", item.id)
    return {"key": {k: v for k, v in as_dict(item).items() if k != "secret_hash"}, "secret": secret}


@router.delete("/keys/{key_id}")
def revoke_key(workspace_id: str, key_id: str, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("developer:write")
    item = owned(db, APIKey, workspace_id, key_id)
    item.revoked_at = now()
    audit(db, actor, "api_key.revoked", key_id)
    return {"status": "revoked"}


@router.get("/settings")
def settings_get(workspace_id: str, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("settings:read")
    workspace = db.get(Workspace, workspace_id)
    return {"business_name": workspace.name, "industry": workspace.settings_data.get("industry", ""), "timezone": workspace.timezone, "notifications_enabled": workspace.settings_data.get("notifications_enabled", True)}


@router.put("/settings")
def settings_put(workspace_id: str, body: SettingsWrite, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("settings:write")
    try:
        ZoneInfo(body.timezone)
    except ZoneInfoNotFoundError:
        raise HTTPException(422, "Use a valid IANA timezone")
    workspace = db.get(Workspace, workspace_id)
    workspace.name, workspace.timezone = body.business_name, body.timezone
    workspace.settings_data = {"industry": body.industry, "notifications_enabled": body.notifications_enabled}
    audit(db, actor, "workspace.settings_updated", workspace_id)
    return body.model_dump()


@router.post("/fixtures", status_code=201)
def load_fixture(workspace_id: str, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("agents:write")
    if not settings.dev_seed_enabled or settings.app_env == "production":
        raise HTTPException(404, "Fixture loader is unavailable")
    existing = db.scalar(select(KnowledgeBase).where(KnowledgeBase.workspace_id == workspace_id, KnowledgeBase.website_url == "https://example.test/"))
    if existing:
        return {"status": "already_loaded", "kb_id": existing.id}
    kb = KnowledgeBase(workspace_id=workspace_id, name="Gift studio · sample knowledge", website_url="https://example.test/", status="ready")
    db.add(kb); db.flush()
    source = add_source(db, workspace_id, kb.id, "https://example.test/products/cufflinks", "Personalised cufflinks — synthetic fixture",
                        "This is a synthetic product fixture, not a live offer. Personalised cufflinks cost INR 999. The engraving name limit is 20 characters. No refund terms or stock status have been provided.")
    snapshot = Snapshot(workspace_id=workspace_id, kb_id=kb.id, revision=1, state="published", source_ids=[source.id])
    db.add(snapshot); db.flush()
    kb.active_snapshot_id, kb.pages_indexed = snapshot.id, 1
    kb.chunks_indexed = db.scalar(select(func.count()).select_from(Chunk).where(Chunk.source_id == source.id))
    kb.assessment = {"products": "covered", "pricing": "covered", "refunds": "missing", "shipping": "missing", "hours": "missing", "contact": "missing"}
    config = default_agent("Gift studio assistant")
    config["knowledge_snapshot_ids"] = [snapshot.id]
    agent = Agent(workspace_id=workspace_id, name=config["name"], draft_config=config)
    db.add(agent); db.flush()
    publish_agent(db, workspace_id, agent, 1)
    store = Store(workspace_id=workspace_id, name="Gift studio · synthetic catalog", website_url="https://example.test")
    db.add(store); db.flush()
    db.add(Product(workspace_id=workspace_id, store_id=store.id, title="Personalised cufflinks", canonical_url="https://example.test/products/cufflinks", description="Synthetic fixture · engraved cufflinks", price_minor=99900, currency="INR", availability="unknown", customization_max_chars=20, provenance={"synthetic": True}))
    from .admission import immediate
    immediate(db,workspace_id,'fixture-widget:'+uid(),'widgets',1)
    installation = Installation(workspace_id=workspace_id, agent_id=agent.id, public_id=secrets.token_urlsafe(18), name="Sample store chat", allowed_origins=[settings.app_origin, settings.app_origin.replace("localhost", "127.0.0.1")], theme={"preset": "minimal", "accent_color": "#d9ef75"})
    db.add(installation); db.flush()
    audit(db, actor, "development.fixtures_loaded", kb.id)
    return {"status": "loaded", "agent_id": agent.id, "kb_id": kb.id, "installation_id": installation.id}

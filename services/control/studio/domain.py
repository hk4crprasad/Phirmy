from datetime import timezone
import hashlib
import json
import re
from fastapi import HTTPException
from sqlalchemy import select, func, update
from .db import uid, now, as_dict
from .models import *
from .security import audit

TERMINAL = {"completed", "failed", "canceled", "no_answer", "busy"}


def owned(db, model, workspace_id, resource_id):
    item = db.scalar(select(model).where(model.id == resource_id, model.workspace_id == workspace_id))
    if not item:
        raise HTTPException(404, "Resource not found")
    return item


def page(db, model, workspace_id, **filters):
    query = select(model).where(model.workspace_id == workspace_id)
    for key, value in filters.items():
        query = query.where(getattr(model, key) == value)
    return [as_dict(x) for x in db.scalars(query.order_by(model.created_at.desc()).limit(200))]


def request_identity(db, workspace_id, key, body):
    if not key or len(key) > 180:
        raise HTTPException(422, "A stable Idempotency-Key is required")
    hashed = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    existing = db.scalar(select(Idempotency).where(Idempotency.workspace_id == workspace_id, Idempotency.operation_key == key))
    if existing and existing.request_hash != hashed:
        raise HTTPException(409, "Idempotency key was already used with different input")
    return hashed, existing.result if existing else None


def remember(db, workspace_id, key, hashed, result):
    db.add(Idempotency(workspace_id=workspace_id, operation_key=key, request_hash=hashed, result=result))
    db.flush()
    return result


def wallet_state(db, workspace_id):
    wallet = db.scalar(select(Wallet).where(Wallet.workspace_id == workspace_id))
    if not wallet:
        raise HTTPException(409, "Workspace wallet is not initialized")
    reserved = db.scalar(select(func.coalesce(func.sum(Reservation.amount_minor), 0)).where(Reservation.workspace_id == workspace_id, Reservation.state == "active"))
    from .billing_accounting import risk_total
    risk=risk_total(db,workspace_id)
    debt=db.scalar(select(BillingAccount.debt_minor).where(BillingAccount.workspace_id==workspace_id)) or 0
    return {"currency":wallet.currency,"balance_minor":wallet.balance_minor,"reserved_minor":reserved,
            "at_risk_minor":risk,"billing_adjustment_minor":debt,"available_minor":max(0,wallet.balance_minor-reserved-risk)}


def post_ledger(db, workspace_id, amount, operation, description, call_id=None):
    wallet = db.scalar(select(Wallet).where(Wallet.workspace_id == workspace_id).with_for_update().execution_options(populate_existing=True))
    previous = db.scalar(select(Ledger).where(Ledger.workspace_id == workspace_id, Ledger.operation_key == operation))
    if previous:
        if previous.amount_minor != amount:
            raise HTTPException(409, "Ledger operation conflicts with existing posting")
        return previous
    if wallet.balance_minor + amount < 0:
        raise HTTPException(409, "Insufficient wallet balance")
    entry = Ledger(workspace_id=workspace_id, amount_minor=amount, kind="credit" if amount > 0 else "debit", operation_key=operation, description=description, call_id=call_id)
    db.add(entry)
    wallet.balance_minor += amount
    db.flush()
    return entry


def reserve(db, call, amount):
    db.scalar(select(Wallet).where(Wallet.workspace_id == call.workspace_id).with_for_update())
    state = wallet_state(db, call.workspace_id)
    if state["available_minor"] < amount:
        raise HTTPException(409, "Available wallet balance cannot cover this call budget")
    db.add(Reservation(workspace_id=call.workspace_id, call_id=call.id, amount_minor=amount))


def settle_call(db, call, connected_ms=None, state="completed"):
    db.scalar(select(Workspace).where(Workspace.id==call.workspace_id).with_for_update())
    call = db.scalar(select(Call).where(Call.id == call.id, Call.workspace_id == call.workspace_id).with_for_update().execution_options(populate_existing=True))
    if call.state in TERMINAL:
        return call
    connected_ms = max(0, connected_ms if connected_ms is not None else call.connected_ms)
    call.connected_ms = connected_ms
    call.ended_at = now()
    call.state = state
    reservation = db.scalar(select(Reservation).where(Reservation.workspace_id == call.workspace_id, Reservation.call_id == call.id))
    # Synthetic/local sessions do not spend real money. The UI labels the ledger as development credit.
    # Live tariff is snapshotted per call in metadata; no mutable global pricing lookup here.
    from .tariffs import voice_charge
    charge=voice_charge(db,call,connected_ms)
    if reservation:
        charge = min(charge, reservation.amount_minor)
        reservation.state = "consumed" if charge else "released"
    if charge:
        post_ledger(db, call.workspace_id, -charge, f"call:{call.id}:voice:v1", f"{call.mode.title()} voice · {connected_ms/1000:g}s", call.id)
    from .billing_accounting import settle_released_funds
    settle_released_funds(db,call.workspace_id,'released-call-funds:'+call.id)
    from .metering import record_usage,record_cost
    record_usage(db,call.workspace_id,'voice-duration:'+call.id,'voice_ms',connected_ms,scope_id=call.id)
    from .admission import finish
    finish(db,call.workspace_id,'voice-quota:'+call.id)
    if not call.connected_at:finish(db,call.workspace_id,'stt:'+call.id)
    carrier=call.metadata_data.get('provider','plivo') if call.transport=='pstn' else call.transport
    if carrier in {'plivo','twilio'}:
        record_cost(db,call.workspace_id,'carrier:'+call.id,carrier,'carrier',{'carrier_ms':connected_ms},
                    call_id=call.id,source='synthetic' if call.mode=='simulation' else 'measured_duration',mode='development' if call.mode=='simulation' else 'production')
    turns = list(db.scalars(select(Turn).where(Turn.workspace_id == call.workspace_id, Turn.call_id == call.id).order_by(Turn.ordinal)))
    user_turns = [x for x in turns if x.speaker == "user" and x.text_content.strip()]
    call.analysis = {
        "schema_version": "1", "call_id": call.id, "user_turn_count": len(user_turns),
        "disposition": "no_engagement" if not user_turns else "unknown",
        "is_lead": False, "lead_reason": "No qualification tool/evidence established a lead.",
        "summary": "No caller engagement." if not user_turns else "Caller: "+' '.join(x.text_content for x in user_turns)[:1000],
        "sentiment": "unknown", "evidence_turn_ids": [], "requested_actions": [], "confidence": 1 if not user_turns else 0,
    }
    emit(db, call.workspace_id, "call.completed" if state == "completed" else "call.failed", {"call_id": call.id, "state": state})
    db.flush()
    return call


def emit(db, workspace_id, event_type, payload):
    event_id = uid()
    messages = {
        'conversation.started': ('A visitor opened a conversation', 'Follow the live chat or take over in your inbox.', '/app/inbox?conversation=' + str(payload.get('conversation_id',''))),
        'conversation.message': ('New visitor message', 'Read and reply in your live inbox.', '/app/inbox?conversation=' + str(payload.get('conversation_id',''))),
        'conversation.mode_changed': ('Conversation updated', 'A team member changed the conversation status.', '/app/inbox?conversation=' + str(payload.get('conversation_id',''))),
        'appointment.created': ('Appointment recorded locally', 'Review the appointment before syncing a calendar.', '/app/appointments'),
        'appointment.confirmed': ('Meeting booked', 'Review the confirmed meeting details.', '/app/appointments'),
        'appointment.pending_approval': ('Meeting needs approval', 'Review the pending meeting.', '/app/appointments'),
        'ticket.created': ('A customer needs your help', 'A support ticket is ready in your inbox.', '/app/inbox'),
        'lead.created': ('A new contact is ready', 'Review the contact and choose the next step.', '/app/leads'),
        'call.completed': ('Conversation completed', 'Your conversation is ready to review.', '/app/calls'),
        'transfer.requested': ('Human transfer requested', 'Carrier connection is not confirmed yet.', '/app/calls'),
        'transfer.unknown': ('Transfer outcome needs review', 'Review the carrier outcome before taking another action.', '/app/operations'),
        'call.failed': ('A call needs attention', 'Review its status before trying again.', '/app/calls'),
        'job.completed': ('Your task is complete', 'Review the result in Operations.', '/app/operations'),
        'job.failed': ('A task needs attention', 'Review the task and choose whether to retry.', '/app/operations'),
    }
    if event_type in messages:
        title, description, href = messages[event_type]
        db.add(Notification(workspace_id=workspace_id, kind=event_type, title=title, description=description, href=href))
    for endpoint in db.scalars(select(WebhookEndpoint).where(WebhookEndpoint.workspace_id == workspace_id, WebhookEndpoint.enabled.is_(True))):
        if event_type in endpoint.event_types:
            db.add(Delivery(workspace_id=workspace_id, endpoint_id=endpoint.id, event_id=event_id, event_type=event_type, payload={"id": event_id, "type": event_type, "workspace_id": workspace_id, "created_at": now().isoformat(), "data": payload}))


def enqueue(db, workspace_id, kind, payload):
    item = Job(workspace_id=workspace_id, kind=kind, payload=payload)
    db.add(item)
    db.flush()
    return item


def default_agent(name="Support assistant"):
    from .config import settings
    config = {
        "schema_version": "1", "name": name, "greeting": "Hello, this is your AI support assistant. How can I help?",
        "instructions": "Answer from the connected knowledge and product facts. Never invent a price, stock status or policy. Offer a support ticket when information is missing.",
        "language": "en", "llm": {"provider": "openai", "model": settings.openai_model, "reasoning_effort": "none", "max_output_tokens": 1200},
        "speech": {"provider": "fish", "model": settings.fish_tts_model, "voice_id": settings.fish_voice_id or "CONFIGURE_FISH_VOICE",
                   "live_stt_provider": "deepgram", "live_stt_model": "nova-3", "live_stt_language": settings.deepgram_language, "postcall_asr_model": "transcribe-1-pro"},
        "knowledge_snapshot_ids": [], "priority_guidance": "", "variables": [], "tools": [],
        "behavior": {"interruptible": True, "silence_prompt_seconds": 8, "idle_end_seconds": 30, "max_connected_seconds": 300, "max_tool_rounds": 3},
        "recording": {"enabled": False, "retention_days": 0},
        "postcall": {"analysis_enabled": True, "capture_lead": False, "webhook_endpoint_ids": []},
    }

    from .voice_config import speech_config
    if settings.voice_provider == 'sarvam':
        config['speech']['live_stt_language'] = settings.sarvam_language
    config['speech'] = speech_config(config)
    return config


def bind_variables(config, values=None):
    bound=json.loads(json.dumps(config));values=values or {}
    declared={x['name']:x for x in config.get('variables',[])}
    replacements={}
    for name,definition in declared.items():
        value=values.get(name,definition.get('default'))
        if definition.get('required') and (value is None or str(value).strip()==''):
            raise HTTPException(422,'A value is required for agent variable: '+name)
        replacements[name]=str(value if value is not None else '')[:2000]
    for key in ['greeting','instructions']:
        bound[key]=re.sub(r'{{\s*([A-Za-z][A-Za-z0-9_]*)\s*}}',lambda match:replacements.get(match[1],''),bound.get(key,''))
    bound['_runtime_variables']={**values,**replacements}
    return bound


def validate_agent(db, workspace_id, config):
    from pathlib import Path
    from jsonschema import Draft202012Validator
    schema = json.loads((Path(__file__).resolve().parents[3] / "packages/contracts/agent-config.schema.json").read_text())
    errors = [{"code": "config_schema", "message": e.message, "path": ".".join(map(str, e.path))} for e in Draft202012Validator(schema).iter_errors(config)]
    defined = {x["name"] for x in config.get("variables", [])}
    if len(defined) != len(config.get('variables', [])) or len(defined) > 30:
        errors.append({'code': 'variable_names', 'message': 'Use at most 30 variables with unique names'})
    used = set(re.findall(r"{{\s*([A-Za-z][A-Za-z0-9_]*)\s*}}", config.get("instructions", "") + config.get("greeting", "")))
    for name in used - defined:
        errors.append({"code": "undefined_variable", "message": f"Undefined variable: {name}"})
    from .agent_tools import DEFINITIONS
    for tool in config.get('tools',[]):
        custom=owned(db,HTTPTool,workspace_id,tool['tool_id']) if tool.get('tool_id') else None
        if custom and (not custom.enabled or custom.name!=tool.get('name') or str(custom.revision)!=tool.get('schema_revision')):
            errors.append({'code':'tool_revision','message':'Review and reattach the latest tool revision before publishing'})
        if not custom and tool.get('name') not in DEFINITIONS:
            errors.append({'code':'unsupported_tool','message':'Tool is not in the permitted business registry: '+str(tool.get('name'))})
    from .config import settings
    llm=config.get('llm',{})
    if llm.get('profile_id'):
        profile=owned(db,LLMProfile,workspace_id,llm['profile_id'])
        if not profile.enabled or profile.model!=llm.get('model'):
            errors.append({'code':'model_profile','message':'Select an enabled, matching model profile'})
    elif llm.get('model')!=settings.openai_model:
        errors.append({'code':'model_research','message':'Add and test a documented model profile before selecting this model'})
    if config.get('recording',{}).get('enabled') and config.get('recording',{}).get('retention_days',0)<1:
        errors.append({'code':'recording_retention','message':'Recording requires at least one retention day'})
    for snapshot_id in config.get("knowledge_snapshot_ids", []):
        snapshot = db.scalar(select(Snapshot).where(Snapshot.id == snapshot_id, Snapshot.workspace_id == workspace_id, Snapshot.state == "published"))
        if not snapshot:
            errors.append({"code": "invalid_snapshot", "message": "Knowledge snapshot is unavailable in this workspace"})
    return errors


def publish_agent(db, workspace_id, agent, expected_revision):
    if agent.draft_revision != expected_revision:
        raise HTTPException(409, "Draft changed; reload before publishing")
    errors = validate_agent(db, workspace_id, agent.draft_config)
    if errors:
        raise HTTPException(422, {"code": "invalid_agent", "errors": errors})
    version = (db.scalar(select(func.max(AgentVersion.version)).where(AgentVersion.agent_id == agent.id, AgentVersion.workspace_id == workspace_id)) or 0) + 1
    config = json.loads(json.dumps(agent.draft_config))
    item = AgentVersion(workspace_id=workspace_id, agent_id=agent.id, version=version, config=config, config_hash=hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest())
    db.add(item)
    db.flush()
    agent.published_version_id = item.id
    return item

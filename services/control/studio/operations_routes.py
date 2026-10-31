from datetime import timezone
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import hashlib
import re
import secrets
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form
from sqlalchemy import select, func
from .config import settings
from .db import as_dict, now
from .models import *
from .schemas import *
from .security import principal, db_dependency, audit
from .domain import *
from .knowledge import canonical_url, validate_public_url

router = APIRouter(prefix="/v1/workspaces/{workspace_id}")


@router.get("/stores")
def stores(workspace_id: str, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("products:read")
    return {"items": page(db, Store, workspace_id)}


@router.post("/stores", status_code=201)
async def store_create(workspace_id: str, body: StoreWrite, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("products:write")
    await validate_public_url(body.website_url)
    url = canonical_url(body.website_url)
    existing = db.scalar(select(Store).where(Store.workspace_id == workspace_id, Store.website_url == url))
    if existing:
        return as_dict(existing)
    store = Store(workspace_id=workspace_id, name=body.name, website_url=url)
    db.add(store); db.flush()
    return as_dict(store)


@router.post("/stores/{store_id}/scans", status_code=202)
def scan(workspace_id: str, store_id: str, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("products:write")
    owned(db, Store, workspace_id, store_id)
    for existing in db.scalars(select(Job).where(Job.workspace_id == workspace_id, Job.kind == "catalog", Job.state.in_(["queued", "running"]))):
        if existing.payload.get("store_id") == store_id:
            return as_dict(existing)
    return as_dict(enqueue(db, workspace_id, "catalog", {"store_id": store_id}))


@router.get("/products")
def products(workspace_id: str, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("products:read")
    return {"items": page(db, Product, workspace_id, archived=False)}


@router.post("/products", status_code=201)
async def product_create(workspace_id: str, body: ProductWrite, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("products:write")
    owned(db, Store, workspace_id, body.store_id)
    url = canonical_url(body.canonical_url)
    if not url.startswith(("http://", "https://")):
        raise HTTPException(422, "Use an HTTP/HTTPS product URL")
    existing = db.scalar(select(Product).where(Product.workspace_id == workspace_id, Product.store_id == body.store_id, Product.canonical_url == url))
    if existing:
        for key, value in {**body.model_dump(), "canonical_url": url}.items():
            setattr(existing, key, value)
        existing.provenance = {**existing.provenance, "manual_override": True}
        return as_dict(existing)
    item = Product(workspace_id=workspace_id, **{**body.model_dump(), "canonical_url": url}, provenance={"source": "manual"})
    db.add(item); db.flush()
    return as_dict(item)


@router.put("/products/{product_id}")
def product_update(workspace_id: str, product_id: str, body: ProductWrite, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("products:write")
    product = owned(db, Product, workspace_id, product_id)
    owned(db, Store, workspace_id, body.store_id)
    for key, value in body.model_dump().items():
        setattr(product, key, canonical_url(value) if key == "canonical_url" else value)
    product.provenance = {**product.provenance, "manual_override": True}
    return as_dict(product)


@router.delete("/products/{product_id}")
def product_archive(workspace_id: str, product_id: str, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("products:write")
    product = owned(db, Product, workspace_id, product_id)
    product.archived = True
    return {"status": "archived"}


@router.get("/installations")
def installations(workspace_id: str, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("widget:read")
    from .widget_branding import installation_record
    items=page(db,Installation,workspace_id)
    items = [installation_record(item, db) for item in items]
    return {'items':items}


def validate_origins(origins):
    from .origin_ownership import normalize_origin
    for origin in origins:
        normalize_origin(origin)
        parsed = urlparse(origin)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise HTTPException(422, "Allowed origins must be complete scheme://host[:port] origins")
    return list(dict.fromkeys(normalize_origin(origin) for origin in origins))


@router.post("/installations", status_code=201)
def installation_create(workspace_id: str, body: InstallationWrite, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("widget:write")
    owned(db, Agent, workspace_id, body.agent_id)
    body.allowed_origins = validate_origins(body.allowed_origins)
    from .widget_branding import MANAGED_THEME_FIELDS
    body.theme = {**{k:v for k,v in body.theme.items() if k not in MANAGED_THEME_FIELDS}, 'publishable_key':'cyne_pk_' + secrets.token_urlsafe(24)}
    from .admission import immediate
    immediate(db,workspace_id,'widget-create:'+uid(),'widgets',1)
    item = Installation(workspace_id=workspace_id, public_id=secrets.token_urlsafe(18), **body.model_dump())
    db.add(item); db.flush()
    from .widget_branding import installation_record
    return installation_record(item, db)


@router.put("/installations/{installation_id}")
def installation_update(workspace_id: str, installation_id: str, body: InstallationWrite, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("widget:write")
    item = owned(db, Installation, workspace_id, installation_id)
    owned(db, Agent, workspace_id, body.agent_id)
    body.allowed_origins = validate_origins(body.allowed_origins)
    from .widget_branding import MANAGED_THEME_FIELDS
    managed={k:v for k,v in item.theme.items() if k in MANAGED_THEME_FIELDS and k not in {'logo_path','logo_remove'}}
    if body.theme.get('logo_url') or body.theme.get('logo_remove'):
        managed={k:v for k,v in managed.items() if k not in {'logo_object_key','logo_content_type'}}
    body.theme = {**{k:v for k,v in body.theme.items() if k not in MANAGED_THEME_FIELDS}, **managed}
    for key, value in body.model_dump().items():
        setattr(item, key, value)
    audit(db,actor,"widget.updated",item.id)
    from .widget_branding import installation_record
    return installation_record(item, db)


@router.post('/installations/{installation_id}/logo')
async def upload_widget_logo(workspace_id:str,installation_id:str,file:UploadFile=File(...),settings_json:str|None=Form(default=None),actor=Depends(principal),db=Depends(db_dependency,scope='function')):
    actor.require('widget:write')
    item=owned(db,Installation,workspace_id,installation_id)
    if settings_json is not None:
        from pydantic import ValidationError
        try:settings_body=InstallationWrite.model_validate_json(settings_json)
        except ValidationError:raise HTTPException(422,'Use valid widget settings')
        # Apply appearance only after validating and storing the image.
    body=await file.read(2_000_001)
    if len(body)>2_000_000:raise HTTPException(413,'Choose a logo smaller than 2 MB')
    import io,asyncio
    from PIL import Image,UnidentifiedImageError
    try:
        with Image.open(io.BytesIO(body)) as image:
            if image.format not in {'PNG','JPEG','WEBP'} or max(image.size)>4096 or min(image.size)<1:raise ValueError()
            content_type=Image.MIME[image.format]
            image.verify()
    except (UnidentifiedImageError,OSError,ValueError,Image.DecompressionBombError):raise HTTPException(422,'Use a valid PNG, JPEG or WebP logo up to 4096 pixels')
    from .storage import get_store,put_checked
    db.commit()
    key=await asyncio.to_thread(put_checked,workspace_id,'logos',body,content_type)
    item=owned(db,Installation,workspace_id,installation_id)
    if settings_json is not None:installation_update(workspace_id,installation_id,settings_body,actor,db)
    from .metering import stored
    stored(db,workspace_id,key,len(body))
    item.theme={**item.theme,'logo_object_key':key,'logo_content_type':content_type,'logo_url':''}
    audit(db,actor,'widget.logo_uploaded',item.id)
    from .widget_branding import installation_record
    return installation_record(item)


@router.delete('/installations/{installation_id}/logo')
def remove_widget_logo(workspace_id:str,installation_id:str,actor=Depends(principal),db=Depends(db_dependency,scope='function')):
    actor.require('widget:write')
    item=owned(db,Installation,workspace_id,installation_id)
    item.theme={k:v for k,v in item.theme.items() if k not in {'logo_object_key','logo_content_type','logo_path','logo_url'}}
    audit(db,actor,'widget.logo_removed',item.id)
    from .widget_branding import installation_record
    return installation_record(item)


@router.delete('/installations/{installation_id}')
def installation_disable(workspace_id: str, installation_id: str, actor=Depends(principal), db=Depends(db_dependency, scope='function')):
    actor.require('widget:write')
    item = owned(db, Installation, workspace_id, installation_id)
    item.enabled = False
    audit(db, actor, 'widget.disabled', item.id)
    return {'status': 'disabled'}


@router.get("/conversations")
def conversations(workspace_id: str, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("inbox:read")
    items = page(db, Conversation, workspace_id)
    ids = [item['id'] for item in items]
    ranked = select(Message.id, func.row_number().over(partition_by=Message.conversation_id, order_by=(Message.created_at.desc(),Message.id.desc())).label('position')).where(Message.workspace_id == workspace_id, Message.conversation_id.in_(ids)).subquery()
    latest = {row.conversation_id:row.text_content[:120] for row in db.scalars(select(Message).join(ranked,Message.id == ranked.c.id).where(ranked.c.position == 1))}
    visitors = {row.conversation_id:row.variables.get('_widget_lead',{}) for row in db.scalars(select(ConversationContext).where(ConversationContext.workspace_id == workspace_id, ConversationContext.conversation_id.in_(ids)))}
    for item in items:
        item['preview'] = latest.get(item['id'],'')
        item['visitor'] = visitors.get(item['id'],{})
    return {"items": items}


@router.get("/conversations/{conversation_id}/messages")
def conversation_messages(workspace_id: str, conversation_id: str, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("inbox:read")
    owned(db, Conversation, workspace_id, conversation_id)
    from .widget_live import lead_details, history
    row = owned(db, Conversation, workspace_id, conversation_id)
    return {"items": history(db, row), "conversation":as_dict(row), "visitor":lead_details(db,row)}


@router.get("/tickets")
def tickets(workspace_id: str, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("inbox:read")
    return {"items": page(db, Ticket, workspace_id)}


@router.post("/tickets", status_code=201)
def ticket_create(workspace_id: str, body: TicketCreate, request: Request, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("inbox:write")
    owned(db, Conversation, workspace_id, body.conversation_id)
    key = request.headers.get("idempotency-key", "")
    hashed, previous = request_identity(db, workspace_id, "ticket:" + key if key else "", body.model_dump())
    if previous:
        return previous
    ticket = Ticket(workspace_id=workspace_id, operation_key="ticket:" + key, **body.model_dump())
    db.add(ticket); db.flush()
    emit(db, workspace_id, "ticket.created", {"ticket_id": ticket.id})
    return remember(db, workspace_id, "ticket:" + key, hashed, as_dict(ticket))


@router.patch("/tickets/{ticket_id}")
def ticket_update(workspace_id: str, ticket_id: str, body: dict, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("inbox:write")
    ticket = owned(db, Ticket, workspace_id, ticket_id)
    if set(body) != {"state"} or body["state"] not in {"open", "pending", "resolved"}:
        raise HTTPException(422, "Provide a valid ticket state")
    ticket.state = body["state"]
    audit(db, actor, "ticket.state_changed", ticket.id, body)
    return as_dict(ticket)


@router.get("/leads")
def leads(workspace_id: str, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("leads:read")
    from .widget_email import lead_records
    return {"items": lead_records(db,page(db,Lead,workspace_id))}


@router.post("/leads", status_code=201)
def lead_create(workspace_id: str, body: LeadWrite, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("leads:write")
    lead = Lead(workspace_id=workspace_id, **body.model_dump())
    db.add(lead); db.flush()
    emit(db, workspace_id, "lead.created", {"lead_id": lead.id})
    return as_dict(lead)


@router.put("/leads/{lead_id}")
def lead_update(workspace_id: str, lead_id: str, body: LeadWrite, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("leads:write")
    lead = owned(db, Lead, workspace_id, lead_id)
    for key, value in body.model_dump().items():
        setattr(lead, key, value)
    return as_dict(lead)


@router.get("/numbers")
def numbers(workspace_id: str, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("calls:read")
    return {"items": page(db, Number, workspace_id)}


@router.post("/numbers", status_code=202)
def register_number(workspace_id: str, body: NumberWrite, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("calls:write")
    existing = db.scalar(select(Number).where(Number.workspace_id == workspace_id, Number.e164 == body.e164))
    if existing:
        return as_dict(existing)
    if db.scalar(select(Number.id).where(Number.provider == body.provider, Number.e164 == body.e164)):
        raise HTTPException(409, "This provider number is already assigned")
    item = Number(workspace_id=workspace_id, **body.model_dump(), status="unverified")
    db.add(item); db.flush()
    from .carrier_config import credentials
    carrier = credentials(body.provider, workspace_id)
    if carrier.get('auth_token'):
        enqueue(db, workspace_id, "verify_number", {"number_id": item.id})
    audit(db, actor, "number.registered", item.id)
    return as_dict(item)


@router.put("/numbers/{number_id}/route")
def inbound_route(workspace_id: str, number_id: str, body: RouteWrite, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("calls:write")
    number = owned(db, Number, workspace_id, number_id)
    agent = owned(db, Agent, workspace_id, body.agent_id)
    if not number.can_inbound or number.status != "active":
        raise HTTPException(409, "Verify an inbound-capable owned number before attaching it")
    if not agent.published_version_id:
        raise HTTPException(409, "Publish the selected agent")
    number.agent_id = agent.id
    audit(db, actor, "number.route_changed", number.id, {"agent_id": agent.id})
    return as_dict(number)


@router.post("/calls/outbound", status_code=202)
def outbound(workspace_id: str, body: Outbound, request: Request, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("calls:write")
    key = request.headers.get("idempotency-key", "")
    hashed, previous = request_identity(db, workspace_id, "outbound:" + key if key else "", body.model_dump())
    if previous:
        return previous
    agent = owned(db, Agent, workspace_id, body.agent_id)
    if not agent.published_version_id:
        raise HTTPException(409, "Publish this agent before calling")
    bind_variables(owned(db,AgentVersion,workspace_id,agent.published_version_id).config,body.variables)
    if body.mode == "live":
        from .llm import live_voice_ready
        from .carrier_config import telephony_ready
        if not telephony_ready(workspace_id) or not live_voice_ready(owned(db,AgentVersion,workspace_id,agent.published_version_id).config,workspace_id):
            raise HTTPException(409, "Connect your voice services and carrier, then configure the public call endpoint")
        number = owned(db, Number, workspace_id, body.number_id or "")
        if number.status != "active" or not number.can_outbound:
            raise HTTPException(409, "Select a verified outbound-capable number")
        from .phone_trials import for_number
        if not for_number(db, number.id) and body.destination not in [x.strip() for x in settings.test_destination_allowlist.split(",") if x.strip()]:
            raise HTTPException(403, "Destination is outside this deployment's controlled test allowlist")
    call = Call(workspace_id=workspace_id, agent_version_id=agent.published_version_id, agent_name=agent.name, direction="outbound", transport="pstn", mode=body.mode,
                destination=body.destination, metadata_data={"number_id":body.number_id,"budget_minor":body.budget_minor,'variables':body.variables})
    db.add(call); db.flush()
    db.scalar(select(Workspace).where(Workspace.id==workspace_id).with_for_update())
    from .phone_trials import admit_call
    if body.mode=='live':admit_call(db,call)
    from .admission import admit_voice as admit_plan_voice
    admit_plan_voice(db,call,owned(db,AgentVersion,workspace_id,agent.published_version_id).config)
    enqueue(db, workspace_id, "outbound", {"call_id": call.id})
    audit(db, actor, "call.dispatched", call.id, {"mode": body.mode})
    return remember(db, workspace_id, "outbound:" + key, hashed, as_dict(call))


@router.get("/campaigns")
def campaigns(workspace_id: str, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("campaigns:read")
    items = page(db, Campaign, workspace_id)
    for item in items:
        attempts = list(db.scalars(select(Attempt).where(Attempt.workspace_id == workspace_id, Attempt.campaign_id == item["id"])))
        item["total_contacts"] = len(item["contacts"])
        item["completed_contacts"] = len({x.contact_identity for x in attempts if x.state == "completed"})
        item["failed_contacts"] = len({x.contact_identity for x in attempts if x.state == "failed"})
    return {"items": items}


@router.post("/campaigns", status_code=201)
def campaign_create(workspace_id: str, body: CampaignWrite, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("campaigns:write")
    owned(db, AgentVersion, workspace_id, body.agent_version_id)
    try:
        ZoneInfo(body.timezone)
    except ZoneInfoNotFoundError:
        raise HTTPException(422, "Invalid IANA timezone")
    if body.number_id:
        owned(db, Number, workspace_id, body.number_id)
    if body.mode == 'live':
        from .carrier_config import telephony_ready
        if not telephony_ready(workspace_id):
            raise HTTPException(409, 'Connect a carrier and configure the public call endpoint first')
        if not body.number_id:
            raise HTTPException(422, 'Select a verified caller number for a live campaign')
        number = owned(db, Number, workspace_id, body.number_id)
        from .phone_trials import for_number
        if for_number(db, number.id):
            raise HTTPException(409, 'Phone trials support individual test calls. Connect your own carrier for campaigns.')
        if number.status != 'active' or not number.can_outbound:
            raise HTTPException(409, 'Verify an outbound-capable number first')
        from .llm import live_voice_ready
        if not live_voice_ready(owned(db, AgentVersion, workspace_id, body.agent_version_id).config, workspace_id):
            raise HTTPException(409, 'Connect the agent’s voice services before starting a live campaign')
    if body.calling_hour_start >= body.calling_hour_end:
        raise HTTPException(422,'Calling-hour start must precede end in the same local day')
    values=body.model_dump()
    policy={key:values.pop(key) for key in ['retry_delay_seconds','calling_hour_start','calling_hour_end']}
    item = Campaign(workspace_id=workspace_id, **values, policy=policy)
    db.add(item); db.flush()
    return as_dict(item)


@router.get("/campaigns/{campaign_id}")
def campaign_get(workspace_id: str, campaign_id: str, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("campaigns:read")
    return as_dict(owned(db, Campaign, workspace_id, campaign_id))


@router.post("/campaigns/{campaign_id}/contacts")
def import_contacts(workspace_id: str, campaign_id: str, body: ContactsImport, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("campaigns:write")
    campaign = owned(db, Campaign, workspace_id, campaign_id)
    if campaign.state != "draft":
        raise HTTPException(409, "Contacts can only change while the campaign is a draft")
    contacts, seen, errors, duplicates = [], set(), [], 0
    for index, contact in enumerate(body.contacts):
        phone = re.sub(r"[\s()\-]", "", str(contact.get("phone", "")))
        if not re.fullmatch(r"\+[1-9][0-9]{6,14}", phone):
            errors.append({"row": index + 1, "message": "Use an E.164 phone number including +country code"})
        elif phone in seen:
            duplicates += 1
        else:
            seen.add(phone)
            contacts.append({"phone": phone, "name": str(contact.get("name", ""))[:160], "variables": contact.get("variables", {})})
    if not body.dry_run:
        if errors:
            raise HTTPException(422, {"errors": errors, "message": "Fix invalid rows before importing"})
        campaign.contacts = contacts
    return {"accepted": len(contacts), "duplicates": duplicates, "errors": errors, "dry_run": body.dry_run}


@router.post("/campaigns/{campaign_id}/{action}")
def campaign_command(workspace_id: str, campaign_id: str, action: str, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("campaigns:write")
    campaign = owned(db, Campaign, workspace_id, campaign_id)
    if action == "start":
        if campaign.state in {"running", "scheduled", "completed"}:
            return as_dict(campaign)
        if campaign.state == "canceled":
            raise HTTPException(409, "Canceled campaign cannot restart")
        if not campaign.contacts:
            raise HTTPException(409, "Import at least one valid contact")
        if campaign.mode == "live":
            config = owned(db, AgentVersion, workspace_id, campaign.agent_version_id).config
            for contact in campaign.contacts:
                bind_variables(config, contact.get('variables', {}))
                if contact.get('contact_id'):
                    saved = owned(db, Contact, workspace_id, contact['contact_id'])
                    if saved.archived or saved.consent != 'granted':
                        raise HTTPException(409, 'A selected contact no longer has permission to call')
            allow = {x.strip() for x in settings.test_destination_allowlist.split(",")}
            if not all(x["phone"] in allow for x in campaign.contacts):
                raise HTTPException(403, "Campaign contains a destination outside the controlled allowlist")
        campaign.state = "scheduled" if campaign.scheduled_at and campaign.scheduled_at.replace(tzinfo=timezone.utc) > now() else "running"
        enqueue(db, workspace_id, "campaign", {"campaign_id": campaign.id})
    elif action == "pause":
        if campaign.state in {"running", "scheduled"}:
            campaign.state = "paused"
    elif action == "cancel":
        if campaign.state != "completed":
            campaign.state = "canceled"
    else:
        raise HTTPException(404, "Unknown campaign command")
    audit(db, actor, "campaign." + action, campaign.id)
    return as_dict(campaign)


@router.get("/campaigns/{campaign_id}/attempts")
def attempts(workspace_id: str, campaign_id: str, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("campaigns:read")
    owned(db, Campaign, workspace_id, campaign_id)
    return {"items": page(db, Attempt, workspace_id, campaign_id=campaign_id)}


@router.get("/connections")
def connections(workspace_id: str, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("settings:read")
    from .connectors import PROVIDERS
    rows = page(db, Connection, workspace_id)
    existing = {row['provider'] for row in rows}
    rows += [{'id': provider, 'workspace_id': workspace_id, 'provider': provider, 'name': name,
              'state': 'disconnected', 'scopes': []} for provider, name in PROVIDERS.items() if provider not in existing]
    return {'items': rows}


@router.get("/appointments")
def appointments(workspace_id: str, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("appointments:read")
    return {"items": page(db, Appointment, workspace_id)}


@router.post("/appointments", status_code=201)
def book_appointment(workspace_id: str, body: AppointmentWrite, request: Request, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("appointments:write")
    if body.start.tzinfo is None or body.end.tzinfo is None or body.end <= body.start:
        raise HTTPException(422, "Use timezone-aware start/end times with end after start")
    try:
        ZoneInfo(body.timezone)
    except ZoneInfoNotFoundError:
        raise HTTPException(422, "Invalid IANA timezone")
    db.scalar(select(Workspace).where(Workspace.id == workspace_id).with_for_update())
    key = request.headers.get("idempotency-key", "")
    hashed, previous = request_identity(db, workspace_id, "booking:" + key if key else "", body.model_dump(mode="json"))
    if previous:
        return previous
    conflict = db.scalar(select(Appointment).where(Appointment.workspace_id == workspace_id, Appointment.state != "canceled", Appointment.start_at < body.end, Appointment.end_at > body.start))
    if conflict:
        raise HTTPException(409, "This workspace already has an appointment in that time slot")
    item = Appointment(workspace_id=workspace_id, title=body.title, start_at=body.start, end_at=body.end, timezone=body.timezone, state="local", operation_key="booking:" + key)
    db.add(item); db.flush()
    return remember(db, workspace_id, "booking:" + key, hashed, as_dict(item))


@router.post("/appointments/{appointment_id}/cancel")
def cancel_appointment(workspace_id: str, appointment_id: str, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("appointments:write")
    item = owned(db, Appointment, workspace_id, appointment_id)
    if db.scalar(select(SchedulingBooking.id).where(SchedulingBooking.workspace_id == workspace_id, SchedulingBooking.appointment_id == item.id)):
        raise HTTPException(409, 'Manage this booking in its scheduling provider. A local change would not cancel the remote meeting.')
    item.state = "canceled"
    return as_dict(item)


@router.get("/webhooks")
def webhooks(workspace_id: str, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("developer:read")
    return {"items": [{k: v for k, v in row.items() if k != "secret"} for row in page(db, WebhookEndpoint, workspace_id)]}


@router.post("/webhooks", status_code=201)
async def webhook_create(workspace_id: str, body: WebhookWrite, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("developer:write")
    from .secrets import encrypt
    if urlparse(body.url).scheme != 'https':
        raise HTTPException(422, 'Use an HTTPS webhook endpoint')
    await validate_public_url(body.url)
    secret = secrets.token_urlsafe(32)
    endpoint = WebhookEndpoint(workspace_id=workspace_id, url=body.url, secret=encrypt(secret), event_types=body.events, enabled=body.enabled)
    db.add(endpoint); db.flush()
    return {"endpoint": {k: v for k, v in as_dict(endpoint).items() if k != "secret"}, "signing_secret": secret}


@router.put('/webhooks/{endpoint_id}')
async def webhook_update(workspace_id: str, endpoint_id: str, body: WebhookWrite, actor=Depends(principal), db=Depends(db_dependency, scope='function')):
    actor.require('developer:write')
    endpoint = owned(db, WebhookEndpoint, workspace_id, endpoint_id)
    if urlparse(body.url).scheme != 'https':
        raise HTTPException(422, 'Use an HTTPS webhook endpoint')
    await validate_public_url(body.url)
    endpoint.url, endpoint.event_types, endpoint.enabled = body.url, body.events, body.enabled
    if not body.enabled:
        for delivery in db.scalars(select(Delivery).where(Delivery.workspace_id == workspace_id, Delivery.endpoint_id == endpoint.id, Delivery.state == 'pending')):
            delivery.state = 'canceled'
    audit(db, actor, 'webhook.updated', endpoint.id)
    return {k: v for k, v in as_dict(endpoint).items() if k != 'secret'}


@router.delete('/webhooks/{endpoint_id}')
def webhook_disable(workspace_id: str, endpoint_id: str, actor=Depends(principal), db=Depends(db_dependency, scope='function')):
    actor.require('developer:write')
    endpoint = owned(db, WebhookEndpoint, workspace_id, endpoint_id)
    endpoint.enabled = False
    for delivery in db.scalars(select(Delivery).where(Delivery.workspace_id == workspace_id, Delivery.endpoint_id == endpoint.id, Delivery.state == 'pending')):
        delivery.state = 'canceled'
    audit(db, actor, 'webhook.disabled', endpoint.id)
    return {'status': 'disabled'}


@router.post('/webhooks/{endpoint_id}/rotate-secret')
def webhook_rotate(workspace_id: str, endpoint_id: str, actor=Depends(principal), db=Depends(db_dependency, scope='function')):
    actor.require('developer:write')
    from .secrets import encrypt
    endpoint = owned(db, WebhookEndpoint, workspace_id, endpoint_id)
    secret = secrets.token_urlsafe(32)
    endpoint.secret = encrypt(secret)
    audit(db, actor, 'webhook.secret_rotated', endpoint.id)
    return {'signing_secret': secret}


@router.get("/deliveries")
def deliveries(workspace_id: str, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("developer:read")
    return {"items": page(db, Delivery, workspace_id)}


@router.post("/deliveries/{delivery_id}/replay")
def delivery_replay(workspace_id: str, delivery_id: str, actor=Depends(principal), db=Depends(db_dependency, scope="function")):
    actor.require("developer:write")
    item = owned(db, Delivery, workspace_id, delivery_id)
    if not owned(db, WebhookEndpoint, workspace_id, item.endpoint_id).enabled:
        raise HTTPException(409, 'Enable the webhook endpoint before replaying a delivery')
    item.state, item.next_attempt_at = "pending", now()
    return as_dict(item)

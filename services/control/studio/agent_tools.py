"""A closed business-tool registry. Side effects are local, scoped and idempotent."""
import hashlib
import re
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from fastapi import HTTPException
from sqlalchemy import select
from .db import session_scope,now,as_dict
from .models import Product,Conversation,Ticket,Lead,Appointment,Call,Workspace
from .domain import emit

DEFINITIONS={
 'request_human_transfer':{'description':'Request transfer of this live phone call to the workspace-approved staff destination. Requires complete readback and later confirmation. Never choose a number or promise connection before carrier evidence.','parameters':{'type':'object','properties':{'reason':{'type':'string'}},'required':['reason'],'additionalProperties':False}},
 'request_callback':{'description':'Request a manual callback in the team inbox using only a phone number and optional time supplied by the visitor. Requires a later complete readback confirmation. Never promise a callback time or claim a call was placed.','parameters':{'type':'object','properties':{'phone':{'type':'string'},'name':{'type':'string'},'preferred_time':{'type':'string'},'reason':{'type':'string'}},'required':['phone','name','preferred_time','reason'],'additionalProperties':False}},
 'search_products':{'description':'Search verified product facts. Never infer stock or a policy from a product title.','parameters':{'type':'object','properties':{'query':{'type':'string'}},'required':['query'],'additionalProperties':False}},
 'create_support_ticket':{'description':'Propose a support ticket after an explicit visitor request. The server requires a later confirmation before recording it.','parameters':{'type':'object','properties':{'subject':{'type':'string'}},'required':['subject'],'additionalProperties':False}},
 'capture_lead':{'description':'Record contact details the user explicitly provided for follow-up. Requires explicit permission in the user message.','parameters':{'type':'object','properties':{'name':{'type':'string'},'email':{'type':'string'},'phone':{'type':'string'}},'required':['name','email','phone'],'additionalProperties':False}},
 'check_appointments':{'description':'Return workspace-local busy intervals. These are not remote calendar availability.','parameters':{'type':'object','properties':{'start':{'type':'string'},'end':{'type':'string'}},'required':['start','end'],'additionalProperties':False}},
 'book_appointment':{'description':'Record a workspace-local appointment the user explicitly asked to book. Report local recording; do not claim remote calendar confirmation. Ask for the exact time and timezone first.','parameters':{'type':'object','properties':{'title':{'type':'string'},'start':{'type':'string'},'end':{'type':'string'},'timezone':{'type':'string'}},'required':['title','start','end','timezone'],'additionalProperties':False}},
 'get_scheduling_link':{'description':'Return the connected Cal.com or Calendly scheduling page. This is a link, not a confirmed booking.','parameters':{'type':'object','properties':{'provider':{'type':'string','enum':['calcom','calendly']}},'required':['provider'],'additionalProperties':False}},
 'check_calendar_availability':{'description':'Check actual busy intervals in the connected Google Calendar. Requires exact timezone-aware start/end times.','parameters':{'type':'object','properties':{'start':{'type':'string'},'end':{'type':'string'}},'required':['start','end'],'additionalProperties':False}},
 'sync_calendar_appointment':{'description':'Sync a previously recorded local appointment to the connected Google Calendar after explicit booking confirmation. Only succeeded confirms remote booking.','parameters':{'type':'object','properties':{'appointment_id':{'type':'string'}},'required':['appointment_id'],'additionalProperties':False}},
}

from .scheduling import AvailabilityInput, PrepareInput, BookingInput

for _name, _description, _schema in [
    ('check_scheduling_availability', 'Check actual available slots in connected Cal.com or Calendly. Ask for the caller timezone. Only offer the returned slots; this does not book.', AvailabilityInput),
    ('prepare_scheduling_booking', 'Prepare a Cal.com or Calendly booking from a returned availability_id and exact slot. Collect caller-provided name, email and required question answers. The server reads back details and asks for confirmation; no booking is created yet.', PrepareInput),
    ('confirm_scheduling_booking', 'Create the prepared booking only after the caller clearly confirms the server read-back on a later turn. Never invent a booking ID or repeat an unknown submission. Only booking_confirmed true means confirmed.', BookingInput),
    ('get_scheduling_booking', 'Read or reconcile the status of this conversation’s booking. Never creates another booking. Pending approval and unknown outcomes are not confirmed.', BookingInput),
]:
    DEFINITIONS[_name] = {'description': _description, 'parameters': _schema.model_json_schema()}


def tool_definitions(config):
    import copy
    output = []
    for tool in config.get('tools', []):
        name = tool.get('name')
        from .config import settings
        if name=='request_human_transfer' and not settings.live_transfer_enabled:continue
        if name=='request_callback' and not settings.callback_requests_enabled:continue
        if name not in DEFINITIONS:
            continue
        definition = copy.deepcopy(DEFINITIONS[name])
        if name == 'check_scheduling_availability' and tool.get('scheduling_provider'):
            definition['parameters']['properties']['provider']['enum'] = [tool['scheduling_provider']]
            definition['description'] += ' Use the configured service; do not ask the caller to choose a platform.'
        output.append({'type': 'function', 'name': name, **definition})
    return output


def time_range(args):
    try:
        start=datetime.fromisoformat(args['start'].replace('Z','+00:00'));end=datetime.fromisoformat(args['end'].replace('Z','+00:00'))
        if not start.tzinfo or not end.tzinfo or end<=start or end-start>timedelta(hours=8):raise ValueError()
        return start,end
    except (ValueError,KeyError,TypeError):raise HTTPException(422,'Exact timezone-aware start and end times are required')


def execute(name,args,context):
    from .tool_safety import BUILTIN_WRITES, approved, admit_attempt, propose, confirmation_text
    if name in BUILTIN_WRITES and not approved(name,args,context):
        try:
            admit_attempt(context,name,hashlib.sha256(str(args).encode()).hexdigest())
            proposal=propose({},name,args,context)
            return {'confirmation_required':True,'confirmation':proposal,'message':confirmation_text(proposal)}
        except HTTPException as error:
            return {'error':str(error.detail)}
    if name=='request_human_transfer':
        from .transfers import request as transfer
        return transfer(args,context)
    if name=='request_callback':
        from .callbacks import execute as callback
        return callback(args,context)
    ws=context['workspace_id'];user_text=context['user_text']
    operation='tool:'+hashlib.sha256((context['operation_id']+':'+name).encode()).hexdigest()
    with session_scope(write=True) as db:
        db.scalar(select(Workspace).where(Workspace.id==ws).with_for_update())
        if name == 'get_scheduling_link':
            from .models import ConnectorCredential
            from .secrets import decrypt
            from .connectors import validate_booking_url
            import json
            provider = args.get('provider')
            if provider not in {'calcom', 'calendly'}:
                return {'error': 'Choose Cal.com or Calendly'}
            secret = db.scalar(select(ConnectorCredential).where(ConnectorCredential.workspace_id == ws, ConnectorCredential.provider == provider))
            if not secret:
                return {'error': 'The scheduling service is not connected'}
            url = json.loads(decrypt(secret.encrypted_data)).get('booking_url', '')
            validate_booking_url(url, 'cal.com' if provider == 'calcom' else 'calendly.com')
            return {'url': url, 'provider': provider, 'booking_confirmed': False}
        if name=='search_products':
            if context.get('knowledge_snapshot_ids') is not None:
                from .website_actions import corpus, ranked_products
                _, rows = corpus(db, ws, context['knowledge_snapshot_ids'])
                return {'products':ranked_products(rows, str(args.get('query','')), context.get('page_url'), context.get('history'))[:5]}
            terms=set(re.findall(r'\w+',str(args.get('query','')).lower()))
            rows=list(db.scalars(select(Product).where(Product.workspace_id==ws,Product.archived.is_(False)).limit(200)))
            matches=[r for r in rows if terms.intersection(re.findall(r'\w+',r.title.lower()))]
            return {'products':[{k:as_dict(r)[k] for k in ['title','canonical_url','price_minor','currency','availability','customization_max_chars']} for r in matches[:5]]}
        if name=='create_support_ticket':
            ticket=db.scalar(select(Ticket).where(Ticket.workspace_id==ws,Ticket.operation_key==operation))
            if not ticket:
                conversation_id=context.get('conversation_id')
                if not conversation_id:
                    call=db.scalar(select(Call).where(Call.workspace_id==ws,Call.id==context.get('call_id')))
                    if not call:raise HTTPException(404,'Call context unavailable')
                    conversation_id=call.metadata_data.get('conversation_id')
                    if not conversation_id:
                        conversation=Conversation(workspace_id=ws,channel='voice');db.add(conversation);db.flush();conversation_id=conversation.id
                        call.metadata_data={**call.metadata_data,'conversation_id':conversation_id}
                ticket=Ticket(workspace_id=ws,conversation_id=conversation_id,subject=str(args.get('subject','Follow-up request'))[:200],description=user_text,operation_key=operation)
                db.add(ticket);db.flush();emit(db,ws,'ticket.created',{'ticket_id':ticket.id})
            return {'ticket_id':ticket.id,'state':'recorded','message':'The team can review this request; no callback time is promised.'}
        if name=='capture_lead':
            email=str(args.get('email','')).strip();phone=str(args.get('phone','')).strip()
            if not (email or phone) or (email and email.lower() not in user_text.lower()) or (phone and re.sub(r'\D','',phone) not in re.sub(r'\D','',user_text)):return {'error':'Do not invent contact details; ask the user for them'}
            lead=db.scalar(select(Lead).where(Lead.workspace_id==ws,Lead.evidence==operation+'\n'+user_text))
            if not lead:
                lead=Lead(workspace_id=ws,name=str(args.get('name') or 'Customer')[:160],email=email[:254],phone=phone[:20],evidence=operation+'\n'+user_text)
                db.add(lead);db.flush();emit(db,ws,'lead.created',{'lead_id':lead.id})
            if context.get('call_id'):
                call=db.scalar(select(Call).where(Call.workspace_id==ws,Call.id==context['call_id']))
                if call:call.metadata_data={**call.metadata_data,'lead_id':lead.id}
            return {'lead_id':lead.id,'state':'recorded','remote_crm_sync':False}
        if name in {'check_appointments','book_appointment'}:
            start,end=time_range(args)
            conflicts=list(db.scalars(select(Appointment).where(Appointment.workspace_id==ws,Appointment.state!='canceled',Appointment.start_at<end,Appointment.end_at>start)))
            if name=='check_appointments':return {'scope':'workspace-local','busy':[{'start':x.start_at.isoformat(),'end':x.end_at.isoformat()} for x in conflicts],'remote_calendar_checked':False}
            previous=db.scalar(select(Appointment).where(Appointment.workspace_id==ws,Appointment.operation_key==operation))
            if previous:return {'appointment_id':previous.id,'state':'local','remote_calendar_synced':False}
            if start<now():return {'error':'Booking must be in the future'}
            if conflicts:return {'error':'That time conflicts with another local appointment; ask for another time'}
            try:ZoneInfo(args['timezone'])
            except Exception:return {'error':'A valid timezone is required'}
            item=Appointment(workspace_id=ws,title=str(args.get('title','Customer appointment'))[:200],start_at=start,end_at=end,timezone=args['timezone'],operation_key=operation,state='local')
            db.add(item);db.flush();emit(db,ws,'appointment.created',{'appointment_id':item.id})
            return {'appointment_id':item.id,'state':'local','remote_calendar_synced':False,'start':start.isoformat()}
        return {'error':'Tool is not permitted'}

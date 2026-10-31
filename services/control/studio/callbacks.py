"""Confirmed callback requests for the team's inbox; never an automatic dial."""
import hashlib
import re
import string

from fastapi import HTTPException
from sqlalchemy import select

from .config import settings
from .db import session_scope
from .models import Call, Conversation, Membership, Ticket, User, Workspace
from .domain import emit
from .mail_outbox import enqueue_email

ASK_PHONE = 'What phone number, including the country code, should the team use for your callback? I will ask you to confirm it before saving the request.'
RECORDED = 'Your callback request is in the team inbox. The team will review it; a callback time is not confirmed.'


def phone(value):
    value = re.sub(r'[ ()-]', '', str(value))
    if not re.fullmatch(r'\+[1-9][0-9]{6,14}', value):
        raise HTTPException(422, 'Use a phone number with its + country code')
    return value


def provided_numbers(text):
    output = set()
    for value in re.findall(r'\+[1-9][0-9 ()-]{5,22}[0-9]', text):
        try:output.add(phone(value))
        except HTTPException:pass
    return output


def validate(args, user_text):
    if not settings.callback_requests_enabled:
        raise HTTPException(409, 'Callback requests are currently disabled')
    if set(args) - {'phone', 'name', 'preferred_time', 'reason'}:
        raise HTTPException(422, 'Unexpected callback details')
    number = phone(args.get('phone', ''))
    if number not in provided_numbers(user_text):
        raise HTTPException(422, 'Use only a phone number explicitly supplied by the visitor')
    values = {'phone':number}
    for field, limit in [('name',120), ('preferred_time',200), ('reason',400)]:
        value = str(args.get(field, '')).strip()
        if len(value)>limit:
            raise HTTPException(422, 'Callback details are too long')
        # A preferred time is a visitor request, never a promised appointment.
        if field=='preferred_time' and value and value.casefold() not in user_text.casefold():
            raise HTTPException(422, 'Use only a callback time supplied by the visitor')
        values[field]=value
    return values


def wording(text):
    normalized = ' '.join(text.casefold().translate(str.maketrans('', '', string.punctuation)).split())
    for prefix in ['could you please ', 'can you please ', 'i would like to ', 'i want to ',
                   'could you ', 'can you ', 'please ']:
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix):]
            break
    return any(normalized.startswith(phrase) for phrase in ['call me back', 'request a callback'])


def draft(text):
    numbers = provided_numbers(text)
    if len(numbers)!=1:
        return None
    return {'phone':next(iter(numbers)), 'name':'', 'preferred_time':'', 'reason':text[:400]}


def execute(args, context):
    from .tool_safety import approved
    if not approved('request_callback', args, context):
        raise HTTPException(409, 'Confirm the complete callback request first')
    if not settings.callback_requests_enabled:
        return {'error':'Callback requests are currently disabled','state':'failed'}
    args = validate(args, context['user_text'])
    workspace_id = context['workspace_id']
    operation = 'callback:' + hashlib.sha256(context['operation_id'].encode()).hexdigest()
    with session_scope(write=True) as db:
        db.scalar(select(Workspace).where(Workspace.id==workspace_id).with_for_update())
        previous = db.scalar(select(Ticket).where(Ticket.workspace_id==workspace_id, Ticket.operation_key==operation))
        if previous:
            return {'ticket_id':previous.id, 'callback_requested':True, 'state':'recorded', 'message':RECORDED}
        conversation_id=context.get('conversation_id')
        if conversation_id:
            conversation=db.scalar(select(Conversation).where(Conversation.workspace_id==workspace_id,Conversation.id==conversation_id))
            if conversation is None:raise HTTPException(404, 'Conversation unavailable')
        else:
            call=db.scalar(select(Call).where(Call.workspace_id==workspace_id,Call.id==context.get('call_id')))
            if call is None:raise HTTPException(404, 'Call unavailable')
            conversation_id=call.metadata_data.get('conversation_id')
            if not conversation_id:
                conversation=Conversation(workspace_id=workspace_id,channel='voice')
                db.add(conversation);db.flush();conversation_id=conversation.id
                call.metadata_data={**call.metadata_data,'conversation_id':conversation_id}
        description = (f"Callback requested by visitor.\nPhone: {args['phone']} (caller-provided, unverified)\n"
                       f"Name: {args['name'] or 'Not provided'}\n"
                       f"Preferred time: {args['preferred_time'] or 'Not specified'} (not confirmed)\n"
                       f"Reason: {args['reason']}\nPermission: confirmed request for this callback only; not marketing consent.")
        ticket=Ticket(workspace_id=workspace_id,conversation_id=conversation_id,subject='Callback request',
                      description=description,operation_key=operation)
        db.add(ticket);db.flush()
        emit(db,workspace_id,'ticket.created',{'ticket_id':ticket.id})
        emit(db,workspace_id,'callback.requested',{'ticket_id':ticket.id})
        owners=db.scalars(select(User.email).join(Membership,Membership.user_id==User.id).where(
            Membership.workspace_id==workspace_id,Membership.role=='owner'))
        for email in owners:
            enqueue_email(db,email,'A visitor requested a callback',description+'\nReview and update the request in your team inbox.',
                          operation_key=operation+':'+hashlib.sha256(email.encode()).hexdigest()[:32])
        return {'ticket_id':ticket.id,'callback_requested':True,'state':'recorded','message':RECORDED}

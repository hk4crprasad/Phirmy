"""Call-agent scheduling: real availability, read-back, consent and durable results."""
import asyncio
from datetime import datetime, timedelta
import hashlib
import json
import re
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field, field_validator, ValidationError
from sqlalchemy import select

from . import scheduling_providers as remote
from .db import session_scope, now
from .domain import owned, emit
from .models import (ConnectorCredential, Connection, Workspace, Appointment,
                     SchedulingAvailability, SchedulingBooking)
from .schemas import Input
from .secrets import decrypt, encrypt
from .scheduling_oauth import ensure_access, note_auth_failure, revision as scheduling_revision
from .security import principal, db_dependency, audit
from .async_work import durable_to_thread

router = APIRouter(prefix='/v1/workspaces/{workspace_id}')
PROVIDERS = ('calcom', 'calendly')
TOOL_NAMES = ('check_scheduling_availability', 'prepare_scheduling_booking', 'confirm_scheduling_booking', 'get_scheduling_booking')


class AvailabilityInput(Input):
    provider: Literal['calcom', 'calendly']
    start: datetime
    end: datetime
    timezone: str = Field(max_length=80)

    @field_validator('timezone')
    @classmethod
    def valid_zone(cls, value):
        try:
            ZoneInfo(value)
        except Exception:
            raise ValueError('Use an IANA timezone such as Asia/Kolkata') from None
        return value


class PrepareInput(Input):
    availability_id: str = Field(min_length=1, max_length=36)
    start: datetime
    name: str = Field(min_length=1, max_length=160)
    email: str = Field(min_length=3, max_length=254)
    phone: str = Field(default='', max_length=20)
    answers: dict[str, str] = Field(default_factory=dict, max_length=20)

    @field_validator('email')
    @classmethod
    def email_address(cls, value):
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', value):
            raise ValueError('Ask for a valid confirmation email')
        return value.lower()

    @field_validator('phone')
    @classmethod
    def phone_number(cls, value):
        if value and not re.fullmatch(r'\+[1-9]\d{6,14}', value):
            raise ValueError('Use the caller-provided phone in international format')
        return value


class BookingInput(Input):
    booking_id: str = Field(min_length=1, max_length=36)


class BookingSettings(Input):
    event_type_id: str = Field(min_length=1, max_length=200)


def context_key(context):
    # A public voice call continues the widget conversation, including a booking
    # prepared in text. Ordinary phone/browser calls retain their call scope.
    if context.get('conversation_id'):
        return 'conversation:' + context['conversation_id']
    if context.get('call_id'):
        return 'call:' + context['call_id']
    raise ValueError('A call or conversation is required')


def credentials(db, ws, provider):
    connection = db.scalar(select(Connection).where(Connection.workspace_id == ws, Connection.provider == provider))
    secret = db.scalar(select(ConnectorCredential).where(ConnectorCredential.workspace_id == ws, ConnectorCredential.provider == provider))
    if provider not in PROVIDERS or not connection or connection.state != 'connected' or not secret:
        raise ValueError('Connect the scheduling provider first')
    data = json.loads(decrypt(secret.encrypted_data))
    if data.get("_oauth", {}).get("status", "ready") != "ready": raise ValueError("Scheduling authorization needs refreshing. Check availability again.")
    return data, scheduling_revision(data, secret.encrypted_data)


def bound_credentials(db, availability):
    data, revision = credentials(db, availability.workspace_id, availability.provider)
    if revision != availability.credential_revision or str(data.get('event_type_id')) != availability.event_type_id:
        raise ValueError('The scheduling connection changed. Check availability again.')
    return data


def error_text(exc):
    if isinstance(exc, ValidationError):
        field = str(exc.errors()[0]['loc'][0]).replace('_', ' ') if exc.errors()[0]['loc'] else 'booking details'
        return 'Please check the ' + field + ' before booking.'
    if isinstance(exc, remote.ProviderError):
        if exc.status in (401, 403):
            return 'The scheduling account needs access approval. Calendly direct booking requires Standard or above and scheduling permissions.'
        if exc.status == 429:
            return 'The scheduling service is busy. Please try checking availability later.'
        return 'The scheduling service could not complete this request. Do not claim a booking.'
    return str(exc) if isinstance(exc, ValueError) else 'Scheduling could not be completed. Ask for the missing details.'


@router.get('/connections/{provider}/event-types')
async def event_types(workspace_id: str, provider: str, actor=Depends(principal), db=Depends(db_dependency, scope='function')):
    actor.require('settings:read')
    db.commit()
    try:
        await ensure_access(workspace_id, provider)
        data, _ = credentials(db, workspace_id, provider)
        rows = await remote.event_types(provider, data)
        return {'items': [{k: r.get(k) for k in ('id', 'title', 'duration_minutes', 'supported', 'unavailable_reason')} for r in rows]}
    except Exception as exc:
        if 'data' in locals(): await asyncio.to_thread(note_auth_failure, workspace_id, provider, data, exc)
        raise HTTPException(422 if isinstance(exc, ValueError) else 502, error_text(exc)) from None


@router.put('/connections/{provider}/booking-settings')
async def booking_settings(workspace_id: str, provider: str, body: BookingSettings, actor=Depends(principal), db=Depends(db_dependency, scope='function')):
    actor.require('settings:write')
    db.commit()
    try:
        await ensure_access(workspace_id, provider)
        data, revision = credentials(db, workspace_id, provider)
        event = await remote.event(provider, data, body.event_type_id)
        if not event['supported']:
            raise ValueError(event['unavailable_reason'])
        # Do not overwrite a connection replaced while its event was loading.
        db.scalar(select(Workspace).where(Workspace.id == workspace_id).with_for_update())
        latest, current = credentials(db, workspace_id, provider)
        if current != revision:
            raise ValueError('The connection changed. Please select the event again.')
        data = latest
        secret = db.scalar(select(ConnectorCredential).where(ConnectorCredential.workspace_id == workspace_id, ConnectorCredential.provider == provider))
        data['event_type_id'] = event['id']
        if event.get('scheduling_url'): data['booking_url'] = event['scheduling_url']
        secret.encrypted_data = encrypt(json.dumps(data))
        connection = db.scalar(select(Connection).where(Connection.workspace_id == workspace_id, Connection.provider == provider))
        connection.scopes = list(dict.fromkeys(connection.scopes + ['availability:read', 'bookings:write']))
        audit(db, actor, 'scheduling.configured', connection.id, {'provider': provider, 'event_type_id': event['id']})
        return {'status': 'configured', 'event': {k: event[k] for k in ('id', 'title', 'duration_minutes')}}
    except Exception as exc:
        if 'data' in locals(): await asyncio.to_thread(note_auth_failure, workspace_id, provider, data, exc)
        raise HTTPException(422 if isinstance(exc, ValueError) else 502, error_text(exc)) from None


async def availability(args, context):
    body = AvailabilityInput.model_validate(args)
    if context.get('scheduling_provider') and body.provider != context['scheduling_provider']:
        raise ValueError('Use the scheduling service configured for this agent.')
    if not body.start.tzinfo or not body.end.tzinfo or body.start <= now() or not timedelta() < body.end - body.start <= timedelta(days=7):
        raise ValueError('Ask for a future start/end with timezone, within a seven-day search window.')
    ws, key = context['workspace_id'], context_key(context)
    await ensure_access(ws, body.provider)
    def load_credentials():
        with session_scope() as db:return credentials(db,ws,body.provider)
    data,revision=await asyncio.to_thread(load_credentials)
    try:
        event = await remote.event(body.provider, data)
        slots = await remote.slots(body.provider, data, event, body.start, body.end, body.timezone)
    except remote.ProviderError as exc:
        await asyncio.to_thread(note_auth_failure, ws, body.provider, data, exc); raise
    def persist_availability():
        with session_scope(write=True) as db:
            _, current = credentials(db, ws, body.provider)
            if current != revision:
                raise ValueError('The scheduling connection changed. Check availability again.')
            row = SchedulingAvailability(workspace_id=ws, provider=body.provider, event_type_id=event['id'],
                context_key=key, credential_revision=revision, timezone=body.timezone, event_data=event, slots=slots,
                expires_at=now() + timedelta(minutes=10))
            db.add(row); db.flush()
            return {'availability_id': row.id, 'provider': row.provider, 'event': event['title'],
                    'timezone': row.timezone, 'slots': slots, 'questions': event['questions'],
                    'phone_required': event['phone_required'], 'remote_calendar_checked': True,
                    'message': 'Offer only these returned slots. Collect name, email and any required answers before preparing a booking.'}
    return await durable_to_thread(persist_availability)


def normalize_evidence(value):
    value = re.sub(r'\bat\b', '@', value.lower())
    value = re.sub(r'\bdot\b', '.', value)
    return re.sub(r'\s+', '', value)


def caller_details(body, event, context):
    history = context.get('user_history', []) + [context.get('user_text', '')]
    evidence = ' '.join(history)
    if normalize_evidence(body.email) not in normalize_evidence(evidence):
        raise ValueError('Ask the caller for the confirmation email. Do not invent an address.')
    if normalize_evidence(body.name) not in normalize_evidence(evidence):
        raise ValueError('Ask the caller for their name before preparing the booking.')
    if body.phone and re.sub(r'\D', '', body.phone) not in re.sub(r'\D', '', evidence + str(context.get('caller_number') or '')):
        raise ValueError('Ask for the phone number. Do not invent one.')
    if event['phone_required'] and not body.phone:
        raise ValueError('This meeting needs the caller’s phone number in international format.')
    allowed = {q['key'] for q in event['questions']}
    if set(body.answers) - allowed:
        raise ValueError('Use only the questions returned with availability.')
    for question in event['questions']:
        answer = body.answers.get(question['key'], '').strip()
        if question['required'] and not answer:
            raise ValueError('Ask the caller: ' + question['label'])
        if answer and (len(answer) > 1000 or normalize_evidence(answer) not in normalize_evidence(evidence)):
            raise ValueError('Collect the caller’s answer to ' + question['label'] + '; do not invent it.')


def summary_text(data):
    time = remote.timestamp(data['start']).astimezone(ZoneInfo(data['timezone']))
    minutes = int((remote.timestamp(data['end']) - remote.timestamp(data['start'])).total_seconds() / 60)
    return (data['event_title'] + ' for ' + data['name'] + ' on ' + time.strftime('%A, %d %B %Y at %I:%M %p') +
            ' ' + data['timezone'] + ' for ' + str(minutes) + ' minutes, using email ' + data['email'] +
            (', phone ' + data['phone'] if data.get('phone') else ''))


def public_booking(row):
    data = row.request_data
    result = {'id': row.id, 'booking_id': row.id, 'provider': row.provider, 'state': row.state, 'booking_confirmed': row.state == 'confirmed',
              'start': data['start'], 'end': data['end'], 'timezone': data['timezone'], 'event': data['event_title'],
              'appointment_id': row.appointment_id, 'remote_id': row.remote_id, **row.result}
    if row.state == 'prepared':
        result['confirmation_text'] = row.confirmation_text
    return result


def prepare(args, context):
    body = PrepareInput.model_validate(args)
    ws, key = context['workspace_id'], context_key(context)
    with session_scope(write=True) as db:
        db.scalar(select(Workspace).where(Workspace.id == ws).with_for_update())
        offer = owned(db, SchedulingAvailability, ws, body.availability_id)
        if offer.context_key != key or offer.expires_at <= now():
            raise ValueError('Check availability again in this conversation before preparing a booking.')
        bound_credentials(db, offer)
        start = remote.utc(body.start)
        slot = next((s for s in offer.slots if s['start'] == start), None)
        if not slot or body.start <= now():
            raise ValueError('Choose an available future slot returned by the scheduling service.')
        caller_details(body, offer.event_data, context)
        previous = db.scalar(select(SchedulingBooking).where(SchedulingBooking.workspace_id == ws,
            SchedulingBooking.context_key == key, SchedulingBooking.provider == offer.provider,
            SchedulingBooking.state.in_(['submitting', 'unknown', 'pending_approval', 'confirmed'])))
        if previous:
            return public_booking(previous)
        operation = hashlib.sha256((key + ':' + offer.provider + ':' + offer.event_type_id + ':' + start).encode()).hexdigest()
        row = db.scalar(select(SchedulingBooking).where(SchedulingBooking.workspace_id == ws, SchedulingBooking.operation_key == operation))
        if row and row.state != 'prepared':
            return public_booking(row)
        data = {'start': start, 'end': slot['end'], 'timezone': offer.timezone, 'event_type_id': offer.event_type_id,
                'event_title': offer.event_data['title'], 'name': body.name, 'email': body.email, 'phone': body.phone,
                'answers': body.answers}
        if not row:
            row = SchedulingBooking(workspace_id=ws, availability_id=offer.id, provider=offer.provider, context_key=key,
                operation_key=operation, request_data=data, prepared_turn=context['operation_id'], confirmation_text='')
            db.add(row)
        row.request_data, row.availability_id, row.prepared_turn = data, offer.id, context['operation_id']
        row.expires_at, row.result = now() + timedelta(minutes=10), {}
        questions = ' '.join(q['label'] + ': ' + body.answers[q['key']] + '.' for q in offer.event_data['questions'] if q['key'] in body.answers)
        row.confirmation_text = 'Please confirm: ' + summary_text(data) + '.' + (' ' + questions if questions else '') + ' Should I book it?'
        db.flush()
        return public_booking(row)


def explicit_confirmation(text):
    value = re.sub(r'[,!.?;:।]', ' ', text.strip().lower())
    value = re.sub(r'\s+', ' ', value).strip()
    if re.search(r"\b(no|not|don.t|cancel|change|different|wait|stop|hold)\b|नहीं|नही|मत", value):
        return False
    # A qualified "yes, but at 11" changes the request; it does not authorize
    # the earlier time. Keep confirmation phrases deliberately unambiguous.
    return bool(re.fullmatch(
        r'(yes|yeah|yep|confirm|confirmed|correct|okay|ok|i confirm|please book|please confirm|book it|go ahead|haan|han|हाँ|हां|जी)'
        r'( (please|book|it|that|is|correct|i|confirm|confirmed|go|ahead|schedule|the|meeting|appointment|thank|you|thanks|okay|ok|kar|do|kardo|जी|हाँ|हां|कर|दो|बुक|पक्का))*', value))


def locked_booking(db,booking_id):
    workspace_id=db.scalar(select(SchedulingBooking.workspace_id).where(SchedulingBooking.id==booking_id))
    if workspace_id is None:return None
    db.scalar(select(Workspace.id).where(Workspace.id==workspace_id).with_for_update())
    return db.scalar(select(SchedulingBooking).where(SchedulingBooking.id==booking_id).with_for_update()
                     .execution_options(populate_existing=True))


def store_result(booking_id, result):
    with session_scope(write=True) as db:
        row = locked_booking(db,booking_id)
        if row is None:raise HTTPException(404,'Booking record unavailable')
        if row.state in ('confirmed', 'canceled') and result['state'] not in ('confirmed', 'canceled'):
            return public_booking(row)
        previous_state = row.state
        row.remote_id, row.remote_event_uri = result['remote_id'], result.get('remote_event_uri')
        row.state = result['state']
        row.result = {'manage_url': result['manage_url'], 'last_checked_at': now().isoformat()}
        if not row.appointment_id and row.state != 'failed':
            item = Appointment(workspace_id=row.workspace_id, title=row.request_data['event_title'],
                start_at=remote.timestamp(row.request_data['start']), end_at=remote.timestamp(row.request_data['end']),
                timezone=row.request_data['timezone'], operation_key='scheduling:' + row.id, state=row.state)
            db.add(item); db.flush(); row.appointment_id = item.id
        elif row.appointment_id:
            db.get(Appointment, row.appointment_id).state = row.state
        if row.state != previous_state:
            emit(db, row.workspace_id, 'appointment.' + row.state, {'appointment_id': row.appointment_id, 'provider': row.provider})
        return public_booking(row)


def mark_unknown(booking_id):
    with session_scope(write=True) as db:
        row = locked_booking(db,booking_id)
        if row and row.state == 'submitting':
            row.state = 'unknown'
            row.result = {'message': 'The provider may have received this booking. Check its status before trying another time.'}


def cancel_unsubmitted(booking_id):
    with session_scope(write=True) as db:
        row=locked_booking(db,booking_id)
        if row and row.state=='submitting':
            row.state='failed'
            row.result={'message':'Booking canceled before external submission.'}


async def confirm(args, context):
    body = BookingInput.model_validate(args)
    ws, key = context['workspace_id'], context_key(context)
    def load_prepared():
        with session_scope(write=True) as db:
            db.scalar(select(Workspace).where(Workspace.id == ws).with_for_update())
            row = owned(db, SchedulingBooking, ws, body.booking_id)
            if row.context_key != key:
                raise ValueError('This booking belongs to another conversation.')
            if row.state != 'prepared':
                return {'public':public_booking(row)}
            if (row.expires_at <= now() or row.prepared_turn == context['operation_id'] or
                    row.confirmation_text not in context.get('last_assistant_text', '') or not explicit_confirmation(context.get('user_text', ''))):
                raise ValueError('Read back the exact booking details and wait for the caller’s clear confirmation.')
            offer = db.get(SchedulingAvailability, row.availability_id)
        return {'snapshot':row,'offer':offer}
    prepared=await asyncio.to_thread(load_prepared)
    if 'public' in prepared:return prepared['public']
    snapshot,offer=prepared['snapshot'],prepared['offer']
    await ensure_access(ws, snapshot.provider)
    def load_bound_credentials():
        with session_scope() as db:return bound_credentials(db,db.get(SchedulingAvailability,snapshot.availability_id))
    data=await asyncio.to_thread(load_bound_credentials)
    # Recheck the provider immediately before committing the one-shot intent.
    metadata = await remote.event(snapshot.provider, data)
    if metadata != offer.event_data:
        raise ValueError('The meeting settings changed. Check availability and read back the details again.')
    current = await remote.slots(snapshot.provider, data, metadata, remote.timestamp(snapshot.request_data['start']),
                                 remote.timestamp(snapshot.request_data['end']), snapshot.request_data['timezone'])
    if not any(s['start'] == snapshot.request_data['start'] and s['end'] == snapshot.request_data['end'] for s in current):
        raise ValueError('That time is no longer available. Check availability and offer another slot.')
    if metadata['duration_minutes'] != int((remote.timestamp(snapshot.request_data['end']) - remote.timestamp(snapshot.request_data['start'])).total_seconds() / 60):
        raise ValueError('The event duration changed. Check availability again.')
    def claim_submission():
        with session_scope(write=True) as db:
            db.scalar(select(Workspace).where(Workspace.id == ws).with_for_update())
            row = owned(db, SchedulingBooking, ws, body.booking_id)
            if row.state != 'prepared':
                return {'public':public_booking(row)}
            existing = db.scalar(select(SchedulingBooking.id).where(SchedulingBooking.workspace_id == ws,
                SchedulingBooking.context_key == key, SchedulingBooking.provider == row.provider, SchedulingBooking.id != row.id,
                SchedulingBooking.state.in_(['submitting', 'unknown', 'pending_approval', 'confirmed'])).limit(1))
            if existing:
                raise ValueError('This conversation already has a booking request. Check its status before creating another.')
            offer = db.get(SchedulingAvailability, row.availability_id)
            bound_credentials(db, offer)
            if row.expires_at <= now() or row.prepared_turn != snapshot.prepared_turn or row.request_data != snapshot.request_data:
                raise ValueError('The booking details changed. Read them back and ask for confirmation again.')
            # Required fields/location may change since the first offer. Never fill
            # newly required answers from guesses after the caller has confirmed.
            caller_details(PrepareInput(availability_id=offer.id, start=row.request_data['start'], name=row.request_data['name'],
                email=row.request_data['email'], phone=row.request_data['phone'], answers=row.request_data['answers']), metadata, context)
            row.state = 'submitting'
        return {'snapshot':row}
    try:
        claimed=await durable_to_thread(claim_submission)
    except asyncio.CancelledError:
        await durable_to_thread(cancel_unsubmitted,snapshot.id)
        raise
    if 'public' in claimed:return claimed['public']
    snapshot=claimed['snapshot']
    try:
        result = await remote.create(snapshot.provider, data, snapshot, metadata)
        return await durable_to_thread(store_result,snapshot.id,result)
    except asyncio.CancelledError:
        await durable_to_thread(mark_unknown,snapshot.id)
        raise
    except Exception as exc:
        await asyncio.to_thread(note_auth_failure, ws, snapshot.provider, data, exc)
        if isinstance(exc, remote.ProviderError) and exc.definitive_rejection:
            def reject_submission():
                with session_scope(write=True) as db:
                    row = locked_booking(db,snapshot.id)
                    if row.state == 'submitting':
                        row.state, row.result = 'failed', {'message': error_text(exc)}
                    return public_booking(row)
            return await durable_to_thread(reject_submission)
        await durable_to_thread(mark_unknown,snapshot.id)
        return await refresh_booking(snapshot.id, ws, key)


async def refresh_booking(booking_id, ws, key=None):
    def load_provider():
        with session_scope() as db:
            initial = owned(db, SchedulingBooking, ws, booking_id)
            if key and initial.context_key != key: raise ValueError('This booking belongs to another conversation.')
            provider = initial.provider
        return provider
    provider=await asyncio.to_thread(load_provider)
    try:
        await ensure_access(ws, provider)
    except ValueError:
        def reconnect_result():
            with session_scope() as db:
                return {**public_booking(owned(db, SchedulingBooking, ws, booking_id)), 'status_refreshed':False, 'message':'Reconnect the scheduling account to check the latest status.'}
        return await asyncio.to_thread(reconnect_result)
    def load_snapshot():
        with session_scope() as db:
            row = owned(db, SchedulingBooking, ws, booking_id)
            if key and row.context_key != key:
                raise ValueError('This booking belongs to another conversation.')
            if row.state not in ('submitting', 'unknown', 'pending_approval', 'confirmed'):
                return {'public':public_booking(row)}
            offer = db.get(SchedulingAvailability, row.availability_id)
            try:
                data = bound_credentials(db, offer)
            except ValueError:
                return {'public':{**public_booking(row), 'status_refreshed': False, 'message': 'Reconnect the original scheduling account to refresh its status.'}}
            metadata = offer.event_data
        return {'row':row,'data':data,'metadata':metadata}
    snapshot=await asyncio.to_thread(load_snapshot)
    if 'public' in snapshot:return snapshot['public']
    row,data,metadata=snapshot['row'],snapshot['data'],snapshot['metadata']
    try:
        async with asyncio.timeout(25):
            result = await remote.reconcile(row.provider, data, row, metadata)
        if result:
            return await durable_to_thread(store_result,row.id,result)
    except Exception as exc:
        await asyncio.to_thread(note_auth_failure, ws, row.provider, data, exc)
    await durable_to_thread(mark_unknown,row.id)
    def latest_result():
        with session_scope() as db:
            return {**public_booking(db.get(SchedulingBooking, row.id)), 'status_refreshed': False,
                    'message': 'The latest provider status could not be confirmed. The recorded status is shown.'}
    return await asyncio.to_thread(latest_result)


async def agent_action(name, args, context):
    try:
        if name == 'check_scheduling_availability':
            return await availability(args, context)
        if name == 'prepare_scheduling_booking':
            return await durable_to_thread(prepare,args,context)
        if name == 'confirm_scheduling_booking':
            return await confirm(args, context)
        if name == 'get_scheduling_booking':
            body = BookingInput.model_validate(args)
            return await refresh_booking(body.booking_id, context['workspace_id'], context_key(context))
        raise ValueError('Scheduling action is not enabled.')
    except HTTPException as exc:
        return {'error': 'This scheduling record is not available in your workspace.' if exc.status_code == 404 else 'Scheduling could not finish.', 'booking_confirmed': False}
    except Exception as exc:
        return {'error': error_text(exc), 'booking_confirmed': False}


def spoken_result(result):
    if result.get('confirmation_text'):
        return result['confirmation_text']
    state = result.get('state')
    if result.get('status_refreshed') is False and state == 'confirmed':
        return 'Your booking was previously confirmed, but I could not check its latest status just now.'
    if state == 'confirmed':
        return 'Your booking is confirmed for ' + remote.timestamp(result['start']).astimezone(ZoneInfo(result['timezone'])).strftime('%A, %d %B at %I:%M %p') + ' ' + result['timezone'] + '.'
    if state == 'pending_approval':
        return 'Your booking request was received and is waiting for the host’s approval. It is not confirmed yet.'
    if state in ('unknown', 'submitting'):
        return 'I’m checking whether the scheduling service received your request. Please don’t make another booking until its status is confirmed.'
    if state == 'canceled':
        return 'The scheduling service reports that this booking was canceled.'
    if state == 'failed':
        return result.get('message', 'The booking could not be completed. Please use the scheduling page or contact the team.')
    return None


@router.get('/scheduling-bookings')
def bookings(workspace_id: str, actor=Depends(principal), db=Depends(db_dependency, scope='function')):
    actor.require('appointments:read')
    rows = db.scalars(select(SchedulingBooking).where(SchedulingBooking.workspace_id == workspace_id)
                      .order_by(SchedulingBooking.created_at.desc()).limit(100))
    return {'items': [public_booking(row) for row in rows]}


@router.post('/scheduling-bookings/{booking_id}/refresh')
async def refresh(workspace_id: str, booking_id: str, actor=Depends(principal), db=Depends(db_dependency, scope='function')):
    actor.require('appointments:write')
    db.commit()
    return await refresh_booking(booking_id, workspace_id)

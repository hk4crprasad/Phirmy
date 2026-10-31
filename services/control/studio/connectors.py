"""Explicit, encrypted, verifiable business connectors. No arbitrary tool URLs."""
import hashlib
import json
from urllib.parse import quote, urlparse
import httpx
from fastapi import APIRouter,Depends,HTTPException,Request
from pydantic import Field
from sqlalchemy import select
from .db import session_scope,as_dict
from .config import settings
from .models import Connection,ConnectorCredential,ConnectorAction,Lead,Appointment,Workspace,Number,Call
from .security import principal,db_dependency,audit
from .domain import owned, enqueue
from .schemas import Input
from .secrets import encrypt,decrypt

router=APIRouter(prefix='/v1/workspaces/{workspace_id}')
PROVIDERS = {'hubspot': 'HubSpot', 'google_calendar': 'Google Calendar', 'sms': 'Plivo SMS',
             'calcom': 'Cal.com', 'calendly': 'Calendly', 'twilio': 'Twilio', 'plivo': 'Plivo'}
SUPPORTED=set(PROVIDERS)


class Connect(Input):
    credentials:dict=Field(default_factory=dict, max_length=12)


class Action(Input):
    action:str=Field(max_length=60)
    input:dict=Field(default_factory=dict)


async def request(method,url,headers=None,**kwargs):
    async with httpx.AsyncClient(timeout=20,follow_redirects=False) as client:
        response=await client.request(method,url,headers=headers,**kwargs)
        if response.status_code>=400:
            raise HTTPException(502,'Provider request failed (HTTP '+str(response.status_code)+'). Check credentials, scopes and provider logs.')
        return response.json() if response.content else {}


async def google_token(credentials):
    data=await request('POST','https://oauth2.googleapis.com/token',data={'client_id':credentials['client_id'],'client_secret':credentials['client_secret'],'refresh_token':credentials['refresh_token'],'grant_type':'refresh_token'})
    return {'Authorization':'Bearer '+data['access_token']}


async def test_connection(provider,c):
    try:
        if provider=='hubspot':
            await request('GET','https://api.hubapi.com/crm/v3/objects/contacts?limit=1',headers={'Authorization':'Bearer '+c['access_token']})
        elif provider=='google_calendar':
            headers=await google_token(c)
            await request('GET','https://www.googleapis.com/calendar/v3/calendars/'+quote(c.get('calendar_id','primary'),safe=''),headers=headers)
        elif provider=='sms':
            import plivo,asyncio
            client=plivo.RestClient(c['auth_id'],c['auth_token'])
            await asyncio.to_thread(client.accounts.get)
            if not c.get('sender'):raise ValueError('sender required')
        elif provider == 'calcom':
            await request('GET', 'https://api.cal.com/v2/me', headers={'Authorization': 'Bearer ' + c['api_key']})
            validate_booking_url(c.get('booking_url', ''), 'cal.com')
        elif provider == 'calendly':
            await request('GET', 'https://api.calendly.com/users/me', headers={'Authorization': 'Bearer ' + c['access_token']})
            validate_booking_url(c.get('booking_url', ''), 'calendly.com')
        elif provider == 'twilio':
            import asyncio
            from twilio.rest import Client
            await asyncio.to_thread(Client(c['account_sid'], c['auth_token']).api.accounts(c['account_sid']).fetch)
        elif provider == 'plivo':
            import asyncio, plivo
            await asyncio.to_thread(plivo.RestClient(c['auth_id'], c['auth_token']).accounts.get)
        else:raise HTTPException(422,'This connector is not supported yet')
    except HTTPException:raise
    except Exception:raise HTTPException(422,'Required connector settings are missing or invalid')


def validate_booking_url(url, host):
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.hostname != host or parsed.username or parsed.password or parsed.port not in (None, 443) or not parsed.path.strip('/'):
        raise HTTPException(422, 'Use your public https://' + host + '/ scheduling link')


@router.put('/connections/{provider}')
async def connect(workspace_id:str,provider:str,body:Connect,actor=Depends(principal),db=Depends(db_dependency,scope='function')):
    actor.require('settings:write')
    if provider not in SUPPORTED:raise HTTPException(422,'Choose an available integration')
    if any(key.startswith('_') for key in body.credentials): raise HTTPException(422, 'OAuth state can only be established through authorization')
    if len(json.dumps(body.credentials)) > 20000:raise HTTPException(413, 'Connection settings are too large')
    await test_connection(provider,body.credentials)
    db.scalar(select(Workspace).where(Workspace.id==workspace_id).with_for_update())
    row=db.scalar(select(Connection).where(Connection.workspace_id==workspace_id,Connection.provider==provider))
    if not row:
        row=Connection(workspace_id=workspace_id,provider=provider,name=PROVIDERS[provider]);db.add(row);db.flush()
    secret=db.scalar(select(ConnectorCredential).where(ConnectorCredential.workspace_id==workspace_id,ConnectorCredential.provider==provider))
    if not secret:secret=ConnectorCredential(workspace_id=workspace_id,provider=provider);db.add(secret)
    secret.encrypted_data=encrypt(json.dumps(body.credentials));row.state='connected'
    if provider in {'twilio', 'plivo'}:
        for number in db.scalars(select(Number).where(Number.workspace_id == workspace_id, Number.provider == provider)):
            number.status = 'unverified'
            enqueue(db, workspace_id, 'verify_number', {'number_id': number.id})
    row.scopes={'hubspot':['contacts.read','contacts.write'],'google_calendar':['calendar.events'],
                'sms':['messages.send'], 'calcom':['profile.read','scheduling.link'], 'calendly':['users.read','scheduling.link'],
                'twilio':['numbers.read','calls.write'], 'plivo':['numbers.read','calls.write']}[provider]
    audit(db,actor,'connection.connected',row.id)
    return as_dict(row)


@router.get('/connections/{provider}/scheduling-link')
def scheduling_link(workspace_id: str, provider: str, actor=Depends(principal), db=Depends(db_dependency, scope='function')):
    actor.require('appointments:read')
    if provider not in {'calcom', 'calendly'}:
        raise HTTPException(422, 'Choose a connected scheduling service')
    secret = db.scalar(select(ConnectorCredential).where(ConnectorCredential.workspace_id == workspace_id,
                       ConnectorCredential.provider == provider))
    if not secret:
        raise HTTPException(409, 'Connect your scheduling service first')
    c = json.loads(decrypt(secret.encrypted_data))
    validate_booking_url(c.get('booking_url', ''), 'cal.com' if provider == 'calcom' else 'calendly.com')
    return {'url': c['booking_url'], 'status': 'ready', 'booking_confirmed': False}


@router.delete('/connections/{provider}')
def disconnect(workspace_id:str,provider:str,actor=Depends(principal),db=Depends(db_dependency,scope='function')):
    actor.require('settings:write')
    db.scalar(select(Workspace).where(Workspace.id==workspace_id).with_for_update())
    row=db.scalar(select(Connection).where(Connection.workspace_id==workspace_id,Connection.provider==provider))
    if not row:raise HTTPException(404,'Connection not found')
    if provider in {'twilio', 'plivo'}:
        active = list(db.scalars(select(Call).where(Call.workspace_id == workspace_id, Call.transport == 'pstn',
                                    Call.state.in_(['created', 'connecting', 'ringing', 'connected', 'ending']))))
        if any(call.metadata_data.get('provider', 'plivo') == provider for call in active):
            raise HTTPException(409, 'End active calls before disconnecting this carrier')
        for number in db.scalars(select(Number).where(Number.workspace_id == workspace_id, Number.provider == provider)):
            number.status = 'unverified'
    secret=db.scalar(select(ConnectorCredential).where(ConnectorCredential.workspace_id==workspace_id,ConnectorCredential.provider==provider))
    if secret:db.delete(secret)
    row.state='disconnected';row.scopes=[];audit(db,actor,'connection.disconnected',row.id)
    return as_dict(row)


async def execute_action(provider,action,c,input,operation_id):
    if provider=='hubspot' and action=='sync_lead':
        if not input.get('email'):raise HTTPException(422,'A lead email is required for identity-safe CRM upsert')
        headers={'Authorization':'Bearer '+c['access_token']}
        result=await request('POST','https://api.hubapi.com/crm/v3/objects/contacts/batch/upsert',headers=headers,json={'inputs':[{'idProperty':'email','id':input['email'],'properties':{'email':input['email'],'firstname':input.get('name',''),'phone':input.get('phone','')}}]})
        return {'remote_id':result['results'][0]['id'],'status':'synced'}
    if provider=='google_calendar' and action=='sync_appointment':
        headers=await google_token(c);calendar=quote(c.get('calendar_id','primary'),safe='')
        remote_id=hashlib.sha256(('voice-studio-appointment:'+input.get('id',operation_id)).encode()).hexdigest()[:40]
        url='https://www.googleapis.com/calendar/v3/calendars/'+calendar+'/events'
        # Stable Google event ID allows reconciliation after a lost response without a duplicate.
        try:
            existing=await request('GET',url+'/'+remote_id,headers=headers)
            return {'remote_id':existing['id'],'status':'synced'}
        except HTTPException as exc:
            if 'HTTP 404' not in str(exc.detail):raise
        free=await request('POST','https://www.googleapis.com/calendar/v3/freeBusy',headers=headers,json={'timeMin':input['start_at'],'timeMax':input['end_at'],'items':[{'id':c.get('calendar_id','primary')}]})
        calendar_result = free.get('calendars', {}).get(c.get('calendar_id', 'primary'))
        if not isinstance(calendar_result, dict) or 'busy' not in calendar_result or calendar_result.get('errors') or calendar_result.get('busy'):
            raise HTTPException(409, 'Calendar is unavailable or this time is already busy')
        event=await request('POST',url,headers=headers,json={'id':remote_id,'summary':input['title'],'start':{'dateTime':input['start_at'],'timeZone':input['timezone']},'end':{'dateTime':input['end_at'],'timeZone':input['timezone']}})
        return {'remote_id':event['id'],'status':'synced'}
    if provider=='sms' and action=='send_sms':
        if input.get('consent_confirmed') is not True:raise HTTPException(422,'Confirm recipient consent before sending')
        import re,plivo,asyncio
        if not re.fullmatch(r'\+[1-9][0-9]{6,14}',input.get('to','')):raise HTTPException(422,'Use an E.164 recipient')
        text=input.get('text','')
        if not isinstance(text,str) or not 1<=len(text)<=1000:raise HTTPException(422,'SMS text must contain 1–1000 characters')
        client=plivo.RestClient(c['auth_id'],c['auth_token'])
        result=await asyncio.to_thread(client.messages.create,src=c['sender'],dst=input['to'],text=text)
        ids=getattr(result,'message_uuid',[]) if not isinstance(result,dict) else result.get('message_uuid',[])
        return {'remote_id':ids[0] if ids else None,'status':'accepted','delivery':'not_yet_confirmed'}
    raise HTTPException(422,'Unsupported connector action')


@router.post('/connections/{provider}/actions',status_code=202)
async def action(workspace_id:str,provider:str,body:Action,request:Request,actor=Depends(principal),db=Depends(db_dependency,scope='function')):
    actor.require('settings:write')
    key=request.headers.get('Idempotency-Key','')
    return await recorded_action(workspace_id, provider, body, key, db, actor)


async def recorded_action(workspace_id, provider, body, key, db, actor=None):
    if not key or len(key)>180:raise HTTPException(422,'Idempotency-Key required')
    source=dict(body.input)
    if body.action=='sync_lead':source=as_dict(owned(db,Lead,workspace_id,source.get('lead_id','')))
    elif body.action=='sync_appointment':
        source=as_dict(owned(db,Appointment,workspace_id,source.get('appointment_id','')))
        if source['state'] == 'canceled':
            raise HTTPException(409, 'A canceled appointment cannot be synced')
    hashed=hashlib.sha256(json.dumps({'provider':provider,'action':body.action,'input':source},sort_keys=True).encode()).hexdigest()
    db.scalar(select(Workspace).where(Workspace.id==workspace_id).with_for_update())
    previous=db.scalar(select(ConnectorAction).where(ConnectorAction.workspace_id==workspace_id,ConnectorAction.operation_key==key))
    if previous:
        if previous.request_hash!=hashed:raise HTTPException(409,'Idempotency key conflicts with earlier action')
        return as_dict(previous)
    secret=db.scalar(select(ConnectorCredential).where(ConnectorCredential.workspace_id==workspace_id,ConnectorCredential.provider==provider))
    if not secret:raise HTTPException(409,'Connect this provider first')
    c=json.loads(decrypt(secret.encrypted_data))
    row=ConnectorAction(workspace_id=workspace_id,provider=provider,action=body.action,operation_key=key,request_hash=hashed)
    db.add(row);db.flush();db.commit()
    try:
        row.result=await execute_action(provider,body.action,c,source,row.id)
        row.state='succeeded'
        if actor:
            audit(db,actor,'connection.action_succeeded',row.id)
    except HTTPException as exc:
        row.state='failed';row.result={'message':str(exc.detail)};db.commit()
        raise
    except Exception:
        row.state='unknown';row.result={'message':'Provider outcome is unknown. Reconcile before sending again.'};db.commit()
        raise HTTPException(502,'Provider outcome is unknown. Do not resubmit with a new key.')
    return as_dict(row)


async def agent_calendar_action(name, args, context):
    from .agent_tools import time_range
    ws = context['workspace_id']
    if name == 'check_calendar_availability':
        start, end = time_range(args)
        with session_scope() as db:
            secret = db.scalar(select(ConnectorCredential).where(ConnectorCredential.workspace_id == ws, ConnectorCredential.provider == 'google_calendar'))
            if not secret:
                return {'error': 'Google Calendar is not connected'}
            credentials = json.loads(decrypt(secret.encrypted_data))
        headers = await google_token(credentials)
        result = await request('POST', 'https://www.googleapis.com/calendar/v3/freeBusy', headers=headers,
                               json={'timeMin': start.isoformat(), 'timeMax': end.isoformat(), 'items': [{'id': credentials.get('calendar_id', 'primary')}]})
        calendars = list(result.get('calendars', {}).values())
        if not calendars or any(c.get('errors') for c in calendars):
            return {'error': 'Calendar availability could not be confirmed'}
        return {'scope': 'google-calendar', 'remote_calendar_checked': True,
                'busy': [busy for calendar in calendars for busy in calendar.get('busy', [])]}
    if name == 'sync_calendar_appointment':
        import re
        if not re.search(r'book|schedule|appointment|reserve', context['user_text'], re.I):
            return {'error': 'Ask the customer to confirm the booking first'}
        key = 'agent-calendar:' + hashlib.sha256((context['operation_id'] + ':' + str(args.get('appointment_id'))).encode()).hexdigest()
        with session_scope(write=True) as db:
            body = Action(action='sync_appointment', input={'appointment_id': args.get('appointment_id', '')})
            result = await recorded_action(ws, 'google_calendar', body, key, db)
            return {'state': result['state'], **result['result']}
    return {'error': 'Calendar action is unavailable'}


@router.get('/connector-actions')
def actions(workspace_id:str,actor=Depends(principal),db=Depends(db_dependency,scope='function')):
    actor.require('settings:read')
    return {'items':[as_dict(x) for x in db.scalars(select(ConnectorAction).where(ConnectorAction.workspace_id==workspace_id).order_by(ConnectorAction.created_at.desc()).limit(200))]}

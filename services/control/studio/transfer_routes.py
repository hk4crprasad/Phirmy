"""Staff destination approval, transfer status and signed carrier callbacks."""
import asyncio
import json
import math
from xml.etree.ElementTree import Element, SubElement, tostring

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import Field
from sqlalchemy import select

from .async_work import durable_to_thread
from .callbacks import phone
from .config import settings
from .db import now, session_scope, uid
from .models import TransferPolicy, CallTransfer, Call, Workspace
from .operator_billing import operator
from .security import principal, db_dependency, audit, Principal
from .schemas import Input
from .secrets import encrypt, decrypt
from . import transfers, admission

router=APIRouter()


class PolicyWrite(Input):
    destination:str=Field(max_length=30)
    label:str=Field(min_length=1,max_length=100)
    maximum_seconds:int=Field(default=120,ge=5,le=300)
    enabled:bool=False


class Approval(Input):
    revision:str
    approved:bool
    verified_staff:bool=False


def owner(actor):
    actor.require('settings:write')
    if actor.key_scopes is not None or actor.role not in {'owner','admin'}:
        raise HTTPException(403,'Use an owner or admin dashboard session')


def policy_data(row):
    if row is None:return {'configured':False,'live_activation_enabled':False}
    number=decrypt(row.encrypted_destination)
    return {'configured':True,'revision':row.revision,'label':row.label,'destination_last4':number[-4:],
            'maximum_seconds':row.maximum_seconds,'enabled':row.enabled,'approved':row.approved_at is not None,
            'live_activation_enabled':bool(settings.live_transfer_enabled and settings.live_calls_enabled and settings.paid_activation_enabled)}


@router.get('/v1/workspaces/{workspace_id}/transfer-policy')
def policy_get(workspace_id:str,actor=Depends(principal),db=Depends(db_dependency,scope='function')):
    owner(actor)
    return policy_data(db.scalar(select(TransferPolicy).where(TransferPolicy.workspace_id==workspace_id)))


@router.put('/v1/workspaces/{workspace_id}/transfer-policy')
def policy_write(workspace_id:str,body:PolicyWrite,actor=Depends(principal),db=Depends(db_dependency,scope='function')):
    owner(actor)
    number=phone(body.destination)
    if not body.label.strip():raise HTTPException(422,'A team label is required')
    db.scalar(select(Workspace).where(Workspace.id==workspace_id).with_for_update())
    row=db.scalar(select(TransferPolicy).where(TransferPolicy.workspace_id==workspace_id).with_for_update())
    if row is None:
        row=TransferPolicy(workspace_id=workspace_id);db.add(row)
    row.revision,row.label,row.encrypted_destination=uid(),body.label.strip(),encrypt(number)
    row.maximum_seconds,row.enabled=body.maximum_seconds,body.enabled
    row.approved_at,row.approved_by=None,None
    db.flush()
    audit(db,actor,'transfer.destination_changed',row.id)
    return policy_data(row)


@router.get('/v1/operator/transfers/{workspace_id}/policy')
def operator_policy(workspace_id:str,user=Depends(operator),db=Depends(db_dependency,scope='function')):
    row=db.scalar(select(TransferPolicy).where(TransferPolicy.workspace_id==workspace_id))
    result=policy_data(row)
    if row is not None:result['destination']=decrypt(row.encrypted_destination)
    return result


@router.post('/v1/operator/transfers/{workspace_id}/approval')
def approve(workspace_id:str,body:Approval,user=Depends(operator),db=Depends(db_dependency,scope='function')):
    db.scalar(select(Workspace).where(Workspace.id==workspace_id).with_for_update())
    row=db.scalar(select(TransferPolicy).where(TransferPolicy.workspace_id==workspace_id).with_for_update())
    if row is None or row.revision!=body.revision:
        raise HTTPException(409,'Review the current destination revision before approval')
    if body.approved and not body.verified_staff:
        raise HTTPException(422,'Confirm verification of the staff destination')
    row.approved_at,row.approved_by=(now(),user.id) if body.approved else (None,None)
    audit(db,Principal(user.id,workspace_id,'admin'),'transfer.approval_changed',row.id,{'revision':row.revision,'approved':body.approved})
    return policy_data(row)


def public(row):
    return {'id':row.id,'call_id':row.call_id,'provider':row.provider,'state':row.state,
            'created_at':row.created_at.isoformat(),'maximum_seconds':row.maximum_seconds,
            'child_bill_ms':row.child_bill_ms,'child_outcome':row.child_outcome,'error_code':row.error_code,
            'connection_confirmed':bool(row.child_bill_ms and row.state=='completed')}


@router.get('/v1/workspaces/{workspace_id}/call-transfers')
def listing(workspace_id:str,actor=Depends(principal),db=Depends(db_dependency,scope='function')):
    actor.require('calls:read')
    return {'items':[public(row) for row in db.scalars(select(CallTransfer).where(CallTransfer.workspace_id==workspace_id)
        .order_by(CallTransfer.created_at.desc(),CallTransfer.id.desc()).limit(100))]}


def binding(identity):
    with session_scope() as db:
        row=db.get(CallTransfer,identity)
        if row is None:raise HTTPException(404,'Transfer unavailable')
        return {'provider':row.provider,'parent_leg_id':row.parent_leg_id,**transfers.snapshot(row)}


async def verified(request,identity,*,child=False):
    # Callbacks stay available after activation is disabled, so already-started
    # calls can settle. Only a valid frozen account signature authorizes them.
    data=await asyncio.to_thread(binding,identity)
    form={key:str(value) for key,value in (await request.form()).items()}
    url=settings.media_public_origin.rstrip('/')+request.url.path+('?' +request.url.query if request.url.query else '')
    if not url.startswith('https://'):raise HTTPException(503,'HTTPS callback origin required')
    credentials=data['credentials']
    if data['provider']=='twilio':
        from twilio.request_validator import RequestValidator
        if (not RequestValidator(credentials['auth_token']).validate(url,form,request.headers.get('X-Twilio-Signature',''))
                or form.get('AccountSid')!=credentials['account_sid'] or form.get('CallSid')!=data['parent_leg_id']):
            raise HTTPException(401,'Invalid transfer callback')
    else:
        from plivo.utils import validate_v3_signature
        signature=request.headers.get('x-plivo-signature-v3','');nonce=request.headers.get('x-plivo-signature-v3-nonce','')
        parent=form.get('DialALegUUID') if child else form.get('CallUUID')
        if (not signature or not nonce or not validate_v3_signature(request.method,url,nonce,credentials['auth_token'],signature,form)
                or parent!=data['parent_leg_id']):
            raise HTTPException(401,'Invalid transfer callback')
    return form


def instructions(identity):
    with session_scope(write=True) as db:
        row=transfers.locked(db,identity)
        if row is None:raise HTTPException(404,'Transfer unavailable')
        root=Element('Response')
        try:
            _,policy=transfers.eligible(db,row.workspace_id,row.call_id)
            valid=policy.revision==transfers.snapshot(row)['revision']
        except HTTPException:valid=False
        remaining=math.floor((row.deadline_at-now()).total_seconds())
        maximum=min(row.maximum_seconds,remaining-20)
        if not valid or maximum<5 or row.xml_served_at is not None or row.state not in {'submitting','accepted','unknown'}:
            SubElement(root,'Hangup')
            if row.xml_served_at is None:
                row.state='failed';row.error_code='instructions_denied'
                admission.finish(db,row.workspace_id,transfers.cost_key(row.id))
            return tostring(root,encoding='unicode')
        row.xml_served_at=now();row.state='accepted'
        status=settings.media_public_origin.rstrip('/')+'/v1/transfer-webhooks/'+row.id+'/status'
        if row.provider=='plivo':
            SubElement(root,'Hangup',{'schedule':str(max(1,remaining))})
            dial=SubElement(root,'Dial',{'timeLimit':str(maximum),'timeout':'10','action':status,
                'method':'POST','callbackUrl':status,'callbackMethod':'POST','redirect':'true'})
        else:
            dial=SubElement(root,'Dial',{'timeLimit':str(maximum),'timeout':'10','action':status,
                'method':'POST','answerOnBridge':'true'})
        SubElement(dial,'Number').text=transfers.snapshot(row)['destination']
        SubElement(root,'Hangup')
        return tostring(root,encoding='unicode')


def seconds(value):
    if not isinstance(value,str) or not value.isdecimal() or len(value)>6 or int(value)>86400:
        raise HTTPException(422,'Invalid carrier duration')
    return int(value)


def status(identity,form):
    from .metering import record_cost
    with session_scope(write=True) as db:
        row=transfers.locked(db,identity)
        if row is None:raise HTTPException(404,'Transfer unavailable')
        if row.xml_served_at is None:raise HTTPException(409,'No staff leg was authorized')
        if row.provider=='twilio':
            outcome=form.get('DialCallStatus','')
            if outcome not in {'completed','busy','no-answer','failed','canceled'}:
                raise HTTPException(422,'Invalid dial outcome')
            duration=seconds(form.get('DialCallDuration','')) if outcome=='completed' else 0
            child_id=form.get('DialCallSid') or None
            if duration and not child_id:raise HTTPException(422,'Staff leg identity required')
        else:
            if form.get('DialAction')=='hangup':
                duration=seconds(form.get('DialBLegBillDuration') or form.get('DialBLegDuration',''))
                child_id=form.get('DialBLegUUID') or None
                outcome='completed' if duration else 'not-connected'
                if duration and not child_id:raise HTTPException(422,'Staff leg identity required')
            elif form.get('DialStatus') in {'busy','timeout','failed','no-answer','cancel'}:
                duration=0;child_id=form.get('DialBLegUUID') or None;outcome=form['DialStatus']
            else:
                return  # Await the signed hangup event for actual billed duration.
        if child_id is not None and len(child_id)>100:raise HTTPException(422,'Invalid staff leg identity')
        units={'carrier_ms':duration*1000}
        if row.child_bill_ms is not None and row.child_bill_ms!=units['carrier_ms']:
            raise HTTPException(409,'Conflicting carrier duration needs operator review')
        if row.child_leg_id and child_id and row.child_leg_id!=child_id:
            raise HTTPException(409,'Staff leg identity changed')
        row.child_leg_id=child_id or row.child_leg_id
        row.child_bill_ms=units['carrier_ms'];row.child_outcome=outcome
        row.state='completed' if duration else 'failed'
        record_cost(db,row.workspace_id,transfers.cost_key(row.id),row.provider,'transfer_carrier',units,
                    call_id=row.call_id,source='provider_duration')


@router.post('/v1/transfer-webhooks/{identity}/instructions')
async def instruction_route(identity:str,request:Request):
    await verified(request,identity)
    body=await durable_to_thread(instructions,identity)
    return Response(body,media_type='application/xml')


@router.post('/v1/transfer-webhooks/{identity}/status')
async def status_route(identity:str,request:Request):
    form=await verified(request,identity,child=True)
    await durable_to_thread(status,identity,form)
    return Response('<Response><Hangup /></Response>',media_type='application/xml')

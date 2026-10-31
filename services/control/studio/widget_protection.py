"""Independent installation/IP admission, conservative spend reservations and alerts."""
import hashlib
import hmac
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field
from sqlalchemy import select,update
from sqlalchemy.exc import IntegrityError

from .config import settings
from .db import now,session_scope,as_dict
from .models import Installation,WidgetProtection,WidgetBucket,WidgetIPBucket,WidgetAdmission,Membership,User
from .security import principal,db_dependency,audit
from .domain import owned
from .mail_outbox import enqueue_email

router=APIRouter(prefix='/v1/workspaces/{workspace_id}/installations')


def digest(value):
    return hmac.new(settings.app_secret.encode(),value.encode(),hashlib.sha256).hexdigest()


def defaults():
    return {'daily_sessions':settings.widget_daily_sessions,'daily_turns':settings.widget_daily_turns,
            'ip_daily_sessions':settings.widget_ip_daily_sessions,'ip_daily_turns':settings.widget_ip_daily_turns,
            'monthly_spend_cap_minor':settings.widget_monthly_spend_cap_minor,
            'voice_max_seconds':settings.widget_voice_max_seconds}


def policy(db,installation):
    row=db.scalar(select(WidgetProtection).where(WidgetProtection.workspace_id==installation.workspace_id,
                                               WidgetProtection.installation_id==installation.id))
    return {**defaults(),**(row.policy if row else {})}


def bucket(db,installation,period):
    row=db.scalar(select(WidgetBucket).where(WidgetBucket.workspace_id==installation.workspace_id,
        WidgetBucket.installation_id==installation.id,WidgetBucket.period==period))
    if row is None:
        row=WidgetBucket(workspace_id=installation.workspace_id,installation_id=installation.id,period=period,
                         sessions=0,turns=0,reserved_minor=0);db.add(row);db.flush()
    return row


def alert(db,installation,period,cap,threshold):
    recipients=list(db.scalars(select(User.email).join(Membership,Membership.user_id==User.id).where(
        Membership.workspace_id==installation.workspace_id,Membership.role=='owner')))
    for email in recipients:
        enqueue_email(db,email,'Widget spending limit '+str(threshold)+'%',
            f'{installation.name} has reached {threshold}% of its configured monthly spending allowance '
            f'or the next request would exceed it. Cap: INR {cap/100:.2f}. '
            'Usage reservations are DRAFT estimates until final provider tariffs are configured. '
            'Review widget protection in your workspace.',
            operation_key=f'widget-cap:{installation.id}:{period}:{cap}:{threshold}:'+digest(email)[:16])


def require_admission(db,installation,remote_ip,kind,operation_key):
    # Call only before creating messages/calls. A denial commits only the admission
    # alert/counter bookkeeping so the outbox survives the HTTP error rollback.
    installation=db.scalar(select(Installation).where(Installation.id==installation.id,
        Installation.workspace_id==installation.workspace_id).with_for_update())
    operation=digest('widget-admission:'+installation.id+':'+operation_key)
    if db.scalar(select(WidgetAdmission.id).where(WidgetAdmission.workspace_id==installation.workspace_id,
                                                WidgetAdmission.operation_key==operation)):return
    config=policy(db,installation);day=now().strftime('%Y-%m-%d');month=now().strftime('%Y-%m')
    daily=bucket(db,installation,day);monthly=bucket(db,installation,month)
    amount={'session':0,'turn':settings.widget_chat_reservation_minor,'voice':settings.widget_voice_reservation_minor,
            'transcribe':settings.widget_transcription_reservation_minor}[kind]
    cap=config['monthly_spend_cap_minor']
    if monthly.reserved_minor+amount>cap or cap==0:
        alert(db,installation,month,cap,100);db.commit()
        raise HTTPException(429,'This assistant has reached its spending limit. Please contact the business.')
    counter='sessions' if kind=='session' else 'turns'
    if getattr(daily,counter)>=config['daily_'+counter]:
        db.commit();raise HTTPException(429,'This assistant has reached its daily allowance. Please try tomorrow.')
    ip_hash=digest('widget-ip:'+remote_ip)
    iprow=db.scalar(select(WidgetIPBucket).where(WidgetIPBucket.ip_hash==ip_hash,
        WidgetIPBucket.period==day,WidgetIPBucket.kind==counter))
    if iprow is None:
        try:
            with db.begin_nested():
                iprow=WidgetIPBucket(ip_hash=ip_hash,period=day,kind=counter,amount=0);db.add(iprow);db.flush()
        except IntegrityError:
            iprow=db.scalar(select(WidgetIPBucket).where(WidgetIPBucket.ip_hash==ip_hash,
                WidgetIPBucket.period==day,WidgetIPBucket.kind==counter))
    admitted=db.execute(update(WidgetIPBucket).where(WidgetIPBucket.id==iprow.id,
        WidgetIPBucket.amount<min(config['ip_daily_'+counter],getattr(settings,'widget_ip_daily_'+counter))).values(amount=WidgetIPBucket.amount+1).returning(WidgetIPBucket.id)).scalar()
    if not admitted:
        db.commit();raise HTTPException(429,'This visitor has reached the daily allowance. Please try tomorrow.')
    setattr(daily,counter,getattr(daily,counter)+1);monthly.reserved_minor+=amount
    db.add(WidgetAdmission(workspace_id=installation.workspace_id,installation_id=installation.id,
                          operation_key=operation,kind=kind,reserved_minor=amount,rate_status='DRAFT'))
    if monthly.reserved_minor*5>=cap*4:alert(db,installation,month,cap,80)
    if monthly.reserved_minor>=cap:alert(db,installation,month,cap,100)
    db.flush()


class ProtectionWrite(BaseModel):
    daily_sessions:int=Field(ge=1,le=100000)
    daily_turns:int=Field(ge=1,le=100000)
    ip_daily_sessions:int=Field(ge=1,le=10000)
    ip_daily_turns:int=Field(ge=1,le=10000)
    monthly_spend_cap_minor:int=Field(ge=0,le=100_000_000)
    voice_max_seconds:int=Field(ge=10,le=300)


def record(db,installation):
    config=policy(db,installation)
    spend=db.scalar(select(WidgetBucket).where(WidgetBucket.workspace_id==installation.workspace_id,
        WidgetBucket.installation_id==installation.id,WidgetBucket.period==now().strftime('%Y-%m')))
    return {**config,'reserved_minor':spend.reserved_minor if spend else 0,'currency':'INR',
            'period':now().strftime('%Y-%m'),'rate_status':'DRAFT','bot_challenge_required':__import__('studio.bot_challenge',fromlist=['required']).required()}


@router.get('/{installation_id}/protection')
def get_protection(workspace_id:str,installation_id:str,actor=Depends(principal),db=Depends(db_dependency,scope='function')):
    actor.require('widget:read');return record(db,owned(db,Installation,workspace_id,installation_id))


@router.put('/{installation_id}/protection')
def update_protection(workspace_id:str,installation_id:str,body:ProtectionWrite,actor=Depends(principal),db=Depends(db_dependency,scope='function')):
    actor.require('widget:write')
    if not actor.user_id:raise HTTPException(403,'Use your verified browser account to change widget protection')
    installation=owned(db,Installation,workspace_id,installation_id)
    db.scalar(select(Installation).where(Installation.id==installation.id).with_for_update())
    row=db.scalar(select(WidgetProtection).where(WidgetProtection.workspace_id==workspace_id,WidgetProtection.installation_id==installation.id))
    if row is None:row=WidgetProtection(workspace_id=workspace_id,installation_id=installation.id);db.add(row)
    row.policy=body.model_dump();audit(db,actor,'installation.protection_changed',installation.id)
    return record(db,installation)

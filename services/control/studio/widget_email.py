"""Visitor email proof and optional consent; no OTP enters the model context."""
from datetime import timedelta
import hmac
import json
import secrets

from fastapi import APIRouter,HTTPException,Request
from pydantic import Field,field_validator,StrictBool
from sqlalchemy import select

from .db import now,session_scope,uid
from .schemas import Input,PublicSession
from .models import WidgetEmailChallenge,WidgetMarketingConsent,ConversationContext,Lead
from .widget_live import visitor_context
from .widget_protection import digest
from .security import limiter
from .secrets import encrypt,decrypt
from .mail_outbox import enqueue_email
from .domain import emit
from .config import settings

router=APIRouter(prefix='/v1/public/email')
CONSENT_VERSION='DRAFT-2026-10-25'
CONSENT_TEXT='Email me offers and updates from this business. I can unsubscribe at any time.'


class EmailRequest(Input):
    email:str=Field(max_length=254,min_length=3)

    @field_validator('email')
    @classmethod
    def valid_email(cls,value):return PublicSession.visitor_email_valid(value)


class EmailVerify(Input):
    challenge_id:str=Field(min_length=36,max_length=36)
    code:str=Field(pattern=r'^\d{6}$')
    marketing_opt_in:StrictBool=False


@router.post('/request',status_code=202)
def request_code(body:EmailRequest,request:Request):
    email=body.email
    ip=request.client.host if request.client else 'unknown'
    limiter.check('widget-otp-ip:'+digest(ip),10,3600)
    limiter.check('widget-otp-email:'+digest(email),5,3600)
    with session_scope(write=True) as db:
        claims,installation,conversation=visitor_context(request,db)
        from .models import Conversation
        db.scalar(select(Conversation).where(Conversation.id==conversation.id,Conversation.workspace_id==conversation.workspace_id).with_for_update())
        if conversation.state=='resolved':raise HTTPException(409,'This conversation is closed')
        limiter.check('widget-otp-install:'+installation.id,100,3600)
        limiter.check('widget-otp-conversation:'+conversation.id,1,60)
        if db.scalar(select(WidgetEmailChallenge.id).where(WidgetEmailChallenge.workspace_id==conversation.workspace_id,
            WidgetEmailChallenge.conversation_id==conversation.id,WidgetEmailChallenge.created_at>now()-timedelta(seconds=60))):
            raise HTTPException(429,'Wait one minute before requesting another code')
        old=list(db.scalars(select(WidgetEmailChallenge).where(WidgetEmailChallenge.workspace_id==conversation.workspace_id,
            WidgetEmailChallenge.conversation_id==conversation.id,WidgetEmailChallenge.consumed_at.is_(None)).with_for_update()))
        for row in old:row.consumed_at=now()
        identity=uid();code=f'{secrets.randbelow(1_000_000):06d}'
        row=WidgetEmailChallenge(id=identity,workspace_id=conversation.workspace_id,conversation_id=conversation.id,
            encrypted_email=encrypt(email),email_hash=digest('visitor-email:'+email),
            code_hash=digest('widget-otp:'+identity+':'+email+':'+code),expires_at=now()+timedelta(minutes=10),attempts=0)
        db.add(row)
        enqueue_email(db,email,'Verify your email',f'Your verification code is {code}. It expires in 10 minutes. '
            'Enter it only in the email verification form. Your AI assistant will never ask you to share it in chat.',
            operation_key='widget-otp:'+identity)
        return {'status':'accepted','challenge_id':identity,'expires_at':row.expires_at.isoformat(),
                'consent_text':CONSENT_TEXT,'consent_version':CONSENT_VERSION,
                'consent_enabled':settings.widget_marketing_consent_enabled}


@router.post('/verify')
def verify_code(body:EmailVerify,request:Request):
    limiter.check('widget-otp-verify-ip:'+digest(request.client.host if request.client else 'unknown'),30,3600)
    with session_scope(write=True) as db:
        claims,installation,conversation=visitor_context(request,db)
        # Serialize all email changes in a conversation as well as individual codes.
        from .models import Conversation
        db.scalar(select(Conversation).where(Conversation.id==conversation.id,Conversation.workspace_id==conversation.workspace_id).with_for_update())
        row=db.scalar(select(WidgetEmailChallenge).where(WidgetEmailChallenge.id==body.challenge_id,
            WidgetEmailChallenge.workspace_id==conversation.workspace_id,WidgetEmailChallenge.conversation_id==conversation.id).with_for_update())
        if not row:raise HTTPException(400,'Verification code is invalid or expired')
        if row.verified_at is not None:
            return {'email_verified':True,'marketing_opt_in':bool(db.scalar(select(WidgetMarketingConsent.id).where(WidgetMarketingConsent.challenge_id==row.id)))}
        if row.consumed_at is not None or row.expires_at<=now() or row.attempts>=5:
            raise HTTPException(400,'Verification code is invalid or expired')
        email=decrypt(row.encrypted_email);row.attempts+=1
        if not hmac.compare_digest(row.code_hash,digest('widget-otp:'+row.id+':'+email+':'+body.code)):
            if row.attempts>=5:row.consumed_at=now()
            db.commit();raise HTTPException(400,'Verification code is invalid or expired')
        if body.marketing_opt_in and not settings.widget_marketing_consent_enabled:
            raise HTTPException(409,'Promotional email consent is not available. Verify without opting in.')
        context=db.scalar(select(ConversationContext).where(ConversationContext.workspace_id==conversation.workspace_id,
            ConversationContext.conversation_id==conversation.id).with_for_update())
        visitor=(context.variables if context else {}).get('_widget_lead',{})
        lead=db.get(Lead,visitor.get('lead_id')) if visitor.get('lead_id') else None
        if not lead or lead.workspace_id!=conversation.workspace_id or lead.email.lower()!=email:
            lead=Lead(workspace_id=conversation.workspace_id,name=email.split('@')[0],email=email,stage='new',evidence='Verified widget email')
            db.add(lead);db.flush();emit(db,conversation.workspace_id,'lead.created',{'lead_id':lead.id})
        row.verified_at=row.consumed_at=now();row.lead_id=lead.id
        proof={'source':'widget_email_form','conversation_id':conversation.id,'installation_id':installation.id,
               'origin':claims['origin'],'email_verified':True,'verified_at':row.verified_at.isoformat(),
               'marketing_opt_in':body.marketing_opt_in}
        lead.evidence=json.dumps(proof)
        if context is None:context=ConversationContext(workspace_id=conversation.workspace_id,conversation_id=conversation.id,variables={});db.add(context)
        context.variables={**context.variables,'_widget_lead':{'email':email,'lead_id':lead.id,**proof}}
        if body.marketing_opt_in:
            db.add(WidgetMarketingConsent(workspace_id=conversation.workspace_id,challenge_id=row.id,lead_id=lead.id,
                email_hash=row.email_hash,origin=claims['origin'],ip_hash=digest(request.client.host if request.client else ''),
                text_version=CONSENT_VERSION,text_content=CONSENT_TEXT))
        emit(db,conversation.workspace_id,'visitor.email_verified',{'lead_id':lead.id})
        return {'email_verified':True,'marketing_opt_in':body.marketing_opt_in}


def lead_records(db,rows):
    if not rows:return rows
    ids=[row['id'] for row in rows]
    verified={(row.lead_id,row.email_hash) for row in db.scalars(select(WidgetEmailChallenge).where(
        WidgetEmailChallenge.lead_id.in_(ids),WidgetEmailChallenge.verified_at.is_not(None)))}
    consent={(row.lead_id,row.email_hash) for row in db.scalars(select(WidgetMarketingConsent).where(WidgetMarketingConsent.lead_id.in_(ids)))}
    return [{**row,'email_verified':(row['id'],digest('visitor-email:'+row.get('email','').lower())) in verified,
             'marketing_opt_in':(row['id'],digest('visitor-email:'+row.get('email','').lower())) in consent} for row in rows]

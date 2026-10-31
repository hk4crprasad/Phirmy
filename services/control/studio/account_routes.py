"""Account recovery, own-password changes and workspace invitations."""
import json
import secrets
import smtplib
import ssl
from email.message import EmailMessage
from datetime import timedelta
from pathlib import Path
from fastapi import APIRouter, Depends, Request, HTTPException
from pydantic import Field,field_validator
from sqlalchemy import select, delete, func
from .config import settings
from .db import now, as_dict
from .models import User, AccountToken, AuthSession, Membership, Invitation, Workspace
from .schemas import Input, Signup
from .security import db_dependency, active_user, principal, digest, password_hash, password_matches, check_origin, audit, limiter
from .domain import owned

router = APIRouter()
ROLES = {'admin','builder','operator','analyst','billing'}


class Email(Input):
    email: str = Field(max_length=254)
    @field_validator('email')
    @classmethod
    def valid_email(cls,value):
        return Signup.email_valid(value)


class Reset(Input):
    token: str = Field(min_length=20, max_length=256)
    password: str = Field(min_length=12, max_length=256)


class ChangePassword(Input):
    current_password: str = Field(max_length=256)
    new_password: str = Field(min_length=12, max_length=256)


class Invite(Email):
    role: str = 'operator'


class Token(Input):
    token: str = Field(min_length=20, max_length=256)


class Role(Input):
    role: str


def send_account_email(email, subject, url, *, db=None):
    return send_email(email, subject, subject+'\n\n'+url+'\n\nIf you did not request this, you can ignore this message.', db=db)


def send_email(email, subject, body, *, db=None, operation_key=None):
    from .mail_outbox import enqueue_email
    if db is not None:
        return enqueue_email(db, email, subject, body, operation_key=operation_key)
    from .db import session_scope
    with session_scope(write=True) as owned_db:
        return enqueue_email(owned_db, email, subject, body, operation_key=operation_key)


@router.post('/v1/auth/forgot-password', status_code=202)
def forgot(body: Email, request: Request, db=Depends(db_dependency,scope='function')):
    check_origin(request)
    limiter.check('recovery:'+(request.client.host if request.client else 'unknown'),5,3600)
    limiter.check('recovery-email:' + digest(body.email), 3, 3600)
    from .account_policy import uniform_auth_response
    from .mail_outbox import enqueue_email
    with uniform_auth_response():
        password_hash('recovery-timing-' + digest(body.email))
        user = db.scalar(select(User).where(User.email == body.email))
        token = secrets.token_urlsafe(32)
        if user:
            db.add(AccountToken(user_id=user.id,purpose='reset_password',token_hash=digest(token),expires_at=now()+timedelta(minutes=30)))
        enqueue_email(db, body.email, 'Reset your Phirmy password',
                      settings.app_origin + '/reset-password?token=' + token, noop=user is None)
        return {'message':'If an account exists, a password reset email has been prepared.'}


@router.post('/v1/auth/reset-password')
def reset(body: Reset, request: Request, db=Depends(db_dependency,scope='function')):
    check_origin(request)
    limiter.check('reset:'+(request.client.host if request.client else 'unknown'),10,3600)
    token=db.scalar(select(AccountToken).where(AccountToken.token_hash==digest(body.token),AccountToken.purpose=='reset_password',AccountToken.consumed_at.is_(None),AccountToken.expires_at>now()).with_for_update())
    if not token:raise HTTPException(400,'Reset link is invalid or expired')
    db.get(User,token.user_id).password_hash=password_hash(body.password)
    from .sessions import profile_for
    profile_for(db, token.user_id).email_verified_at = now()
    from .account_policy import complete_registration
    complete_registration(db, db.get(User, token.user_id))
    db.execute(delete(AuthSession).where(AuthSession.user_id==token.user_id))
    for other in db.scalars(select(AccountToken).where(AccountToken.user_id==token.user_id,AccountToken.purpose=='reset_password',AccountToken.consumed_at.is_(None))):other.consumed_at=now()
    return {'message':'Password updated. Sign in with your new password.'}


@router.post('/v1/auth/password')
def change_password(body: ChangePassword,request: Request,db=Depends(db_dependency,scope='function')):
    user=active_user(request,db)
    from .account_policy import require_verified
    require_verified(db, user)
    if not password_matches(body.current_password,user.password_hash):raise HTTPException(403,'Current password is incorrect')
    user.password_hash=password_hash(body.new_password)
    db.execute(delete(AuthSession).where(AuthSession.user_id==user.id))
    return {'message':'Password updated; all sessions were signed out.'}


@router.get('/v1/workspaces/{workspace_id}/invitations')
def invitations(workspace_id:str,actor=Depends(principal),db=Depends(db_dependency,scope='function')):
    actor.require('team:read')
    return {'items':[{k:v for k,v in as_dict(x).items() if k!='token_hash'} for x in db.scalars(select(Invitation).where(Invitation.workspace_id==workspace_id).order_by(Invitation.created_at.desc()))]}


@router.post('/v1/workspaces/{workspace_id}/invitations',status_code=201)
def invite(workspace_id:str,body:Invite,actor=Depends(principal),db=Depends(db_dependency,scope='function')):
    actor.require('team:write')
    if body.role not in ROLES:raise HTTPException(422,'Choose an available team role')
    pending=db.scalar(select(Invitation).where(Invitation.workspace_id==workspace_id,Invitation.email==body.email,Invitation.state=='pending'))
    if pending:pending.state='revoked'
    db.flush()
    from .admission import immediate
    immediate(db,workspace_id,'seat-invite:'+secrets.token_urlsafe(16),'seats',1)
    token=secrets.token_urlsafe(32)
    row=Invitation(workspace_id=workspace_id,email=body.email.lower(),role=body.role,token_hash=digest(token),expires_at=now()+timedelta(days=7))
    db.add(row);db.flush();audit(db,actor,'team.invited',row.id)
    # Return the link once to the inviter, who decides how to share it. No unsolicited email.
    return {'invitation':{k:v for k,v in as_dict(row).items() if k!='token_hash'},'accept_url':settings.app_origin+'/invite?token='+token}


@router.delete('/v1/workspaces/{workspace_id}/invitations/{invitation_id}')
def revoke_invite(workspace_id:str,invitation_id:str,actor=Depends(principal),db=Depends(db_dependency,scope='function')):
    actor.require('team:write');row=owned(db,Invitation,workspace_id,invitation_id)
    if row.state=='pending':row.state='revoked'
    audit(db,actor,'team.invitation_revoked',row.id)
    return {'state':row.state}


@router.post('/v1/auth/accept-invitation')
def accept(body:Token,request:Request,db=Depends(db_dependency,scope='function')):
    user=active_user(request,db)
    from .account_policy import require_verified
    require_verified(db, user)
    row=db.scalar(select(Invitation).where(Invitation.token_hash==digest(body.token),Invitation.state=='pending',Invitation.expires_at>now()).with_for_update())
    if not row:raise HTTPException(410,'Invitation is invalid, used or expired')
    if user.email.lower()!=row.email.lower():raise HTTPException(403,'Sign in with the invited email address')
    existing=db.scalar(select(Membership).where(Membership.workspace_id==row.workspace_id,Membership.user_id==user.id))
    row.state='accepted';db.flush()
    if not existing:
        from .admission import immediate
        immediate(db,row.workspace_id,'seat-accept:'+row.id,'seats',1)
        db.add(Membership(workspace_id=row.workspace_id,user_id=user.id,role=row.role))
    return {'workspace_id':row.workspace_id,'name':db.get(Workspace,row.workspace_id).name}


def guard_member(db,actor,workspace_id,user_id):
    row=db.scalar(select(Membership).where(Membership.workspace_id==workspace_id,Membership.user_id==user_id).with_for_update())
    if not row:raise HTTPException(404,'Member not found')
    if row.role=='owner':raise HTTPException(409,'The owner cannot be removed or demoted here')
    if actor.user_id==user_id:raise HTTPException(409,'Ask another administrator to change your access')
    return row


@router.patch('/v1/workspaces/{workspace_id}/members/{user_id}')
def member_role(workspace_id:str,user_id:str,body:Role,actor=Depends(principal),db=Depends(db_dependency,scope='function')):
    actor.require('team:write')
    if body.role not in ROLES:raise HTTPException(422,'Invalid team role')
    row=guard_member(db,actor,workspace_id,user_id);row.role=body.role;audit(db,actor,'team.role_updated',user_id)
    return {'user_id':user_id,'role':row.role}


@router.delete('/v1/workspaces/{workspace_id}/members/{user_id}')
def remove_member(workspace_id:str,user_id:str,actor=Depends(principal),db=Depends(db_dependency,scope='function')):
    actor.require('team:write');db.delete(guard_member(db,actor,workspace_id,user_id));audit(db,actor,'team.member_removed',user_id)
    return {'status':'removed'}

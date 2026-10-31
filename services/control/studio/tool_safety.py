"""Server-owned tool budgets, exact argument consent, replay fencing and read-only policies."""
import asyncio
from datetime import timedelta
import hashlib
import hmac
import json
import re
import string

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .config import settings
from .db import now, session_scope
from .models import Call, Conversation, ToolAttempt, ToolBudget, ToolConsent
from .prompt_safety import safe_arguments, sanitized
from .secrets import decrypt, encrypt

READ_ONLY = {'search_products','check_appointments','get_scheduling_link','check_calendar_availability',
             'website_search','website_open_page','website_scroll','check_scheduling_availability',
             'get_scheduling_booking'}
# These have their own scoped, server-owned later-turn read-back protocol.
CONFIRMED_PROTOCOLS = {'prepare_scheduling_booking','confirm_scheduling_booking'}
BUILTIN_WRITES = {'request_human_transfer','request_callback','create_support_ticket','capture_lead','book_appointment','sync_calendar_appointment'}


def _fingerprint(value):
    return hmac.new(settings.app_secret.encode(), json.dumps(value,sort_keys=True,default=str).encode(), hashlib.sha256).hexdigest()


def scope(context, db, lock=False):
    ws = context['workspace_id']
    kind, identity, model = ('call', context['call_id'], Call) if context.get('call_id') else ('conversation',context.get('conversation_id'),Conversation)
    query = select(model).where(model.id == identity, model.workspace_id == ws)
    row = db.scalar(query.with_for_update() if lock else query)
    if row is None or row.state in {'resolved','human','completed','failed','canceled','ending'}:
        raise HTTPException(403, 'This tool context is unavailable')
    return kind+':'+identity


def admit_attempt(context, name, identity):
    with session_scope(write=True) as db:
        key = scope(context, db, lock=True)
        budget = db.scalar(select(ToolBudget).where(ToolBudget.workspace_id == context['workspace_id'],ToolBudget.scope_key == key).with_for_update())
        if budget is None:
            try:
                with db.begin_nested():
                    db.add(ToolBudget(workspace_id=context['workspace_id'], scope_key=key));db.flush()
            except IntegrityError:
                pass
            budget = db.scalar(select(ToolBudget).where(ToolBudget.workspace_id == context['workspace_id'],ToolBudget.scope_key == key).with_for_update())
        operation = _fingerprint([context.get('operation_id'),identity])
        old = db.scalar(select(ToolAttempt.id).where(ToolAttempt.workspace_id == context['workspace_id'],
                       ToolAttempt.scope_key == key,ToolAttempt.operation_key == operation))
        if old:
            return
        if budget.calls_used >= settings.tool_calls_per_conversation:
            raise HTTPException(429, 'This conversation reached its tool-call limit')
        budget.calls_used += 1
        db.add(ToolAttempt(workspace_id=context['workspace_id'],scope_key=key,operation_key=operation,tool_name=name[:100]))


def requires_confirmation(config, name, context):
    attachment = next((tool for tool in config.get('tools',[]) if tool.get('name')==name and tool.get('tool_id')),None)
    if attachment:
        from .models import HTTPTool, HTTPToolVersion
        with session_scope() as db:
            row = db.scalar(select(HTTPToolVersion).where(HTTPToolVersion.workspace_id==context['workspace_id'],
                            HTTPToolVersion.tool_id==attachment['tool_id'],HTTPToolVersion.revision==int(attachment['schema_revision'])))
            tool = db.get(HTTPTool,attachment['tool_id'])
            if not tool or not tool.enabled or not row:
                raise HTTPException(403,'Tool is unavailable')
            return not (row.config.get('approval_policy')=='approved_read_only' and row.config.get('method')=='GET'
                        and not row.config.get('side_effecting',True) and not tool.config.get('side_effecting',True)
                        and tool.config.get('approval_policy')=='approved_read_only' and tool.config.get('method')=='GET')
    return name not in READ_ONLY and name not in CONFIRMED_PROTOCOLS


def public_proposal(row):
    payload = json.loads(decrypt(row.encrypted_payload))
    return {'id':row.id,'tool_name':row.tool_name,'summary':payload['summary'],
            'expires_at':row.expires_at.isoformat(),'state':row.state}


def propose(config, name, args, context):
    if not safe_arguments(args):
        raise HTTPException(422,'Do not request credentials or secret arguments')
    if len(json.dumps(args,ensure_ascii=False)) > 2000:
        raise HTTPException(422,'This action has too many details for visitor confirmation; ask an operator to review it')
    if name=='request_human_transfer':
        from .transfers import proposal
        args=proposal(args,context)
    original_user_text=context.get('user_text','')
    if name in {'capture_lead','request_callback'}:
        original_user_text+='\n'+'\n'.join(context.get('user_history',[])[-8:])
        if name=='request_callback':
            from .callbacks import validate
            args=validate(args,original_user_text)
        email=str(args.get('email','')).strip();phone=str(args.get('phone','')).strip()
        if not (email or phone) or (email and email.casefold() not in original_user_text.casefold()) or (phone and re.sub(r'\D','',phone) not in re.sub(r'\D','',original_user_text)):
            raise HTTPException(422,'Only contact details provided by the visitor may be recorded')
    with session_scope(write=True) as db:
        key = scope(context,db,lock=True)
        args_hash = _fingerprint([name,args])
        previous = db.scalar(select(ToolConsent).where(ToolConsent.workspace_id==context['workspace_id'],
            ToolConsent.scope_key==key,ToolConsent.tool_name==name,ToolConsent.args_hash==args_hash,
            ToolConsent.state.in_(['running','unknown','queued'])))
        if previous:
            raise HTTPException(409,'An earlier action needs reconciliation before another submission')
        pending = db.scalar(select(ToolConsent).where(ToolConsent.workspace_id==context['workspace_id'],
            ToolConsent.scope_key==key,ToolConsent.tool_name==name,ToolConsent.args_hash==args_hash,
            ToolConsent.state=='pending',ToolConsent.expires_at>now()).with_for_update())
        if pending:
            return public_proposal(pending)
        for old in db.scalars(select(ToolConsent).where(ToolConsent.workspace_id==context['workspace_id'],
                          ToolConsent.scope_key==key,ToolConsent.state=='pending').with_for_update()):
            old.state='canceled'
        summary = 'Confirm '+name.replace('_',' ')+': '+json.dumps(args,ensure_ascii=False,default=str)
        attachment = next((tool for tool in config.get('tools',[]) if tool.get('name')==name and tool.get('tool_id')),None)
        row = ToolConsent(workspace_id=context['workspace_id'],scope_key=key,tool_name=name,args_hash=args_hash,
            expires_at=now()+timedelta(seconds=settings.tool_confirmation_seconds),
            encrypted_payload=encrypt(json.dumps({'args':args,'summary':summary,
                'original_user_text':original_user_text,'attachment':attachment},default=str)))
        db.add(row);db.flush()
        return public_proposal(row)


def confirmation_text(proposal):
    return proposal['summary']+'. Reply "Confirm request" to proceed or "Cancel" to stop.'


def mark_presented(context, identity, text):
    with session_scope(write=True) as db:
        key=scope(context,db,lock=True)
        row=db.scalar(select(ToolConsent).where(ToolConsent.workspace_id==context['workspace_id'],
                      ToolConsent.scope_key==key,ToolConsent.id==identity,ToolConsent.state=='pending').with_for_update())
        if row and confirmation_text(public_proposal(row)) in text:
            row.presented_at=now()


def approved(name,args,context):
    identity=context.get('_approved_consent_id')
    if not identity:
        return False
    with session_scope() as db:
        key=scope(context,db)
        row=db.scalar(select(ToolConsent).where(ToolConsent.id==identity,ToolConsent.workspace_id==context['workspace_id'],
                      ToolConsent.scope_key==key,ToolConsent.state=='running',ToolConsent.tool_name==name))
        return bool(row and row.presented_at and row.expires_at>now() and row.args_hash==_fingerprint([name,args]))


def _normalized(text):
    return ' '.join(str(text).casefold().translate(str.maketrans('','',string.punctuation)).split())


def claim_confirmation(context, identity=None):
    text=_normalized(context.get('user_text',''))
    yes=text in {'yes','yes please','confirm request','i confirm','yes do that','yes do it'}
    cancel=text in {'no','no thanks','cancel','cancel request','never mind','do not do that'}
    if not identity and not yes and not cancel:
        return None
    with session_scope(write=True) as db:
        key=scope(context,db,lock=True)
        query=select(ToolConsent).where(ToolConsent.workspace_id==context['workspace_id'],ToolConsent.scope_key==key)
        query=query.where(ToolConsent.id==identity) if identity else query.where(ToolConsent.state=='pending')
        row=db.scalar(query.order_by(ToolConsent.created_at.desc()).limit(1).with_for_update())
        if not row:
            if identity:raise HTTPException(404,'Confirmation is unavailable')
            return None
        if not identity and not cancel and confirmation_text(public_proposal(row)) not in context.get('last_assistant_text',''):
            return None
        if row.state in {'succeeded','failed','unknown','queued'} and row.encrypted_result:
            return {'replay':json.loads(decrypt(row.encrypted_result))}
        if row.state!='pending' or row.expires_at<=now():
            raise HTTPException(409,'Confirmation expired or was already submitted')
        if cancel:
            row.state='canceled'
            return {'replay':{'text':'Canceled. No action was submitted.'}}
        if not yes or not row.presented_at:
            raise HTTPException(409,'Review the complete action before confirming it')
        payload=json.loads(decrypt(row.encrypted_payload))
        row.state='running'
        return {'id':row.id,'name':row.tool_name,**payload}


async def execute_confirmation(config, context, identity=None):
    claimed=await asyncio.to_thread(claim_confirmation,context,identity)
    if claimed is None:return None
    if 'replay' in claimed:return claimed['replay']
    approved_context={**context,'user_text':claimed['original_user_text'],
                      'operation_id':'confirmed:'+claimed['id'],'_approved_consent_id':claimed['id']}
    try:
        attachment=next((tool for tool in config.get('tools',[]) if tool.get('name')==claimed['name'] and tool.get('tool_id')),None)
        if attachment != claimed.get('attachment'):
            raise HTTPException(403,'Tool permission changed')
        if attachment:
            from .http_tools import invoke_attached
            result=await invoke_attached(config,claimed['name'],claimed['args'],approved_context)
        elif claimed['name']=='sync_calendar_appointment':
            from .connectors import agent_calendar_action
            result=await agent_calendar_action(claimed['name'],claimed['args'],approved_context)
        else:
            from .agent_tools import execute
            result=await asyncio.to_thread(execute,claimed['name'],claimed['args'],approved_context)
        from .prompt_safety import without_secrets
        from .llm import resolve
        profile=await asyncio.to_thread(resolve,config,context['workspace_id'])
        result=without_secrets(sanitized(result,private_endpoint=bool(attachment)),[profile.get('api_key')])
        state='failed' if result.get('error') or result.get('state')=='failed' else 'unknown' if result.get('state')=='unknown' else 'queued' if result.get('accepted') and not result.get('completion_confirmed') else 'succeeded'
        text = 'The action could not be completed.' if state=='failed' else 'The action outcome needs review; completion is not confirmed.' if state in {'unknown','queued'} else 'The confirmed action was recorded.'
        if result.get('ticket_id'):text="I've recorded your request as a support ticket. The team can review it in the inbox."
        if result.get('callback_requested'):
            from .callbacks import RECORDED
            text=RECORDED
        if result.get('transfer_id'):text='Transfer requested. A connection to the team is not confirmed yet.'
        response={'text':text,'result':result,**({'ticket_id':result['ticket_id']} if result.get('ticket_id') else {})}
    except Exception:
        # Preserve uncertainty; never automatically repeat a possibly committed external write.
        state='unknown';response={'text':'The action outcome needs review; do not resubmit until it is reconciled.'}
    def settle():
        with session_scope(write=True) as db:
            row=db.scalar(select(ToolConsent).where(ToolConsent.id==claimed['id'],ToolConsent.state=='running').with_for_update())
            if row:row.state,row.encrypted_result=state,encrypt(json.dumps(response,default=str))
    await asyncio.to_thread(settle)
    return response

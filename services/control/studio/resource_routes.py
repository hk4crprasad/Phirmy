"""Operational exports, recording lifecycle and auditable operator actions."""
import asyncio
import csv
import io
import json
from fastapi import APIRouter,Depends,HTTPException,Request
from fastapi.responses import Response
from sqlalchemy import select
from .config import settings
from .db import as_dict,now
from .models import Call,Turn,Recording,Lead,Ticket,Audit,Conversation,Membership,Agent,AgentVersion
from .security import principal,db_dependency,audit
from .domain import owned
from .storage import get_store

router=APIRouter(prefix='/v1/workspaces/{workspace_id}')


@router.get('/audit')
def audit_log(workspace_id:str,actor=Depends(principal),db=Depends(db_dependency,scope='function')):
    actor.require('team:read')
    return {'items':[as_dict(x) for x in db.scalars(select(Audit).where(Audit.workspace_id==workspace_id).order_by(Audit.created_at.desc()).limit(200))]}


@router.get('/recordings')
def recordings(workspace_id:str,actor=Depends(principal),db=Depends(db_dependency,scope='function')):
    actor.require('calls:read')
    return {'items':[{k:v for k,v in as_dict(x).items() if k!='object_key'} for x in db.scalars(select(Recording).where(Recording.workspace_id==workspace_id,Recording.deleted_at.is_(None),Recording.expires_at>now()))]}


@router.get('/recordings/{recording_id}/audio')
async def download(workspace_id:str,recording_id:str,actor=Depends(principal),db=Depends(db_dependency,scope='function')):
    actor.require('calls:read');row=owned(db,Recording,workspace_id,recording_id)
    if row.deleted_at or row.expires_at<=now():raise HTTPException(410,'Recording has expired or was deleted')
    body=await asyncio.to_thread(get_store().get,workspace_id,row.object_key)
    audit(db,actor,'recording.downloaded',row.id)
    return Response(body,media_type='audio/wav',headers={'Content-Disposition':'attachment; filename="call-'+row.call_id+'.wav"'})


@router.delete('/recordings/{recording_id}')
async def delete_recording(workspace_id:str,recording_id:str,actor=Depends(principal),db=Depends(db_dependency,scope='function')):
    actor.require('calls:write');row=owned(db,Recording,workspace_id,recording_id)
    if not row.deleted_at:
        await asyncio.to_thread(get_store().delete,workspace_id,row.object_key);row.deleted_at=now();audit(db,actor,'recording.deleted',row.id)
        from .metering import removed
        removed(db,workspace_id,row.object_key)
    return {'status':'deleted'}


@router.get('/calls/{call_id}/export')
def transcript(workspace_id:str,call_id:str,actor=Depends(principal),db=Depends(db_dependency,scope='function')):
    actor.require('calls:read');call=owned(db,Call,workspace_id,call_id)
    turns=[as_dict(x) for x in db.scalars(select(Turn).where(Turn.workspace_id==workspace_id,Turn.call_id==call.id).order_by(Turn.ordinal))]
    return Response(json.dumps({'call':as_dict(call),'turns':turns},indent=2),media_type='application/json',headers={'Content-Disposition':'attachment; filename="call-'+call.id+'.json"'})


def csv_cell(value):
    value=str(value if value is not None else '')
    return "'"+value if value.lstrip().startswith(('=','+','-','@','\t','\r')) else value


@router.get('/exports/{resource}')
def export(workspace_id:str,resource:str,actor=Depends(principal),db=Depends(db_dependency,scope='function')):
    resources={'leads':(Lead,'leads:read',['name','email','phone','stage','evidence','created_at']), 'tickets':(Ticket,'inbox:read',['id','subject','description','priority','state','created_at']), 'calls':(Call,'calls:read',['id','agent_name','direction','transport','mode','state','connected_ms','created_at'])}
    if resource not in resources:raise HTTPException(404,'Export not found')
    model,scope,fields=resources[resource];actor.require(scope)
    stream=io.StringIO();writer=csv.writer(stream);writer.writerow(fields)
    for row in db.scalars(select(model).where(model.workspace_id==workspace_id).order_by(model.created_at).limit(10000)):
        data=as_dict(row);writer.writerow([csv_cell(data[f]) for f in fields])
    audit(db,actor,'export.downloaded',resource)
    return Response('\ufeff'+stream.getvalue(),media_type='text/csv; charset=utf-8',headers={'Content-Disposition':'attachment; filename="'+resource+'.csv"'})


@router.patch('/conversations/{conversation_id}/assignment')
def assign(workspace_id:str,conversation_id:str,body:dict,actor=Depends(principal),db=Depends(db_dependency,scope='function')):
    actor.require('inbox:write');row=owned(db,Conversation,workspace_id,conversation_id)
    user_id=body.get('user_id')
    if user_id and not db.scalar(select(Membership).where(Membership.workspace_id==workspace_id,Membership.user_id==user_id)):raise HTTPException(422,'Assignee must belong to this workspace')
    row.assigned_user_id=user_id
    if 'state' in body:
        if body['state'] not in {'open','resolved'}:raise HTTPException(422,'Invalid conversation state')
        row.state=body['state']
    audit(db,actor,'conversation.assigned',row.id)
    return as_dict(row)


@router.post('/agents/{agent_id}/archive')
def archive_agent(workspace_id:str,agent_id:str,actor=Depends(principal),db=Depends(db_dependency,scope='function')):
    actor.require('agents:write');row=owned(db,Agent,workspace_id,agent_id);row.archived=True;audit(db,actor,'agent.archived',row.id)
    from .models import Installation
    for installation in db.scalars(select(Installation).where(Installation.workspace_id == workspace_id, Installation.agent_id == row.id)):
        installation.enabled = False
    return {'status':'archived'}

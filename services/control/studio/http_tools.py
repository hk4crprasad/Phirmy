"""Declarative HTTP tools. cURL is parsed as data and is never executed by a shell."""
import asyncio
import hashlib
import json
import re
import shlex
import time
from urllib.parse import urlparse,quote
import httpx
from fastapi import APIRouter,Depends,HTTPException,Request
from pydantic import Field
from sqlalchemy import select
from jsonschema import Draft202012Validator
from .schemas import Input
from .db import session_scope,as_dict,now
from .models import HTTPTool,HTTPToolVersion,ToolExecution,Agent,Job,Workspace
from .security import principal,db_dependency,audit
from .domain import owned,enqueue
from .secrets import encrypt,decrypt
from .knowledge import validate_public_url
from .network import PublicTransport
from .async_work import durable_await, durable_to_thread

router=APIRouter(prefix='/v1/workspaces/{workspace_id}')
PLACEHOLDER=re.compile(r'{{\s*([A-Za-z][A-Za-z0-9_.]*)\s*}}')
FORBIDDEN_HEADERS={'host','content-length','transfer-encoding','connection','proxy-authorization','proxy-connection','upgrade'}


class ToolWrite(Input):
    name:str=Field(pattern=r'^[a-z][a-z0-9_]{0,63}$')
    description:str=Field(min_length=3,max_length=3000)
    method:str='POST'
    url:str=Field(min_length=8,max_length=2000)
    arguments:dict=Field(default_factory=lambda:{'type':'object','properties':{},'additionalProperties':False})
    body_template:dict|list|None=None
    headers:dict[str,str]|None=None
    timeout_seconds:int=Field(default=15,ge=1,le=120)
    execution_mode:str='wait_for_result'
    error_handling:str='hide'
    side_effecting:bool=True
    approval_policy:str='always_confirm'
    public_response_fields:list[str]=Field(default_factory=list,max_length=30)
    mock_response:dict|None=None


class Import(Input):
    text:str=Field(min_length=4,max_length=30000)


class Invoke(Input):
    arguments:dict=Field(default_factory=dict)
    mock:bool=False


class Access(Input):
    agent_ids:list[str]=Field(max_length=100)


def parse_curl(command):
    try:tokens=shlex.split(command.replace('\\\n',' '))
    except ValueError:raise HTTPException(422,'The cURL command has an unmatched quote')
    if not tokens or tokens.pop(0)!='curl':raise HTTPException(422,'Paste a cURL HTTP request')
    method='GET';url='';headers={};body=None;i=0
    while i<len(tokens):
        token=tokens[i];i+=1
        if token in {'-X','--request','--url','-H','--header','-d','--data','--data-raw','--data-binary','-u','--user'}:
            if i>=len(tokens):raise HTTPException(422,'Missing cURL option value')
            value=tokens[i];i+=1
            if token in {'-X','--request'}:method=value.upper()
            elif token=='--url':url=value
            elif token in {'-H','--header'}:
                if ':' not in value:raise HTTPException(422,'Header must contain a colon')
                key,val=value.split(':',1);headers[key.strip()]=val.strip()
            elif token in {'-u','--user'}:
                import base64
                headers['Authorization']='Basic '+base64.b64encode(value.encode()).decode()
            else:
                if value.startswith('@'):raise HTTPException(422,'File uploads and local-file reads are not supported by import')
                try:body=json.loads(value)
                except ValueError:raise HTTPException(422,'Use a JSON request body for this tool')
                if method=='GET':method='POST'
        elif token in {'-s','--silent','-S','--show-error','--compressed','--location','-L'}:continue
        elif token.startswith(('https://','http://')) and not url:url=token
        else:raise HTTPException(422,'Unsupported cURL option; only method, URL, headers and JSON body are imported')
    if not url:raise HTTPException(422,'The request needs an endpoint URL')
    props={name:{'type':'string','description':'Value for '+name} for name in set(PLACEHOLDER.findall(json.dumps(body)+url)) if not name.startswith('system.') and '.' not in name}
    return {'method':method,'url':url,'headers':headers,'body_template':body,'arguments':{'type':'object','properties':props,'required':list(props),'additionalProperties':False}}


async def validate(body):
    if body.approval_policy not in {'always_confirm','approved_read_only'}:
        raise HTTPException(422,'Choose a supported confirmation policy')
    if body.approval_policy=='approved_read_only' and (body.method.upper()!='GET' or body.side_effecting):
        raise HTTPException(422,'Only an explicitly approved GET lookup may skip confirmation')
    from .prompt_safety import PRIVATE_FIELDS
    if any(not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.]{0,79}',field) or
           any(part.lower() in PRIVATE_FIELDS | {'headers','payload','private_key','encryption_key'} or part.lower().startswith('encrypted_') for part in field.split('.')) for field in body.public_response_fields):
        raise HTTPException(422,'Choose public response paths without credential fields')
    if body.method.upper() not in {'GET','POST','PUT','PATCH','DELETE'}:raise HTTPException(422,'Unsupported HTTP method')
    if body.execution_mode not in {'wait_for_result','background','fire_and_forget'}:raise HTTPException(422,'Invalid execution mode')
    if body.error_handling not in {'hide','passthrough'}:raise HTTPException(422,'Invalid error handling mode')
    if '{{' in urlparse(body.url).netloc:raise HTTPException(422,'The destination host must be fixed, not model-generated')
    await validate_public_url(PLACEHOLDER.sub('sample',body.url))
    try:Draft202012Validator.check_schema(body.arguments)
    except Exception:raise HTTPException(422,'Arguments must be a valid JSON Schema')
    if body.arguments.get('type')!='object' or len(body.arguments.get('properties',{}))>30:raise HTTPException(422,'Use an object schema with at most 30 arguments')
    def check_refs(value):
        if isinstance(value,dict):
            for k,v in value.items():
                if k in {'$ref','$dynamicRef'} and (not isinstance(v,str) or not v.startswith('#')):raise HTTPException(422,'External JSON Schema references are not allowed')
                check_refs(v)
        elif isinstance(value,list):
            for item in value:check_refs(item)
    check_refs(body.arguments)
    if len(json.dumps(body.model_dump()))>50000:raise HTTPException(413,'Tool definition is too large')
    from .agent_tools import DEFINITIONS
    if body.name in DEFINITIONS:raise HTTPException(422,'That name is reserved for a built-in tool')
    if body.name in {'website_search','website_open_page','website_scroll'}:
        raise HTTPException(422,'That name is reserved for a website tool')
    body.method=body.method.upper()
    for key,value in (body.headers or {}).items():
        if not re.fullmatch(r'[!#$%&\x27*+.^_`|~0-9A-Za-z-]+',key) or key.lower() in FORBIDDEN_HEADERS or '\n' in value or '\r' in value:raise HTTPException(422,'Invalid or reserved request header')


def public(row):
    config=dict(row.config)
    return {'id':row.id,'name':row.name,'description':row.description,'revision':row.revision,'enabled':row.enabled,**config,'headers':{name:None for name in json.loads(decrypt(row.encrypted_headers))},'has_secret':bool(json.loads(decrypt(row.encrypted_headers)))}


def snapshot(db,row):
    db.add(HTTPToolVersion(workspace_id=row.workspace_id,tool_id=row.id,revision=row.revision,name=row.name,description=row.description,config=row.config,encrypted_headers=row.encrypted_headers))


@router.get('/tools')
def tools(workspace_id:str,actor=Depends(principal),db=Depends(db_dependency,scope='function')):
    actor.require('agents:read')
    return {'items':[public(x) for x in db.scalars(select(HTTPTool).where(HTTPTool.workspace_id==workspace_id).order_by(HTTPTool.created_at.desc()))]}


@router.post('/tools/import-curl')
def import_curl(workspace_id:str,body:Import,actor=Depends(principal)):
    actor.require('agents:write');return parse_curl(body.text)


@router.post('/tools',status_code=201)
async def create(workspace_id:str,body:ToolWrite,actor=Depends(principal),db=Depends(db_dependency,scope='function')):
    actor.require('agents:write');await validate(body)
    if db.scalar(select(HTTPTool).where(HTTPTool.workspace_id==workspace_id,HTTPTool.name==body.name)):raise HTTPException(409,'Tool name is already in use')
    config=body.model_dump(exclude={'name','description','headers'})
    row=HTTPTool(workspace_id=workspace_id,name=body.name,description=body.description,config=config,encrypted_headers=encrypt(json.dumps(body.headers or {})))
    db.add(row);db.flush();snapshot(db,row);audit(db,actor,'tool.created',row.id)
    return public(row)


@router.put('/tools/{tool_id}')
async def update(workspace_id:str,tool_id:str,body:ToolWrite,actor=Depends(principal),db=Depends(db_dependency,scope='function')):
    actor.require('agents:write');await validate(body);row=owned(db,HTTPTool,workspace_id,tool_id)
    if row.name!=body.name:raise HTTPException(422,'Tool names are stable; create a new tool to change its name')
    row.description=body.description;row.config=body.model_dump(exclude={'name','description','headers'});row.revision+=1
    if body.headers is not None:row.encrypted_headers=encrypt(json.dumps(body.headers))
    snapshot(db,row);audit(db,actor,'tool.updated',row.id)
    return public(row)


@router.delete('/tools/{tool_id}')
def disable(workspace_id:str,tool_id:str,actor=Depends(principal),db=Depends(db_dependency,scope='function')):
    actor.require('agents:write');row=owned(db,HTTPTool,workspace_id,tool_id);row.enabled=False;audit(db,actor,'tool.disabled',row.id)
    return {'status':'disabled'}


@router.put('/tools/{tool_id}/access')
def access(workspace_id:str,tool_id:str,body:Access,actor=Depends(principal),db=Depends(db_dependency,scope='function')):
    actor.require('agents:write');tool=owned(db,HTTPTool,workspace_id,tool_id)
    for agent_id in body.agent_ids:owned(db,Agent,workspace_id,agent_id)
    for agent in db.scalars(select(Agent).where(Agent.workspace_id==workspace_id)):
        config=json.loads(json.dumps(agent.draft_config));attached=[x for x in config.get('tools',[]) if x.get('tool_id')!=tool.id]
        if agent.id in body.agent_ids:attached.append({'name':tool.name,'schema_revision':str(tool.revision),'timeout_ms':tool.config['timeout_seconds']*1000,'side_effecting':tool.config['side_effecting'],'tool_id':tool.id})
        if attached!=config.get('tools',[]):config['tools']=attached;agent.draft_config=config;agent.draft_revision+=1
    audit(db,actor,'tool.access_updated',tool.id)
    return {'agent_ids':body.agent_ids,'publication_required':True}


def attached_definitions(config,workspace_id):
    result=[]
    with session_scope() as db:
        for attachment in config.get('tools',[]):
            if not attachment.get('tool_id'):continue
            tool=owned(db,HTTPTool,workspace_id,attachment['tool_id'])
            if not tool.enabled:continue
            revision=db.scalar(select(HTTPToolVersion).where(HTTPToolVersion.workspace_id==workspace_id,HTTPToolVersion.tool_id==tool.id,HTTPToolVersion.revision==int(attachment['schema_revision'])))
            if revision:result.append({'type':'function','name':revision.name,'description':revision.description,'parameters':revision.config['arguments']})
    return result


def background_results(context):
    with session_scope() as db:
        query=select(ToolExecution).where(ToolExecution.workspace_id==context['workspace_id'],ToolExecution.state.in_(['succeeded','failed','unknown']))
        if context.get('call_id'):query=query.where(ToolExecution.call_id==context['call_id'])
        elif context.get('conversation_id'):query=query.where(ToolExecution.payload['conversation_id'].as_string()==context['conversation_id'])
        else:return []
        return [assistant_result(db,context['workspace_id'],x.tool_id,int(x.payload['revision']),as_dict(x))
                for x in db.scalars(query.order_by(ToolExecution.created_at.desc()).limit(20))
                if x.payload.get('execution_mode')=='background'][:8]


def assistant_result(db, workspace_id, tool_id, revision, result):
    version=db.scalar(select(HTTPToolVersion).where(HTTPToolVersion.workspace_id==workspace_id,
        HTTPToolVersion.tool_id==tool_id,HTTPToolVersion.revision==revision))
    current=db.get(HTTPTool,tool_id)
    fields=(set(version.config.get('public_response_fields',[])) & set(current.config.get('public_response_fields',[]))) if version and current and current.enabled else set()
    source=result.get('result',{}).get('response',{})
    exported={}
    for field in sorted(fields):
        value=source
        for component in field.split('.'):
            if not isinstance(value,dict) or component not in value:
                value=None;break
            value=value[component]
        if value is not None:exported[field]=value
    from .prompt_safety import sanitized
    return {'id':result['id'],'execution_id':result['id'],'state':result['state'],
            'accepted':result.get('accepted',False),'completion_confirmed':result['state']=='succeeded',
            'result':{'response':sanitized(exported,private_endpoint=True)}}


def lookup(values,path):
    value=values
    for part in path.split('.'):
        if not isinstance(value,dict) or part not in value:raise ValueError('Missing template variable: '+path)
        value=value[part]
    return value


def render(value,values,url=False):
    if isinstance(value,dict):return {k:render(v,values) for k,v in value.items()}
    if isinstance(value,list):return [render(v,values) for v in value]
    if not isinstance(value,str):return value
    full=PLACEHOLDER.fullmatch(value)
    if full and not url:return lookup(values,full[1])
    return PLACEHOLDER.sub(lambda m:quote(str(lookup(values,m[1])),safe='') if url else str(lookup(values,m[1])),value)


def redact(value,secrets):
    if isinstance(value,dict):return {str(redact(k,secrets)):redact(v,secrets) for k,v in value.items()}
    if isinstance(value,list):return [redact(v,secrets) for v in value]
    if isinstance(value,str):
        for secret in sorted(set(secrets),key=len,reverse=True):
            if secret and (len(secret)>6 or value==secret):value=value.replace(secret,'[redacted]')
    return value


def _start_execution(execution_id):
    with session_scope(write=True) as db:
        workspace_id=db.scalar(select(ToolExecution.workspace_id).where(ToolExecution.id==execution_id))
        if workspace_id is None:return {'public':None}
        db.scalar(select(Workspace).where(Workspace.id==workspace_id).with_for_update())
        row=db.scalar(select(ToolExecution).where(ToolExecution.id==execution_id).with_for_update())
        if row.state!='queued':return {'public':as_dict(row)}
        tool=owned(db,HTTPTool,row.workspace_id,row.tool_id)
        if not tool.enabled:row.state='failed';row.result={'error':'Tool disabled'};return {'public':as_dict(row)}
        revision=db.scalar(select(HTTPToolVersion).where(HTTPToolVersion.workspace_id==row.workspace_id,HTTPToolVersion.tool_id==tool.id,HTTPToolVersion.revision==row.payload['revision']))
        cfg=revision.config;headers=json.loads(decrypt(revision.encrypted_headers));values=row.payload['values'];ws=row.workspace_id
        row.state='running'
    return {'cfg':cfg,'headers':headers,'values':values,'workspace_id':ws}


def _finish_execution(execution_id,workspace_id,state,result,started):
    with session_scope(write=True) as db:
        db.scalar(select(Workspace).where(Workspace.id==workspace_id).with_for_update())
        row=owned(db,ToolExecution,workspace_id,execution_id)
        if row.state=='running':
            row.state=state;row.result=result;row.elapsed_ms=round((time.monotonic()-started)*1000)
        return as_dict(row)


async def perform(execution_id):
    started=time.monotonic()
    prepared=None
    request_started=False
    outcome_ready=False
    state='failed';result={'error':'Request canceled before external submission'}
    async def initialize():
        nonlocal prepared
        prepared=await asyncio.to_thread(_start_execution,execution_id)
    try:
        await durable_await(initialize())
        if 'public' in prepared:return prepared['public']
        cfg,headers,values=prepared['cfg'],prepared['headers'],prepared['values']
        url=render(cfg['url'],values,url=True);await validate_public_url(url)
        headers={name:str(render(value,values)) for name,value in headers.items()}
        headers['X-Voice-Studio-Execution']=execution_id
        headers.setdefault('Idempotency-Key',execution_id)
        secrets=list(headers.values())+[v.removeprefix('Bearer ') for v in headers.values() if v.startswith('Bearer ')]
        body=render(cfg.get('body_template'),values)
        async with httpx.AsyncClient(timeout=cfg['timeout_seconds'],follow_redirects=False,trust_env=False,transport=PublicTransport()) as client:
            request_started=True
            async with client.stream(cfg['method'],url,headers=headers,json=body if cfg['method']!='GET' else None) as response:
                content=bytearray();truncated=False
                async for part in response.aiter_bytes():
                    if len(content)+len(part)>65536:content.extend(part[:65536-len(content)]);truncated=True;break
                    content.extend(part)
                try:data=json.loads(content)
                except ValueError:data=content.decode(errors='replace')
                result={'http_status':response.status_code,'response':data,'response_truncated':truncated}
                state='succeeded' if 200<=response.status_code<300 else 'failed'
                if state=='failed' and cfg['error_handling']=='hide':result={'http_status':response.status_code,'error':'The endpoint rejected this action'}
                result=redact(result,secrets)
                outcome_ready=True
    except asyncio.CancelledError:
        if not outcome_ready:
            state='unknown' if request_started else 'failed'
            result={'error':'Endpoint outcome is unknown; reconcile before repeating a side effect' if request_started else 'Request canceled before external submission'}
        raise
    except (httpx.TimeoutException,httpx.TransportError):
        if not outcome_ready:
            state='unknown' if request_started else 'failed'
            result={'error':'Endpoint outcome is unknown; reconcile before repeating a side effect' if request_started else 'Endpoint connection could not be prepared'}
    except Exception:
        if prepared is None:raise
        if not outcome_ready:
            state='unknown' if request_started else 'failed'
            result={'error':'Endpoint outcome needs review' if request_started else 'Invalid arguments, unsafe URL or request configuration'}
    finally:
        if prepared is not None and 'public' not in prepared:
            completed=await durable_to_thread(_finish_execution,execution_id,prepared['workspace_id'],state,result,started)
    return completed


def _queue_execution(workspace_id,tool_id,revision,args,context,operation_key,mock=False):
    if len(json.dumps(args))>30000:raise HTTPException(413,'Tool arguments are too large')
    with session_scope(write=True) as db:
        db.scalar(select(Workspace).where(Workspace.id==workspace_id).with_for_update())
        tool=owned(db,HTTPTool,workspace_id,tool_id)
        if not tool.enabled:raise HTTPException(409,'Tool disabled')
        version=db.scalar(select(HTTPToolVersion).where(HTTPToolVersion.workspace_id==workspace_id,HTTPToolVersion.tool_id==tool_id,HTTPToolVersion.revision==revision))
        if not version:raise HTTPException(404,'Tool revision not found')
        errors=list(Draft202012Validator(version.config['arguments']).iter_errors(args))
        if errors:raise HTTPException(422,'Arguments do not match the declared schema: '+errors[0].message[:300])
        if mock:
            return {'public':{'state':'mock','result':version.config.get('mock_response') or {},'external_request':False}}
        hashed=hashlib.sha256(json.dumps({'tool_id':tool_id,'revision':revision,'arguments':args},sort_keys=True).encode()).hexdigest()
        existing=db.scalar(select(ToolExecution).where(ToolExecution.workspace_id==workspace_id,ToolExecution.operation_key==operation_key))
        if existing:
            if existing.request_hash!=hashed:raise HTTPException(409,'Execution identity conflicts with different arguments')
            return {'public':as_dict(existing)}
        values={**context.get('variables',{}),**args,'system':{'call_id':context.get('call_id'),'caller_number':context.get('caller_number'),'workspace_id':workspace_id}}
        row=ToolExecution(workspace_id=workspace_id,tool_id=tool_id,operation_key=operation_key,request_hash=hashed,call_id=context.get('call_id'),payload={'revision':revision,'values':values,'conversation_id':context.get('conversation_id'),'execution_mode':version.config['execution_mode']})
        db.add(row);db.flush();execution_id=row.id
        mode=version.config['execution_mode']
        if mode!='wait_for_result':enqueue(db,workspace_id,'http_tool',{'execution_id':row.id})
        queued=as_dict(row)
    return {'execution_id':execution_id,'mode':mode,'queued':queued}


async def invoke(workspace_id,tool_id,revision,args,context,operation_key,mock=False):
    queued=None
    async def initialize():
        nonlocal queued
        queued=await asyncio.to_thread(_queue_execution,workspace_id,tool_id,revision,args,context,operation_key,mock)
    try:
        await durable_await(initialize())
    except asyncio.CancelledError:
        if queued and 'public' not in queued and queued['mode']=='wait_for_result':
            def abandon():
                with session_scope(write=True) as db:
                    db.scalar(select(Workspace).where(Workspace.id==workspace_id).with_for_update())
                    row=owned(db,ToolExecution,workspace_id,queued['execution_id'])
                    if row.state=='queued':
                        row.state='failed';row.result={'error':'Request canceled before external submission'}
            await durable_to_thread(abandon)
        raise
    if 'public' in queued:return queued['public']
    if queued['mode']=='wait_for_result':return await perform(queued['execution_id'])
    return {**queued['queued'],'accepted':True,'completion_confirmed':False}


async def invoke_attached(config,name,args,context):
    from .tool_safety import requires_confirmation, approved, admit_attempt, propose, confirmation_text
    if await asyncio.to_thread(requires_confirmation,config,name,context) and not await asyncio.to_thread(approved,name,args,context):
        await asyncio.to_thread(admit_attempt,context,name,'attached:'+json.dumps(args,sort_keys=True))
        proposal=await asyncio.to_thread(propose,config,name,args,context)
        return {'confirmation_required':True,'confirmation':proposal,'message':confirmation_text(proposal)}
    attachment=next(x for x in config.get('tools',[]) if x.get('name')==name and x.get('tool_id'))
    key='agent-tool:'+hashlib.sha256((context['operation_id']+':'+name+':'+json.dumps(args,sort_keys=True)).encode()).hexdigest()
    result=await invoke(context['workspace_id'],attachment['tool_id'],int(attachment['schema_revision']),args,context,key)
    def export():
        with session_scope() as db:
            return assistant_result(db,context['workspace_id'],attachment['tool_id'],int(attachment['schema_revision']),result)
    return await asyncio.to_thread(export)


@router.post('/tools/{tool_id}/test')
async def test(workspace_id:str,tool_id:str,body:Invoke,request:Request,actor=Depends(principal),db=Depends(db_dependency,scope='function')):
    actor.require('agents:write');tool=owned(db,HTTPTool,workspace_id,tool_id);revision=tool.revision;db.commit()
    key=request.headers.get('Idempotency-Key','')
    if not key or len(key)>180:raise HTTPException(422,'Idempotency-Key required for a real tool test')
    return await invoke(workspace_id,tool_id,revision,body.arguments,{},'test:'+key,body.mock)


@router.get('/tool-executions')
def executions(workspace_id:str,actor=Depends(principal),db=Depends(db_dependency,scope='function')):
    actor.require('agents:read')
    return {'items':[{k:v for k,v in as_dict(x).items() if k!='payload'} for x in db.scalars(select(ToolExecution).where(ToolExecution.workspace_id==workspace_id).order_by(ToolExecution.created_at.desc()).limit(200))]}

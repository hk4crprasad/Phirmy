"""Documented model profiles with write-only keys and a streaming connection test."""
import asyncio
import hashlib
from urllib.parse import urlparse
from datetime import datetime,timezone
from fastapi import APIRouter,Depends,HTTPException
from pydantic import Field
from sqlalchemy import select
from .db import as_dict,now
from .models import LLMProfile
from .schemas import Input
from .security import principal,db_dependency,audit
from .domain import owned
from .knowledge import validate_public_url,safe_fetch,extract_page
from .secrets import encrypt
from .llm import Turn,environment_profile

router=APIRouter(prefix='/v1/workspaces/{workspace_id}')


class ModelWrite(Input):
    name:str=Field(min_length=1,max_length=160)
    model:str=Field(min_length=1,max_length=200)
    base_url:str=Field(max_length=2000)
    api_key:str=Field(min_length=1,max_length=4000)
    api_style:str='chat_completions'
    token_parameter:str='max_completion_tokens'
    reasoning_effort:str|None=None
    temperature:float|None=Field(default=None,ge=0,le=2)
    documentation_url:str=Field(max_length=2000)


async def prepare(body):
    if body.api_style not in {'chat_completions','responses'}:raise HTTPException(422,'Choose Responses or Chat Completions')
    if body.token_parameter not in {'max_tokens','max_completion_tokens','max_output_tokens','none'}:raise HTTPException(422,'Choose a supported token-cap parameter or omit it')
    if body.api_style=='responses' and body.token_parameter not in {'max_output_tokens','none'}:raise HTTPException(422,'Responses uses max_output_tokens')
    if body.api_style=='chat_completions' and body.token_parameter=='max_output_tokens':raise HTTPException(422,'Chat Completions does not use max_output_tokens')
    if urlparse(body.base_url).scheme!='https':raise HTTPException(422,'Custom model endpoints must use HTTPS')
    await validate_public_url(body.base_url)
    try:
        target,raw,_=await asyncio.wait_for(safe_fetch(body.documentation_url,max_bytes=2000000),timeout=15)
        doc=extract_page(raw,target)['text']
    except Exception:raise HTTPException(422,'Could not read the model documentation. Supply a public provider documentation page first.')
    if body.token_parameter!='none' and body.token_parameter not in doc:raise HTTPException(422,'The selected token parameter does not appear in the supplied documentation. Review its exact API/model support.')
    if body.temperature is not None and 'temperature' not in doc.lower():raise HTTPException(422,'Temperature support is not documented here. Leave it unset.')
    research={'source_url':target,'checked_at':now().isoformat(),'content_hash':hashlib.sha256(raw).hexdigest(),'excerpt':doc[:2000],'status':'documentation-read; connection-test-required'}
    return {'model':body.model,'base_url':body.base_url.rstrip('/'),'api_key':body.api_key,'api_style':body.api_style,'token_parameter':body.token_parameter,'options':{'reasoning_effort':body.reasoning_effort,'temperature':body.temperature},'research':research,'public_only':True}


async def probe(profile):
    turn=Turn(profile,'Connection test. Reply briefly with OK. Do not call any tools.',[{'role':'user','content':'Are you ready?'}],tools=[{'type':'function','name':'connection_probe','description':'An inert connection-test schema. Do not call it.','parameters':{'type':'object','properties':{},'additionalProperties':False}}],limit=1200)
    output=''
    try:
        async for delta in turn.stream():output+=delta
    except Exception:raise HTTPException(422,'The model did not complete the streaming/tool-schema test. Check API style, token cap, reasoning settings and provider access.')
    if not output.strip():raise HTTPException(422,'The endpoint returned no visible text. Check model reasoning/output budget and streaming support.')
    return {'status':'passed','first_token_ms':turn.first_token_ms,'text':output[:300],'tools_schema_accepted':True}


def public(row):return {k:v for k,v in as_dict(row).items() if k!='encrypted_key'}


@router.get('/models')
def models(workspace_id:str,actor=Depends(principal),db=Depends(db_dependency,scope='function')):
    actor.require('agents:read')
    env=environment_profile()
    return {'items':[public(row) for row in db.scalars(select(LLMProfile).where(LLMProfile.workspace_id==workspace_id,LLMProfile.enabled.is_(True)))], 'default':{k:v for k,v in env.items() if k!='api_key'}}


@router.post('/models/test')
async def test_model(workspace_id:str,body:ModelWrite,actor=Depends(principal)):
    actor.require('developer:write');profile=await prepare(body)
    return {**await probe(profile),'research':profile['research']}


@router.post('/models',status_code=201)
async def create(workspace_id:str,body:ModelWrite,actor=Depends(principal),db=Depends(db_dependency,scope='function')):
    actor.require('developer:write');profile=await prepare(body);result=await probe(profile)
    research={**profile['research'],'status':'streaming-tested','probe':result}
    row=LLMProfile(workspace_id=workspace_id,name=body.name,model=body.model,base_url=profile['base_url'],encrypted_key=encrypt(body.api_key),api_style=body.api_style,token_parameter=body.token_parameter,options=profile['options'],research=research)
    db.add(row);db.flush();audit(db,actor,'model.created',row.id)
    return public(row)


@router.delete('/models/{profile_id}')
def revoke(workspace_id:str,profile_id:str,actor=Depends(principal),db=Depends(db_dependency,scope='function')):
    actor.require('developer:write');row=owned(db,LLMProfile,workspace_id,profile_id);row.enabled=False;audit(db,actor,'model.disabled',row.id)
    return {'status':'disabled'}

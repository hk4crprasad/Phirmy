"""Validated configuration-defined plans. Defaults are explicitly unapproved DRAFT."""
import hashlib
import json
from pathlib import Path
import threading
from typing import Literal

from pydantic import BaseModel,ConfigDict,Field,StrictInt
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .config import settings
from .models import PlanCatalogSnapshot,WorkspaceSubscription,Workspace
from .db import now


class Limits(BaseModel):
    model_config=ConfigDict(extra='forbid')
    conversations:StrictInt=Field(ge=0)
    chat_turns:StrictInt=Field(ge=0)
    voice_ms:StrictInt=Field(ge=0)
    crawl_pages:StrictInt=Field(ge=0)
    storage_bytes:StrictInt=Field(ge=0)
    seats:StrictInt=Field(ge=1)
    widgets:StrictInt=Field(ge=1)


class Rates(BaseModel):
    model_config=ConfigDict(extra='forbid')
    embedding_minor_per_million_tokens:StrictInt=Field(gt=0)
    llm_input_minor_per_million_tokens:StrictInt=Field(gt=0)
    llm_cached_input_minor_per_million_tokens:StrictInt=Field(gt=0)
    llm_cache_write_30m_minor_per_million_tokens:StrictInt|None=Field(default=None,gt=0)
    llm_cache_write_12h_minor_per_million_tokens:StrictInt|None=Field(default=None,gt=0)
    llm_output_minor_per_million_tokens:StrictInt=Field(gt=0)
    sarvam_stt_minor_per_minute:StrictInt|None=Field(default=None,gt=0)
    sarvam_tts_minor_per_million_characters:StrictInt|None=Field(default=None,gt=0)
    stt_minor_per_minute:StrictInt=Field(gt=0)
    tts_minor_per_million_utf8_bytes:StrictInt=Field(gt=0)
    carrier_minor_per_minute:StrictInt=Field(gt=0)
    storage_minor_per_gb_month:StrictInt=Field(gt=0)


class Plan(BaseModel):
    model_config=ConfigDict(extra='forbid')
    name:str=Field(min_length=1,max_length=80)
    monthly_price_minor:StrictInt=Field(ge=0)
    self_serve:bool
    included:Limits
    spend_cap_minor:StrictInt=Field(ge=0)
    voice_retail_minor_per_minute:StrictInt=Field(gt=0)
    chat_turn_retail_minor:StrictInt=Field(gt=0)
    voice_billing:Literal['included','wallet']='included'


class Catalog(BaseModel):
    model_config=ConfigDict(extra='forbid')
    version:str=Field(min_length=1,max_length=80)
    status:Literal['DRAFT','APPROVED']
    currency:Literal['INR']
    provider_rates:Rates
    model_rates:dict[str,Rates]=Field(default_factory=dict)
    development_voice_minor_per_minute:StrictInt=Field(ge=0,default=600)
    plans:dict[str,Plan]


_cache={};_lock=threading.RLock()


def catalog():
    path=Path(settings.plans_config_path)
    try:
        stat=path.stat();identity=(str(path),stat.st_mtime_ns,stat.st_size)
        with _lock:
            if identity not in _cache:
                parsed=Catalog.model_validate_json(path.read_text())
                if not {'free','starter','growth','custom'}.issubset(parsed.plans):raise ValueError('Missing required plans')
                _cache.clear();_cache[identity]=parsed.model_dump_json()
            body=json.loads(_cache[identity])
    except (OSError,ValueError):raise ValueError('Plan configuration is unavailable or invalid') from None
    canonical=json.dumps(body,sort_keys=True,separators=(',',':'))
    return {**body,'content_hash':hashlib.sha256(canonical.encode()).hexdigest()}


def catalog_snapshot(db):
    body=catalog()
    row=db.scalar(select(PlanCatalogSnapshot).where(PlanCatalogSnapshot.content_hash==body['content_hash']))
    if row:return row
    try:
        with db.begin_nested():
            row=PlanCatalogSnapshot(content_hash=body['content_hash'],version=body['version'],status=body['status'],content=body)
            db.add(row);db.flush()
    except IntegrityError:row=db.scalar(select(PlanCatalogSnapshot).where(PlanCatalogSnapshot.content_hash==body['content_hash']))
    return row


def month_bounds(instant,timezone_name):
    from zoneinfo import ZoneInfo
    from datetime import timezone
    local=instant.astimezone(ZoneInfo(timezone_name));start=local.replace(day=1,hour=0,minute=0,second=0,microsecond=0)
    end=start.replace(year=start.year+1,month=1) if start.month==12 else start.replace(month=start.month+1)
    return start.astimezone(timezone.utc),end.astimezone(timezone.utc)


def subscription(db,workspace_id):
    workspace=db.scalar(select(Workspace).where(Workspace.id==workspace_id).with_for_update())
    if workspace is None:raise ValueError('Workspace unavailable')
    row=db.scalar(select(WorkspaceSubscription).where(WorkspaceSubscription.workspace_id==workspace_id))
    if row is None:
        snapshot=catalog_snapshot(db);start,end=month_bounds(now(),workspace.timezone)
        row=WorkspaceSubscription(workspace_id=workspace_id,catalog_id=snapshot.id,plan_slug='free',state='free',
            period_start=start,period_end=end,billing_profile={});db.add(row);db.flush()
    return row


def public_plans():
    body=catalog()
    activated=False
    if settings.paid_activation_enabled and body['status']=='APPROVED':
        from .gst import business
        try:activated=business()['status']=='APPROVED' and settings.capabilities()['payments']
        except ValueError:pass
    return {'version':body['version'],'status':body['status'],'currency':body['currency'],
            'paid_activation_enabled':activated,
            'items':[{'id':slug,'name':plan['name'],'monthly_price_minor':plan['monthly_price_minor'],
                      'self_serve':plan['self_serve'],'included':plan['included']} for slug,plan in body['plans'].items()]}

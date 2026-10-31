"""Immutable measured usage and tariff-bound cost lines; integer financial units."""
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import json

from fastapi import HTTPException
from sqlalchemy import select,func

from .db import now,session_scope,uid,as_dict
from .models import PlanCatalogSnapshot,TariffSnapshot,MeterEvent,CallCostRecord,StoredObjectMeter,Workspace,WorkspaceSubscription,Membership,Installation,BudgetAdmission
from .plans import subscription,catalog_snapshot,catalog,month_bounds

MICRO=1_000_000
context=ContextVar('metering_context',default={})
RESOURCES={'conversations','chat_turns','voice_ms','crawl_pages','storage_bytes','embedding_tokens','llm_input_tokens','llm_output_tokens','llm_cache_write_30m_tokens','llm_cache_write_12h_tokens','stt_ms','tts_ms','tts_characters','tts_utf8_bytes','carrier_ms'}


def operation(value):return hashlib.sha256(value.encode()).hexdigest()


@contextmanager
def scope(**values):
    token=context.set({**context.get(),**values})
    try:yield
    finally:context.reset(token)


def snapshot(db,workspace_id,operation_key,call_id=None,mode='production'):
    db.scalar(select(Workspace).where(Workspace.id==workspace_id).with_for_update())
    identity=operation(operation_key)
    previous=db.scalar(select(TariffSnapshot).where(TariffSnapshot.workspace_id==workspace_id,TariffSnapshot.operation_key==identity))
    if previous:return previous
    current=subscription(db,workspace_id);catalog=db.get(PlanCatalogSnapshot,current.catalog_id)
    plan=catalog.content['plans'][current.plan_slug]
    from .models import Call
    call=db.get(Call,call_id) if call_id else None
    if call and call.workspace_id!=workspace_id:raise HTTPException(403,'Call tariff is outside this workspace')
    provider_catalog=catalog_snapshot(db)
    row=TariffSnapshot(workspace_id=workspace_id,operation_key=identity,call_id=call_id,catalog_id=catalog.id,
        content={'schema_version':3,'catalog_hash':catalog.content_hash,'catalog_version':catalog.version,'plan':current.plan_slug,'currency':catalog.content['currency'],
                 'status':catalog.status,'mode':mode,'provider_rates':provider_catalog.content['provider_rates'],
                 'provider_catalog_id':provider_catalog.id,'provider_catalog_hash':provider_catalog.content_hash,
                 'provider_rates_status':provider_catalog.status,
                 'model_rates':provider_catalog.content.get('model_rates',{}),
                 'voice_billing':plan.get('voice_billing','included'),
                 'call_transport':call.transport if call else None,'phone_trial':bool(call and call.metadata_data.get('phone_trial_id')),
                 'development_voice_minor_per_minute':catalog.content.get('development_voice_minor_per_minute',600),
                 'voice_retail_minor_per_minute':plan['voice_retail_minor_per_minute'],
                 'chat_turn_retail_minor':plan['chat_turn_retail_minor']})
    db.add(row);db.flush();return row


def record_usage(db,workspace_id,operation_key,resource,quantity,*,scope_id=None,tariff_id=None,direction='consume'):
    if resource not in RESOURCES or type(quantity) is not int or quantity<0 or direction not in {'consume','release'}:
        raise ValueError('Invalid measured usage')
    if quantity==0:return None
    db.scalar(select(Workspace).where(Workspace.id==workspace_id).with_for_update())
    identity=operation(operation_key)
    previous=db.scalar(select(MeterEvent).where(MeterEvent.workspace_id==workspace_id,MeterEvent.operation_key==identity))
    if previous:
        if (previous.resource,previous.quantity,previous.direction,previous.scope_id)!=(resource,quantity,direction,scope_id):
            raise HTTPException(409,'Usage identity conflicts with its original measurement')
        return previous
    if resource in {'conversations','chat_turns','crawl_pages'}:
        from .admission import immediate
        admitted = immediate(db,workspace_id,'usage:'+operation_key,resource,quantity,scope_id)
        tariff_id = tariff_id or admitted.tariff_id
    if tariff_id is None:
        pinned = db.scalar(select(TariffSnapshot).where(TariffSnapshot.workspace_id==workspace_id,
            TariffSnapshot.call_id==scope_id)) if resource=='voice_ms' and scope_id else None
        tariff_id = pinned.id if pinned else snapshot(db,workspace_id,'meter:'+operation_key).id
    row=MeterEvent(workspace_id=workspace_id,operation_key=identity,resource=resource,quantity=quantity,
                   direction=direction,scope_id=scope_id,tariff_id=tariff_id);db.add(row);db.flush();return row


def cost_micro(rates,provider,units):
    """One micro-minor unit is one millionth of a paise; never use binary floats."""
    if provider=='embedding':return units.get('input_tokens',0)*rates['embedding_minor_per_million_tokens']
    if provider in {'openai','llm','sarvam-llm'}:
        cached=min(units.get('cached_input_tokens',0),units.get('input_tokens',0))
        write_30m=units.get('cache_write_30m_tokens',0)
        write_12h=units.get('cache_write_12h_tokens',0)
        written=write_30m+write_12h
        if written+cached>units.get('input_tokens',0) or units.get('cache_write_tokens',written)!=written:
            raise ValueError('Inconsistent cache token measurements')
        if (write_30m and not rates.get('llm_cache_write_30m_minor_per_million_tokens')) or (write_12h and not rates.get('llm_cache_write_12h_minor_per_million_tokens')):
            raise ValueError('Cache write pricing is unavailable')
        return ((units.get('input_tokens',0)-cached-written)*rates['llm_input_minor_per_million_tokens']+
                cached*rates['llm_cached_input_minor_per_million_tokens']+
                write_30m*(rates.get('llm_cache_write_30m_minor_per_million_tokens') or 0)+
                write_12h*(rates.get('llm_cache_write_12h_minor_per_million_tokens') or 0)+
                units.get('output_tokens',0)*rates['llm_output_minor_per_million_tokens'])
    if provider=='sarvam-stt':
        return ((units.get('stt_ms',0)+999)//1000*rates['sarvam_stt_minor_per_minute']*MICRO+59)//60
    if provider=='sarvam-tts':return units.get('tts_characters',0)*rates['sarvam_tts_minor_per_million_characters']
    if provider=='deepgram':return (units.get('stt_ms',0)*rates['stt_minor_per_minute']*MICRO+59999)//60000
    if provider=='fish':return units.get('tts_utf8_bytes',0)*rates['tts_minor_per_million_utf8_bytes']
    if provider in {'plivo','twilio'}:return (units.get('carrier_ms',0)*rates['carrier_minor_per_minute']*MICRO+59999)//60000
    raise ValueError('Unknown cost provider')


def effective_rates(terms,provider,model=None,strict=False):
    if provider in {'sarvam-stt', 'sarvam-tts'}:
        key = 'sarvam_stt_minor_per_minute' if provider == 'sarvam-stt' else 'sarvam_tts_minor_per_million_characters'
        if not terms['provider_rates'].get(key):raise HTTPException(409,'This call tariff predates Sarvam; start a new call')
    if provider in {'llm','openai','sarvam-llm'}:
        if model and model in terms.get('model_rates',{}):return terms['model_rates'][model]
        if provider == 'sarvam-llm':raise HTTPException(409,'This call tariff has no Sarvam model rate; start a new call')
        if strict:
            from .config import settings
            if settings.app_env=='production':raise HTTPException(409,'Configure a provider tariff for this model before enabling it')
    return terms['provider_rates']


def record_cost(db,workspace_id,operation_key,provider,stage,units,*,call_id=None,tariff_id=None,source='measured',mode='production',model=None):
    if not isinstance(units,dict) or any(type(value) is not int or value<0 for value in units.values()):raise ValueError('Invalid provider units')
    if set(units)-{'input_tokens','cached_input_tokens','output_tokens','cache_write_tokens','cache_write_30m_tokens','cache_write_12h_tokens','stt_ms','tts_ms','tts_characters','tts_utf8_bytes','carrier_ms'}:
        raise ValueError('Unsupported provider units')
    db.scalar(select(Workspace).where(Workspace.id==workspace_id).with_for_update())
    identity=operation(operation_key)
    previous=db.scalar(select(CallCostRecord).where(CallCostRecord.workspace_id==workspace_id,CallCostRecord.operation_key==identity))
    if previous:
        if (previous.provider,previous.stage,previous.units,previous.call_id,previous.model)!=(provider,stage,units,call_id,model):
            raise HTTPException(409,'Cost identity conflicts with its original measurement')
        return previous
    tariff=db.get(TariffSnapshot,tariff_id) if tariff_id else snapshot(db,workspace_id,'call:'+call_id if call_id else 'cost:'+operation_key,call_id,mode)
    if not tariff or tariff.workspace_id!=workspace_id:raise ValueError('Cost tariff is outside this workspace')
    rates=effective_rates(tariff.content,provider,model)
    unpriced_cache = ((units.get('cache_write_30m_tokens',0) and not rates.get('llm_cache_write_30m_minor_per_million_tokens')) or
                      (units.get('cache_write_12h_tokens',0) and not rates.get('llm_cache_write_12h_minor_per_million_tokens')) or
                      units.get('cache_write_tokens',0)!=units.get('cache_write_30m_tokens',0)+units.get('cache_write_12h_tokens',0))
    if unpriced_cache and source!='synthetic':
        # Retain the actual token facts without inventing a monetary charge.
        # Keep the admission hold unknown and stop new spending for review.
        source='unreported'
        current=subscription(db,workspace_id);current.operator_paused=True
        from .admission import alert
        alert(db,workspace_id,current.period_start.isoformat(),'unpriced_provider_cache_usage',100,0)
    amount=0 if source in {'synthetic','unreported'} else cost_micro(rates,provider,units)
    row=CallCostRecord(workspace_id=workspace_id,operation_key=identity,call_id=call_id,tariff_id=tariff.id,
                      provider=provider,model=model,stage=stage,units=units,cost_micro_minor=amount,source=source)
    db.add(row)
    from .admission import measured
    measured(db,workspace_id,operation_key,amount,source)
    mapping={'input_tokens':'llm_input_tokens','output_tokens':'llm_output_tokens','stt_ms':'stt_ms','tts_ms':'tts_ms',
             'tts_characters':'tts_characters','tts_utf8_bytes':'tts_utf8_bytes','carrier_ms':'carrier_ms'}
    mapping.update(cache_write_30m_tokens='llm_cache_write_30m_tokens',cache_write_12h_tokens='llm_cache_write_12h_tokens')
    if provider=='embedding':mapping['input_tokens']='embedding_tokens'
    for key,resource in mapping.items():
        if units.get(key):record_usage(db,workspace_id,operation_key+':'+key,resource,units[key],scope_id=call_id,tariff_id=tariff.id)
    db.flush();return row


def append_cost(values,provider,stage,units,operation_key=None,source='measured'):
    if not values.get('workspace_id'):return
    if values.get('db') is not None:
        return record_cost(values['db'],values['workspace_id'],operation_key or provider+':'+uid(),provider,stage,units,
                           call_id=values.get('call_id'),source=source,model=values.get('model')).id
    with session_scope(write=True) as db:
        return record_cost(db,values['workspace_id'],operation_key or provider+':'+uid(),provider,stage,units,
            call_id=values.get('call_id'),tariff_id=values.get('tariff_id'),source=source,
            mode='development' if values.get('mode')=='simulation' else 'production',model=values.get('model')).id


def stored(db,workspace_id,key,size):
    if not key.startswith(workspace_id+'/') or type(size) is not int or size<0:raise ValueError('Invalid stored object measurement')
    db.scalar(select(Workspace).where(Workspace.id==workspace_id).with_for_update())
    row=db.scalar(select(StoredObjectMeter).where(StoredObjectMeter.workspace_id==workspace_id,StoredObjectMeter.object_key==key))
    if row:
        if row.size_bytes!=size:raise ValueError('Stored object identity changed size')
        if row.state=='active':return
        row.state='active';row.deleted_at=None;identity='storage-readd:'+row.id+':'+uid()
    else:
        row=StoredObjectMeter(workspace_id=workspace_id,object_key=key,size_bytes=size,state='active');db.add(row);db.flush()
        identity='storage-add:'+row.id
    record_usage(db,workspace_id,identity,'storage_bytes',size,scope_id=row.id)


def removed(db,workspace_id,key):
    db.scalar(select(Workspace).where(Workspace.id==workspace_id).with_for_update())
    row=db.scalar(select(StoredObjectMeter).where(StoredObjectMeter.workspace_id==workspace_id,StoredObjectMeter.object_key==key).with_for_update())
    if row is None or row.state=='deleted':return
    row.state='deleted';row.deleted_at=now()
    record_usage(db,workspace_id,'storage-remove:'+row.id+':'+uid(),'storage_bytes',row.size_bytes,scope_id=row.id,direction='release')


def usage_summary(db,workspace_id,shared_user_id=None):
    current=db.scalar(select(WorkspaceSubscription).where(WorkspaceSubscription.workspace_id==workspace_id));totals={}
    if current:
        body=db.get(PlanCatalogSnapshot,current.catalog_id).content
        start,end=current.period_start,current.period_end;slug=current.plan_slug;state=current.state
        if slug=='free' and end<=now():start,end=month_bounds(now(),db.get(Workspace,workspace_id).timezone)
    else:
        workspace=db.get(Workspace,workspace_id)
        if workspace is None:raise ValueError('Workspace unavailable')
        body=catalog();start,end=month_bounds(now(),workspace.timezone);slug='free';state='free'
    for resource,direction,amount in db.execute(select(MeterEvent.resource,MeterEvent.direction,func.sum(MeterEvent.quantity)).where(
        MeterEvent.workspace_id==workspace_id,MeterEvent.created_at>=start,
        MeterEvent.created_at<end).group_by(MeterEvent.resource,MeterEvent.direction)):
        totals[resource]=totals.get(resource,0)+int(amount)*(1 if direction=='consume' else -1)
    totals['storage_bytes']=int(db.scalar(select(func.coalesce(func.sum(StoredObjectMeter.size_bytes),0)).where(
        StoredObjectMeter.workspace_id==workspace_id,StoredObjectMeter.state=='active')))
    totals['seats']=int(db.scalar(select(func.count()).select_from(Membership).where(Membership.workspace_id==workspace_id)))
    totals['widgets']=int(db.scalar(select(func.count()).select_from(Installation).where(Installation.workspace_id==workspace_id)))
    pending=list(db.scalars(select(BudgetAdmission).where(BudgetAdmission.workspace_id==workspace_id,
        BudgetAdmission.state.in_(['held','unknown']))))
    reserved={}
    for row in pending:
        for resource,amount in row.resources.items():
            if resource in {'voice_ms','storage_bytes'} or row.created_at>=start:
                reserved[resource]=reserved.get(resource,0)+amount
    cost=int(db.scalar(select(func.coalesce(func.sum(CallCostRecord.cost_micro_minor),0)).where(
        CallCostRecord.workspace_id==workspace_id,CallCostRecord.created_at>=start,CallCostRecord.created_at<end)))
    limit=(current.spend_cap_minor if current and current.spend_cap_minor is not None else body['plans'][slug]['spend_cap_minor'])
    from .config import settings
    from .models import StorageInventoryState
    multiplier=1000 if settings.app_env in {'test','development'} and settings.billing_development_allowances_enabled else 1
    if not current or current.spend_cap_minor is None:limit*=multiplier
    shared = None
    if slug=='free':
        workspace = db.get(Workspace,workspace_id)
        if shared_user_id and workspace.free_allowance_user_id==shared_user_id:
            from .free_allowance import snapshot as shared_snapshot
            shared = shared_snapshot(db,workspace.free_allowance_user_id)
    return {'period_start':start.isoformat(),'period_end':end.isoformat(),
            'plan':slug,'state':state,'status':body['status'],'currency':body['currency'],
            'included':body['plans'][slug]['included'],'usage':totals,'reserved':reserved,
            'development_allowance_multiplier':multiplier,
            'effective_included':{key:value*multiplier for key,value in body['plans'][slug]['included'].items()},
            'estimated_provider_cost_micro_minor':cost,'provider_spend_cap_minor':limit,
            'held_cost_micro_minor':sum(max(0,row.reserved_micro_minor-row.measured_micro_minor) for row in pending),
            'unreported_requests':sum(row.state=='unknown' for row in pending),
            'operator_paused':bool(current and current.operator_paused),
            'billing_blocked':bool(current and current.billing_blocked),'shared_free':shared,
            'storage_inventory_ready':bool(db.scalar(select(StorageInventoryState.id).where(StorageInventoryState.workspace_id==workspace_id)))}

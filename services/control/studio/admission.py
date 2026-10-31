"""Shared admission before work. Unknown provider outcomes keep their cost hold.

Workspace locks serialize PostgreSQL replicas; SQLite writers use BEGIN IMMEDIATE.
Financial estimates use pinned DRAFT rates, never a claim about a vendor invoice.
"""
from fastapi import HTTPException
from sqlalchemy import select,func

from .config import settings
from .db import now,session_scope
from .models import (Workspace,WorkspaceSubscription,PlanCatalogSnapshot,BudgetAdmission,
                     MeterEvent,CallCostRecord,StoredObjectMeter,Membership,User,Installation,Invitation,TariffSnapshot,Call,WidgetBucket)
from .plans import subscription,month_bounds
from .metering import MICRO,operation,snapshot,cost_micro,effective_rates
from .mail_outbox import enqueue_email


def policy(db,workspace_id):
    current=subscription(db,workspace_id)
    from .billing_subscriptions import apply_lifecycle
    apply_lifecycle(db,current)
    from .billing_accounting import refresh_block
    refresh_block(db,workspace_id)
    if current.plan_slug=='free' and current.period_end<=now():
        workspace=db.get(Workspace,workspace_id)
        current.period_start,current.period_end=month_bounds(now(),workspace.timezone)
    body=db.get(PlanCatalogSnapshot,current.catalog_id).content
    plan=body['plans'][current.plan_slug]
    multiplier=1000 if settings.app_env in {'test','development'} and settings.billing_development_allowances_enabled else 1
    limits={key:value*multiplier for key,value in plan['included'].items()}
    cap=current.spend_cap_minor if current.spend_cap_minor is not None else plan['spend_cap_minor']*multiplier
    return current,limits,cap


def alert(db,workspace_id,period,resource,threshold,limit):
    recipients=db.scalars(select(User.email).join(Membership,Membership.user_id==User.id).where(
        Membership.workspace_id==workspace_id,Membership.role=='owner'))
    for email in recipients:
        enqueue_email(db,email,'Workspace allowance '+str(threshold)+'%',
            f'Your workspace has reached {threshold}% of its {resource} allowance or the next request would exceed it. '
            f'Configured limit: {limit}. Prices and provider cost estimates are DRAFT. '
            'Review Billing usage before admitting more work.',
            operation_key='workspace-cap:'+operation(f'{workspace_id}:{period}:{resource}:{threshold}:{limit}:{email}'))


def deny(db,workspace_id,current,resource,limit,message):
    period=current.period_start.isoformat()
    # Roll back unrelated pending work; persist only the notification separately.
    db.rollback()
    with session_scope(write=True) as notice:
        alert(notice,workspace_id,period,resource,100,limit)
    raise HTTPException(429,message)


def usage(db,workspace_id,current,resource):
    if resource=='storage_bytes':
        return int(db.scalar(select(func.coalesce(func.sum(StoredObjectMeter.size_bytes),0)).where(
            StoredObjectMeter.workspace_id==workspace_id,StoredObjectMeter.state=='active')))
    if resource=='widgets':return int(db.scalar(select(func.count()).select_from(Installation).where(Installation.workspace_id==workspace_id)))
    if resource=='seats':
        members=int(db.scalar(select(func.count()).select_from(Membership).where(Membership.workspace_id==workspace_id)))
        invites=int(db.scalar(select(func.count(func.distinct(Invitation.email))).where(Invitation.workspace_id==workspace_id,
            Invitation.state=='pending',Invitation.expires_at>now())))
        return members+invites
    total=0
    for direction,quantity in db.execute(select(MeterEvent.direction,func.sum(MeterEvent.quantity)).where(
        MeterEvent.workspace_id==workspace_id,MeterEvent.resource==resource,
        MeterEvent.created_at>=current.period_start,MeterEvent.created_at<current.period_end).group_by(MeterEvent.direction)):
        total+=int(quantity)*(1 if direction=='consume' else -1)
    return total


def reserve(db,workspace_id,operation_key,*,kind='resource',resources=None,cost=0,scope_id=None,tariff_id=None,installation_id=None):
    resources=resources or {}
    if type(cost) is not int or cost<0 or any(type(value) is not int or value<0 for value in resources.values()):
        raise ValueError('Invalid budget reservation')
    db.scalar(select(Workspace).where(Workspace.id==workspace_id).with_for_update().execution_options(populate_existing=True))
    identity=operation(operation_key)
    previous=db.scalar(select(BudgetAdmission).where(BudgetAdmission.workspace_id==workspace_id,BudgetAdmission.operation_key==identity))
    if previous:
        if (previous.kind,previous.resources,previous.reserved_micro_minor,previous.scope_id)!=(kind,resources,cost,scope_id):
            raise HTTPException(409,'Admission identity conflicts with its original request')
        return previous
    current,limits,cap=policy(db,workspace_id)
    if current.operator_paused or current.billing_blocked:raise HTTPException(429,'This workspace is paused. Contact the workspace owner or review Billing.')
    pending=list(db.scalars(select(BudgetAdmission).where(BudgetAdmission.workspace_id==workspace_id,
        BudgetAdmission.state.in_(['held','unknown']))))
    for resource,amount in resources.items():
        if resource not in limits:raise ValueError('Unknown plan resource')
        # Voice reservations cross month boundaries; storage is a current balance.
        held=sum(row.resources.get(resource,0) for row in pending if resource in {'voice_ms','storage_bytes'} or row.created_at>=current.period_start)
        projected=usage(db,workspace_id,current,resource)+held+amount;limit=limits[resource]
        if projected>limit:
            deny(db,workspace_id,current,resource,limit,f'This workspace has reached its {resource.replace("_"," ")} allowance. Review Billing usage.')
        if projected*5>=limit*4:alert(db,workspace_id,current.period_start.isoformat(),resource,80,limit)
        if projected>=limit:alert(db,workspace_id,current.period_start.isoformat(),resource,100,limit)
    spent=int(db.scalar(select(func.coalesce(func.sum(CallCostRecord.cost_micro_minor),0)).where(
        CallCostRecord.workspace_id==workspace_id,CallCostRecord.created_at>=current.period_start,
        CallCostRecord.created_at<current.period_end)))
    held=sum(max(0,row.reserved_micro_minor-row.measured_micro_minor) for row in pending)
    projected=spent+held+cost
    if cap==0 or projected>cap*MICRO:
        deny(db,workspace_id,current,'provider_spend_minor',cap,'This workspace has reached its spending cap. Contact the workspace owner.')
    if projected*5>=cap*MICRO*4:alert(db,workspace_id,current.period_start.isoformat(),'provider_spend_minor',80,cap)
    if projected>=cap*MICRO:alert(db,workspace_id,current.period_start.isoformat(),'provider_spend_minor',100,cap)
    from .free_allowance import check as check_shared_free
    check_shared_free(db,workspace_id,current,resources,cost)
    if installation_id:
        installation=db.scalar(select(Installation).where(Installation.workspace_id==workspace_id,Installation.id==installation_id))
        if not installation:raise HTTPException(409,'Widget is no longer available')
        from .widget_protection import policy as widget_policy,alert as widget_alert
        month=now().strftime('%Y-%m');start=now().replace(day=1,hour=0,minute=0,second=0,microsecond=0)
        rows=db.scalars(select(BudgetAdmission).where(BudgetAdmission.workspace_id==workspace_id,
            BudgetAdmission.installation_id==installation_id,BudgetAdmission.created_at>=start))
        estimated=sum(max(row.measured_micro_minor,row.reserved_micro_minor if row.state in {'held','unknown'} else 0) for row in rows)
        legacy=db.scalar(select(WidgetBucket).where(WidgetBucket.installation_id==installation_id,WidgetBucket.period==month))
        estimated+=cost+(legacy.reserved_minor*MICRO if legacy else 0)
        widget_cap=widget_policy(db,installation)['monthly_spend_cap_minor']
        if widget_cap==0 or estimated>widget_cap*MICRO:
            # Notification survives rollback, while no new provider request starts.
            db.rollback()
            with session_scope(write=True) as notice:
                widget_alert(notice,notice.get(Installation,installation_id),month,widget_cap,100)
            raise HTTPException(429,'This assistant has reached its spending limit. Please contact the business.')
        if estimated*5>=widget_cap*MICRO*4:widget_alert(db,installation,month,widget_cap,80)
        if estimated>=widget_cap*MICRO:widget_alert(db,installation,month,widget_cap,100)
    tariff=db.get(TariffSnapshot,tariff_id) if tariff_id else snapshot(db,workspace_id,'admission:'+operation_key)
    if not tariff or tariff.workspace_id!=workspace_id:raise ValueError('Invalid admission tariff')
    row=BudgetAdmission(workspace_id=workspace_id,operation_key=identity,kind=kind,scope_id=scope_id,
        installation_id=installation_id,tariff_id=tariff.id,resources=resources,reserved_micro_minor=cost,state='held')
    db.add(row);db.flush();return row


def finish(db,workspace_id,operation_key,*,unknown=False):
    db.scalar(select(Workspace).where(Workspace.id==workspace_id).with_for_update())
    row=db.scalar(select(BudgetAdmission).where(BudgetAdmission.workspace_id==workspace_id,
        BudgetAdmission.operation_key==operation(operation_key)))
    if row and row.state in {'held','unknown'}:
        row.state='unknown' if unknown else 'completed';row.settled_at=None if unknown else now()
    return row


def provider_hold(values,operation_key,provider,units,*,cache_mode=None):
    if not values.get('workspace_id'):return None
    def hold(db):
        tariff=snapshot(db,values['workspace_id'],'call:'+values['call_id'] if values.get('call_id') else 'cost:'+operation_key,
            values.get('call_id'),'development' if values.get('mode')=='simulation' else 'production')
        installation_id=values.get('installation_id')
        if not installation_id and values.get('call_id'):
            call=db.get(Call,values['call_id'])
            if call:installation_id=call.metadata_data.get('widget_installation_id')
        rates=effective_rates(tariff.content,provider,values.get('model'),strict=True)
        cache_priced=bool(rates.get('llm_cache_write_30m_minor_per_million_tokens'))
        bounded_units=dict(units)
        if cache_mode:
            if not cache_priced and cache_mode=='chat_30m':
                raise HTTPException(409,'Use Responses or configure cache-write rates before using this model with Chat Completions')
            incoming=bounded_units.get('input_tokens',0)
            worst=max((rates['llm_input_minor_per_million_tokens'],'ordinary'),
                      (rates['llm_cached_input_minor_per_million_tokens'],'cached'),
                      (rates.get('llm_cache_write_30m_minor_per_million_tokens') or 0,'write'))[1]
            if worst=='cached':bounded_units['cached_input_tokens']=incoming
            elif worst=='write':bounded_units['cache_write_30m_tokens']=incoming
        row=reserve(db,values['workspace_id'],operation_key,kind='provider',
                    cost=cost_micro(rates,provider,bounded_units),scope_id=values.get('call_id'),tariff_id=tariff.id,
                    installation_id=installation_id)
        return {'id':row.id,'cache_writes_priced':cache_priced} if cache_mode else row.id
    if values.get('db') is not None:return hold(values['db'])
    with session_scope(write=True) as db:return hold(db)


def provider_release(values,operation_key):
    """Release a preflight reservation only when no provider request was sent."""
    if values.get('db') is not None:
        return finish(values['db'],values['workspace_id'],operation_key)
    with session_scope(write=True) as db:
        finish(db,values['workspace_id'],operation_key)


def measured(db,workspace_id,operation_key,amount,source):
    row=db.scalar(select(BudgetAdmission).where(BudgetAdmission.workspace_id==workspace_id,
        BudgetAdmission.operation_key==operation(operation_key)))
    if not row:return
    row.measured_micro_minor=amount
    row.state='unknown' if source=='unreported' else 'completed'
    row.settled_at=None if source=='unreported' else now()
    if amount>row.reserved_micro_minor:
        # Never hide a provider overrun by truncating measured cost.
        current=subscription(db,workspace_id);current.operator_paused=True
        alert(db,workspace_id,current.period_start.isoformat(),'provider_reservation_overrun',100,row.reserved_micro_minor)


def provider_extend(values,operation_key,provider,units):
    """Grow a streaming operation hold before forwarding each bounded text chunk."""
    from .db import uid
    with session_scope(write=True) as db:
        loan={**values,'db':db}
        db.scalar(select(Workspace).where(Workspace.id==values['workspace_id']).with_for_update())
        parent=db.scalar(select(BudgetAdmission).where(BudgetAdmission.workspace_id==values['workspace_id'],
            BudgetAdmission.operation_key==operation(operation_key)))
        if parent is None:
            provider_hold(loan,operation_key,provider,{})
            parent=db.scalar(select(BudgetAdmission).where(BudgetAdmission.workspace_id==values['workspace_id'],
                BudgetAdmission.operation_key==operation(operation_key)))
        if parent.state!='held':raise HTTPException(409,'Streaming budget is already settled')
        tariff=db.get(TariffSnapshot,parent.tariff_id)
        amount=cost_micro(tariff.content['provider_rates'],provider,units)
        child=reserve(db,values['workspace_id'],operation_key+':chunk:'+uid(),kind='stream_chunk',
            cost=amount,scope_id=values.get('call_id'),tariff_id=tariff.id,installation_id=parent.installation_id)
        child.state='completed';child.settled_at=now();parent.reserved_micro_minor+=amount


def immediate(db,workspace_id,operation_key,resource,quantity,scope_id=None):
    row=reserve(db,workspace_id,operation_key,resources={resource:quantity},scope_id=scope_id)
    finish(db,workspace_id,operation_key)
    return row


def resource_hold(workspace_id,operation_key,resource,quantity,scope_id=None):
    with session_scope(write=True) as db:
        return reserve(db,workspace_id,operation_key,resources={resource:quantity},scope_id=scope_id).id


def admit_voice(db,call,config):
    maximum=min(900,int(config.get('behavior',{}).get('max_connected_seconds',300)),
                int(call.metadata_data.get('installation_max_duration_ms',900000))//1000,
                int(call.metadata_data.get('phone_trial_seconds',900)))
    from .tariffs import voice_admission
    maximum=voice_admission(db,call,maximum)
    reserve(db,call.workspace_id,'voice-quota:'+call.id,resources={'voice_ms':maximum*1000},scope_id=call.id)
    call.metadata_data={**call.metadata_data,'admitted_max_seconds':maximum}
    if call.mode=='live':
        values={'workspace_id':call.workspace_id,'call_id':call.id}
        values['db']=db
        from .voice_config import stt_provider
        provider_hold(values,'stt:'+call.id,stt_provider(),{'stt_ms':maximum*1000})
        if call.transport in {'pstn','plivo','twilio'}:
            provider_hold(values,'carrier:'+call.id,call.metadata_data.get('provider','plivo'),{'carrier_ms':maximum*1000})

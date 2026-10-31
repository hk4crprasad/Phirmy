"""Receipt-first subscriptions; captured fees alone grant paid plan coverage."""
import asyncio
from datetime import datetime,timedelta,timezone
import hashlib
import hmac
import json

from fastapi import APIRouter,Depends,HTTPException,Request
from pydantic import Field
from sqlalchemy import select

from . import billing_accounting as money,billing_events,billing_quote,plans,gst
from .config import settings
from .db import session_scope,now,as_dict,uid
from .domain import owned,enqueue
from .models import BillingProviderOperation,WorkspaceSubscription,PaymentOrder,Workspace,PlanCatalogSnapshot,Job
from .schemas import Input
from .security import principal,db_dependency,audit
from .secrets import encrypt

router=APIRouter()
ACTIVE={'creating','unknown','created','authenticated','active','pending','halted','paused','cancel_pending','activation_paused'}


class Subscribe(Input):
    plan_slug:str=Field(min_length=1,max_length=40)
    quote_token:str=Field(min_length=1,max_length=5000)


class Cancel(Input):
    at_cycle_end:bool=True


class CheckoutProof(Input):
    razorpay_payment_id:str=Field(min_length=1,max_length=100)
    razorpay_subscription_id:str=Field(min_length=1,max_length=100)
    razorpay_signature:str=Field(pattern=r'^[0-9a-fA-F]{64}$')


@router.post('/v1/workspaces/{workspace_id}/billing/subscriptions/{operation_id}/verify')
async def verify_checkout(workspace_id:str,operation_id:str,body:CheckoutProof,actor=Depends(principal),db=Depends(db_dependency,scope='function')):
    actor.require('billing:write')
    contract=owned(db,BillingProviderOperation,workspace_id,operation_id)
    if contract.kind!='subscription' or not contract.provider_id or contract.provider_id!=body.razorpay_subscription_id:
        raise HTTPException(409,'Checkout subscription does not match its server receipt')
    credentials=settings.razorpay_credentials()
    if not all(credentials):raise HTTPException(409,'Payment verification credentials are not configured')
    billing_events.identifier(body.razorpay_payment_id)
    expected=hmac.new(credentials[1].encode(),(body.razorpay_payment_id+'|'+contract.provider_id).encode(),hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected,body.razorpay_signature.lower()):raise HTTPException(401,'Subscription checkout signature is invalid')
    from .payment_routes import provider
    provider_id=contract.provider_id
    db.commit()
    subscription,payment=await asyncio.gather(provider('GET','/subscriptions/'+provider_id),provider('GET','/payments/'+body.razorpay_payment_id))
    if subscription.get('id')!=provider_id or payment.get('id')!=body.razorpay_payment_id:raise HTTPException(409,'Payment verification identity mismatch')
    event={'event':'subscription.checkout_verified','created_at':int(now().timestamp()),'payload':{'subscription':{'entity':subscription}}}
    apply_event(db,event,'checkout-observation:'+uid(),payment,source='provider_api_verification')
    return {'status':'captured' if payment.get('status')=='captured' else 'awaiting_capture','subscription':operation_record(db.get(BillingProviderOperation,operation_id))}


def operation_record(row):
    return {'id':row.id,'kind':row.kind,'state':row.state,'provider_id':row.provider_id,
            'plan_slug':row.details.get('plan_slug'),'created_at':row.created_at.isoformat(),
            'paid_period_end':row.details.get('paid_period_end'),'cancel_at_cycle_end':row.details.get('cancel_at_cycle_end',False)}


@router.get('/v1/workspaces/{workspace_id}/billing/subscriptions')
def subscriptions(workspace_id:str,actor=Depends(principal),db=Depends(db_dependency,scope='function')):
    actor.require('billing:read')
    current=db.scalar(select(WorkspaceSubscription).where(WorkspaceSubscription.workspace_id==workspace_id))
    rows=db.scalars(select(BillingProviderOperation).where(BillingProviderOperation.workspace_id==workspace_id,
        BillingProviderOperation.kind=='subscription').order_by(BillingProviderOperation.created_at.desc()).limit(50))
    return {'items':[operation_record(row) for row in rows],'entitlement':{'plan':current.plan_slug,'state':current.state,
            'period_end':current.period_end.isoformat(),'pending_plan':current.pending_plan_slug} if current else {'plan':'free','state':'free'},
            'key_id':settings.razorpay_credentials()[0] if settings.paid_activation_enabled else ''}


@router.post('/v1/workspaces/{workspace_id}/billing/subscriptions',status_code=202)
def subscribe(workspace_id:str,body:Subscribe,request:Request,actor=Depends(principal),db=Depends(db_dependency,scope='function')):
    actor.require('billing:write');money.lock(db,workspace_id)
    key=request.headers.get('Idempotency-Key','')
    if not key or len(key)>180:raise HTTPException(422,'Idempotency-Key required')
    previous=db.scalar(select(BillingProviderOperation).where(BillingProviderOperation.workspace_id==workspace_id,
        BillingProviderOperation.operation_key=='subscription:'+key))
    if previous:
        if previous.kind!='subscription' or previous.details.get('plan_slug')!=body.plan_slug:raise HTTPException(409,'Subscription identity conflicts with its original plan')
        return operation_record(previous)
    current=plans.subscription(db,workspace_id)
    apply_lifecycle(db,current);money.refresh_block(db,workspace_id)
    if current.plan_slug!='free' and current.period_end>now():
        raise HTTPException(409,'Existing paid coverage must end before a new self-service subscription starts')
    if current.operator_paused or current.billing_blocked:raise HTTPException(409,'Resolve the workspace billing review before starting a subscription')
    if db.scalar(select(BillingProviderOperation.id).where(BillingProviderOperation.workspace_id==workspace_id,
        BillingProviderOperation.kind=='subscription',BillingProviderOperation.state.in_(ACTIVE))):
        raise HTTPException(409,'Resolve or cancel the existing subscription before creating another')
    quoted=billing_quote.authorize(db,workspace_id,0,body.quote_token,purpose='subscription',plan_slug=body.plan_slug)
    catalog=plans.catalog_snapshot(db);quote=quoted['quote']
    hashed=hashlib.sha256(json.dumps(quote,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    row=BillingProviderOperation(workspace_id=workspace_id,operation_key='subscription:'+key,kind='subscription',request_hash=hashed,
        state='creating',details={'catalog_id':catalog.id,'plan_slug':body.plan_slug,'quote':quote,'dispatch_started':False,'last_event_at':0})
    db.add(row);db.flush();enqueue(db,workspace_id,'billing_subscription_create',{'operation_id':row.id,'errors':0})
    audit(db,actor,'billing.subscription_requested',row.id,{'plan':body.plan_slug})
    return operation_record(row)


@router.post('/v1/workspaces/{workspace_id}/billing/subscriptions/{operation_id}/reconcile',status_code=202)
def reconcile(workspace_id:str,operation_id:str,actor=Depends(principal),db=Depends(db_dependency,scope='function')):
    actor.require('billing:write');money.lock(db,workspace_id)
    row=owned(db,BillingProviderOperation,workspace_id,operation_id)
    if row.kind!='subscription':raise HTTPException(404,'Subscription not found')
    enqueue(db,workspace_id,'billing_subscription_create',{'operation_id':row.id,'errors':0})
    return operation_record(row)


@router.post('/v1/workspaces/{workspace_id}/billing/subscriptions/{operation_id}/cancel',status_code=202)
def cancel(workspace_id:str,operation_id:str,body:Cancel,request:Request,actor=Depends(principal),db=Depends(db_dependency,scope='function')):
    actor.require('billing:write');money.lock(db,workspace_id)
    contract=owned(db,BillingProviderOperation,workspace_id,operation_id)
    if contract.kind!='subscription':raise HTTPException(404,'Subscription not found')
    if not contract.provider_id and not contract.details.get('dispatch_started'):
        contract.state='cancelled';return operation_record(contract)
    if not contract.provider_id:raise HTTPException(409,'Reconcile the unknown provider identity before cancellation')
    key=request.headers.get('Idempotency-Key','')
    if not key or len(key)>180:raise HTTPException(422,'Idempotency-Key required')
    previous=db.scalar(select(BillingProviderOperation).where(BillingProviderOperation.workspace_id==workspace_id,
        BillingProviderOperation.operation_key=='cancel:'+key))
    if previous:
        if previous.details.get('subscription_operation_id')!=contract.id or previous.details.get('at_cycle_end')!=body.at_cycle_end:
            raise HTTPException(409,'Cancellation identity conflicts with its original request')
        if previous.state!='completed':
            active=db.scalar(select(Job.id).where(Job.workspace_id==workspace_id,Job.kind=='billing_subscription_cancel',
                Job.state.in_(['queued','running']),Job.payload['operation_id'].as_string()==previous.id))
            if not active:enqueue(db,workspace_id,'billing_subscription_cancel',{'operation_id':previous.id,'errors':0})
        return operation_record(previous)
    unresolved=db.scalar(select(BillingProviderOperation.id).where(BillingProviderOperation.workspace_id==workspace_id,
        BillingProviderOperation.kind=='subscription_cancel',BillingProviderOperation.state!='completed',
        BillingProviderOperation.details['subscription_operation_id'].as_string()==contract.id))
    if unresolved:raise HTTPException(409,'Reconcile the existing cancellation with its original idempotency key')
    row=BillingProviderOperation(workspace_id=workspace_id,operation_key='cancel:'+key,kind='subscription_cancel',request_hash=str(body.at_cycle_end),
        details={'subscription_operation_id':contract.id,'at_cycle_end':body.at_cycle_end},state='creating')
    db.add(row);db.flush();enqueue(db,workspace_id,'billing_subscription_cancel',{'operation_id':row.id,'errors':0})
    audit(db,actor,'billing.subscription_cancel_requested',contract.id,{'at_cycle_end':body.at_cycle_end})
    return operation_record(row)


async def find_provider(path,receipt_key,identity):
    from .payment_routes import provider
    # Read-only reconciliation is bounded. An inconclusive scan never replays an
    # ambiguous subscription write; an operator can inspect/reconcile its receipt.
    for skip in range(0,1000,100):
        result=await provider('GET',path,params={'count':100,'skip':skip})
        rows=result.get('items',[])
        if not isinstance(rows,list):raise HTTPException(502,'Invalid provider collection')
        for row in rows:
            notes=row.get('notes') or {}
            if isinstance(notes,dict) and notes.get(receipt_key)==identity:return row
        if len(rows)<100:return None
    raise HTTPException(409,'Provider collection exceeds automatic reconciliation budget')


async def create_job(job_id):
    from .job_control import get_job
    from .payment_routes import provider
    def load():
        with session_scope(write=True) as db:
            job=get_job(db,job_id);money.lock(db,job.workspace_id)
            row=owned(db,BillingProviderOperation,job.workspace_id,job.payload['operation_id'])
            if row.kind!='subscription' or row.state in {'cancelled','completed'}:return None
            if row.provider_id:return {'known':True}
            if not row.details.get('dispatch_started') and not settings.paid_activation_enabled:
                row.state='activation_paused';job.state='queued';job.available_at=now()+timedelta(hours=1);return None
            quote=row.details['quote'];plan_key='provider-plan:'+row.details['catalog_id']+':'+row.details['plan_slug']+':'+quote['seller']['content_hash']
            plan=db.scalar(select(BillingProviderOperation).where(BillingProviderOperation.workspace_id==row.workspace_id,BillingProviderOperation.operation_key==plan_key))
            if not plan:
                plan=BillingProviderOperation(workspace_id=row.workspace_id,operation_key=plan_key,kind='plan',state='creating',request_hash=row.request_hash,
                    details={'plan_slug':row.details['plan_slug'],'amount_minor':quote['tax']['gross_minor']})
                db.add(plan);db.flush()
            return {'workspace_id':row.workspace_id,'id':row.id,'quote':quote,'plan_id':plan.id,'provider_plan_id':plan.provider_id,
                    'dispatched':bool(row.details.get('dispatch_started'))}
    data=await asyncio.to_thread(load)
    if not data or data.get('known'):return
    try:
        provider_plan=data['provider_plan_id']
        if not provider_plan:
            found=await find_provider('/plans','studio_plan_receipt',data['plan_id'])
            if not found:
                found=await provider('POST','/plans',json={'period':'monthly','interval':1,
                    'item':{'name':data['quote']['description'],'amount':data['quote']['tax']['gross_minor'],'currency':'INR'},
                    'notes':{'studio_plan_receipt':data['plan_id']}})
            provider_plan=billing_events.identifier(found.get('id'))
            item=found.get('item') or {}
            if item.get('amount')!=data['quote']['tax']['gross_minor'] or item.get('currency')!='INR':raise HTTPException(409,'Provider plan conflicts with approved price')
            def save_plan():
                with session_scope(write=True) as db:
                    get_job(db,job_id);plan=owned(db,BillingProviderOperation,data['workspace_id'],data['plan_id'])
                    plan.provider_id=provider_plan;plan.state='created'
            await asyncio.to_thread(save_plan)
        if data['dispatched']:
            result=await find_provider('/subscriptions','studio_subscription_receipt',data['id'])
            if result is None:raise HTTPException(409,'Unknown subscription outcome requires provider reconciliation')
        else:
            def before_dispatch():
                with session_scope(write=True) as db:
                    get_job(db,job_id);money.lock(db,data['workspace_id'])
                    row=owned(db,BillingProviderOperation,data['workspace_id'],data['id'])
                    if row.state=='cancelled':return False
                    if not settings.paid_activation_enabled:raise HTTPException(409,'Paid activation was disabled before dispatch')
                    row.details={**row.details,'dispatch_started':True,'provider_plan_id':provider_plan};return True
            if not await asyncio.to_thread(before_dispatch):return
            result=await provider('POST','/subscriptions',json={'plan_id':provider_plan,'quantity':1,'total_count':120,
                'customer_notify':False,'notes':{'studio_subscription_receipt':data['id']}})
        identity=billing_events.identifier(result.get('id'))
        if result.get('plan_id')!=provider_plan:raise HTTPException(409,'Provider subscription plan mismatch')
        def save():
            with session_scope(write=True) as db:
                get_job(db,job_id);money.lock(db,data['workspace_id'])
                row=owned(db,BillingProviderOperation,data['workspace_id'],data['id'])
                if row.provider_id and row.provider_id!=identity:raise HTTPException(409,'Subscription receipt already bound to another identity')
                row.provider_id=identity
                if row.state in {'creating','unknown','activation_paused'}:row.state=result.get('status','created')
                current=plans.subscription(db,row.workspace_id);current.provider_subscription_id=identity
        await asyncio.to_thread(save)
    except asyncio.CancelledError:raise
    except Exception:
        def failed():
            with session_scope(write=True) as db:
                job=get_job(db,job_id);row=owned(db,BillingProviderOperation,data['workspace_id'],data['id'])
                if row.provider_id:return False
                row.state='unknown';errors=job.payload.get('errors',0)+1;job.payload={**job.payload,'errors':errors}
                if errors<8:job.state='queued';job.available_at=now()+timedelta(seconds=min(3600,30*2**errors))
                return errors>=8
        if await asyncio.to_thread(failed):raise RuntimeError('Subscription outcome requires provider reconciliation') from None


async def cancel_job(job_id):
    from .job_control import get_job
    from .payment_routes import provider
    def load():
        with session_scope() as db:
            job=get_job(db,job_id);operation=owned(db,BillingProviderOperation,job.workspace_id,job.payload['operation_id'])
            contract=owned(db,BillingProviderOperation,job.workspace_id,operation.details['subscription_operation_id'])
            return operation.id,contract.id,contract.provider_id,operation.details['at_cycle_end'],operation.state,job.workspace_id
    identity,contract_id,provider_id,at_end,state,workspace_id=await asyncio.to_thread(load)
    if state=='completed':return
    if state=='unknown':
        result=await provider('GET','/subscriptions/'+provider_id)
        if result.get('status')!='cancelled':raise RuntimeError('Unknown cancellation outcome requires provider reconciliation')
    else:
        def dispatch():
            with session_scope(write=True) as db:
                get_job(db,job_id);operation=owned(db,BillingProviderOperation,workspace_id,identity);operation.state='unknown'
        await asyncio.to_thread(dispatch)
        result=await provider('POST','/subscriptions/'+provider_id+'/cancel',json={'cancel_at_cycle_end':at_end})
    if result.get('id')!=provider_id:raise HTTPException(409,'Cancellation response identity mismatch')
    def save():
        with session_scope(write=True) as db:
            get_job(db,job_id);money.lock(db,workspace_id)
            operation=owned(db,BillingProviderOperation,workspace_id,identity);contract=owned(db,BillingProviderOperation,workspace_id,contract_id)
            operation.state='completed';contract.details={**contract.details,'cancel_at_cycle_end':at_end};contract.state='cancel_pending' if at_end else 'cancelled'
            current=plans.subscription(db,workspace_id);current.pending_plan_slug='free'
            # Retain already-paid coverage; no automatic renewal follows cancellation.
            audit_data={'subscription_operation_id':contract.id,'at_cycle_end':at_end}
            money.financial_event(db,workspace_id,'subscription-cancel:'+identity,'subscription_cancelled',audit_data,provider_id)
    await asyncio.to_thread(save)


def timestamp(value,name):
    if type(value) is not int or not 0<=value<=4_102_444_800:raise HTTPException(422,'Invalid subscription '+name)
    return datetime.fromtimestamp(value,timezone.utc)


def apply_event(db,event,event_key,payment,source='provider_webhook'):
    payload=event.get('payload',{}).get('subscription',{}).get('entity')
    if not isinstance(payload,dict):raise HTTPException(422,'Subscription snapshot missing')
    identity=billing_events.identifier(payload.get('id'))
    contract=db.scalar(select(BillingProviderOperation).where(BillingProviderOperation.kind=='subscription',BillingProviderOperation.provider_id==identity))
    if not contract:
        notes=payload.get('notes') or {}
        receipt=notes.get('studio_subscription_receipt') if isinstance(notes,dict) else None
        contract=db.get(BillingProviderOperation,receipt) if isinstance(receipt,str) and len(receipt)<=36 else None
        if not contract or contract.kind!='subscription':raise LookupError('unmatched_subscription')
    money.lock(db,contract.workspace_id)
    contract=db.scalar(select(BillingProviderOperation).where(BillingProviderOperation.id==contract.id).with_for_update().execution_options(populate_existing=True))
    if contract.provider_id and contract.provider_id!=identity:raise HTTPException(409,'Subscription identity conflicts with its receipt')
    expected_plan=contract.details.get('provider_plan_id')
    if not expected_plan or payload.get('plan_id')!=expected_plan:raise HTTPException(409,'Subscription plan conflicts with its admitted price')
    stamp=event.get('created_at');when=timestamp(stamp,'event timestamp')
    if stamp>int(now().timestamp())+300:raise HTTPException(422,'Subscription event timestamp is in the future')
    contract.provider_id=identity
    current=plans.subscription(db,contract.workspace_id)
    review_required=current.state=='refund_review'
    status=payload.get('status')
    full_capture=bool(payment and payment.get('status')=='captured' and payment.get('amount')==contract.details['quote']['tax']['gross_minor'])
    rank=6 if status in {'cancelled','completed','expired'} else 5 if status=='paused' else 4 if full_capture else 3 if status in {'active','resumed'} else 2 if status=='authenticated' else 1
    newest=(stamp,rank)>=(contract.details.get('last_event_at',0),contract.details.get('last_event_rank',0))
    if contract.state in {'cancelled','completed','expired'} and status not in {'cancelled','completed','expired'}:newest=False
    name=event['event'];paid=False
    if payment and payment.get('status')=='captured':
        full=payment.get('amount')==contract.details['quote']['tax']['gross_minor']
        if payment.get('currency')!='INR':raise HTTPException(409,'Subscription payment currency mismatch')
        payment_id=billing_events.identifier(payment.get('id'))
        quoted={**contract.details['quote'],'subscription_id':identity,'contract_operation_id':contract.id}
        if full:
            start=timestamp(payload.get('current_start'),'period start');end=timestamp(payload.get('current_end'),'period end')
            if end<=start or end-start>timedelta(days=35):raise HTTPException(422,'Invalid monthly subscription coverage')
            created=timestamp(payment.get('created_at'),'payment timestamp')
            # Immediate monthly contracts have no advance/trial charges. Never
            # combine an old signed payment with a later subscription period.
            if not start-timedelta(days=1)<=created<=end+timedelta(days=7):
                raise HTTPException(409,'Payment does not cover the reported subscription period')
            quote={**quoted,'subscription_id':identity,'contract_operation_id':contract.id,'period_start':start.isoformat(),'period_end':end.isoformat()}
        else:
            # Mandate authentication is not a paid plan charge. Its small capture
            # and later reversal never become purchased wallet funds or revenue.
            amount=billing_events.integer(payment.get('amount'),'authorization amount',1)
            if amount>quoted['seller'].get('subscription_authorization_max_minor',1000) or amount>=quoted['tax']['gross_minor']:
                raise HTTPException(409,'Unexpected subscription amount requires provider reconciliation')
            quote={**quoted,'purpose':'subscription_authorization','authorized_paid':False,'description':'Subscription authorization hold',
                'tax':{**quoted['tax'],'net_minor':amount,'gross_minor':amount,'tax_minor':0,'cgst_minor':0,'sgst_minor':0,'igst_minor':0,'gst_rate_basis_points':0}}
        order=db.scalar(select(PaymentOrder).where(PaymentOrder.provider_payment_id==payment_id))
        if order and order.workspace_id!=contract.workspace_id:raise HTTPException(409,'Subscription payment belongs to another workspace')
        if order:
            original=billing_events.quote_for(db,order)
            if original.get('purpose') not in {'subscription','subscription_authorization'} or original.get('contract_operation_id')!=contract.id:
                raise HTTPException(409,'Payment is already assigned to another billing purpose')
            if full and original.get('period_start') and original.get('period_end'):
                start=datetime.fromisoformat(original['period_start']);end=datetime.fromisoformat(original['period_end'])
        if not order:
            order=PaymentOrder(workspace_id=contract.workspace_id,amount_minor=quote['tax']['gross_minor'],net_minor=quote['tax']['net_minor'],
                operation_key='subscription-payment:'+payment_id,provider_order_id=payment.get('order_id'),
                provider_payment_id=payment_id,encrypted_snapshot=encrypt(json.dumps(quote)))
            db.add(order);db.flush()
        billing_events.capture(db,payment,order=order)
        if full:
            from .models import PaymentRefund
            blocked_payment=order.reversed_net_minor>0 or db.scalar(select(PaymentRefund.id).where(
                PaymentRefund.order_id==order.id,PaymentRefund.state.in_(money.REFUND_HELD|{'processed'})))
            if blocked_payment:review_required=True
            paid=True
            prior_end=contract.details.get('paid_period_end')
            if not prior_end or end>=datetime.fromisoformat(prior_end):
                contract.details={**contract.details,'paid_period_start':start.isoformat(),'paid_period_end':end.isoformat()}
            if not blocked_payment and end>now() and (current.plan_slug=='free' or end>=current.period_end) and (not current.provider_subscription_id or current.provider_subscription_id==identity):
                cancelled=current.pending_plan_slug=='free' or contract.state in {'cancel_pending','cancelled','completed','expired'}
                current.provider_subscription_id=identity;current.catalog_id=contract.details['catalog_id'];current.plan_slug=contract.details['plan_slug']
                current.period_start=start;current.period_end=end;current.state='cancelled' if cancelled else 'active';current.failed_payments=0;current.dunning_at=None;current.pending_plan_slug='free' if cancelled else None
    if newest:
        status=payload.get('status')
        allowed={'created','authenticated','active','pending','halted','cancelled','completed','paused','resumed','expired'}
        if status not in allowed:raise HTTPException(422,'Unknown subscription state')
        contract.state=status
        contract.details={**contract.details,'last_event_at':stamp,'last_event_rank':rank}
        if not current.provider_subscription_id:current.provider_subscription_id=identity
        if current.provider_subscription_id==identity:
            if status in {'pending','halted'} and current.plan_slug!='free':
                current.state='past_due';current.failed_payments+=1
                if not current.dunning_at:current.dunning_at=when
                billing_events.owner_alert(db,current.workspace_id,'subscription-past-due:'+identity+':'+str(stamp),'Subscription payment needs attention',
                    'A subscription charge failed. Review Billing and contact support to resolve payment. Paid service does not renew without a captured charge; read/export access remains available.')
            elif status in {'cancelled','completed','expired'}:
                current.pending_plan_slug='free'
                if current.plan_slug!='free':current.state='cancelled'
            elif status=='paused' and current.plan_slug!='free':current.state='paused'
            elif status in {'active','resumed'} and not paid and current.plan_slug!='free':
                coverage=contract.details.get('paid_period_end')
                if coverage and datetime.fromisoformat(coverage)>now():current.state='active';current.dunning_at=None
    if review_required and current.plan_slug!='free':current.state='refund_review'
    money.financial_event(db,contract.workspace_id,'subscription-event:'+event_key,'subscription_state',
        {'state':contract.state,'event_type':name,'event_time':stamp,'event_source':source,'paid_coverage':paid},identity)
    apply_lifecycle(db,current)
    money.refresh_block(db,current.workspace_id)
    return True


def apply_lifecycle(db,current):
    """Admission also checks expiry, so an unavailable worker cannot renew access."""
    if current.plan_slug=='free' or current.period_end>now():return
    contract=db.scalar(select(BillingProviderOperation).where(BillingProviderOperation.kind=='subscription',
        BillingProviderOperation.provider_id==current.provider_subscription_id)) if current.provider_subscription_id else None
    cancelled=bool(current.pending_plan_slug=='free' or (contract and contract.state in {'cancelled','completed','expired'}))
    grace=gst.business()['dunning_grace_days']
    if not cancelled:
        if not current.dunning_at:current.dunning_at=current.period_end
        current.state='past_due'
        deadline=current.dunning_at+timedelta(days=grace)
        if now()<deadline:return # Read/export grace; new cost is blocked below.
    workspace=db.get(Workspace,current.workspace_id)
    current.plan_slug='free';current.state='free';current.pending_plan_slug=None
    current.period_start,current.period_end=plans.month_bounds(now(),workspace.timezone)
    money.financial_event(db,current.workspace_id,'downgrade:'+str(current.provider_subscription_id)+':'+current.period_start.isoformat(),
        'subscription_downgraded',{'plan':'free','reason':'cancelled' if cancelled else 'dunning_expired'},current.provider_subscription_id)
    billing_events.owner_alert(db,current.workspace_id,'subscription-downgraded:'+str(current.provider_subscription_id)+':'+current.period_start.isoformat(),
        'Workspace moved to Free','Your paid subscription coverage ended. The workspace now follows Free plan allowances. Your data remains available for export and review.')


def maintenance():
    with session_scope(write=True) as db:
        rows=list(db.scalars(select(WorkspaceSubscription).where(WorkspaceSubscription.plan_slug!='free',
            WorkspaceSubscription.period_end<=now()).order_by(WorkspaceSubscription.maintenance_at.asc().nullsfirst(),WorkspaceSubscription.period_end).limit(100)))
        for current in rows:
            money.lock(db,current.workspace_id)
            current=db.scalar(select(WorkspaceSubscription).where(WorkspaceSubscription.id==current.id).with_for_update().execution_options(populate_existing=True))
            current.maintenance_at=now()
            apply_lifecycle(db,current);money.refresh_block(db,current.workspace_id)
            if current.state=='past_due' and current.dunning_at:
                days=(now()-current.dunning_at).days
                for threshold in [0,3,6]:
                    if days>=threshold and threshold<gst.business()['dunning_grace_days']:
                        billing_events.owner_alert(db,current.workspace_id,'dunning:'+str(current.provider_subscription_id)+':'+current.dunning_at.isoformat()+':'+str(threshold),
                            'Subscription payment reminder','Your paid subscription coverage has expired. Review Billing and contact support to resolve payment. Data export remains available; new paid usage awaits a captured renewal charge.')

"""Scoped refund requests; stable provider idempotency and durable worker recovery."""
import asyncio
from datetime import timedelta
import hashlib
from fastapi import APIRouter,Depends,HTTPException,Request
from pydantic import Field
from sqlalchemy import select,func

from . import billing_events,billing_accounting as money
from .db import session_scope,now,as_dict
from .domain import owned,wallet_state,enqueue
from .models import PaymentOrder,PaymentRefund,PaymentDispute,Job
from .schemas import Input
from .security import principal,db_dependency,audit

router=APIRouter()


class RefundWrite(Input):
    amount_minor:int=Field(ge=1,le=10_000_000,strict=True)


@router.get('/v1/workspaces/{workspace_id}/payments/{order_id}/refunds')
def refunds(workspace_id:str,order_id:str,actor=Depends(principal),db=Depends(db_dependency,scope='function')):
    actor.require('billing:read');owned(db,PaymentOrder,workspace_id,order_id)
    return {'items':[as_dict(row) for row in db.scalars(select(PaymentRefund).where(
        PaymentRefund.workspace_id==workspace_id,PaymentRefund.order_id==order_id).order_by(PaymentRefund.created_at.desc()).limit(100))]}


@router.post('/v1/workspaces/{workspace_id}/payments/{order_id}/refunds',status_code=202)
def request_refund(workspace_id:str,order_id:str,body:RefundWrite,request:Request,actor=Depends(principal),db=Depends(db_dependency,scope='function')):
    actor.require('billing:write')
    return create_refund(db,workspace_id,order_id,body.amount_minor,request.headers.get('Idempotency-Key',''),actor)


def create_refund(db,workspace_id,order_id,amount_minor,key,actor,*,reviewed=False):
    money.lock(db,workspace_id)
    order=owned(db,PaymentOrder,workspace_id,order_id)
    if not key or len(key)>180:raise HTTPException(422,'Idempotency-Key required')
    row=db.scalar(select(PaymentRefund).where(PaymentRefund.workspace_id==workspace_id,PaymentRefund.operation_key==key))
    if row:
        if row.order_id!=order_id or row.amount_minor!=amount_minor:raise HTTPException(409,'Refund identity conflicts with its original request')
    else:
        if not order.provider_payment_id or not (order.captured_at or order.state=='credited'):raise HTTPException(409,'Only captured payments can be refunded')
        subscription_refund=billing_events.quote_for(db,order).get('purpose')=='subscription'
        if subscription_refund and not reviewed:raise HTTPException(409,'Subscription refund requests require billing review')
        if db.scalar(select(PaymentDispute.id).where(PaymentDispute.workspace_id==workspace_id,
            PaymentDispute.order_id==order_id,PaymentDispute.state.in_(money.DISPUTE_HELD))):
            raise HTTPException(409,'Resolve the open payment dispute before requesting a refund')
        committed=int(db.scalar(select(func.coalesce(func.sum(PaymentRefund.amount_minor),0)).where(
            PaymentRefund.workspace_id==workspace_id,PaymentRefund.order_id==order_id,
            PaymentRefund.state.in_(money.REFUND_HELD|{'processed'}))))
        if committed+amount_minor>order.amount_minor:raise HTTPException(409,'Refund exceeds the remaining captured amount')
        net=billing_events.proportional(order,amount_minor)
        if not reviewed and wallet_state(db,workspace_id)['available_minor']<net:raise HTTPException(409,'Only unspent available wallet credit can be refunded')
        row=PaymentRefund(workspace_id=workspace_id,order_id=order_id,operation_key=key,
                          amount_minor=amount_minor,reserved_net_minor=0 if subscription_refund else net,state='creating')
        db.add(row);db.flush()
        if subscription_refund:
            from .plans import subscription
            current=subscription(db,workspace_id);current.state='refund_review';current.billing_blocked=True
            from .models import BillingProviderOperation
            quote=billing_events.quote_for(db,order)
            contract=db.get(BillingProviderOperation,quote.get('contract_operation_id'))
            if not contract or contract.workspace_id!=workspace_id or not contract.provider_id:
                raise HTTPException(409,'Reconcile subscription identity before refund review')
            cancellation=BillingProviderOperation(workspace_id=workspace_id,operation_key='refund-cancel:'+row.id,
                kind='subscription_cancel',request_hash='False',state='creating',
                details={'subscription_operation_id':contract.id,'at_cycle_end':False})
            db.add(cancellation);db.flush()
            enqueue(db,workspace_id,'billing_subscription_cancel',{'operation_id':cancellation.id,'errors':0})
        db.add(row);db.flush();audit(db,actor,'payment.refund_requested',row.id,{'gross_minor':amount_minor})
    if row.state in money.REFUND_HELD:
        active=db.scalar(select(Job).where(Job.workspace_id==workspace_id,Job.kind=='billing_refund',Job.state.in_(['queued','running'])).where(
            Job.payload['refund_id'].as_string()==row.id))
        if not active:enqueue(db,workspace_id,'billing_refund',{'refund_id':row.id,'polls':0,'errors':0})
    return as_dict(row)


async def refund_job(job_id):
    from .job_control import get_job
    from .payment_routes import provider
    def load():
        with session_scope(write=True) as db:
            job=get_job(db,job_id);row=owned(db,PaymentRefund,job.workspace_id,job.payload['refund_id'])
            if row.state in {'processed','failed','superseded'}:return None
            order=owned(db,PaymentOrder,job.workspace_id,row.order_id)
            job.phase='reconciling_refund' if row.provider_refund_id else 'requesting_refund'
            row.state='submitted' if not row.provider_refund_id else row.state
            return job.workspace_id,row.id,order.id,order.provider_payment_id,row.provider_refund_id,row.amount_minor
    data=await asyncio.to_thread(load)
    if not data:return
    workspace_id,identity,order_id,payment_id,refund_id,amount=data
    try:
        if refund_id:result=await provider('GET','/refunds/'+refund_id)
        else:
            result=await provider('POST','/payments/'+payment_id+'/refund',
                headers={'X-Refund-Idempotency':identity},
                json={'amount':amount,'speed':'normal','receipt':identity,'notes':{'studio_refund_receipt':identity}})
        if result.get('payment_id')!=payment_id or result.get('amount')!=amount:raise HTTPException(409,'Provider refund response conflicts with its request')
        def save():
            with session_scope(write=True) as db:
                job=get_job(db,job_id);money.lock(db,workspace_id)
                row=billing_events.refund(db,result,None,'refund-result:'+identity+':'+str(job.attempts),local_refund_id=identity)
                if row.state in money.REFUND_HELD:
                    polls=job.payload.get('polls',0)+1
                    if polls>64:raise RuntimeError('Refund still pending; operator reconciliation required')
                    job.payload={**job.payload,'polls':polls,'errors':0}
                    job.state='queued';job.available_at=now()+timedelta(seconds=min(21600,60*2**min(polls,9)))
                job.result={'refund_id':identity,'provider_state':row.state}
        await asyncio.to_thread(save)
    except asyncio.CancelledError:raise
    except Exception:
        def retry():
            with session_scope(write=True) as db:
                job=get_job(db,job_id);row=owned(db,PaymentRefund,workspace_id,identity)
                if row.state=='processed':return
                row.state='unknown';errors=job.payload.get('errors',0)+1
                job.payload={**job.payload,'errors':errors}
                if errors<8:
                    job.state='queued';job.available_at=now()+timedelta(seconds=min(3600,30*2**errors));job.phase='refund_retry'
                return errors>=8
        if await asyncio.to_thread(retry):raise RuntimeError('Refund outcome requires provider reconciliation') from None

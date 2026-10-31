"""Razorpay top-ups: captured server-verified payment is the only credit trigger."""
import hashlib
import asyncio
import hmac
import json
import httpx
from fastapi import APIRouter,Depends,Request,HTTPException
from pydantic import Field
from sqlalchemy import select
from .config import settings
from .db import session_scope,uid,as_dict
from .models import PaymentOrder,Workspace
from .schemas import Input
from .security import principal,db_dependency,audit
from .domain import post_ledger

router=APIRouter()


class Topup(Input):
    amount_minor:int=Field(ge=10000,le=10000000)
    quote_token:str=Field(default='',max_length=5000)


class PaymentProof(Input):
    razorpay_order_id:str=Field(max_length=100)
    razorpay_payment_id:str=Field(max_length=100)
    razorpay_signature:str=Field(pattern=r'^[0-9a-fA-F]{64}$')


def configured():
    from .plans import catalog
    if not settings.paid_activation_enabled or catalog()['status']!='APPROVED':
        raise HTTPException(409,'Paid activation is disabled pending approved prices')
    if not settings.capabilities()['payments']:raise HTTPException(409,'Payment checkout is not configured')
    from .gst import business
    if business()['status']!='APPROVED':raise HTTPException(409,'Invoice business details require approval before checkout')


def order_record(row):
    kind='wallet'
    if row.encrypted_snapshot:
        from .secrets import decrypt
        try:kind=json.loads(decrypt(row.encrypted_snapshot)).get('purpose','wallet')
        except (ValueError,KeyError):kind='needs_review'
    return {**{key:value for key,value in as_dict(row).items() if not key.startswith('encrypted_')},'kind':kind}


async def provider(method,path,**kwargs):
    async with httpx.AsyncClient(timeout=20,auth=settings.razorpay_credentials()) as client:
        response=await client.request(method,'https://api.razorpay.com/v1'+path,**kwargs)
        if response.status_code>=400:raise HTTPException(502,'Payment provider rejected this request; no credit was posted')
        return response.json()


def credit_capture(db,payment):
    from .billing_events import capture
    try:return capture(db,payment)
    except LookupError:raise HTTPException(404,'Payment order not found') from None


@router.get('/v1/workspaces/{workspace_id}/payments')
def payments(workspace_id:str,actor=Depends(principal),db=Depends(db_dependency,scope='function')):
    actor.require('billing:read')
    return {'items':[order_record(x) for x in db.scalars(select(PaymentOrder).where(PaymentOrder.workspace_id==workspace_id).order_by(PaymentOrder.created_at.desc()).limit(200))]}


@router.post('/v1/workspaces/{workspace_id}/payments/orders',status_code=201)
async def order(workspace_id:str,body:Topup,request:Request,actor=Depends(principal),db=Depends(db_dependency,scope='function')):
    actor.require('billing:write')
    key=request.headers.get('Idempotency-Key','')
    if not key or len(key)>180:raise HTTPException(422,'Idempotency-Key required')
    db.scalar(select(Workspace).where(Workspace.id==workspace_id).with_for_update())
    row=db.scalar(select(PaymentOrder).where(PaymentOrder.workspace_id==workspace_id,PaymentOrder.operation_key==key))
    if row:
        from .secrets import decrypt
        original=json.loads(decrypt(row.encrypted_snapshot))['requested_amount_minor'] if row.encrypted_snapshot else row.amount_minor
        if original!=body.amount_minor:raise HTTPException(409,'Idempotency key conflicts with existing amount')
        if not row.provider_order_id:raise HTTPException(409,'Previous order outcome requires reconciliation; do not retry with a new key')
    else:
        configured()
        from .billing_quote import authorize
        from .secrets import encrypt
        quoted=authorize(db,workspace_id,body.amount_minor,body.quote_token)
        saved=quoted['quote'];total=saved['tax']['gross_minor']
        row=PaymentOrder(workspace_id=workspace_id,amount_minor=total,net_minor=saved['tax']['net_minor'],operation_key=key,
                         quote_hash=quoted['quote_hash'],encrypted_snapshot=encrypt(json.dumps(saved)))
        db.add(row);db.flush();db.commit()  # Persist the receipt before a possibly-ambiguous network write.
        try:
            result=await provider('POST','/orders',json={'amount':total,'currency':'INR','receipt':row.id})
            if result.get('amount')!=total or result.get('currency')!='INR':raise HTTPException(502,'Unexpected payment order response')
            from .billing_events import identifier
            identifier(result.get('id'))
            row.provider_order_id,row.state=result['id'],'created';audit(db,actor,'payment.order_created',row.id)
        except Exception:
            row.state='unknown';db.commit();raise
    return {**order_record(row),'key_id':settings.razorpay_credentials()[0]}


@router.post('/v1/workspaces/{workspace_id}/payments/verify')
async def verify(workspace_id:str,body:PaymentProof,actor=Depends(principal),db=Depends(db_dependency,scope='function')):
    actor.require('billing:write')
    if not all(settings.razorpay_credentials()):raise HTTPException(409,'Payment reconciliation credentials are not configured')
    order=db.scalar(select(PaymentOrder).where(PaymentOrder.workspace_id==workspace_id,PaymentOrder.provider_order_id==body.razorpay_order_id))
    if not order:raise HTTPException(404,'Payment order not found')
    expected=hmac.new(settings.razorpay_credentials()[1].encode(),(order.provider_order_id+'|'+body.razorpay_payment_id).encode(),hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected,body.razorpay_signature.lower()):raise HTTPException(401,'Payment signature is invalid')
    payment=await provider('GET','/payments/'+body.razorpay_payment_id)
    if payment.get('order_id')!=order.provider_order_id:raise HTTPException(409,'Payment belongs to a different order')
    return order_record(credit_capture(db,payment))


@router.post('/v1/provider-webhooks/razorpay')
async def webhook(request:Request):
    body=await request.body()
    from .billing_inbox import accept
    return await asyncio.to_thread(accept,body,request.headers.get('X-Razorpay-Event-Id',''),request.headers.get('X-Razorpay-Signature',''))

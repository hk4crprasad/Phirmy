"""Fast signed webhook admission and leased background financial reconciliation."""
import asyncio
from datetime import datetime,timedelta,timezone
import hashlib
import hmac
import json

from fastapi import HTTPException
from sqlalchemy import select,update
from sqlalchemy.exc import IntegrityError

from .config import settings
from .db import now,session_scope,uid
from .models import BillingWebhookInbox,PaymentOrder
from .secrets import encrypt,decrypt
from . import billing_events


def verify_signature(body,signature):
    import re
    if not isinstance(signature,str) or not re.fullmatch('[0-9a-fA-F]{64}',signature):raise HTTPException(401,'Invalid payment webhook signature')
    signature=signature.lower()
    secrets=[settings.razorpay_webhook_secret] if settings.razorpay_webhook_secret else []
    if settings.razorpay_webhook_previous_secrets_json:
        try:
            previous=json.loads(settings.razorpay_webhook_previous_secrets_json)
            if not isinstance(previous,list) or len(previous)>3:raise ValueError()
            for item in previous:
                expiry=datetime.fromisoformat(item['valid_until'])
                if expiry.tzinfo is None or not isinstance(item['secret'],str) or not item['secret']:raise ValueError()
                if expiry>now():secrets.append(item['secret'])
        except (KeyError,TypeError,ValueError):raise HTTPException(503,'Payment signature configuration requires review') from None
    if not secrets:raise HTTPException(503,'Payment webhook is not configured')
    matches=[hmac.compare_digest(hmac.new(secret.encode(),body,hashlib.sha256).hexdigest(),signature) for secret in secrets]
    if not any(matches):raise HTTPException(401,'Invalid payment webhook signature')


def accept(body,event_id,signature):
    if len(body)>1_000_000:raise HTTPException(413,'Webhook too large')
    verify_signature(body,signature)
    if not event_id or len(event_id)>200 or any(ord(value)<33 or ord(value)>126 for value in event_id):
        raise HTTPException(422,'X-Razorpay-Event-Id is required')
    try:
        event=json.loads(body)
        if not isinstance(event,dict) or not isinstance(event.get('event'),str) or len(event['event'])>100 or not isinstance(event.get('payload'),dict):raise ValueError()
    except (ValueError,UnicodeDecodeError):raise HTTPException(422,'Invalid payment webhook body') from None
    digest=hashlib.sha256(body).hexdigest()
    with session_scope(write=True) as db:
        row=db.scalar(select(BillingWebhookInbox).where(BillingWebhookInbox.provider_event_id==event_id))
        if not row:
            try:
                with db.begin_nested():
                    row=BillingWebhookInbox(provider_event_id=event_id,payload_hash=digest,encrypted_payload=encrypt(body.decode()))
                    db.add(row);db.flush()
            except IntegrityError:row=db.scalar(select(BillingWebhookInbox).where(BillingWebhookInbox.provider_event_id==event_id))
        if row.payload_hash!=digest:raise HTTPException(409,'Webhook identity conflicts with its original payload')
        return {'status':'acknowledged','receipt_id':row.id}


def claim():
    with session_scope(write=True) as db:
        row=db.scalar(select(BillingWebhookInbox).where(BillingWebhookInbox.state.in_(['pending','processing']),
            BillingWebhookInbox.next_attempt_at<=now()).order_by(BillingWebhookInbox.created_at,BillingWebhookInbox.id).limit(1).with_for_update(skip_locked=True))
        if not row:return None
        row.state='processing';row.attempts+=1;row.lease_token=uid();row.next_attempt_at=now()+timedelta(minutes=3)
        return row.id,row.lease_token,row.attempts,row.provider_event_id,row.encrypted_payload


def entity(event,name):
    value=event.get('payload',{}).get(name,{})
    candidate=value.get('entity') if isinstance(value,dict) else None
    return candidate if isinstance(candidate,dict) else None


async def resolve(event):
    name=event['event']
    payment=entity(event,'payment')
    reversal=entity(event,'refund') if name.startswith('refund.') else entity(event,'dispute') if name.startswith('payment.dispute.') else None
    if reversal:
        payment_id=billing_events.identifier(reversal.get('payment_id'))
        def known():
            with session_scope() as db:return bool(db.scalar(select(PaymentOrder.id).where(PaymentOrder.provider_payment_id==payment_id)))
        if (not payment or payment.get('status')!='captured') and not await asyncio.to_thread(known):
            from .payment_routes import provider
            payment=await provider('GET','/payments/'+payment_id)
            if payment.get('id')!=payment_id:raise HTTPException(409,'Reconciled payment identity mismatch')
    return payment


def apply(identity,lease,event_id,event,payment):
    event_id=hashlib.sha256(event_id.encode()).hexdigest()
    with session_scope(write=True) as db:
        receipt=db.scalar(select(BillingWebhookInbox).where(BillingWebhookInbox.id==identity,BillingWebhookInbox.lease_token==lease))
        if not receipt or receipt.state!='processing':return False
        name=event['event'];recognized=True
        if name in {'payment.captured','order.paid'}:
            if not payment:raise HTTPException(422,'Payment snapshot missing')
            billing_events.capture(db,payment)
        elif name=='payment.failed':
            if not payment:raise HTTPException(422,'Payment snapshot missing')
            recognized=billing_events.failed(db,payment)
        elif name.startswith('refund.'):
            refund=entity(event,'refund')
            if not refund:raise HTTPException(422,'Refund snapshot missing')
            billing_events.refund(db,refund,payment,event_id)
        elif name.startswith('payment.dispute.'):
            dispute=entity(event,'dispute')
            if not dispute:raise HTTPException(422,'Dispute snapshot missing')
            stamp=event.get('created_at')
            if type(stamp) is not int or stamp<0:raise HTTPException(422,'Dispute event timestamp missing')
            billing_events.dispute(db,dispute,payment,event_id,stamp,name)
        elif name.startswith('subscription.'):
            # Implemented by the subscription adapter; the durable receipt is
            # retained if deployment races ahead of its migration/configuration.
            from .billing_subscriptions import apply_event
            recognized=apply_event(db,event,event_id,payment)
        else:recognized=False
        changed=db.execute(update(BillingWebhookInbox).where(BillingWebhookInbox.id==identity,
            BillingWebhookInbox.lease_token==lease,BillingWebhookInbox.state=='processing').values(
            state='processed' if recognized else 'ignored',lease_token=None,error_code=None))
        if not changed.rowcount:raise RuntimeError('Billing inbox lease lost') # Rolls back every financial write.
        return True


def failure(identity,lease,attempt,category,*,ignored=False):
    with session_scope(write=True) as db:
        db.execute(update(BillingWebhookInbox).where(BillingWebhookInbox.id==identity,BillingWebhookInbox.lease_token==lease).values(
            state='ignored' if ignored else 'failed' if attempt>=8 else 'pending',lease_token=None,error_code=category,
            next_attempt_at=now()+timedelta(seconds=min(3600,30*2**min(attempt-1,7)))))


async def process_inbox(limit=4):
    processed=0
    for _ in range(limit):
        claimed=await asyncio.to_thread(claim)
        if not claimed:break
        identity,lease,attempt,event_id,ciphertext=claimed
        try:
            event=json.loads(decrypt(ciphertext));payment=await resolve(event)
            if await asyncio.to_thread(apply,identity,lease,event_id,event,payment):processed+=1
        except LookupError:
            await asyncio.to_thread(failure,identity,lease,attempt,'unmatched_payment')
        except asyncio.CancelledError:raise # Lease expires; no financial result is guessed.
        except Exception:
            await asyncio.to_thread(failure,identity,lease,attempt,'reconciliation_failed')
    return processed

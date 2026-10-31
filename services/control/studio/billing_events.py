"""Verified provider snapshots -> monotonic state and immutable accounting.

No checkout activation flag is consulted while reconciling earlier payments.
"""
from datetime import datetime,timezone
import json
import re
from fastapi import HTTPException
from sqlalchemy import select,func

from . import billing_accounting as money,gst
from .db import now
from .models import (PaymentOrder,PaymentRefund,PaymentDispute,Workspace,User,Membership,Invoice)
from .secrets import decrypt
from .mail_outbox import enqueue_email
from .invoices import issue


def integer(value,name,minimum=0):
    if type(value) is not int or not minimum<=value<=1_000_000_000:raise HTTPException(422,'Invalid payment '+name)
    return value


def identifier(value):
    if not isinstance(value,str) or not re.fullmatch('[A-Za-z0-9_-]{1,100}',value):raise HTTPException(422,'Invalid provider identity')
    return value


def owner_alert(db,workspace_id,key,subject,body):
    for recipient in db.scalars(select(User.email).join(Membership,Membership.user_id==User.id).where(
        Membership.workspace_id==workspace_id,Membership.role=='owner')):
        from .metering import operation
        enqueue_email(db,recipient,subject,body,operation_key=key+':'+operation(recipient))


def order_for(db,payment=None,payment_id=None):
    query=select(PaymentOrder)
    if payment_id:query=query.where(PaymentOrder.provider_payment_id==payment_id)
    elif payment and payment.get('order_id'):query=query.where(PaymentOrder.provider_order_id==payment['order_id'])
    else:return None
    hint=db.scalar(query)
    if not hint:return None
    money.lock(db,hint.workspace_id)
    order=db.scalar(select(PaymentOrder).where(PaymentOrder.id==hint.id).with_for_update().execution_options(populate_existing=True))
    from .models import Wallet
    if order.currency!='INR' or db.get(Workspace,order.workspace_id).currency!=order.currency or db.scalar(select(Wallet.currency).where(Wallet.workspace_id==order.workspace_id))!=order.currency:
        raise HTTPException(409,'Payment currency requires billing reconciliation')
    return order


def quote_for(db,order):
    if order.encrypted_snapshot:return json.loads(decrypt(order.encrypted_snapshot))
    # Old wallet captures have no established GST snapshot. Never invent a final
    # tax invoice from today's business details or retroactively add GST.
    seller={**gst.business(),'status':'DRAFT','payment_terms':'DRAFT: legacy payment tax treatment requires review'}
    workspace=db.get(Workspace,order.workspace_id)
    email=db.scalar(select(User.email).join(Membership,Membership.user_id==User.id).where(
        Membership.workspace_id==order.workspace_id,Membership.role=='owner').order_by(User.id)) or ''
    return {'seller':seller,'buyer':{'legal_name':workspace.name,'address':'DRAFT: billing address not recorded',
        'state_code':seller['state_code'],'gstin':'','email':email},'price_status':'DRAFT','payment_mode':'legacy',
        'authorized_paid':False,'description':'Legacy wallet payment receipt',
        'tax':{'net_minor':order.amount_minor,'gross_minor':order.amount_minor,'tax_minor':0,
               'cgst_minor':0,'sgst_minor':0,'igst_minor':0,'gst_rate_basis_points':0,
               'place_of_supply':seller['state_code'],'sac':seller['sac'],'prices_include_gst':False}}


def capture(db,payment,order=None):
    order=order or order_for(db,payment)
    if not order:raise LookupError('unmatched_payment')
    money.lock(db,order.workspace_id)
    from .models import Wallet
    if order.currency!='INR' or db.get(Workspace,order.workspace_id).currency!=order.currency or db.scalar(select(Wallet.currency).where(Wallet.workspace_id==order.workspace_id))!=order.currency:
        raise HTTPException(409,'Payment currency requires billing reconciliation')
    payment_id=identifier(payment.get('id'))
    integer(payment.get('amount'),'captured amount',1)
    if payment.get('status')!='captured' or payment.get('amount')!=order.amount_minor or payment.get('currency')!=order.currency:
        raise HTTPException(409,'Payment is not captured for its admitted amount/currency')
    if order.provider_payment_id and order.provider_payment_id!=payment_id:raise HTTPException(409,'Order already bound to another payment')
    if order.captured_at or order.state=='credited':
        if not order.captured_at:order.captured_at=now()
        return order
    net=order.net_minor if order.net_minor is not None else order.amount_minor
    quote=quote_for(db,order)
    extra={'order_id':order.id,'gross_minor':order.amount_minor,'quote_hash':order.quote_hash,
           'provider_fee_minor':payment.get('fee') if type(payment.get('fee')) is int else None}
    operation_key='razorpay:'+(order.provider_order_id or payment_id)
    if quote.get('purpose') in {'subscription','subscription_authorization'}:
        authorization=quote['purpose']=='subscription_authorization'
        money.financial_event(db,order.workspace_id,operation_key,'subscription_authorization' if authorization else 'subscription_fee',
                              {'net_minor':net,'revenue_delta_minor':0 if authorization else net,**extra},payment_id)
    else:money.credit(db,order.workspace_id,net,operation_key,provider_id=payment_id,
                      extra=extra)
    order.provider_payment_id=payment_id;order.captured_at=now();order.state='credited'
    if quote.get('purpose')!='subscription_authorization':issue(db,order.workspace_id,'capture:'+payment_id,quote,payment_id)
    return order


def failed(db,payment):
    order=order_for(db,payment)
    if not order:return False
    payment_id=identifier(payment.get('id'))
    key='payment-failed:'+payment_id
    if not money.previous(db,order.workspace_id,key):
        money.financial_event(db,order.workspace_id,key,'payment_failed',{'order_id':order.id},payment_id)
        if not order.captured_at and order.state!='credited':order.state='failed'
        owner_alert(db,order.workspace_id,key,'Payment failed',
            'A payment attempt failed. No credit was posted for this attempt. Review Billing before trying again.')
    return True


def proportional(order,gross):
    net=order.net_minor if order.net_minor is not None else order.amount_minor
    return gst.round_ratio(gross*net,order.amount_minor)


def reconcile_reversal(db,order,event_key):
    refunds=order.refunded_net_minor
    lost=int(db.scalar(select(func.coalesce(func.sum(PaymentDispute.deducted_net_minor),0)).where(
        PaymentDispute.workspace_id==order.workspace_id,PaymentDispute.order_id==order.id)))
    net=order.net_minor if order.net_minor is not None else order.amount_minor
    target=min(net,refunds+lost);difference=target-order.reversed_net_minor
    extra={'order_id':order.id,'refunded_net_minor':refunds,'disputed_net_minor':lost}
    quote=quote_for(db,order)
    if quote.get('purpose') in {'subscription','subscription_authorization'}:
        if difference:
            money.financial_event(db,order.workspace_id,'subscription-reversal:'+event_key,'subscription_reversal',
                {'net_minor':abs(difference),'revenue_delta_minor':-difference if quote['purpose']=='subscription' else 0,**extra},order.provider_payment_id)
        from .models import WorkspaceSubscription
        current=db.scalar(select(WorkspaceSubscription).where(WorkspaceSubscription.workspace_id==order.workspace_id))
        if target and current and current.provider_subscription_id==quote.get('subscription_id') and current.period_start.isoformat()==quote.get('period_start'):
            current.state='refund_review'
        elif not target and current and current.provider_subscription_id==quote.get('subscription_id') and current.state=='refund_review' and current.period_end>now():
            current.state='active'
    elif difference>0:money.debit(db,order.workspace_id,difference,'order-reversal:'+event_key,
        provider_id=order.provider_payment_id,extra=extra)
    elif difference<0:money.credit(db,order.workspace_id,-difference,'order-restoration:'+event_key,
        provider_id=order.provider_payment_id,kind='payment_restoration',extra=extra)
    order.reversed_net_minor=target
    remaining=max(0,net-target)
    for risk in db.scalars(select(PaymentDispute).where(PaymentDispute.workspace_id==order.workspace_id,
        PaymentDispute.order_id==order.id,PaymentDispute.state.in_(money.DISPUTE_HELD)).order_by(PaymentDispute.id)):
        risk.risk_net_minor=min(proportional(order,risk.amount_minor),remaining);remaining-=risk.risk_net_minor
    db.flush();money.refresh_block(db,order.workspace_id)


def refund(db,entity,payment,event_key,local_refund_id=None):
    refund_id=identifier(entity.get('id'));payment_id=identifier(entity.get('payment_id'))
    order=order_for(db,payment_id=payment_id) or order_for(db,payment)
    if not order:raise LookupError('unmatched_refund')
    if order.provider_payment_id!=payment_id:
        if payment and payment.get('id')==payment_id and payment.get('status')=='captured':order=capture(db,payment)
        else:raise LookupError('capture_reconciliation_required')
    amount=integer(entity.get('amount'),'refund amount',1)
    if amount>order.amount_minor or entity.get('currency')!=order.currency:raise HTTPException(409,'Refund amount/currency conflicts with payment')
    row=db.scalar(select(PaymentRefund).where(PaymentRefund.provider_refund_id==refund_id))
    notes=entity.get('notes') if isinstance(entity.get('notes'),dict) else {}
    local=local_refund_id or entity.get('receipt') or notes.get('studio_refund_receipt')
    candidate=db.get(PaymentRefund,local) if isinstance(local,str) and len(local)<=40 else None
    if candidate:
        if candidate.workspace_id!=order.workspace_id or candidate.order_id!=order.id or candidate.amount_minor!=amount:
            raise HTTPException(409,'Refund receipt conflicts with its admitted payment')
        if candidate.provider_refund_id and candidate.provider_refund_id!=refund_id:raise HTTPException(409,'Refund receipt already has another provider identity')
        if row and row.id!=candidate.id and candidate.state!='superseded':
            # A webhook may beat the POST response without carrying its receipt.
            # Move the mutable projection binding; immutable postings stay keyed
            # to the original provider refund identity and are never replayed.
            prior_id=row.id;state,held=row.state,row.reserved_net_minor
            row.provider_refund_id=None;row.state='superseded';row.reserved_net_minor=0;db.flush()
            candidate.provider_refund_id=refund_id;candidate.state=state;candidate.reserved_net_minor=held;row=candidate
            money.financial_event(db,order.workspace_id,'refund-link:'+refund_id,'refund_receipt_linked',
                {'source_receipt_id':prior_id,'request_receipt_id':candidate.id},refund_id)
        elif not row:
            candidate.provider_refund_id=refund_id;row=candidate
    if row and (row.order_id!=order.id or row.amount_minor!=amount):raise HTTPException(409,'Refund identity conflicts with its original payment')
    if not row:
        row=PaymentRefund(workspace_id=order.workspace_id,order_id=order.id,operation_key='provider:'+refund_id,
                          provider_refund_id=refund_id,amount_minor=amount,reserved_net_minor=proportional(order,amount))
        db.add(row);db.flush()
    if row.state=='processed':return row
    status=entity.get('status')
    if status=='processed':
        previous_tax=order.refunded_gross_minor-order.refunded_net_minor
        total=order.refunded_gross_minor+amount
        if total>order.amount_minor:raise HTTPException(409,'Processed refunds exceed the captured payment')
        refund_net=proportional(order,total);net_delta=refund_net-order.refunded_net_minor
        row.state='processed';row.reserved_net_minor=0
        order.refunded_gross_minor=total;order.refunded_net_minor=refund_net
        order.state='refunded' if total==order.amount_minor else 'partially_refunded'
        money.financial_event(db,order.workspace_id,'refund-processed:'+refund_id,'refund_processed',
            {'order_id':order.id,'gross_minor':amount,'net_minor':net_delta},refund_id)
        reconcile_reversal(db,order,event_key)
        quote=quote_for(db,order);tax=quote['tax'];tax_delta=amount-net_delta
        intra=bool(tax['cgst_minor'] or tax['sgst_minor'])
        cumulative_tax=total-refund_net
        cgst_delta=cumulative_tax//2-previous_tax//2 if intra else 0
        quote={**quote,'tax':{**tax,'gross_minor':amount,'net_minor':net_delta,'tax_minor':tax_delta,
            'cgst_minor':cgst_delta,'sgst_minor':tax_delta-cgst_delta if intra else 0,
            'igst_minor':0 if intra else tax_delta},'description':'Payment refund credit note'}
        original=db.scalar(select(Invoice).where(Invoice.workspace_id==order.workspace_id,Invoice.operation_key=='capture:'+payment_id))
        if quote.get('purpose')!='subscription_authorization':
            issue(db,order.workspace_id,'refund:'+refund_id,quote,refund_id,kind='credit_note',original_number=original.number if original else None)
    elif status=='failed':
        row.state='failed';row.reserved_net_minor=0
        owner_alert(db,order.workspace_id,'refund-failed:'+refund_id,'Refund failed',
            'The provider could not process a refund. No completed refund was recorded. Review Billing.')
    elif status in {'pending','created'}:row.state=status
    else:raise HTTPException(422,'Unknown provider refund state')
    db.flush();return row


def dispute(db,entity,payment,event_key,event_time,event_type):
    identity=identifier(entity.get('id'));payment_id=identifier(entity.get('payment_id'))
    order=order_for(db,payment_id=payment_id) or order_for(db,payment)
    if not order:raise LookupError('unmatched_dispute')
    if order.provider_payment_id!=payment_id:
        if payment and payment.get('id')==payment_id and payment.get('status')=='captured':order=capture(db,payment)
        else:raise LookupError('capture_reconciliation_required')
    amount=integer(entity.get('amount'),'dispute amount',1)
    if amount>order.amount_minor or entity.get('currency')!=order.currency:raise HTTPException(409,'Dispute amount/currency conflicts with payment')
    row=db.scalar(select(PaymentDispute).where(PaymentDispute.provider_dispute_id==identity))
    if row and (row.order_id!=order.id or row.amount_minor!=amount):raise HTTPException(409,'Dispute identity conflicts with its payment')
    status=entity.get('status')
    if status=='open' and event_type=='payment.dispute.action_required':status='action_required'
    ranks={'open':0,'action_required':0,'under_review':1,'closed':2,'lost':3,'won':4}
    if status not in ranks:raise HTTPException(422,'Unknown provider dispute state')
    if row and (event_time<row.last_event_at or (event_time==row.last_event_at and ranks[status]<ranks[row.state])):return row
    if not row:
        row=PaymentDispute(workspace_id=order.workspace_id,order_id=order.id,provider_dispute_id=identity,
                           amount_minor=amount,deducted_net_minor=0,risk_net_minor=0,state='open',last_event_at=0)
        db.add(row);db.flush()
    deducted=integer(entity.get('amount_deducted',0),'dispute deducted amount')
    if deducted>amount:raise HTTPException(409,'Dispute deduction exceeds disputed amount')
    row.state=status;row.last_event_at=event_time
    row.deducted_net_minor=proportional(order,deducted or amount) if status=='lost' or (status=='closed' and deducted) else 0
    row.risk_net_minor=proportional(order,amount) if status in money.DISPUTE_HELD else 0
    money.financial_event(db,order.workspace_id,'dispute:'+event_key,'dispute_state',
        {'order_id':order.id,'state':status,'gross_minor':amount,'amount_deducted_minor':deducted,'event_time':event_time},identity)
    reconcile_reversal(db,order,event_key)
    owner_alert(db,order.workspace_id,'dispute-state:'+identity+':'+status,'Payment dispute updated',
        'A payment dispute is '+status.replace('_',' ')+'. Review Billing. Open disputes restrict new workspace spending until resolved.')
    return row

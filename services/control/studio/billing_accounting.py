"""Append-only payment adjustments and nonnegative wallet/debt accounting."""
from fastapi import HTTPException
from sqlalchemy import select,func
from .db import now
from .models import (Workspace,Wallet,BillingAccount,BillingFinancialEvent,PaymentRefund,
                     PaymentDispute,WorkspaceSubscription)
from .domain import post_ledger,wallet_state

REFUND_HELD={'creating','unknown','submitted','created','pending'}
DISPUTE_HELD={'open','under_review','action_required'}


def lock(db,workspace_id):
    if not db.scalar(select(Workspace).where(Workspace.id==workspace_id).with_for_update()):raise HTTPException(404,'Workspace not found')


def account(db,workspace_id):
    lock(db,workspace_id)
    row=db.scalar(select(BillingAccount).where(BillingAccount.workspace_id==workspace_id))
    if not row:row=BillingAccount(workspace_id=workspace_id,debt_minor=0);db.add(row);db.flush()
    return row


def financial_event(db,workspace_id,operation_key,kind,details,provider_id=None):
    lock(db,workspace_id)
    previous=db.scalar(select(BillingFinancialEvent).where(BillingFinancialEvent.workspace_id==workspace_id,
        BillingFinancialEvent.operation_key==operation_key))
    if previous:
        if (previous.kind,previous.details,previous.provider_id)!=(kind,details,provider_id):
            raise HTTPException(409,'Financial event conflicts with its original posting')
        return previous
    row=BillingFinancialEvent(workspace_id=workspace_id,operation_key=operation_key,kind=kind,details=details,provider_id=provider_id)
    db.add(row);db.flush();return row


def previous(db,workspace_id,key):
    return db.scalar(select(BillingFinancialEvent).where(BillingFinancialEvent.workspace_id==workspace_id,BillingFinancialEvent.operation_key==key))


def risk_total(db,workspace_id):
    refunds=int(db.scalar(select(func.coalesce(func.sum(PaymentRefund.reserved_net_minor),0)).where(
        PaymentRefund.workspace_id==workspace_id,PaymentRefund.state.in_(REFUND_HELD))))
    disputes=int(db.scalar(select(func.coalesce(func.sum(PaymentDispute.risk_net_minor),0)).where(
        PaymentDispute.workspace_id==workspace_id,PaymentDispute.state.in_(DISPUTE_HELD))))
    return refunds+disputes


def refresh_block(db,workspace_id):
    current=db.scalar(select(WorkspaceSubscription).where(WorkspaceSubscription.workspace_id==workspace_id))
    if current:
        debt=db.scalar(select(BillingAccount.debt_minor).where(BillingAccount.workspace_id==workspace_id)) or 0
        disputes=db.scalar(select(func.count()).select_from(PaymentDispute).where(PaymentDispute.workspace_id==workspace_id,
            PaymentDispute.state.in_(DISPUTE_HELD)))
        due=current.plan_slug!='free' and current.state in {'past_due','pending','halted','payment_pending'} and current.period_end<=now()
        current.billing_blocked=bool(debt or disputes or due or current.state=='refund_review')


def credit(db,workspace_id,amount,key,*,provider_id=None,kind='wallet_funding',extra=None):
    if type(amount) is not int or amount<0:raise ValueError('Invalid credit amount')
    owner=account(db,workspace_id);existing=previous(db,workspace_id,key)
    if existing:
        if existing.details['net_minor']!=amount:raise HTTPException(409,'Credit conflicts with its original amount')
        return existing
    covered=min(owner.debt_minor,amount);owner.debt_minor-=covered;available=amount-covered
    if available:post_ledger(db,workspace_id,available,key,'Server-verified payment credit')
    result=financial_event(db,workspace_id,key,kind,{'net_minor':amount,'wallet_delta_minor':available,
        'debt_delta_minor':-covered,**(extra or {})},provider_id)
    refresh_block(db,workspace_id);return result


def debit(db,workspace_id,amount,key,*,provider_id=None,kind='payment_reversal',extra=None):
    if type(amount) is not int or amount<0:raise ValueError('Invalid reversal amount')
    owner=account(db,workspace_id);existing=previous(db,workspace_id,key)
    if existing:
        if existing.details['net_minor']!=amount:raise HTTPException(409,'Reversal conflicts with its original amount')
        return existing
    wallet=db.scalar(select(Wallet).where(Wallet.workspace_id==workspace_id).with_for_update().execution_options(populate_existing=True))
    # Already-authorized calls and other pending reversals keep their backing.
    available=min(wallet_state(db,workspace_id)['available_minor'],amount);unfunded=amount-available
    if available:post_ledger(db,workspace_id,-available,key,'Server-verified payment reversal')
    owner.debt_minor+=unfunded
    result=financial_event(db,workspace_id,key,kind,{'net_minor':amount,'wallet_delta_minor':-available,
        'debt_delta_minor':unfunded,**(extra or {})},provider_id)
    refresh_block(db,workspace_id);return result


def settle_released_funds(db,workspace_id,key):
    owner=account(db,workspace_id)
    amount=min(owner.debt_minor,wallet_state(db,workspace_id)['available_minor'])
    if amount:
        post_ledger(db,workspace_id,-amount,key,'Released wallet funds applied to billing adjustment')
        owner.debt_minor-=amount
        financial_event(db,workspace_id,key,'adjustment_settlement',{'net_minor':amount,
            'wallet_delta_minor':-amount,'debt_delta_minor':-amount})
    refresh_block(db,workspace_id)

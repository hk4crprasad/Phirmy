"""Signed, expiring review of tax totals before any paid provider operation."""
import hashlib
import json
from fastapi import HTTPException
from sqlalchemy import select
from . import gst,plans
from .config import settings
from .models import WorkspaceSubscription,Workspace,User,Membership
from .security import capability,verify_capability


def profile(db,workspace_id,*,required=False):
    current=db.scalar(select(WorkspaceSubscription).where(WorkspaceSubscription.workspace_id==workspace_id))
    if current and current.billing_profile:
        try:
            parsed=gst.BillingProfile.model_validate(current.billing_profile).model_dump()
            if required and any(parsed[key].strip().upper().startswith('DRAFT:') for key in ['legal_name','address']):
                raise HTTPException(409,'Complete your actual billing name and address before checkout')
            return parsed
        except ValueError:
            if required:raise HTTPException(409,'Update your billing name, address, state and email before checkout') from None
    if required:raise HTTPException(409,'Complete your billing details before checkout')
    workspace=db.get(Workspace,workspace_id)
    email=db.scalar(select(User.email).join(Membership,Membership.user_id==User.id).where(
        Membership.workspace_id==workspace_id,Membership.role=='owner').order_by(User.id)) or ''
    return {'legal_name':workspace.name,'address':'DRAFT: complete billing address','state_code':gst.business()['state_code'],'gstin':'','email':email}


def preview(db,workspace_id,amount_minor,*,purpose='wallet',plan_slug=None):
    if db.get(Workspace,workspace_id).currency!='INR':raise HTTPException(409,'Paid billing currently supports INR workspaces')
    body=plans.catalog();seller=gst.business();buyer=profile(db,workspace_id)
    if purpose=='subscription':
        plan=body['plans'].get(plan_slug)
        if not plan or not plan['self_serve'] or plan['monthly_price_minor']<=0:raise HTTPException(409,'Choose a self-service paid plan')
        amount_minor=plan['monthly_price_minor']
    elif purpose!='wallet':raise ValueError('Invalid billing purpose')
    tax=gst.tax_lines(amount_minor,buyer['state_code'],seller)
    quote={'purpose':purpose,'plan_slug':plan_slug,'requested_amount_minor':amount_minor,'catalog_hash':body['content_hash'],'catalog_version':body['version'],
           'price_status':body['status'],'seller':seller,'buyer':buyer,'tax':tax,
           'payment_mode':settings.razorpay_mode,'authorized_paid':False,
           'description':('Voice Studio '+body['plans'][plan_slug]['name']+' monthly subscription') if purpose=='subscription' else 'Voice Studio wallet funding'}
    canonical=json.dumps(quote,sort_keys=True,separators=(',',':'))
    digest=hashlib.sha256(canonical.encode()).hexdigest()
    token=capability({'aud':'billing-quote','workspace_id':workspace_id,'purpose':purpose,'plan_slug':plan_slug,
                      'amount_minor':amount_minor,'quote_hash':digest},ttl=900)
    return {'quote':quote,'quote_hash':digest,'quote_token':token,
            'checkout_enabled':bool(settings.paid_activation_enabled and body['status']=='APPROVED' and seller['status']=='APPROVED' and settings.capabilities()['payments'])}


def authorize(db,workspace_id,amount_minor,quote_token,*,purpose='wallet',plan_slug=None):
    if not quote_token:raise HTTPException(409,'Review the full billing total before checkout')
    claims=verify_capability(quote_token,'billing-quote')
    current=preview(db,workspace_id,amount_minor,purpose=purpose,plan_slug=plan_slug)
    expected_amount=current['quote']['requested_amount_minor']
    if (claims.get('workspace_id'),claims.get('purpose'),claims.get('plan_slug'),claims.get('amount_minor'),claims.get('quote_hash'))!=(
        workspace_id,purpose,plan_slug,expected_amount,current['quote_hash']):
        raise HTTPException(409,'Billing details or prices changed. Review the revised total.')
    if not current['checkout_enabled']:raise HTTPException(409,'Paid activation is disabled pending approved prices and invoice details')
    profile(db,workspace_id,required=True)
    current['quote']['authorized_paid']=True
    return current

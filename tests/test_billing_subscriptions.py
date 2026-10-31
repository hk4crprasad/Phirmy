import asyncio
import json
from datetime import timedelta
from sqlalchemy import select,func
import pytest

from billing_fakes import enable_checkout,PROFILE
from test_payment_reconciliation import send
from studio import payment_routes,billing_inbox,admission
from studio.config import settings
from studio.db import session_scope,now
from studio.models import BillingProviderOperation,WorkspaceSubscription,Job,Invoice,BillingFinancialEvent,PaymentOrder
from studio.workers import execute_job


class Gateway:
    def __init__(self):self.calls=[];self.plans=[];self.subscriptions=[];self.uncertain=False;self.store_unknown=True
    async def __call__(self,method,path,**kwargs):
        self.calls.append((method,path,kwargs))
        if method=='GET' and path=='/plans':return {'items':self.plans}
        if method=='GET' and path=='/subscriptions':return {'items':self.subscriptions}
        if method=='POST' and path=='/plans':
            row={'id':'plan_synthetic','item':kwargs['json']['item'],'notes':kwargs['json']['notes']};self.plans.append(row);return row
        if method=='POST' and path=='/subscriptions':
            row={'id':'sub_synthetic','plan_id':kwargs['json']['plan_id'],'status':'created','notes':kwargs['json']['notes']}
            if self.store_unknown:self.subscriptions.append(row)
            if self.uncertain:raise TimeoutError('synthetic ambiguous subscription response')
            return row
        if method=='POST' and path=='/subscriptions/sub_synthetic/cancel':return {'id':'sub_synthetic','status':'cancelled'}
        if method=='GET' and path=='/subscriptions/sub_synthetic':return self.subscriptions[0]
        raise AssertionError('Unexpected fake gateway operation')


def start(account,monkeypatch,tmp_path,gateway):
    client,_,base=account;enable_checkout(monkeypatch,tmp_path)
    monkeypatch.setattr(payment_routes,'provider',gateway)
    assert client.put(base+'/billing/profile',json=PROFILE).status_code==200
    quote=client.get(base+'/billing/quote?purpose=subscription&plan_slug=starter').json()
    response=client.post(base+'/billing/subscriptions',json={'plan_slug':'starter','quote_token':quote['quote_token']},headers={'Idempotency-Key':'subscription-one'})
    assert response.status_code==202,response.text
    with session_scope() as db:job=db.scalar(select(Job).where(Job.kind=='billing_subscription_create'));job_id=job.id
    return response.json()['id'],job_id,quote['quote']['tax']['gross_minor']


def event_payload(operation_id,amount,*,state='active',period_start=None,period_end=None,paid=True):
    begin=period_start if period_start is not None else int(now().timestamp())-1
    end=period_end if period_end is not None else begin+30*86400
    subscription={'id':'sub_synthetic','plan_id':'plan_synthetic','status':state,'notes':{'studio_subscription_receipt':operation_id},
                  'current_start':begin,'current_end':end,'paid_count':1 if paid else 0}
    payment={'id':'pay_subscription','order_id':'order_subscription','status':'captured','amount':amount,'currency':'INR','created_at':int(now().timestamp())}
    return subscription,payment


def test_subscription_creation_is_durable_and_grants_nothing_until_captured_fee(account,monkeypatch,tmp_path):
    client,_,base=account;gateway=Gateway();identity,job_id,gross=start(account,monkeypatch,tmp_path,gateway)
    assert gateway.calls==[]
    asyncio.run(execute_job(job_id))
    with session_scope() as db:
        contract=db.get(BillingProviderOperation,identity)
        assert contract.provider_id=='sub_synthetic' and contract.state=='created'
        assert db.scalar(select(WorkspaceSubscription)).plan_slug=='free'
    subscription,payment=event_payload(identity,gross)
    send(client,'subscription.activated',{'subscription':subscription},'activated_without_fee')
    with session_scope() as db:assert db.scalar(select(WorkspaceSubscription)).plan_slug=='free'
    send(client,'subscription.charged',{'subscription':subscription,'payment':payment},'paid_cycle')
    send(client,'subscription.charged',{'subscription':subscription,'payment':payment},'paid_cycle_duplicate')
    with session_scope() as db:
        current=db.scalar(select(WorkspaceSubscription));assert current.plan_slug=='starter' and current.state=='active'
        assert db.scalar(select(func.count()).select_from(Invoice))==1
        assert db.scalar(select(func.count()).select_from(BillingFinancialEvent).where(BillingFinancialEvent.kind=='subscription_fee'))==1
    # Subscription fees buy coverage, not spendable wallet money.
    assert client.get(base+'/wallet').json()['balance_minor']==10000


def test_authorization_hold_and_its_refund_never_grant_plan_or_wallet_credit(account,monkeypatch,tmp_path):
    client,_,base=account;gateway=Gateway();identity,job_id,_=start(account,monkeypatch,tmp_path,gateway)
    asyncio.run(execute_job(job_id))
    subscription,payment=event_payload(identity,100,state='authenticated',paid=False)
    send(client,'subscription.authenticated',{'subscription':subscription,'payment':payment},'mandate_authorization')
    refund={'id':'rfnd_authorization','payment_id':payment['id'],'amount':100,'currency':'INR','status':'processed'}
    send(client,'refund.processed',{'payment':payment,'refund':refund},'authorization_released')
    assert client.get(base+'/wallet').json()['balance_minor']==10000
    with session_scope() as db:
        assert db.scalar(select(WorkspaceSubscription)).plan_slug=='free'
        assert db.scalar(select(func.count()).select_from(Invoice))==0
        assert db.scalar(select(BillingFinancialEvent).where(BillingFinancialEvent.kind=='subscription_authorization')).details['revenue_delta_minor']==0


def test_ambiguous_subscription_post_is_reconciled_by_receipt_without_a_second_post(account,monkeypatch,tmp_path):
    gateway=Gateway();gateway.uncertain=True;identity,job_id,_=start(account,monkeypatch,tmp_path,gateway)
    asyncio.run(execute_job(job_id))
    with session_scope() as db:assert db.get(BillingProviderOperation,identity).state=='unknown'
    asyncio.run(execute_job(job_id))
    assert sum(method=='POST' and path=='/subscriptions' for method,path,_ in gateway.calls)==1
    with session_scope() as db:assert db.get(BillingProviderOperation,identity).provider_id=='sub_synthetic'


def test_inconclusive_reconciliation_does_not_replay_subscription_create(account,monkeypatch,tmp_path):
    gateway=Gateway();gateway.uncertain=True;gateway.store_unknown=False
    identity,job_id,_=start(account,monkeypatch,tmp_path,gateway)
    asyncio.run(execute_job(job_id));asyncio.run(execute_job(job_id))
    assert sum(method=='POST' and path=='/subscriptions' for method,path,_ in gateway.calls)==1
    with session_scope() as db:
        assert db.get(BillingProviderOperation,identity).state=='unknown'
        assert db.get(Job,job_id).state=='queued'


def test_paid_capture_fulfils_previously_authorized_subscription_after_checkout_flag_is_off(account,monkeypatch,tmp_path):
    client,_,_=account;gateway=Gateway();identity,job_id,gross=start(account,monkeypatch,tmp_path,gateway)
    asyncio.run(execute_job(job_id));monkeypatch.setattr(settings,'paid_activation_enabled',False)
    subscription,payment=event_payload(identity,gross)
    send(client,'subscription.charged',{'subscription':subscription,'payment':payment},'paid_after_flag_off')
    with session_scope() as db:assert db.scalar(select(WorkspaceSubscription)).plan_slug=='starter'


def test_expired_paid_coverage_cannot_silently_roll_into_new_month_on_admission(account,monkeypatch,tmp_path):
    client,ws,_=account;gateway=Gateway();identity,job_id,gross=start(account,monkeypatch,tmp_path,gateway)
    asyncio.run(execute_job(job_id));subscription,payment=event_payload(identity,gross)
    send(client,'subscription.charged',{'subscription':subscription,'payment':payment},'paid')
    with session_scope(write=True) as db:
        current=db.scalar(select(WorkspaceSubscription));current.period_start=now()-timedelta(days=31);current.period_end=now()-timedelta(seconds=1)
        end=current.period_end
    from fastapi import HTTPException
    for _ in range(2):
        with pytest.raises(HTTPException,match='paused'):
            with session_scope(write=True) as db:admission.reserve(db,ws,'unpaid-renewal',cost=1)
    with session_scope(write=True) as db:
        current=db.scalar(select(WorkspaceSubscription));assert current.period_end==end
        current.dunning_at=now()-timedelta(days=8)
    with session_scope(write=True) as db:
        admission.reserve(db,ws,'after-downgrade',cost=1)
        assert db.scalar(select(WorkspaceSubscription)).plan_slug=='free'


def test_cancellation_retains_paid_coverage_then_downgrades_at_period_end(account,monkeypatch,tmp_path):
    client,ws,base=account;gateway=Gateway();identity,job_id,gross=start(account,monkeypatch,tmp_path,gateway)
    asyncio.run(execute_job(job_id));subscription,payment=event_payload(identity,gross)
    send(client,'subscription.charged',{'subscription':subscription,'payment':payment},'paid')
    result=client.post(base+'/billing/subscriptions/'+identity+'/cancel',json={'at_cycle_end':True},headers={'Idempotency-Key':'cancel-one'})
    assert result.status_code==202,result.text
    with session_scope() as db:cancel_job_id=db.scalar(select(Job.id).where(Job.kind=='billing_subscription_cancel'))
    asyncio.run(execute_job(cancel_job_id))
    with session_scope(write=True) as db:
        current=db.scalar(select(WorkspaceSubscription));assert current.plan_slug=='starter' and current.pending_plan_slug=='free'
        current.period_end=now()-timedelta(seconds=1)
    with session_scope(write=True) as db:
        admission.reserve(db,ws,'after-cancellation',cost=1)
        assert db.scalar(select(WorkspaceSubscription)).plan_slug=='free'


def test_unexpected_captured_subscription_amount_never_grants_paid_access(account,monkeypatch,tmp_path):
    client,_,_=account;gateway=Gateway();identity,job_id,gross=start(account,monkeypatch,tmp_path,gateway)
    asyncio.run(execute_job(job_id))
    subscription,payment=event_payload(identity,gross-1)
    send(client,'subscription.charged',{'subscription':subscription,'payment':payment},'unexpected_amount')
    from studio.models import BillingWebhookInbox
    with session_scope() as db:
        assert db.scalar(select(WorkspaceSubscription)).plan_slug=='free'
        receipt=db.scalar(select(BillingWebhookInbox));assert receipt.state=='pending' and receipt.error_code=='reconciliation_failed'
        assert db.scalar(select(func.count()).select_from(Invoice))==0


def test_later_cancellation_state_survives_out_of_order_paid_snapshot_with_valid_coverage(account,monkeypatch,tmp_path):
    client,_,_=account;gateway=Gateway();identity,job_id,gross=start(account,monkeypatch,tmp_path,gateway)
    asyncio.run(execute_job(job_id));subscription,payment=event_payload(identity,gross)
    stamp=int(now().timestamp())
    send(client,'subscription.cancelled',{'subscription':{**subscription,'status':'cancelled'}},'cancelled_first',stamp=stamp)
    send(client,'subscription.charged',{'subscription':subscription,'payment':payment},'earlier_paid_delivery',stamp=stamp-1)
    with session_scope() as db:
        contract=db.get(BillingProviderOperation,identity);current=db.scalar(select(WorkspaceSubscription))
        assert contract.state=='cancelled' and current.plan_slug=='starter' and current.pending_plan_slug=='free'
        assert current.state=='cancelled'


def test_api_key_cannot_start_cancel_or_change_subscription_billing(account,monkeypatch,tmp_path):
    client,_,base=account;gateway=Gateway();identity,job_id,_=start(account,monkeypatch,tmp_path,gateway)
    key=client.post(base+'/keys',json={'name':'Billing read fixture','scopes':['billing:read']}).json()['secret']
    assert client.get(base+'/billing/subscriptions',headers={'X-API-Key':key}).status_code==200
    assert client.post(base+'/billing/subscriptions/'+identity+'/cancel',json={},headers={'X-API-Key':key,'Idempotency-Key':'denied'}).status_code==403
    assert client.put(base+'/billing/profile',json=PROFILE,headers={'X-API-Key':key}).status_code==403


def test_subscription_checkout_signature_uses_server_identity_and_fetches_authoritative_capture(account,monkeypatch,tmp_path):
    import hashlib,hmac
    client,_,base=account;gateway=Gateway();identity,job_id,gross=start(account,monkeypatch,tmp_path,gateway)
    asyncio.run(execute_job(job_id));subscription,payment=event_payload(identity,gross)
    prior=gateway.__call__
    async def provider(method,path,**kwargs):
        if method=='GET' and path=='/subscriptions/sub_synthetic':return subscription
        if method=='GET' and path=='/payments/pay_subscription':return payment
        return await prior(method,path,**kwargs)
    monkeypatch.setattr(payment_routes,'provider',provider)
    proof={'razorpay_payment_id':payment['id'],'razorpay_subscription_id':'sub_synthetic','razorpay_signature':'0'*64}
    assert client.post(base+'/billing/subscriptions/'+identity+'/verify',json=proof).status_code==401
    proof['razorpay_signature']=hmac.new(b'synthetic_test_secret',b'pay_subscription|sub_synthetic',hashlib.sha256).hexdigest()
    for _ in range(2):
        response=client.post(base+'/billing/subscriptions/'+identity+'/verify',json=proof)
        assert response.status_code==200,response.text
        assert response.json()['status']=='captured'
    with session_scope() as db:
        assert db.scalar(select(WorkspaceSubscription)).plan_slug=='starter'
        assert db.scalar(select(func.count()).select_from(Invoice))==1


def test_old_checkout_payment_cannot_be_reused_to_buy_a_later_subscription_period(account,monkeypatch,tmp_path):
    import hashlib,hmac
    client,_,base=account;gateway=Gateway();identity,job_id,gross=start(account,monkeypatch,tmp_path,gateway)
    asyncio.run(execute_job(job_id))
    subscription,payment=event_payload(identity,gross)
    payment['created_at']=int((now()-timedelta(days=60)).timestamp())
    async def provider(method,path,**kwargs):
        if path=='/subscriptions/sub_synthetic':return subscription
        if path=='/payments/pay_subscription':return payment
        raise AssertionError('Unexpected provider request')
    monkeypatch.setattr(payment_routes,'provider',provider)
    signature=hmac.new(b'synthetic_test_secret',b'pay_subscription|sub_synthetic',hashlib.sha256).hexdigest()
    response=client.post(base+'/billing/subscriptions/'+identity+'/verify',json={
        'razorpay_subscription_id':'sub_synthetic','razorpay_payment_id':'pay_subscription','razorpay_signature':signature})
    assert response.status_code==409 and 'period' in response.text
    with session_scope() as db:assert db.scalar(select(WorkspaceSubscription)).plan_slug=='free'


def test_unknown_cancellation_retry_is_read_only_and_can_recover_after_dead_letter(account,monkeypatch,tmp_path):
    client,_,base=account;gateway=Gateway();identity,job_id,_=start(account,monkeypatch,tmp_path,gateway)
    asyncio.run(execute_job(job_id))
    calls=[]
    async def uncertain(method,path,**kwargs):
        calls.append((method,path))
        if method=='POST':raise TimeoutError('Synthetic ambiguous cancel')
        return {'id':'sub_synthetic','status':'cancelled'}
    monkeypatch.setattr(payment_routes,'provider',uncertain)
    url=base+'/billing/subscriptions/'+identity+'/cancel'
    headers={'Idempotency-Key':'cancel-recovery'}
    assert client.post(url,json={'at_cycle_end':True},headers=headers).status_code==202
    with session_scope() as db:cancel_id=db.scalar(select(Job.id).where(Job.kind=='billing_subscription_cancel'))
    asyncio.run(execute_job(cancel_id))
    with session_scope(write=True) as db:db.get(Job,cancel_id).state='failed'
    assert client.post(url,json={'at_cycle_end':True},headers={'Idempotency-Key':'different-cancel'}).status_code==409
    assert client.post(url,json={'at_cycle_end':True},headers=headers).status_code==202
    with session_scope() as db:
        retry=db.scalar(select(Job.id).where(Job.kind=='billing_subscription_cancel',Job.state=='queued'))
    assert retry and retry!=cancel_id
    asyncio.run(execute_job(retry))
    assert [method for method,_ in calls]==['POST','GET']

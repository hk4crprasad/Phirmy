from sqlalchemy import select,update,delete,func
from sqlalchemy.exc import DBAPIError
import pytest
from studio import billing_accounting as money
from studio.db import session_scope,engine
from studio.models import BillingAccount,BillingFinancialEvent,Wallet,WorkspaceSubscription,PaymentOrder,PaymentDispute
from studio.plans import subscription


def test_spent_payment_reversal_is_recorded_once_without_negative_wallet_or_lost_event(account):
    client,ws,base=account
    with session_scope(write=True) as db:
        subscription(db,ws)
        db.scalar(select(Wallet).where(Wallet.workspace_id==ws)).balance_minor=100
        money.debit(db,ws,10000,'refund:synthetic',provider_id='refund_synthetic')
        money.debit(db,ws,10000,'refund:synthetic',provider_id='refund_synthetic')
    state=client.get(base+'/wallet').json()
    assert state['balance_minor']==0 and state['billing_adjustment_minor']==9900 and state['available_minor']==0
    with session_scope(write=True) as db:
        assert db.scalar(select(WorkspaceSubscription)).billing_blocked is True
        money.credit(db,ws,5000,'capture:first',provider_id='payment_one')
        money.credit(db,ws,5000,'capture:first',provider_id='payment_one')
        money.credit(db,ws,5000,'capture:second',provider_id='payment_two')
        assert db.scalar(select(WorkspaceSubscription)).billing_blocked is False
    state=client.get(base+'/wallet').json()
    assert state['balance_minor']==100 and state['billing_adjustment_minor']==0
    with session_scope() as db:assert db.scalar(select(func.count()).select_from(BillingFinancialEvent))==3


def test_open_dispute_restricts_liquidity_without_posting_a_final_loss(account):
    client,ws,base=account
    with session_scope(write=True) as db:
        current=subscription(db,ws)
        order=PaymentOrder(workspace_id=ws,amount_minor=10000,operation_key='risk-order');db.add(order);db.flush()
        dispute=PaymentDispute(workspace_id=ws,order_id=order.id,provider_dispute_id='risk-one',amount_minor=5000,risk_net_minor=5000,state='open')
        db.add(dispute);db.flush();money.refresh_block(db,ws)
        assert current.billing_blocked is True
    state=client.get(base+'/wallet').json()
    assert state['balance_minor']==10000 and state['available_minor']==5000 and state['at_risk_minor']==5000
    with session_scope(write=True) as db:
        dispute=db.scalar(select(PaymentDispute));dispute.state='won';dispute.risk_net_minor=0
        # A resolved billing dispute cannot clear an independent operator kill switch.
        current=db.scalar(select(WorkspaceSubscription));current.operator_paused=True
        money.refresh_block(db,ws)
        assert current.billing_blocked is False and current.operator_paused is True


def test_financial_adjustments_cannot_be_edited_or_deleted(account):
    _,ws,_=account
    with session_scope(write=True) as db:row=money.credit(db,ws,100,'immutable-credit');identity=row.id
    for statement in [update(BillingFinancialEvent).where(BillingFinancialEvent.id==identity).values(details={}),delete(BillingFinancialEvent)]:
        with pytest.raises(DBAPIError):
            with engine.begin() as db:db.execute(statement)


import asyncio
import hashlib
import hmac
import json
from datetime import timedelta
from studio import billing_inbox,billing_events,admission,gst
from studio.config import settings
from studio.db import now
from studio.models import BillingWebhookInbox,PaymentRefund,Invoice,Ledger
from studio.secrets import encrypt
from unittest.mock import AsyncMock


def payment_fixture(account,monkeypatch):
    _,ws,_=account;monkeypatch.setattr(settings,'razorpay_webhook_secret','synthetic-webhook-secret')
    quote={'seller':gst.business(),'buyer':{'legal_name':'Synthetic buyer','address':'Synthetic address','state_code':'07','gstin':'','email':'billing@example.test'},
           'tax':gst.tax_lines(10000,'07'),'price_status':'DRAFT','authorized_paid':False,'payment_mode':'test','description':'Wallet funding'}
    with session_scope(write=True) as db:
        row=PaymentOrder(workspace_id=ws,amount_minor=11800,net_minor=10000,provider_order_id='order_fixture',operation_key='fixture-order',encrypted_snapshot=encrypt(json.dumps(quote)))
        db.add(row);db.flush();identity=row.id
    payment={'id':'pay_fixture','order_id':'order_fixture','status':'captured','amount':11800,'currency':'INR','email':'synthetic-buyer@example.test'}
    return identity,payment


def send(client,name,payload,event_id,*,stamp=None,process=True):
    event={'event':name,'payload':{key:{'entity':value} for key,value in payload.items()},'created_at':int(now().timestamp()) if stamp is None else stamp}
    body=json.dumps(event,separators=(',',':')).encode()
    signature=hmac.new(b'synthetic-webhook-secret',body,hashlib.sha256).hexdigest()
    response=client.post('/v1/provider-webhooks/razorpay',content=body,headers={'Content-Type':'application/json','X-Razorpay-Event-Id':event_id,'X-Razorpay-Signature':signature})
    if response.status_code==200 and process:asyncio.run(billing_inbox.process_inbox())
    return response,body


def test_signed_inbox_acknowledges_before_accounting_and_deduplicates_events_and_captures(account,monkeypatch):
    client,ws,base=account;_,payment=payment_fixture(account,monkeypatch)
    stamp=int(now().timestamp())
    response,body=send(client,'payment.captured',{'payment':payment},'event_capture',process=False,stamp=stamp)
    assert response.status_code==200 and client.get(base+'/wallet').json()['balance_minor']==10000
    assert send(client,'payment.captured',{'payment':payment},'event_capture',process=False,stamp=stamp)[0].status_code==200
    with session_scope() as db:
        receipt=db.scalar(select(BillingWebhookInbox));assert 'synthetic-buyer' not in receipt.encrypted_payload
        assert db.scalar(select(func.count()).select_from(BillingWebhookInbox))==1
    asyncio.run(billing_inbox.process_inbox())
    send(client,'payment.captured',{'payment':payment},'another_delivery')
    assert client.get(base+'/wallet').json()['balance_minor']==20000
    with session_scope() as db:
        assert db.scalar(select(func.count()).select_from(Ledger).where(Ledger.operation_key=='razorpay:order_fixture'))==1
        assert db.scalar(select(func.count()).select_from(Invoice))==1


def test_bad_signature_missing_event_id_and_changed_payload_cannot_mutate_a_receipt(account,monkeypatch):
    client,_,_=account;_,payment=payment_fixture(account,monkeypatch)
    assert client.post('/v1/provider-webhooks/razorpay',content=b'{}',headers={'X-Razorpay-Signature':'invalid'}).status_code==401
    body=b'{"event":"payment.captured","payload":{}}';signature=hmac.new(b'synthetic-webhook-secret',body,hashlib.sha256).hexdigest()
    assert client.post('/v1/provider-webhooks/razorpay',content=body,headers={'X-Razorpay-Signature':signature}).status_code==422
    assert send(client,'payment.captured',{'payment':payment},'same_identity',process=False)[0].status_code==200
    assert send(client,'payment.captured',{'payment':{**payment,'amount':1}},'same_identity',process=False)[0].status_code==409
    asyncio.run(billing_inbox.process_inbox())
    with session_scope() as db:assert db.scalar(select(PaymentOrder)).state=='credited'


def test_failed_attempt_never_credits_or_regresses_later_capture(account,monkeypatch):
    client,_,base=account;_,payment=payment_fixture(account,monkeypatch)
    failed={**payment,'status':'failed'}
    send(client,'payment.failed',{'payment':failed},'failed_first')
    assert client.get(base+'/wallet').json()['balance_minor']==10000
    send(client,'payment.captured',{'payment':payment},'captured_later')
    send(client,'payment.failed',{'payment':failed},'failed_replayed_late')
    assert client.get(base+'/wallet').json()['balance_minor']==20000
    with session_scope() as db:assert db.scalar(select(PaymentOrder)).state=='credited'


def test_pending_refund_holds_credit_processed_refund_reverses_once_and_failed_late_cannot_regress(account,monkeypatch):
    client,_,base=account;_,payment=payment_fixture(account,monkeypatch)
    send(client,'payment.captured',{'payment':payment},'capture')
    refund={'id':'rfnd_fixture','payment_id':payment['id'],'amount':5900,'currency':'INR','status':'pending'}
    send(client,'refund.created',{'payment':payment,'refund':refund},'refund_pending')
    state=client.get(base+'/wallet').json();assert state['balance_minor']==20000 and state['at_risk_minor']==5000
    send(client,'refund.processed',{'payment':payment,'refund':{**refund,'status':'processed'}},'refund_processed')
    send(client,'refund.processed',{'payment':payment,'refund':{**refund,'status':'processed'}},'refund_processed_duplicate')
    send(client,'refund.failed',{'payment':payment,'refund':{**refund,'status':'failed'}},'refund_failed_late')
    state=client.get(base+'/wallet').json();assert state['balance_minor']==15000 and state['at_risk_minor']==0
    with session_scope() as db:
        assert db.scalar(select(PaymentRefund)).state=='processed'
        assert db.scalar(select(PaymentOrder)).state=='partially_refunded'
        assert db.scalar(select(func.count()).select_from(Invoice))==2


def test_processed_refund_can_arrive_before_capture_without_recrediting_late_capture(account,monkeypatch):
    client,_,base=account;_,payment=payment_fixture(account,monkeypatch)
    refund={'id':'rfnd_first','payment_id':payment['id'],'amount':11800,'currency':'INR','status':'processed'}
    send(client,'refund.processed',{'payment':payment,'refund':refund},'refund_first')
    send(client,'payment.captured',{'payment':payment},'capture_late')
    assert client.get(base+'/wallet').json()['balance_minor']==10000
    with session_scope() as db:
        row=db.scalar(select(PaymentOrder));assert row.state=='refunded' and row.reversed_net_minor==10000


def test_external_refund_after_spend_blocks_new_cost_with_an_audited_adjustment(account,monkeypatch):
    client,ws,base=account;_,payment=payment_fixture(account,monkeypatch)
    send(client,'payment.captured',{'payment':payment},'capture')
    with session_scope(write=True) as db:db.scalar(select(Wallet)).balance_minor=100
    refund={'id':'rfnd_spent','payment_id':payment['id'],'amount':11800,'currency':'INR','status':'processed'}
    send(client,'refund.processed',{'payment':payment,'refund':refund},'refund_spent')
    state=client.get(base+'/wallet').json();assert state['balance_minor']==0 and state['billing_adjustment_minor']==9900
    from fastapi import HTTPException
    with pytest.raises(HTTPException,match='paused'):
        with session_scope(write=True) as db:admission.reserve(db,ws,'after-refund',cost=1)


def test_dispute_holds_then_debits_and_restores_once_and_ignores_older_states(account,monkeypatch):
    client,_,base=account;_,payment=payment_fixture(account,monkeypatch)
    send(client,'payment.captured',{'payment':payment},'capture')
    dispute={'id':'disp_fixture','payment_id':payment['id'],'amount':5900,'currency':'INR','amount_deducted':0,'status':'open'}
    stamp=int(now().timestamp())
    send(client,'payment.dispute.created',{'payment':payment,'dispute':dispute},'dispute_open',stamp=stamp)
    state=client.get(base+'/wallet').json();assert state['balance_minor']==20000 and state['at_risk_minor']==5000
    send(client,'payment.dispute.lost',{'payment':payment,'dispute':{**dispute,'status':'lost','amount_deducted':5900}},'dispute_lost',stamp=stamp+2)
    assert client.get(base+'/wallet').json()['balance_minor']==15000
    send(client,'payment.dispute.won',{'payment':payment,'dispute':{**dispute,'status':'won'}},'dispute_won',stamp=stamp+3)
    send(client,'payment.dispute.created',{'payment':payment,'dispute':dispute},'dispute_old_late',stamp=stamp+1)
    state=client.get(base+'/wallet').json();assert state['balance_minor']==20000 and state['at_risk_minor']==0


def test_overlapping_refund_and_lost_dispute_never_reverse_more_than_original_credit(account,monkeypatch):
    client,_,base=account;_,payment=payment_fixture(account,monkeypatch)
    send(client,'payment.captured',{'payment':payment},'capture')
    stamp=int(now().timestamp())
    dispute={'id':'disp_overlap','payment_id':payment['id'],'amount':5900,'currency':'INR','amount_deducted':5900,'status':'lost'}
    send(client,'payment.dispute.lost',{'payment':payment,'dispute':dispute},'lost',stamp=stamp)
    refund={'id':'rfnd_overlap','payment_id':payment['id'],'amount':11800,'currency':'INR','status':'processed'}
    send(client,'refund.processed',{'payment':payment,'refund':refund},'refunded')
    send(client,'payment.dispute.won',{'payment':payment,'dispute':{**dispute,'status':'won','amount_deducted':0}},'won',stamp=stamp+1)
    assert client.get(base+'/wallet').json()['balance_minor']==10000
    with session_scope() as db:assert db.scalar(select(PaymentOrder)).reversed_net_minor==10000


def test_unmatched_event_is_retained_and_can_reconcile_after_order_binding_arrives(account,monkeypatch):
    client,ws,base=account;_,payment=payment_fixture(account,monkeypatch)
    with session_scope(write=True) as db:db.scalar(select(PaymentOrder)).provider_order_id=None
    send(client,'payment.captured',{'payment':payment},'early_capture')
    with session_scope(write=True) as db:
        receipt=db.scalar(select(BillingWebhookInbox));assert receipt.state=='pending' and receipt.error_code=='unmatched_payment'
        receipt.next_attempt_at=now()-timedelta(seconds=1)
        db.scalar(select(PaymentOrder)).provider_order_id='order_fixture'
    asyncio.run(billing_inbox.process_inbox())
    assert client.get(base+'/wallet').json()['balance_minor']==20000


def test_previous_webhook_secret_is_bounded_by_explicit_expiry(account,monkeypatch):
    client,_,_=account;payment_fixture(account,monkeypatch)
    monkeypatch.setattr(settings,'razorpay_webhook_secret','current-other-secret')
    monkeypatch.setattr(settings,'razorpay_webhook_previous_secrets_json',json.dumps([{'secret':'synthetic-webhook-secret','valid_until':(now()+timedelta(hours=24)).isoformat()}]))
    assert send(client,'unhandled.event',{},'old_secret_accepted')[0].status_code==200
    monkeypatch.setattr(settings,'razorpay_webhook_previous_secrets_json',json.dumps([{'secret':'synthetic-webhook-secret','valid_until':(now()-timedelta(seconds=1)).isoformat()}]))
    assert send(client,'unhandled.event',{},'expired_secret_rejected')[0].status_code==401


def test_checkout_requires_review_of_gst_total_and_pins_business_and_buyer_snapshot(account,monkeypatch,tmp_path):
    from billing_fakes import enable_checkout,PROFILE
    from studio import payment_routes
    client,ws,base=account;enable_checkout(monkeypatch,tmp_path)
    assert client.put(base+'/billing/profile',json=PROFILE).status_code==200
    quote=client.get(base+'/billing/quote?amount_minor=10000').json()
    assert quote['quote']['tax']['gross_minor']==11800 and quote['checkout_enabled'] is True
    fake=AsyncMock(return_value={'id':'order_reviewed','amount':11800,'currency':'INR'});monkeypatch.setattr(payment_routes,'provider',fake)
    assert client.post(base+'/payments/orders',json={'amount_minor':10000},headers={'Idempotency-Key':'unreviewed'}).status_code==409
    response=client.post(base+'/payments/orders',json={'amount_minor':10000,'quote_token':quote['quote_token']},headers={'Idempotency-Key':'reviewed'})
    assert response.status_code==201,response.text
    assert response.json()['amount_minor']==11800 and response.json()['net_minor']==10000
    assert 'encrypted_snapshot' not in response.json()
    assert fake.call_args.kwargs['json']['amount']==11800
    monkeypatch.setattr(settings,'paid_activation_enabled',False)
    assert client.post(base+'/payments/orders',json={'amount_minor':10000},headers={'Idempotency-Key':'reviewed'}).status_code==201
    assert fake.await_count==1


def test_changed_billing_profile_invalidates_reviewed_quote_before_provider_io(account,monkeypatch,tmp_path):
    from billing_fakes import enable_checkout,PROFILE
    from studio import payment_routes
    client,_,base=account;enable_checkout(monkeypatch,tmp_path)
    client.put(base+'/billing/profile',json=PROFILE)
    quote=client.get(base+'/billing/quote?amount_minor=10000').json()
    client.put(base+'/billing/profile',json={**PROFILE,'state_code':'29'})
    fake=AsyncMock();monkeypatch.setattr(payment_routes,'provider',fake)
    response=client.post(base+'/payments/orders',json={'amount_minor':10000,'quote_token':quote['quote_token']},headers={'Idempotency-Key':'changed-profile'})
    assert response.status_code==409 and 'revised total' in response.text
    fake.assert_not_awaited()


def test_refund_request_queues_stable_idempotent_provider_operation_and_survives_timeout(account,monkeypatch):
    from studio import payment_routes
    from studio.models import Job
    from studio.workers import execute_job
    client,_,base=account;order_id,payment=payment_fixture(account,monkeypatch)
    send(client,'payment.captured',{'payment':payment},'capture')
    response=client.post(base+'/payments/'+order_id+'/refunds',json={'amount_minor':5900},headers={'Idempotency-Key':'refund-operation'})
    assert response.status_code==202,response.text
    identity=response.json()['id']
    calls=[]
    async def fake(method,path,**kwargs):
        calls.append((method,path,kwargs))
        if len(calls)==1:raise TimeoutError('simulated uncertain refund response')
        return {'id':'rfnd_worker','payment_id':payment['id'],'amount':5900,'currency':'INR','status':'processed','receipt':identity}
    monkeypatch.setattr(payment_routes,'provider',fake)
    with session_scope() as db:job_id=db.scalar(select(Job.id).where(Job.kind=='billing_refund'))
    asyncio.run(execute_job(job_id))
    with session_scope() as db:
        assert db.get(Job,job_id).state=='queued' and db.get(PaymentRefund,identity).state=='unknown'
    asyncio.run(execute_job(job_id))
    assert calls[0][2]['headers']['X-Refund-Idempotency']==calls[1][2]['headers']['X-Refund-Idempotency']==identity
    assert calls[0][2]['json']==calls[1][2]['json']
    assert client.get(base+'/wallet').json()['balance_minor']==15000
    assert client.post(base+'/payments/'+order_id+'/refunds',json={'amount_minor':5900},headers={'Idempotency-Key':'refund-operation'}).json()['state']=='processed'
    with session_scope() as db:assert db.get(Job,job_id).state=='completed'


def test_spent_wallet_cannot_request_refund_and_invoice_list_is_scoped(account,monkeypatch):
    client,_,base=account;order_id,payment=payment_fixture(account,monkeypatch)
    send(client,'payment.captured',{'payment':payment},'capture')
    with session_scope(write=True) as db:db.scalar(select(Wallet)).balance_minor=100
    response=client.post(base+'/payments/'+order_id+'/refunds',json={'amount_minor':11800},headers={'Idempotency-Key':'refund-too-much'})
    assert response.status_code==409 and 'unspent' in response.text
    listed=client.get(base+'/billing/invoices').json()['items']
    assert len(listed)==1 and listed[0]['status']=='DRAFT' and listed[0]['download_ready'] is False
    assert client.get(base+'/billing/invoices/'+listed[0]['id']+'/pdf').status_code==409


def test_reversal_preserves_authorized_call_funds_and_reconciles_them_on_settlement(account,monkeypatch):
    from studio.models import Call,Reservation
    from studio.domain import reserve,settle_call
    client,ws,base=account;_,payment=payment_fixture(account,monkeypatch)
    send(client,'payment.captured',{'payment':payment},'capture')
    agent=client.post(base+'/agents',json={'name':'Funded call'}).json()
    published=client.post(base+'/agents/'+agent['id']+'/publish',json={'expected_draft_revision':1}).json()
    with session_scope(write=True) as db:
        call=Call(workspace_id=ws,agent_version_id=published['id'],mode='simulation',transport='browser',metadata_data={'rate_minor_per_minute':0})
        db.add(call);db.flush();call_id=call.id;reserve(db,call,20000)
    refund={'id':'rfnd_reserved','payment_id':payment['id'],'amount':11800,'currency':'INR','status':'processed'}
    send(client,'refund.processed',{'payment':payment,'refund':refund},'refunded')
    state=client.get(base+'/wallet').json();assert state['balance_minor']==20000 and state['billing_adjustment_minor']==10000
    with session_scope(write=True) as db:settle_call(db,db.get(Call,call_id),0)
    state=client.get(base+'/wallet').json();assert state['balance_minor']==10000 and state['billing_adjustment_minor']==0


def test_partial_credit_note_tax_rounding_adds_exactly_to_original_cgst_and_sgst(account,monkeypatch):
    from studio.secrets import decrypt
    client,_,_=account;_,payment=payment_fixture(account,monkeypatch)
    with session_scope(write=True) as db:
        order=db.scalar(select(PaymentOrder));snapshot=json.loads(decrypt(order.encrypted_snapshot))
        snapshot['tax']=gst.tax_lines(10000,'29');snapshot['buyer']['state_code']='29';order.encrypted_snapshot=encrypt(json.dumps(snapshot))
    send(client,'payment.captured',{'payment':payment},'capture')
    for index,amount in enumerate([4,4,11792]):
        refund={'id':'rfnd_round_'+str(index),'payment_id':payment['id'],'amount':amount,'currency':'INR','status':'processed'}
        send(client,'refund.processed',{'payment':payment,'refund':refund},'refund_round_'+str(index))
    with session_scope() as db:
        notes=list(db.scalars(select(Invoice).where(Invoice.kind=='credit_note')))
        assert len(notes)==3
        assert sum(row.snapshot['tax']['cgst_minor'] for row in notes)==900
        assert sum(row.snapshot['tax']['sgst_minor'] for row in notes)==900
        assert sum(row.snapshot['tax']['net_minor'] for row in notes)==10000


def test_billing_never_treats_inr_paise_as_another_workspace_currency(account,monkeypatch):
    from studio.models import Workspace,BillingWebhookInbox
    client,ws,base=account;_,payment=payment_fixture(account,monkeypatch)
    with session_scope(write=True) as db:
        db.get(Workspace,ws).currency='USD';db.scalar(select(Wallet)).currency='USD'
    assert client.get(base+'/billing/quote?amount_minor=10000').status_code==409
    send(client,'payment.captured',{'payment':payment},'wrong_currency_workspace')
    with session_scope() as db:
        assert db.scalar(select(Wallet)).balance_minor==10000
        assert db.scalar(select(BillingWebhookInbox)).state=='pending'


def test_current_and_previous_payment_credentials_are_redacted_from_model_context(monkeypatch):
    from studio.prompt_safety import redact_text
    values=['synthetic-test-payment-secret','synthetic-live-payment-secret','synthetic-webhook-current','synthetic-webhook-previous']
    for name,value in zip(['razorpay_test_key_secret','razorpay_live_key_secret','razorpay_webhook_secret'],values):monkeypatch.setattr(settings,name,value)
    monkeypatch.setattr(settings,'razorpay_webhook_previous_secrets_json',json.dumps([{'secret':values[-1],'valid_until':(now()+timedelta(days=1)).isoformat()}]))
    result=redact_text(' '.join(values));assert not any(value in result for value in values)

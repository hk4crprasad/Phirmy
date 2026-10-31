import asyncio
from datetime import timedelta

from fastapi import HTTPException
import pytest
from sqlalchemy import select, func

from studio import admission, billing_accounting, metering, plans
from studio.config import settings
from studio.db import now, session_scope
from studio.models import (
    Audit, BillingProviderOperation, BillingWebhookInbox, BudgetAdmission, Call,
    Job, Ledger, PaymentOrder, PaymentRefund, User, Workspace, WorkspaceSubscription,
)
from studio.security import digest
from studio.sessions import profile_for
from studio.workers import execute_job


def authorize(account, monkeypatch):
    client, _, _ = account
    me = client.get('/v1/auth/me').json()['user']
    monkeypatch.setattr(settings, 'billing_operator_emails', me['email'].upper())
    with session_scope(write=True) as db:
        profile_for(db, me['id']).email_verified_at = now()
    return me


def test_operator_requires_explicit_allowlist_verified_browser_and_csrf(account, monkeypatch):
    client, ws, base = account
    assert client.get('/v1/operator/billing').status_code == 403
    user = client.get('/v1/auth/me').json()['user']
    monkeypatch.setattr(settings, 'billing_operator_emails', user['email'])
    assert client.get('/v1/operator/billing').status_code == 403  # Even development bypass is insufficient.
    authorize(account, monkeypatch)
    assert client.get('/v1/operator/billing').status_code == 200
    key = client.post(base+'/keys', json={'name': 'Restricted reader', 'scopes': ['billing:read']}).json()['secret']
    assert client.get('/v1/operator/billing', headers={'X-API-Key': key}).status_code == 403
    path = '/v1/operator/billing/workspaces/'+ws+'/control'
    body = {'paused': True, 'reason': 'Synthetic abuse review'}
    assert client.put(path, json=body, headers={'X-CSRF-Token': 'invalid'}).status_code == 403
    assert client.put(path, json=body, headers={'Origin': 'https://attacker.example'}).status_code == 403
    assert client.put(path, json=body).status_code == 200


def test_margin_excludes_wallet_funding_and_synthetic_debits_and_retains_old_unknown_holds(account, monkeypatch):
    client, ws, _ = account; authorize(account, monkeypatch)
    with session_scope(write=True) as db:
        current = plans.subscription(db, ws)
        billing_accounting.financial_event(db, ws, 'subscription-income', 'subscription_fee',
            {'revenue_delta_minor': 10000, 'provider_fee_minor': 200})
        billing_accounting.financial_event(db, ws, 'subscription-refund', 'subscription_reversal', {'revenue_delta_minor': -1000})
        billing_accounting.credit(db, ws, 50000, 'topup-liability', extra={'provider_fee_minor': 100})
        for mode in ['live', 'simulation']:
            call = Call(workspace_id=ws, mode=mode); db.add(call); db.flush()
            db.add(Ledger(workspace_id=ws, operation_key='retail-'+mode, kind='debit', amount_minor=-500,
                          description='Synthetic fixture', call_id=call.id))
        metering.record_cost(db, ws, 'provider-cost', 'openai', 'llm', {'input_tokens': 1000}, source='provider_usage')
        metering.record_cost(db, ws, 'unknown-cost', 'openai', 'llm', {}, source='unreported')
        row = admission.reserve(db, ws, 'old-unknown-hold', cost=123*metering.MICRO)
        row.state = 'unknown'; row.created_at = now()-timedelta(days=90)
    response = client.get('/v1/operator/billing?days=7').json()
    item = response['items'][0]
    assert item['recognized_receipts_minor'] == 9500
    assert item['reported_payment_fees_minor'] == 300
    assert item['provider_cost_micro_minor'] == 100*metering.MICRO
    assert item['contribution_micro_minor'] == 9100*metering.MICRO
    assert item['outstanding_cost_micro_minor'] == 123*metering.MICRO
    assert item['unreported_usage_records'] == 1
    assert response['top_consumers'][0]['id'] == ws
    assert 'top-ups excluded' in response['basis']


def test_operator_kill_and_cap_survive_resume_without_clearing_financial_block(account, monkeypatch):
    client, ws, _ = account; authorize(account, monkeypatch)
    path = '/v1/operator/billing/workspaces/'+ws+'/control'
    assert client.put(path, json={'paused': True, 'spend_cap_minor': 0, 'reason': 'Synthetic kill switch test'}).status_code == 200
    with pytest.raises(HTTPException, match='paused'):
        with session_scope(write=True) as db: admission.reserve(db, ws, 'killed', cost=1)
    with session_scope(write=True) as db:
        billing_accounting.account(db, ws).debt_minor = 1
        billing_accounting.refresh_block(db, ws)
    assert client.put(path, json={'paused': False, 'reason': 'Synthetic operator resume'}).json()['billing_blocked'] is True
    with session_scope() as db:
        row = db.scalar(select(WorkspaceSubscription))
        assert not row.operator_paused and row.spend_cap_minor == 0 and row.billing_blocked
        assert db.scalar(select(func.count()).select_from(Audit).where(Audit.action=='operator.billing_control')) == 2
    with pytest.raises(HTTPException, match='paused'):
        with session_scope(write=True) as db: admission.reserve(db, ws, 'debt-still-blocks', cost=1)


def test_global_top_consumers_do_not_depend_on_workspace_page_and_search_is_literal(account, monkeypatch):
    client, ws, _ = account; authorize(account, monkeypatch)
    with session_scope(write=True) as db:
        other = Workspace(name='Other 100% workspace'); db.add(other); db.flush(); other_id=other.id
        metering.record_cost(db, other_id, 'top-consumer', 'openai', 'llm', {'input_tokens': 1000})
    first = client.get('/v1/operator/billing?limit=1').json()
    second = client.get('/v1/operator/billing?limit=1&after='+first['next_cursor']).json()
    assert {first['items'][0]['id'], second['items'][0]['id']} == {ws, other_id}
    assert first['top_consumers'][0]['id'] == other_id
    assert second['top_consumers'][0]['id'] == other_id
    result = client.get('/v1/operator/billing?search=%25').json()
    assert [row['id'] for row in result['items']] == [other_id]


def test_dead_letter_review_redacts_payload_and_retries_original_receipt_once(account, monkeypatch):
    from studio.secrets import encrypt
    client, ws, _ = account; authorize(account, monkeypatch)
    with session_scope(write=True) as db:
        row = BillingWebhookInbox(provider_event_id='dead-letter-fixture', payload_hash=digest('private-payload'),
            encrypted_payload=encrypt('private-payload'), state='failed', attempts=8)
        db.add(row); db.flush(); identity=row.id
    response = client.get('/v1/operator/billing/dead-letters')
    assert response.status_code == 200 and 'private-payload' not in response.text and 'encrypted_payload' not in response.text
    path = f'/v1/operator/billing/workspaces/{ws}/webhooks/{identity}/retry'
    assert client.post(path, json={'reason': 'Provider identity reconciled'}).status_code == 202
    assert client.post(path, json={'reason': 'Provider identity reconciled'}).status_code == 409
    with session_scope() as db:
        row = db.get(BillingWebhookInbox, identity)
        assert row.state=='pending' and row.attempts==0 and row.lease_token is None


def test_reviewed_subscription_refund_cancels_future_billing_and_replay_cannot_restore_coverage(account, monkeypatch, tmp_path):
    from test_billing_subscriptions import Gateway, start, event_payload
    from test_payment_reconciliation import send
    from studio import payment_routes
    client, ws, base = account; gateway=Gateway()
    identity, job_id, gross = start(account, monkeypatch, tmp_path, gateway)
    authorize(account, monkeypatch)
    asyncio.run(execute_job(job_id))
    subscription, payment = event_payload(identity, gross)
    send(client, 'subscription.charged', {'subscription':subscription, 'payment':payment}, 'original-subscription')
    with session_scope() as db: order_id=db.scalar(select(PaymentOrder.id))
    path=f'/v1/operator/billing/workspaces/{ws}/payments/{order_id}/refunds'
    body={'amount_minor':gross,'reason':'Synthetic reviewed subscription refund'}
    headers={'Idempotency-Key':'operator-refund-fixture'}
    assert client.post(path,json=body,headers=headers).status_code==409
    monkeypatch.setattr(settings,'billing_operator_refunds_enabled',True)
    first=client.post(path,json=body,headers=headers)
    assert first.status_code==202,first.text
    assert first.json()['reserved_net_minor']==0
    assert client.post(path,json=body,headers=headers).json()['id']==first.json()['id']
    with session_scope() as db:
        cancel_id=db.scalar(select(Job.id).where(Job.kind=='billing_subscription_cancel'))
        refund_id=db.scalar(select(Job.id).where(Job.kind=='billing_refund'))
    async def refund_provider(method,path,**kwargs):
        if path.endswith('/refund'):
            return {'id':'rfnd_reviewed','payment_id':payment['id'],'amount':gross,'currency':'INR','status':'processed','receipt':first.json()['id']}
        return await gateway(method,path,**kwargs)
    monkeypatch.setattr(payment_routes,'provider',refund_provider)
    asyncio.run(execute_job(cancel_id));asyncio.run(execute_job(refund_id))
    send(client,'subscription.charged',{'subscription':subscription,'payment':payment},'replayed-refunded-charge')
    send(client,'subscription.activated',{'subscription':subscription},'late-active-status')
    with session_scope() as db:
        current=db.scalar(select(WorkspaceSubscription))
        assert current.state=='refund_review' and current.billing_blocked
        assert db.scalar(select(func.count()).select_from(PaymentRefund))==1
    resolve=f'/v1/operator/billing/workspaces/{ws}/resolve-refund-review'
    assert client.post(resolve,json={'reason':'Confirmed refunded coverage ended'}).json()['plan']=='free'
    send(client,'subscription.charged',{'subscription':subscription,'payment':payment},'replayed-after-review')
    with session_scope() as db: assert db.scalar(select(WorkspaceSubscription)).plan_slug=='free'


def test_financial_jobs_cannot_be_retried_or_cancelled_by_api_keys(account, monkeypatch):
    client, ws, base = account; authorize(account, monkeypatch)
    key=client.post(base+'/keys',json={'name':'Knowledge integration','scopes':['kb:write']}).json()['secret']
    with session_scope(write=True) as db:
        job=Job(workspace_id=ws,kind='billing_refund',state='failed',payload={'refund_id':'synthetic','errors':8})
        db.add(job);db.flush();identity=job.id
    assert client.post(base+'/jobs/'+identity+'/retry',json={},headers={'X-API-Key':key}).status_code==403
    assert client.post(base+'/jobs/'+identity+'/cancel',json={},headers={'X-API-Key':key}).status_code==403
    result=client.post(f'/v1/operator/billing/workspaces/{ws}/jobs/{identity}/retry',json={'reason':'Provider evidence has been reviewed'})
    assert result.status_code==202,result.text
    with session_scope() as db:
        job=db.get(Job,identity)
        assert job.state=='queued' and job.payload['errors']==0 and job.payload['refund_id']=='synthetic'


@pytest.mark.asyncio
async def test_operator_kill_stops_existing_idle_media_without_waiting_for_new_input(account,monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from studio.media import VoiceSession
    from studio.domain import default_agent
    client,ws,_=account;authorize(account,monkeypatch)
    with session_scope(write=True) as db:
        call=Call(workspace_id=ws,state='active');db.add(call);db.flush();identity=call.id
    socket=SimpleNamespace(close=AsyncMock())
    voice=VoiceSession(socket,ws,identity,default_agent(),'simulation')
    result=client.put(f'/v1/operator/billing/workspaces/{ws}/control',json={'paused':True,'reason':'Stop synthetic active media'})
    assert result.status_code==200
    await asyncio.wait_for(voice.watch_idle(),3)
    socket.close.assert_awaited_once()

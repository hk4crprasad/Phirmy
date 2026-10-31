from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json

from fastapi import HTTPException
import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from studio import admission, free_allowance, metering, plans, storage
from studio.config import settings
from studio.db import now, session_scope
from studio.models import BudgetAdmission, EmailOutbox, Membership, MeterEvent, User, Workspace


@pytest.fixture
def shared(account, monkeypatch, tmp_path):
    client, first, base = account
    body = plans.catalog()
    body.pop('content_hash')
    free = body['plans']['free']
    free['included'].update(conversations=3, chat_turns=3, crawl_pages=3, voice_ms=3000,
                            storage_bytes=10, widgets=2, seats=1)
    free['spend_cap_minor'] = 100
    path = tmp_path/'shared-free.json'
    path.write_text(json.dumps(body))
    monkeypatch.setattr(settings, 'plans_config_path', str(path))
    monkeypatch.setattr(settings, 'billing_development_allowances_enabled', False)
    response = client.post('/v1/workspaces', json={'name':'Second Free workspace','timezone':'Pacific/Auckland'})
    assert response.status_code == 201, response.text
    second = response.json()['id']
    user_id = client.get('/v1/auth/me').json()['user']['id']
    return client, first, second, user_id, base


@pytest.mark.parametrize('resource,quantity', [('conversations',2),('chat_turns',2),('crawl_pages',2),('voice_ms',2000)])
def test_monthly_free_allowances_cannot_be_multiplied_by_workspaces(shared, resource, quantity):
    _, first, second, user_id, _ = shared
    with session_scope(write=True) as db:
        metering.record_usage(db, first, 'actual:'+resource, resource, quantity)
    with pytest.raises(HTTPException, match='shared across your workspaces'):
        with session_scope(write=True) as db:
            admission.reserve(db, second, 'extra:'+resource, resources={resource:quantity})
    with session_scope() as db:
        assert free_allowance.snapshot(db,user_id)['usage'][resource] == quantity
        assert db.scalar(select(func.count()).select_from(EmailOutbox).where(EmailOutbox.operation_key.like('shared-free:%'))) == 1


def test_concurrent_cross_workspace_holds_share_one_pool(shared):
    _, first, second, _, _ = shared
    def attempt(pair):
        identity, workspace = pair
        try:
            with session_scope(write=True) as db:
                admission.reserve(db, workspace, 'racing:'+str(identity), resources={'chat_turns':2})
            return 'held'
        except HTTPException as error:
            assert error.status_code == 429
            return 'denied'
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, enumerate([first,second])))
    assert sorted(results) == ['denied','held']


def test_unknown_spend_survives_month_change_then_measured_usage_releases_remainder(shared, monkeypatch):
    _, first, second, _, _ = shared
    with session_scope(write=True) as db:
        admission.reserve(db,first,'unknown-cost',cost=60*metering.MICRO).state = 'unknown'
    with pytest.raises(HTTPException,match='shared across your workspaces'):
        with session_scope(write=True) as db:
            admission.reserve(db,second,'other-cost',cost=60*metering.MICRO)
    instant = now()+timedelta(days=40)
    with monkeypatch.context() as future:
        future.setattr(free_allowance,'now',lambda:instant)
        with pytest.raises(HTTPException,match='shared across your workspaces'):
            with session_scope(write=True) as db:
                admission.reserve(db,second,'future-cost',cost=60*metering.MICRO)
    with session_scope(write=True) as db:
        metering.record_cost(db,first,'unknown-cost','openai','llm',{'input_tokens':100},source='provider_usage')
        admission.reserve(db,second,'after-settlement',cost=90*metering.MICRO)


def test_storage_free_allowance_is_shared_before_second_write(shared):
    _, first, second, user_id, _ = shared
    storage.put_checked(first,'documents',b'12345678','text/plain')
    with pytest.raises(HTTPException,match='shared across your workspaces'):
        storage.put_checked(second,'documents',b'abcdefgh','text/plain')
    with session_scope() as db:
        assert free_allowance.snapshot(db,user_id)['usage']['storage_bytes'] == 8
        assert db.scalar(select(func.count()).select_from(BudgetAdmission).where(BudgetAdmission.workspace_id==second)) == 0


def test_paid_usage_excluded_without_resetting_preupgrade_free_history(shared):
    _, first, second, user_id, _ = shared
    with session_scope(write=True) as db:
        metering.record_usage(db,first,'free-before-upgrade','chat_turns',2)
        current = plans.subscription(db,first)
        current.plan_slug, current.state = 'starter','active'
        metering.record_usage(db,first,'paid-chat','chat_turns',50)
    with session_scope(write=True) as db:
        metering.record_usage(db,second,'last-free-turn','chat_turns',1)
        current = plans.subscription(db,first)
        current.plan_slug, current.state = 'free','free'
    with pytest.raises(HTTPException,match='shared across your workspaces'):
        with session_scope(write=True) as db:
            admission.reserve(db,second,'after-downgrade',resources={'chat_turns':1})
    with session_scope() as db:
        assert free_allowance.snapshot(db,user_id)['usage']['chat_turns'] == 3
        assert all(row.tariff_id for row in db.scalars(select(MeterEvent)))


def test_ownership_transfer_keeps_original_pool_and_anchor_is_immutable(shared):
    _, first, second, user_id, _ = shared
    with session_scope(write=True) as db:
        metering.record_usage(db,first,'before-transfer','chat_turns',2)
        other = User(name='New owner',email='new-owner@example.test',password_hash='synthetic-unused')
        db.add(other)
        db.flush()
        membership = db.scalar(select(Membership).where(Membership.workspace_id==first))
        membership.user_id = other.id
        other_id = other.id
    with pytest.raises(HTTPException,match='shared across your workspaces'):
        with session_scope(write=True) as db:
            admission.reserve(db,second,'after-transfer',resources={'chat_turns':2})
    with pytest.raises(IntegrityError,match='free allowance owner is immutable'):
        with session_scope(write=True) as db:
            db.execute(update(Workspace).where(Workspace.id==first).values(free_allowance_user_id=other_id))
    with session_scope() as db:
        assert db.get(Workspace,first).free_allowance_user_id == user_id


def test_shared_period_uses_utc_and_only_sponsor_browser_sees_aggregate(shared):
    client, first, _, _, base = shared
    summary = client.get(base+'/billing/usage')
    assert summary.status_code == 200
    shared_values = summary.json()['shared_free']
    assert shared_values['timezone'] == 'UTC' and shared_values['period_start'].endswith('00:00:00+00:00')
    key = client.post(base+'/keys',json={'name':'Free usage reader','scopes':['billing:read']}).json()['secret']
    assert client.get(base+'/billing/usage',headers={'X-API-Key':key}).json()['shared_free'] is None

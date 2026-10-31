"""Automatic allocation contracts. No external purchases, calls or identity checks."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select, func
from twilio.base.exceptions import TwilioRestException

from studio import number_provisioning as provisioning, phone_trials
from studio.config import settings
from studio.db import session_scope, now
from studio.models import (PhoneTrialPool, PhoneTrial, PhoneNumberOrder,
    PhoneNumberInventory, Number, Job, Membership, Workspace, APIKey)
from studio.security import digest
from studio.workers import execute_job


def carrier_number(e164='+12025550120', marker=None):
    return SimpleNamespace(phone_number=e164, sid='PN-synthetic-owned', account_sid='AC-synthetic-pool',
                           capabilities={'voice': True}, address_requirements='none', friendly_name=marker)


@pytest.fixture
def allocation(account, monkeypatch):
    client, ws, base = account
    monkeypatch.setattr(settings, 'twilio_account_sid', 'AC-synthetic-pool')
    monkeypatch.setattr(settings, 'twilio_auth_token', 'synthetic-token')
    monkeypatch.setattr(settings, 'phone_trials_enabled', True)
    monkeypatch.setattr(settings, 'phone_number_purchases_enabled', True)
    monkeypatch.setattr(settings, 'media_public_origin', 'https://synthetic.example.test')
    monkeypatch.setattr(settings, 'phone_number_max_monthly_price_minor', 150)
    monkeypatch.setattr(settings, 'phone_number_total_budget_minor', 1500)
    with session_scope(write=True) as db:
        pool = phone_trials.create_pool(db, name='Synthetic automatic pool', alert_email='owner@example.test',
                                       expires_at=now() + timedelta(days=19))
        pool.balance_state, pool.balance_minor, pool.balance_checked_at = 'ready', 1500, now()
        pool_id = pool.id
    monkeypatch.setattr(settings, 'phone_trial_auto_assign_pool_id', pool_id)
    sdk = MagicMock()
    sdk.pricing.v1.phone_numbers.countries.return_value.fetch.return_value = SimpleNamespace(
        price_unit='usd', phone_number_prices=[{'number_type': 'local', 'current_price': '1.15'}])
    sdk.available_phone_numbers.return_value.local.list.return_value = [carrier_number()]
    sdk.incoming_phone_numbers.create.side_effect = lambda **kw: carrier_number(kw['phone_number'], kw['friendly_name'])
    sdk.incoming_phone_numbers.list.return_value = []
    factory = MagicMock(return_value=sdk)
    monkeypatch.setattr('studio.carrier_config.twilio_client', factory)
    return client, ws, base, pool_id, sdk, factory


def request(allocation):
    client, _, base, _, _, _ = allocation
    response = client.post(base + '/phone-trial', json={})
    assert response.status_code == 202, response.text
    with session_scope() as db:
        order_id = db.scalar(select(PhoneNumberOrder.id))
    return order_id


def test_one_click_rents_server_selected_number_and_gives_seven_days(allocation):
    client, ws, base, pool_id, sdk, factory = allocation
    assert client.get(base + '/phone-trial').json()['can_request']
    order_id = request(allocation)
    request(allocation)
    with session_scope() as db:
        assert db.scalar(select(func.count()).select_from(Job).where(Job.kind == 'phone_number_allocate')) == 1
        job_id = db.scalar(select(Job.id).where(Job.kind == 'phone_number_allocate'))
    before = now()
    asyncio.run(execute_job(job_id))
    provisioning.allocate(order_id)
    assert sdk.incoming_phone_numbers.create.call_count == 1
    args = sdk.incoming_phone_numbers.create.call_args.kwargs
    assert args['phone_number'] == '+12025550120'
    assert args['friendly_name'] == provisioning.MARKER + order_id
    assert args['voice_url'].endswith('/twilio/answer') and args['status_callback_method'] == 'POST'
    sdk.available_phone_numbers.assert_called_once_with('US')
    assert sdk.available_phone_numbers.return_value.local.list.call_args.kwargs['exclude_all_address_required']
    factory.assert_called_once_with({'account_sid': 'AC-synthetic-pool', 'auth_token': 'synthetic-token', 'api_key': '', 'api_secret': ''}, timeout=10)
    result = client.get(base + '/phone-trial').json()
    assert result['number'] == '+12025550120' and result['status'] == 'active' and result['destinations'] == []
    assert 'synthetic-token' not in str(result) and pool_id not in str(result)
    with session_scope() as db:
        trial = db.scalar(select(PhoneTrial).where(PhoneTrial.workspace_id == ws))
        assert before + timedelta(days=7) <= trial.expires_at <= now() + timedelta(days=7)
        number = db.get(Number, trial.number_id)
        assert number.can_outbound and not number.can_inbound
        assert db.get(PhoneNumberOrder, order_id).quoted_price_minor == 115
        assert db.get(PhoneTrialPool, pool_id).workspaces_issued == 1


def test_users_cannot_choose_number_pool_price_or_other_user(allocation):
    client, _, base, _, sdk, _ = allocation
    for body in [{'number': '+12025550199'}, {'pool_id': 'arbitrary'}, {'price': 1}, {'user_id': 'other'}]:
        assert client.post(base + '/phone-trial', json=body).status_code == 422
    with session_scope() as db:
        assert db.scalar(select(func.count()).select_from(PhoneNumberOrder)) == 0
    sdk.incoming_phone_numbers.create.assert_not_called()
    from studio.main import create_app
    operation = create_app(start_worker=False).openapi()['paths']['/v1/workspaces/{workspace_id}/phone-trial']['post']
    assert operation['security'] == [{'DashboardSession': []}]


def test_two_clicks_and_workers_only_create_one_purchase(allocation):
    client, _, base, _, sdk, _ = allocation
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda _: client.post(base + '/phone-trial', json={}), range(2)))
    assert [r.status_code for r in responses] == [202, 202]
    with session_scope() as db:
        assert db.scalar(select(func.count()).select_from(PhoneNumberOrder)) == 1
        order_id = db.scalar(select(PhoneNumberOrder.id))
    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(provisioning.allocate, [order_id, order_id]))
    sdk.incoming_phone_numbers.create.assert_called_once()


def test_owned_stock_is_verified_and_assigned_without_purchase(allocation, monkeypatch):
    _, ws, _, pool_id, sdk, _ = allocation
    monkeypatch.setattr(settings, 'phone_number_purchases_enabled', False)
    sdk.incoming_phone_numbers.list.return_value = [carrier_number()]
    with session_scope(write=True) as db:
        inventory_id = provisioning.stock_number(db, pool_id, '+12025550120').id
    order_id = request(allocation)
    provisioning.allocate(order_id)
    with session_scope() as db:
        assert db.get(PhoneNumberInventory, inventory_id).assigned_order_id == order_id
        assert db.get(PhoneNumberOrder, order_id).state == 'assigned'
        assert not db.get(PhoneNumberOrder, order_id).purchase_reserved
    sdk.incoming_phone_numbers.create.assert_not_called()
    sdk.pricing.v1.phone_numbers.countries.assert_not_called()


def test_empty_stock_with_purchases_disabled_never_enqueues(allocation, monkeypatch):
    client, _, base, _, sdk, _ = allocation
    monkeypatch.setattr(settings, 'phone_number_purchases_enabled', False)
    assert not client.get(base + '/phone-trial').json()['can_request']
    assert client.post(base + '/phone-trial', json={}).status_code == 409
    sdk.incoming_phone_numbers.create.assert_not_called()


def test_one_owned_number_is_reserved_before_another_person_enrolls(allocation, monkeypatch):
    client, _, _, pool_id, sdk, _ = allocation
    monkeypatch.setattr(settings, 'phone_number_purchases_enabled', False)
    sdk.incoming_phone_numbers.list.return_value = [carrier_number()]
    with session_scope(write=True) as db:
        provisioning.stock_number(db, pool_id, '+12025550120')
    request(allocation)
    from conftest import bootstrap_account
    response = bootstrap_account(client, '/v1/auth/signup', json={'name': 'Second QA', 'email': 'stock-second@example.test',
        'password': 'Long-Second-QA-Password', 'workspace_name': 'Second QA'})
    assert response.status_code == 200
    client.headers['X-CSRF-Token'] = client.cookies['studio_csrf']
    other_base = '/v1/workspaces/' + response.json()['workspaces'][0]['id']
    assert not client.get(other_base + '/phone-trial').json()['can_request']
    assert client.post(other_base + '/phone-trial', json={}).status_code == 409
    with session_scope() as db:
        assert db.scalar(select(func.count()).select_from(PhoneNumberOrder)) == 1
    sdk.incoming_phone_numbers.create.assert_not_called()


@pytest.mark.parametrize('block', ['price', 'budget', 'balance', 'currency', 'expiry', 'paused', 'inventory', 'public_origin'])
def test_preflight_limits_never_issue_purchase(allocation, monkeypatch, block):
    _, _, _, pool_id, sdk, _ = allocation
    order_id = request(allocation)
    if block == 'price':
        sdk.pricing.v1.phone_numbers.countries.return_value.fetch.return_value.phone_number_prices[0]['current_price'] = '9.00'
    elif block == 'budget': monkeypatch.setattr(settings, 'phone_number_total_budget_minor', 100)
    elif block == 'public_origin': monkeypatch.setattr(settings, 'media_public_origin', '')
    elif block == 'inventory': sdk.available_phone_numbers.return_value.local.list.return_value = []
    else:
        with session_scope(write=True) as db:
            pool = db.get(PhoneTrialPool, pool_id)
            if block == 'balance': pool.balance_minor = 300
            elif block == 'currency':
                sdk.pricing.v1.phone_numbers.countries.return_value.fetch.return_value.price_unit = 'EUR'
            elif block == 'expiry': pool.expires_at = now() + timedelta(days=6)
            elif block == 'paused': pool.enabled = False
    provisioning.allocate(order_id)
    sdk.incoming_phone_numbers.create.assert_not_called()
    with session_scope() as db:
        assert db.get(PhoneNumberOrder, order_id).state == 'unavailable'


def test_uncertain_purchase_is_looked_up_and_never_purchased_twice(allocation):
    _, _, _, _, sdk, _ = allocation
    order_id = request(allocation)
    sdk.incoming_phone_numbers.create.side_effect = TimeoutError('synthetic uncertain outcome')
    provisioning.allocate(order_id)
    with session_scope() as db:
        order = db.get(PhoneNumberOrder, order_id)
        assert order.state == 'unknown' and order.purchase_reserved
    provisioning.allocate(order_id)
    assert sdk.incoming_phone_numbers.create.call_count == 1
    sdk.incoming_phone_numbers.list.return_value = [carrier_number(marker=provisioning.MARKER + order_id)]
    provisioning.reconcile(order_id)
    with session_scope() as db:
        assert db.get(PhoneNumberOrder, order_id).state == 'assigned'
    assert sdk.incoming_phone_numbers.create.call_count == 1


def test_wrong_marker_or_account_never_binds_an_uncertain_purchase(allocation):
    _, _, _, _, sdk, _ = allocation
    order_id = request(allocation)
    sdk.incoming_phone_numbers.create.side_effect = TimeoutError()
    sdk.incoming_phone_numbers.list.return_value = [carrier_number(marker='another-order')]
    provisioning.allocate(order_id)
    sdk.incoming_phone_numbers.list.return_value = [carrier_number(marker=provisioning.MARKER + order_id)]
    sdk.incoming_phone_numbers.list.return_value[0].account_sid = 'AC-another-account'
    provisioning.reconcile(order_id)
    with session_scope() as db:
        assert db.get(PhoneNumberOrder, order_id).state == 'unknown'
        assert db.scalar(select(func.count()).select_from(PhoneTrial)) == 0
    sdk.incoming_phone_numbers.create.assert_called_once()


def test_known_carrier_rejection_does_not_leave_a_budget_reservation(allocation):
    _, _, _, _, sdk, _ = allocation
    order_id = request(allocation)
    sdk.incoming_phone_numbers.create.side_effect = TwilioRestException(400, 'synthetic-uri', msg='Trial number limit')
    provisioning.allocate(order_id)
    with session_scope() as db:
        order = db.get(PhoneNumberOrder, order_id)
        assert order.state == 'unavailable' and not order.purchase_reserved
    provisioning.allocate(order_id)
    sdk.incoming_phone_numbers.create.assert_called_once()


def test_owner_membership_api_key_csrf_and_one_person_limit(allocation):
    client, ws, base, _, sdk, _ = allocation
    with session_scope(write=True) as db:
        membership = db.scalar(select(Membership).where(Membership.workspace_id == ws))
        user_id = membership.user_id
        membership.role = 'builder'
        db.add(APIKey(workspace_id=ws, name='Synthetic key', secret_hash=digest('synthetic-key'), prefix='test', scopes=['numbers:write']))
        other = Workspace(name='Other synthetic workspace'); db.add(other); db.flush()
        db.add(Membership(workspace_id=other.id, user_id=user_id, role='owner'))
        other_id = other.id
    assert client.post(base + '/phone-trial', json={}).status_code == 403
    assert client.post(base + '/phone-trial', json={}, headers={'X-API-Key': 'synthetic-key'}).status_code == 403
    assert client.post(base + '/phone-trial', json={}, headers={'X-CSRF-Token': 'wrong'}).status_code == 403
    assert client.post('/v1/workspaces/not-a-member/phone-trial', json={}).status_code == 404
    with session_scope(write=True) as db:
        db.scalar(select(Membership).where(Membership.workspace_id == ws)).role = 'owner'
    request(allocation)
    response = client.post('/v1/workspaces/' + other_id + '/phone-trial', json={})
    assert response.status_code == 409
    sdk.incoming_phone_numbers.create.assert_not_called()


def test_pending_order_reserves_pool_capacity_against_manual_grants(allocation):
    _, _, _, pool_id, _, _ = allocation
    with session_scope(write=True) as db:
        db.get(PhoneTrialPool, pool_id).max_workspaces = 1
        other = Workspace(name='Manual synthetic workspace'); db.add(other); db.flush(); other_id = other.id
    request(allocation)
    with session_scope(write=True) as db:
        with pytest.raises(ValueError, match='allowance'):
            phone_trials.grant_trial(db, pool_id, other_id, '+12025550130', ['+12025550131'])


def test_rental_budget_is_shared_across_pools_and_stale_balance_reservations(allocation, monkeypatch):
    client, _, _, _, sdk, _ = allocation
    monkeypatch.setattr(settings, 'phone_number_total_budget_minor', 150)
    first_id = request(allocation)
    provisioning.allocate(first_id)
    with session_scope(write=True) as db:
        second = phone_trials.create_pool(db, name='Second synthetic pool', alert_email='owner@example.test',
                                         expires_at=now() + timedelta(days=19))
        second.balance_state, second.balance_minor, second.balance_checked_at = 'ready', 1500, now()
        second_id = second.id
    monkeypatch.setattr(settings, 'phone_trial_auto_assign_pool_id', second_id)
    from conftest import bootstrap_account
    response = bootstrap_account(client, '/v1/auth/signup', json={'name': 'Second QA', 'email': 'second-qa@example.test',
        'password': 'Long-Second-QA-Password', 'workspace_name': 'Second QA'})
    assert response.status_code == 200
    client.headers['X-CSRF-Token'] = client.cookies['studio_csrf']
    ws2 = response.json()['workspaces'][0]['id']
    assert client.post('/v1/workspaces/' + ws2 + '/phone-trial', json={}).status_code == 202
    with session_scope() as db:
        order2 = db.scalar(select(PhoneNumberOrder.id).where(PhoneNumberOrder.workspace_id == ws2))
    sdk.available_phone_numbers.return_value.local.list.return_value = [carrier_number('+12025550121')]
    provisioning.allocate(order2)
    assert sdk.incoming_phone_numbers.create.call_count == 1
    with session_scope() as db:
        assert db.get(PhoneNumberOrder, first_id).state == 'assigned'
        assert db.get(PhoneNumberOrder, order2).state == 'unavailable'


@pytest.mark.parametrize('status', [408, 429, 500])
def test_ambiguous_provider_errors_keep_spend_reserved_and_never_retry_post(allocation, status):
    _, _, _, _, sdk, _ = allocation
    order_id = request(allocation)
    sdk.incoming_phone_numbers.create.side_effect = TwilioRestException(status, 'synthetic-uri', msg='synthetic response')
    provisioning.allocate(order_id)
    provisioning.allocate(order_id)
    with session_scope() as db:
        order = db.get(PhoneNumberOrder, order_id)
        assert order.state == 'unknown' and order.purchase_reserved
    sdk.incoming_phone_numbers.create.assert_called_once()


def test_quote_rejects_invalid_currency_and_amounts():
    for amount in ['NaN', 'Infinity', '-1', '0', 'not-a-price']:
        with pytest.raises(ValueError):
            provisioning.quote_minor(SimpleNamespace(price_unit='USD', phone_number_prices=[{'number_type': 'local', 'current_price': amount}]))
    assert provisioning.quote_minor(SimpleNamespace(price_unit='USD', phone_number_prices=[{'number_type': 'local', 'current_price': '1.001'}])) == 101


def test_api_key_pair_is_used_without_changing_signature_token(monkeypatch):
    from studio.carrier_config import twilio_client
    sdk = MagicMock()
    monkeypatch.setattr('twilio.rest.Client', sdk)
    carrier = {'account_sid': 'AC-synthetic', 'auth_token': 'callback-only-token', 'api_key': 'SK-synthetic', 'api_secret': 'synthetic-secret'}
    twilio_client(carrier)
    sdk.assert_called_once_with('SK-synthetic', 'synthetic-secret', account_sid='AC-synthetic')
    assert carrier['auth_token'] == 'callback-only-token'

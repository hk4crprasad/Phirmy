import copy
import json

import pytest
from sqlalchemy import func, select

from studio import admission, free_allowance, metering, plans
from studio.beta_allowances import apply_catalog
from studio.config import settings
from studio.db import session_scope
from studio.models import Audit, BudgetAdmission, MeterEvent, PlanCatalogSnapshot, WorkspaceSubscription


@pytest.fixture
def legacy(account, monkeypatch, tmp_path):
    client, workspace, _ = account
    monkeypatch.setattr(settings, 'billing_development_allowances_enabled', False)
    target = plans.catalog()
    target.pop('content_hash')
    old = copy.deepcopy(target)
    old['version'] = 'DRAFT-legacy-beta'
    old['plans']['free']['included'].update(conversations=50, chat_turns=500, voice_ms=300000,
        crawl_pages=1000, storage_bytes=500000000, seats=1, widgets=1)
    old['plans']['free']['spend_cap_minor'] = 5000
    path = tmp_path / 'beta.json'
    path.write_text(json.dumps(old))
    monkeypatch.setattr(settings, 'plans_config_path', str(path))
    with session_scope(write=True) as db:
        current = plans.subscription(db, workspace)
        original = current.catalog_id
        metering.record_usage(db, workspace, 'existing-beta-chat', 'chat_turns', 2)
        admission.reserve(db, workspace, 'unresolved-beta-cost', cost=100).state = 'unknown'
        current.spend_cap_minor = 12345
        current.operator_paused = True
    path.write_text(json.dumps(target))
    return client, workspace, original, target, path


def test_beta_adoption_dry_run_is_read_only_then_apply_preserves_accounting_and_is_idempotent(legacy):
    _, workspace, original, target, _ = legacy
    with session_scope() as db:
        count = db.scalar(select(func.count()).select_from(PlanCatalogSnapshot))
        result = apply_catalog(db, expected_version=target['version'])
        assert result['changed'] == 1 and not result['applied']
        assert plans.subscription(db, workspace).catalog_id == original
        assert db.scalar(select(func.count()).select_from(PlanCatalogSnapshot)) == count
    with session_scope(write=True) as db:
        result = apply_catalog(db, expected_version=target['version'], apply=True)
        assert result['changed'] == result['explicit_spend_caps_preserved'] == 1
    with session_scope(write=True) as db:
        current, limits, cap = admission.policy(db, workspace)
        assert current.catalog_id != original
        assert limits == target['plans']['free']['included'] and cap == 12345
        assert current.operator_paused and not current.billing_blocked
        assert db.scalar(select(MeterEvent)).quantity == 2
        hold = db.scalar(select(BudgetAdmission).where(
            BudgetAdmission.operation_key == metering.operation('unresolved-beta-cost')))
        assert hold.state == 'unknown' and hold.reserved_micro_minor == 100
        assert apply_catalog(db, expected_version=target['version'], apply=True)['unchanged'] == 1
        assert db.scalar(select(func.count()).select_from(Audit).where(
            Audit.action == 'billing.beta_allowance_granted')) == 1


def test_all_existing_free_workspaces_adopt_target_and_new_accounts_share_the_new_policy(legacy):
    client, first, _, target, _ = legacy
    second = client.post('/v1/workspaces', json={'name': 'Another beta workspace'}).json()['id']
    with session_scope(write=True) as db:
        # Another existing subscriber has the historical catalog, without a cap override.
        current = plans.subscription(db, second)
        current.catalog_id = plans.subscription(db, first).catalog_id
        result = apply_catalog(db, expected_version=target['version'], apply=True)
        assert result['changed'] == 2
        _, limits, cap = admission.policy(db, second)
        assert limits['voice_ms'] == 7200000 and cap == 150000
        shared = free_allowance.snapshot(db, free_allowance.sponsor(db, second))
        assert shared['included'] == limits and shared['usage']['chat_turns'] == 2
        assert shared['spend_cap_minor'] == cap
    third = client.post('/v1/workspaces', json={'name': 'New beta workspace'}).json()['id']
    with session_scope(write=True) as db:
        _, limits, _ = admission.policy(db, third)
        assert limits == target['plans']['free']['included']


def test_paid_subscriptions_are_untouched_and_wrong_version_cannot_apply(legacy):
    _, workspace, original, target, _ = legacy
    with session_scope(write=True) as db:
        row = plans.subscription(db, workspace)
        row.plan_slug, row.state = 'starter', 'active'
        assert apply_catalog(db, expected_version=target['version'], apply=True)['free_workspaces'] == 0
        assert row.catalog_id == original and row.spend_cap_minor == 12345
        with pytest.raises(ValueError, match='matching DRAFT'):
            apply_catalog(db, expected_version='wrong-version', apply=True)


def test_decreasing_beta_catalog_is_rejected_without_changing_subscription(legacy):
    _, workspace, original, target, path = legacy
    target['plans']['free']['included']['voice_ms'] = 100
    path.write_text(json.dumps(target))
    with session_scope(write=True) as db:
        with pytest.raises(ValueError, match='must not reduce'):
            apply_catalog(db, expected_version=target['version'], apply=True)
        assert plans.subscription(db, workspace).catalog_id == original

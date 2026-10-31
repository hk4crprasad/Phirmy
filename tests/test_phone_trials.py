"""Phone demo budgets and lifecycle, without calls, SMTP or carrier purchases."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock
import pytest
from sqlalchemy import select, func
from twilio.request_validator import RequestValidator
from studio import phone_trials as trials, account_routes, llm, twilio_routes
from studio.config import settings
from studio.db import now, session_scope
from studio.models import PhoneTrial, PhoneTrialPool, PhoneTrialAlert, Number, Call, Job, Wallet, Notification
from studio.workers import execute_job


@pytest.fixture
def trial_sample(sample, monkeypatch):
    client, ws, base, fixture = sample
    monkeypatch.setattr(settings, 'phone_trials_enabled', True)
    monkeypatch.setattr(settings, 'live_calls_enabled', True)
    monkeypatch.setattr(settings, 'media_public_origin', 'https://voice.example.test')
    monkeypatch.setattr(settings, 'twilio_account_sid', 'AC-test-original')
    monkeypatch.setattr(settings, 'twilio_auth_token', 'test-original-token')
    monkeypatch.setattr(llm, 'live_voice_ready', lambda *args: True)
    monkeypatch.setattr(twilio_routes, 'live_voice_ready', lambda *args: True)
    with session_scope(write=True) as db:
        pool = trials.create_pool(db, name='Offline QA', expires_at=now() + timedelta(days=19), alert_email='owner@example.test')
        pool.balance_state, pool.balance_minor, pool.balance_checked_at = 'ready', 1500, now()
        trial = trials.grant_trial(db, pool.id, ws, '+12025550110', ['+12025550111'])
        number = db.get(Number, trial.number_id)
        number.status, number.can_outbound = 'active', True
        wallet = db.scalar(select(Wallet).where(Wallet.workspace_id == ws)); wallet.balance_minor = 0
        ids = {'pool': pool.id, 'trial': trial.id, 'number': number.id}
    monkeypatch.setattr(settings, 'twilio_account_sid', '')
    monkeypatch.setattr(settings, 'twilio_auth_token', '')
    return client, ws, base, fixture, ids


def queue(sample, key='trial-1', **overrides):
    client, ws, base, fixture, ids = sample
    body = {'agent_id': fixture['agent_id'], 'mode': 'live', 'number_id': ids['number'], 'destination': '+12025550111', 'budget_minor': 100}
    return client.post(base + '/calls/outbound', json=body | overrides, headers={'Idempotency-Key': key})


def test_trial_admission_zero_wallet_idempotency_and_tenant_redaction(trial_sample):
    response = queue(trial_sample)
    assert response.status_code == 202, response.text
    assert queue(trial_sample).json()['id'] == response.json()['id']
    client, ws, base, _, ids = trial_sample
    data = client.get(base + '/bootstrap').json()
    assert data['summary']['phone_trial']['calls_remaining'] == 2
    assert 'test-original-token' not in str(data) and 'encrypted_credentials' not in str(data)
    with session_scope() as db:
        assert db.get(PhoneTrial, ids['trial']).calls_used == 1
        assert db.scalar(select(Wallet).where(Wallet.workspace_id == ws)).balance_minor == 0
    assert client.post(base + '/phone-trials', json={'max_calls': 100}).status_code == 404


def test_trial_rejects_destination_and_parallel_admissions(trial_sample):
    assert queue(trial_sample, destination='+12025559999').status_code == 409
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda key: queue(trial_sample, key).status_code, ['parallel-1', 'parallel-2']))
    assert sorted(results) == [202, 429]


def test_trial_reservations_are_bounded_and_failures_do_not_reset_them(trial_sample):
    _, _, _, _, ids = trial_sample
    for index in range(3):
        response = queue(trial_sample, 'bounded-' + str(index))
        assert response.status_code == 202
        with session_scope(write=True) as db:
            from studio.domain import settle_call
            settle_call(db, db.get(Call, response.json()['id']), 0, 'failed')
    assert queue(trial_sample, 'bounded-4').status_code == 429
    with session_scope() as db:
        assert db.get(PhoneTrial, ids['trial']).calls_used == 3
        assert db.scalar(select(func.count()).select_from(PhoneTrialAlert).where(PhoneTrialAlert.pool_id == ids['pool'])) == 1


@pytest.mark.parametrize('condition', ['expired', 'low_balance', 'stale_balance', 'disabled', 'revoked'])
def test_trial_blocks_unavailable_allowance(trial_sample, condition):
    _, _, _, _, ids = trial_sample
    with session_scope(write=True) as db:
        pool = db.get(PhoneTrialPool, ids['pool'])
        if condition == 'expired': pool.expires_at = now() - timedelta(seconds=1)
        elif condition == 'low_balance': pool.balance_minor = 200
        elif condition == 'stale_balance': pool.balance_checked_at = now() - timedelta(minutes=11)
        elif condition == 'disabled': pool.enabled = False
        else: db.get(PhoneTrial, ids['trial']).enabled = False
    assert queue(trial_sample).status_code == 409
    with session_scope() as db:
        assert db.get(PhoneTrial, ids['trial']).calls_used == 0


def test_queued_expiry_is_rechecked_before_any_provider_request(trial_sample, monkeypatch):
    response = queue(trial_sample)
    assert response.status_code == 202
    client, _, _, _, ids = trial_sample
    sdk = MagicMock()
    monkeypatch.setattr('twilio.rest.Client', sdk)
    with session_scope(write=True) as db:
        db.get(PhoneTrialPool, ids['pool']).expires_at = now() - timedelta(seconds=1)
        job = db.scalar(select(Job).where(Job.kind == 'outbound')); job_id = job.id
    asyncio.run(execute_job(job_id))
    sdk.assert_not_called()
    with session_scope() as db:
        assert db.get(Call, response.json()['id']).state == 'failed'
        assert db.get(PhoneTrial, ids['trial']).calls_used == 1


def test_trial_dispatch_uses_pinned_account_and_provider_time_limit(trial_sample, monkeypatch):
    response = queue(trial_sample)
    assert response.status_code == 202
    sdk = MagicMock()
    sdk.return_value.calls.create.return_value = SimpleNamespace(sid='CA-test-dispatch')
    monkeypatch.setattr('twilio.rest.Client', sdk)
    monkeypatch.setattr(settings, 'twilio_account_sid', 'AC-other-environment')
    monkeypatch.setattr(settings, 'twilio_auth_token', 'other-environment-token')
    with session_scope() as db:
        job_id = db.scalar(select(Job.id).where(Job.kind == 'outbound'))
    asyncio.run(execute_job(job_id))
    sdk.assert_called_once_with('AC-test-original', 'test-original-token')
    params = sdk.return_value.calls.create.call_args.kwargs
    assert params['time_limit'] == 60 and params['from_'] == '+12025550110'
    assert params['to'] == '+12025550111'


def test_trial_number_is_verified_against_pool_and_never_inbound(trial_sample, monkeypatch):
    sdk = MagicMock()
    sdk.return_value.incoming_phone_numbers.list.return_value = [SimpleNamespace(sid='PN-test', capabilities={'voice': True})]
    monkeypatch.setattr('twilio.rest.Client', sdk)
    with session_scope() as db:
        job_id = db.scalar(select(Job.id).where(Job.kind == 'verify_number'))
    asyncio.run(execute_job(job_id))
    sdk.assert_called_once_with('AC-test-original', 'test-original-token')
    with session_scope() as db:
        number = db.get(Number, trial_sample[4]['number'])
        assert number.can_outbound and not number.can_inbound and number.provider_number_id == 'PN-test'


def test_trial_campaigns_are_rejected(trial_sample):
    client, _, base, fixture, ids = trial_sample
    agent = client.get(base + '/agents/' + fixture['agent_id']).json()
    response = client.post(base + '/campaigns', json={'name': 'No bulk trial', 'agent_version_id': agent['published_version_id'], 'mode': 'live', 'number_id': ids['number']})
    assert response.status_code == 409 and 'individual' in response.text


def test_trial_number_cannot_open_an_inbound_call(trial_sample):
    client, _, _, fixture, ids = trial_sample
    with session_scope(write=True) as db:
        number = db.get(Number, ids['number'])
        number.can_inbound, number.agent_id = True, fixture['agent_id']
    path = '/v1/provider-webhooks/twilio/answer'
    form = {'AccountSid': 'AC-test-original', 'CallSid': 'CA-inbound-trial', 'To': '+12025550110', 'From': '+12025550111'}
    signature = RequestValidator('test-original-token').compute_signature(settings.media_public_origin + path, form)
    response = client.post(path, data=form, headers={'X-Twilio-Signature': signature})
    assert response.status_code == 200 and 'Hangup' in response.text and 'Stream' not in response.text
    with session_scope() as db:
        assert db.scalar(select(Call.id).where(Call.provider_call_id == 'CA-inbound-trial')) is None


def test_unassigned_numbers_cannot_use_platform_trial_credentials(trial_sample, monkeypatch):
    client, _, base, fixture, _ = trial_sample
    monkeypatch.setattr(settings, 'twilio_account_sid', 'AC-platform')
    monkeypatch.setattr(settings, 'twilio_auth_token', 'platform-token')
    number = client.post(base + '/numbers', json={'provider': 'twilio', 'e164': '+12025550119'})
    assert number.status_code == 202 and number.json()['status'] == 'unverified'
    response = queue(trial_sample, number_id=number.json()['id'])
    assert response.status_code == 409
    with session_scope() as db:
        assert not any(job.payload.get('number_id') == number.json()['id'] for job in db.scalars(select(Job).where(Job.kind == 'verify_number')))


@pytest.mark.parametrize('balance,currency,expected', [('1.99', 'USD', 'ready'), ('NaN', 'USD', 'unavailable'), ('15', 'EUR', 'unavailable')])
def test_balance_monitor_uses_exact_currency_and_deduplicates_alerts(trial_sample, monkeypatch, balance, currency, expected):
    sdk = MagicMock()
    sdk.return_value.balance.fetch.return_value = SimpleNamespace(balance=balance, currency=currency)
    monkeypatch.setattr('twilio.rest.Client', sdk)
    with session_scope(write=True) as db:
        db.get(PhoneTrialPool, trial_sample[4]['pool']).balance_checked_at = now() - timedelta(minutes=6)
    trials.check_balances(); trials.check_balances()
    sdk.return_value.balance.fetch.assert_called_once()
    with session_scope() as db:
        pool = db.get(PhoneTrialPool, trial_sample[4]['pool'])
        assert pool.balance_state == expected
        assert db.scalar(select(func.count()).select_from(PhoneTrialAlert)) == 1
    assert queue(trial_sample).status_code == 409


def test_expiry_alert_smtp_retry_and_workspace_notice_are_durable(trial_sample, monkeypatch):
    from studio import mail_outbox
    from studio.models import EmailOutbox
    mail_outbox.process_outbox(20)
    with session_scope(write=True) as db:
        db.get(PhoneTrialPool, trial_sample[4]['pool']).expires_at = now() + timedelta(hours=12)
        db.get(PhoneTrial, trial_sample[4]['trial']).expires_at = now() + timedelta(hours=13)
    send = MagicMock(side_effect=OSError('synthetic SMTP outage'))
    monkeypatch.setattr(mail_outbox, 'deliver_message', send)
    trials.process_alerts()
    assert mail_outbox.process_outbox() == 0
    send.assert_called_once()
    with session_scope(write=True) as db:
        alert = db.scalar(select(PhoneTrialAlert).where(PhoneTrialAlert.state == 'queued'))
        mail = db.scalar(select(EmailOutbox).where(EmailOutbox.operation_key == 'phone-trial:' + alert.id))
        assert mail.attempts == 1 and mail.next_attempt_at > now() and mail.state == 'pending'
        mail.next_attempt_at = now() - timedelta(seconds=1)
    send.side_effect = None
    assert mail_outbox.process_outbox() == 1
    trials.process_alerts(); trials.process_alerts()
    assert send.call_count == 2
    with session_scope() as db:
        assert db.scalar(select(func.count()).select_from(PhoneTrialAlert).where(PhoneTrialAlert.state == 'sent')) == 1
        assert db.scalar(select(func.count()).select_from(Notification).where(Notification.kind == 'phone_trial.expires_24h')) == 1


def test_replacement_preserves_usage_expiry_and_old_callback_account(trial_sample, monkeypatch):
    response = queue(trial_sample)
    with session_scope(write=True) as db:
        from studio.domain import settle_call
        call = db.get(Call, response.json()['id']); call.provider_call_id = 'CA-old-complete'
        settle_call(db, call, 0, 'completed')
        old_expiry = db.get(PhoneTrial, trial_sample[4]['trial']).expires_at
    monkeypatch.setattr(settings, 'twilio_account_sid', 'AC-test-replacement')
    monkeypatch.setattr(settings, 'twilio_auth_token', 'replacement-token')
    with session_scope(write=True) as db:
        pool = trials.create_pool(db, name='Replacement', expires_at=now() + timedelta(days=20), alert_email='owner@example.test')
        trial = trials.replace_binding(db, trial_sample[1], pool.id, '+12025550112')
        assert trial.calls_used == 1 and trial.expires_at == old_expiry and trial.max_calls == 3
        assert db.get(Number, trial_sample[4]['number']).status == 'inactive'
    # A delayed signed callback still resolves the original account after reassignment.
    client = trial_sample[0]
    path = '/v1/provider-webhooks/twilio/status?call_id=' + response.json()['id']
    form = {'AccountSid': 'AC-test-original', 'CallSid': 'CA-old-complete', 'CallStatus': 'completed'}
    signature = RequestValidator('test-original-token').compute_signature(settings.media_public_origin + path, form)
    assert client.post(path, data=form, headers={'X-Twilio-Signature': signature}).status_code == 200


def test_grants_cannot_exceed_pool_capacity_or_be_reissued(trial_sample):
    _, ws, _, _, ids = trial_sample
    with session_scope(write=True) as db:
        with pytest.raises(ValueError, match='already received'):
            trials.grant_trial(db, ids['pool'], ws, '+12025550112', ['+12025550111'])
        pool = db.get(PhoneTrialPool, ids['pool']); pool.max_workspaces = 1
        from studio.models import Workspace
        other = Workspace(name='Capacity QA'); db.add(other); db.flush()
        with pytest.raises(ValueError, match='lifetime'):
            trials.grant_trial(db, ids['pool'], other.id, '+12025550112', ['+12025550111'])


def test_operator_cli_configures_grants_and_pauses_without_revealing_credentials(sample):
    import os
    import subprocess
    import sys
    from pathlib import Path
    env = os.environ | {'TWILIO_ACCOUNT_SID': 'AC-cli-synthetic', 'TWILIO_AUTH_TOKEN': 'synthetic-cli-token', 'BETA_OPERATOR_EMAIL': 'owner@example.test'}
    root = Path(__file__).resolve().parents[1]
    def run(*args):
        result = subprocess.run([sys.executable, 'scripts/manage_phone_trials.py', *args], cwd=root, env=env, capture_output=True, text=True)
        assert result.returncode == 0, result.stdout
        assert 'synthetic-cli-token' not in result.stdout and 'AC-cli-synthetic' not in result.stdout
        return result.stdout
    result = run('configure', '--days', '20')
    pool_id = result.splitlines()[0].removeprefix('Configured pool: ').strip()
    run('grant', '--pool-id', pool_id, '--workspace-id', sample[1], '--number', '+12025550110', '--destination', '+12025550111')
    assert '"workspaces_issued": 1' in run('status')
    run('pause', '--pool-id', pool_id)
    with session_scope() as db:
        assert not db.get(PhoneTrialPool, pool_id).enabled

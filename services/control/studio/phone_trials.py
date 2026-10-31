"""Operator-funded, bounded outbound entitlements and lifecycle checks."""
from datetime import timedelta
from decimal import Decimal, ROUND_FLOOR
import json
import re
from fastapi import HTTPException
from sqlalchemy import select
from .config import settings
from .db import now, session_scope
from .models import PhoneTrialPool, PhoneTrial, PhoneTrialAlert, Number, Workspace, Notification, Call
from .secrets import encrypt, decrypt

BALANCE_FRESHNESS = timedelta(minutes=10)


def create_pool(db, *, name, expires_at, alert_email, max_workspaces=10,
                calls_per_workspace=3, seconds_per_call=60, low_balance_minor=200, currency='USD'):
    if expires_at.tzinfo is None or not now() < expires_at <= now() + timedelta(days=20):
        raise ValueError('Choose a timezone-aware expiry within the next 20 days')
    if not 1 <= max_workspaces <= 20 or not 1 <= calls_per_workspace <= 10 or not 15 <= seconds_per_call <= 120:
        raise ValueError('Use 1–20 workspaces, 1–10 calls each and 15–120 seconds per call')
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', alert_email) or len(alert_email) > 254:
        raise ValueError('Supply the operator email for expiry and balance alerts')
    if not re.fullmatch(r'[A-Z]{3}', currency) or low_balance_minor < 1:
        raise ValueError('Set a three-letter currency and a positive balance floor')
    if not settings.twilio_account_sid or not settings.twilio_auth_token:
        raise ValueError('Configure TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN privately first')
    if bool(settings.twilio_api_key) != bool(settings.twilio_api_secret):
        raise ValueError('Supply both TWILIO_API_KEY and TWILIO_API_SECRET')
    # Keep the old binding for callbacks/hangups if the environment is changed later.
    pool = PhoneTrialPool(name=name[:120], expires_at=expires_at, alert_email=alert_email,
                         max_workspaces=max_workspaces, calls_per_workspace=calls_per_workspace,
                         seconds_per_call=seconds_per_call, low_balance_minor=low_balance_minor, currency=currency,
                         encrypted_credentials=encrypt(json.dumps({'account_sid': settings.twilio_account_sid,
                                                                  'auth_token': settings.twilio_auth_token,
                                                                  'api_key': settings.twilio_api_key, 'api_secret': settings.twilio_api_secret})))
    db.add(pool); db.flush()
    return pool


def grant_trial(db, pool_id, workspace_id, e164, destinations, *, reservation_id=None, verify=True):
    pool = db.scalar(select(PhoneTrialPool).where(PhoneTrialPool.id == pool_id).with_for_update())
    if not pool or not pool.enabled or pool.expires_at <= now():
        raise ValueError('Select an enabled, unexpired trial pool')
    if not db.get(Workspace, workspace_id):
        raise ValueError('Workspace not found')
    if db.scalar(select(PhoneTrial.id).where(PhoneTrial.workspace_id == workspace_id)):
        raise ValueError('This workspace already received a phone trial')
    from .number_provisioning import reserved_slots
    if pool.workspaces_issued + reserved_slots(db, pool_id, reservation_id) >= pool.max_workspaces:
        raise ValueError('This pool has reached its lifetime workspace allowance')
    minimum_destinations = 0 if reservation_id else 1
    if not re.fullmatch(r'\+[1-9]\d{6,14}', e164) or not minimum_destinations <= len(destinations) <= 5 or any(not re.fullmatch(r'\+[1-9]\d{6,14}', x) for x in destinations):
        raise ValueError('Use an owned E.164 source and 1–5 verified, consenting test destinations')
    number = db.scalar(select(Number).where(Number.provider == 'twilio', Number.e164 == e164))
    if number and number.workspace_id != workspace_id:
        raise ValueError('That number is assigned to another workspace')
    if not number:
        number = Number(workspace_id=workspace_id, provider='twilio', e164=e164)
        db.add(number); db.flush()
    # Always prove ownership against this pool, even if a different binding verified it earlier.
    number.status, number.can_inbound, number.can_outbound, number.agent_id = 'unverified', False, False, None
    trial = PhoneTrial(workspace_id=workspace_id, pool_id=pool.id, number_id=number.id,
                       expires_at=min(pool.expires_at, now() + timedelta(days=7)), destinations=list(dict.fromkeys(destinations)),
                       max_calls=pool.calls_per_workspace, seconds_per_call=pool.seconds_per_call)
    pool.workspaces_issued += 1
    db.add(trial); db.flush()
    from .domain import enqueue
    if verify:
        enqueue(db, workspace_id, 'verify_number', {'number_id': number.id})
    if verify:
        db.add(Notification(workspace_id=workspace_id, kind='phone_trial.granted', title='Your phone trial is being prepared',
                            description='Your assigned number is being verified. Check Phone numbers for your allowance and expiry.', href='/app/numbers'))
    return trial


def replace_binding(db, workspace_id, pool_id, e164):
    """Explicit operator reassignment; keep the original expiry and used allowance."""
    trial = db.scalar(select(PhoneTrial).where(PhoneTrial.workspace_id == workspace_id).with_for_update())
    pool = db.scalar(select(PhoneTrialPool).where(PhoneTrialPool.id == pool_id).with_for_update())
    if not trial or not trial.enabled or trial.expires_at <= now() or not pool or not pool.enabled or pool.expires_at <= now():
        raise ValueError('An enabled, unexpired workspace trial and replacement pool are required')
    if pool.workspaces_issued >= pool.max_workspaces or not re.fullmatch(r'\+[1-9]\d{6,14}', e164):
        raise ValueError('Replacement pool capacity or number is unavailable')
    if db.scalar(select(Call.id).where(Call.workspace_id == workspace_id, Call.mode == 'live',
                    Call.state.in_(['created', 'connecting', 'ringing', 'connected', 'ending'])).limit(1)):
        raise ValueError('Finish or reconcile outstanding calls before replacing the binding')
    if db.scalar(select(Number.id).where(Number.provider == 'twilio', Number.e164 == e164)):
        raise ValueError('Use a replacement number that is not already registered')
    old = db.get(Number, trial.number_id)
    old.status, old.can_inbound, old.can_outbound, old.agent_id = 'inactive', False, False, None
    number = Number(workspace_id=workspace_id, provider='twilio', e164=e164)
    db.add(number); db.flush()
    trial.pool_id, trial.number_id = pool.id, number.id
    trial.expires_at = min(trial.expires_at, pool.expires_at)
    trial.max_calls, trial.seconds_per_call = min(trial.max_calls, pool.calls_per_workspace), min(trial.seconds_per_call, pool.seconds_per_call)
    pool.workspaces_issued += 1
    from .domain import enqueue
    enqueue(db, workspace_id, 'verify_number', {'number_id': number.id})
    return trial


def for_number(db, number_id):
    return db.scalar(select(PhoneTrial).where(PhoneTrial.number_id == number_id)) if number_id else None


def pool_credentials(pool_id):
    with session_scope() as db:
        pool = db.get(PhoneTrialPool, pool_id)
        if not pool:
            raise ValueError('Phone trial binding is unavailable')
        return json.loads(decrypt(pool.encrypted_credentials))


def pool_problem(pool):
    if not settings.phone_trials_enabled or not pool.enabled:
        return 'paused', 'Phone trials are paused. Contact your workspace administrator.'
    if pool.expires_at <= now():
        return 'expired', 'This phone trial has ended.'
    if pool.balance_state != 'ready' or not pool.balance_checked_at or now() - pool.balance_checked_at > BALANCE_FRESHNESS:
        return 'balance_unavailable', 'Phone calls are paused while the provider balance is checked.'
    if pool.balance_minor is None or pool.balance_minor <= pool.low_balance_minor:
        return 'low_balance', 'Phone calls are paused because the provider allowance is low.'
    return None


def trial_status(db, workspace_id):
    trial = db.scalar(select(PhoneTrial).where(PhoneTrial.workspace_id == workspace_id))
    if not trial:
        from .number_provisioning import allocation_status
        return allocation_status(db, workspace_id)
    pool, number = db.get(PhoneTrialPool, trial.pool_id), db.get(Number, trial.number_id)
    problem = pool_problem(pool)
    if not trial.enabled:
        problem = ('paused', 'Your phone trial has been paused.')
    elif trial.expires_at <= now():
        problem = ('expired', 'Your phone trial has ended.')
    elif not problem and trial.calls_used >= trial.max_calls:
        problem = ('exhausted', 'You have used your phone trial allowance.')
    elif not problem and (not number or number.status != 'active' or not number.can_outbound):
        problem = ('verifying', 'Your assigned phone number is being verified.')
    return {'status': problem[0] if problem else 'active', 'message': problem[1] if problem else 'Your phone trial is ready.',
            'expires_at': min(trial.expires_at, pool.expires_at).isoformat(), 'calls_used': trial.calls_used,
            'calls_remaining': max(0, trial.max_calls - trial.calls_used), 'max_calls': trial.max_calls,
            'seconds_per_call': trial.seconds_per_call, 'number_id': trial.number_id, 'number': number.e164 if number else None,
            'destinations': trial.destinations}


def _binding(db, call):
    trial_id = call.metadata_data.get('phone_trial_id')
    trial = db.get(PhoneTrial, trial_id) if trial_id else None
    if not trial or trial.workspace_id != call.workspace_id or trial.number_id != call.metadata_data.get('number_id'):
        raise HTTPException(409, 'Phone trial reservation is unavailable')
    pool = db.get(PhoneTrialPool, trial.pool_id)
    if call.metadata_data.get('phone_trial_pool_id') != pool.id:
        raise HTTPException(409, 'Phone trial account binding differs')
    return trial, pool


def call_seconds(db, call):
    trial, pool = _binding(db, call)
    problem = pool_problem(pool)
    if problem or not trial.enabled or trial.expires_at <= now():
        raise HTTPException(409, problem[1] if problem else 'Your phone trial has ended or was paused')
    number = db.get(Number, trial.number_id)
    if not number or number.status != 'active' or not number.can_outbound or call.destination not in trial.destinations:
        raise HTTPException(409, 'Phone trial number or approved destination is unavailable')
    seconds = min(trial.seconds_per_call, pool.seconds_per_call, int((min(pool.expires_at, trial.expires_at) - now()).total_seconds()),
                  call.metadata_data.get('phone_trial_seconds', trial.seconds_per_call))
    if seconds < 1:
        raise HTTPException(409, 'Your phone trial has ended')
    return seconds


def admit_call(db, call):
    trial = for_number(db, call.metadata_data.get('number_id'))
    if not trial:
        return False
    # Workspace lock serializes reservations independently of campaign/HTTP workers.
    db.scalar(select(Workspace).where(Workspace.id == call.workspace_id).with_for_update())
    trial = db.scalar(select(PhoneTrial).where(PhoneTrial.id == trial.id).with_for_update().execution_options(populate_existing=True))
    pool = db.get(PhoneTrialPool, trial.pool_id)
    if trial.calls_used >= trial.max_calls:
        raise HTTPException(429, 'You have used your phone trial allowance')
    active = db.scalar(select(Call.id).where(Call.workspace_id == call.workspace_id, Call.mode == 'live', Call.transport == 'pstn',
                       Call.id != call.id, Call.state.in_(['created', 'connecting', 'ringing', 'connected', 'ending'])).limit(1))
    if active:
        raise HTTPException(429, 'Finish your current phone call before starting another')
    call.metadata_data = {**call.metadata_data, 'phone_trial_id': trial.id, 'phone_trial_pool_id': pool.id,
                          'phone_trial_seconds': pool.seconds_per_call, 'budget_minor': 0, 'provider': 'twilio'}
    seconds = call_seconds(db, call)
    call.metadata_data = {**call.metadata_data, 'phone_trial_seconds': seconds}
    trial.calls_used += 1
    # Reservations count even if the provider outcome is uncertain; no automatic credit reset.
    if trial.calls_used == trial.max_calls:
        queue_alert(db, pool, 'exhausted:' + trial.id, 'Phone trial allowance reserved',
                    'Workspace ' + call.workspace_id + ' has reserved its final trial call.', trial.workspace_id)
    db.flush()
    return True


def queue_alert(db, pool, key, subject, body, workspace_id=None, email=True):
    operation = pool.id + ':' + key
    if db.scalar(select(PhoneTrialAlert.id).where(PhoneTrialAlert.operation_key == operation)):
        return
    db.add(PhoneTrialAlert(pool_id=pool.id, operation_key=operation, subject=subject, state='pending' if email else 'notice',
                          body=body + '\n\nReview Phone numbers and provider settings: ' + settings.app_origin.rstrip('/') + '/app/numbers'))
    if workspace_id:
        db.add(Notification(workspace_id=workspace_id, kind='phone_trial.' + key.split(':')[0], title=subject,
                            description=body[:500], href='/app/numbers'))


def check_balances():
    """Read-only carrier API checks; unknown/stale balances block new demo calls."""
    if not settings.phone_trials_enabled:
        return
    with session_scope() as db:
        ids = list(db.scalars(select(PhoneTrialPool.id).where(PhoneTrialPool.enabled.is_(True), PhoneTrialPool.expires_at > now())))
    for pool_id in ids:
        with session_scope() as db:
            pool = db.get(PhoneTrialPool, pool_id)
            if pool.balance_checked_at and now() - pool.balance_checked_at < timedelta(minutes=5):
                continue
            currency = pool.currency
        balance, state = None, 'unavailable'
        try:
            from .carrier_config import twilio_client
            creds = pool_credentials(pool_id)
            result = twilio_client(creds, timeout=10).balance.fetch()
            amount = Decimal(result.balance)
            if result.currency.upper() != currency or not amount.is_finite():
                raise ValueError('Provider balance currency or amount is unavailable')
            balance, state = int((amount * 100).to_integral_value(rounding=ROUND_FLOOR)), 'ready'
        except Exception:
            # Provider failures can include auth/DSN details; never persist the exception.
            pass
        with session_scope(write=True) as db:
            pool = db.get(PhoneTrialPool, pool_id)
            pool.balance_minor, pool.balance_state, pool.balance_checked_at = balance, state, now()
            if state != 'ready' or balance <= pool.low_balance_minor:
                condition = 'balance_unavailable' if state != 'ready' else 'low_balance'
                queue_alert(db, pool, condition + ':' + now().date().isoformat(), 'Phone trial provider needs attention',
                            'Pool ' + pool.name + ': balance check unavailable.' if state != 'ready' else
                            'Pool ' + pool.name + ': balance is at or below the configured floor. New trial calls are paused.')


def process_alerts():
    from .models import EmailOutbox
    from .mail_outbox import enqueue_email
    with session_scope(write=True) as db:
        for alert, mail in db.execute(select(PhoneTrialAlert, EmailOutbox).join(
                EmailOutbox, EmailOutbox.operation_key == 'phone-trial:' + PhoneTrialAlert.id).where(
                    PhoneTrialAlert.state == 'queued')):
            if mail.state == 'sent':
                alert.state, alert.sent_at = 'sent', mail.sent_at
            elif mail.state == 'failed':
                alert.state = 'failed'
        for pool in db.scalars(select(PhoneTrialPool)):
            remaining = pool.expires_at - now()
            key = 'expired' if remaining <= timedelta() else 'expires_24h' if remaining <= timedelta(days=1) else 'expires_48h' if remaining <= timedelta(days=2) else None
            if key:
                queue_alert(db, pool, key, 'Phone trial ended' if key == 'expired' else 'Phone trial ends soon',
                            'Pool ' + pool.name + ' expires at ' + pool.expires_at.isoformat() +
                            '. Review your provider allowance and reconnect any replacement account and owned numbers before resuming.')
            for trial in db.scalars(select(PhoneTrial).where(PhoneTrial.pool_id == pool.id)):
                remaining = min(trial.expires_at, pool.expires_at) - now()
                key = 'expired' if remaining <= timedelta() else 'expires_24h' if remaining <= timedelta(days=1) else 'expires_48h' if remaining <= timedelta(days=2) else None
                if key:
                    queue_alert(db, pool, key + ':' + trial.id, 'Phone trial ended' if key == 'expired' else 'Phone trial ends soon',
                                'Your phone trial ends at ' + min(trial.expires_at, pool.expires_at).isoformat() + '.', trial.workspace_id,
                                email=trial.expires_at < pool.expires_at)
        pending = list(db.scalars(select(PhoneTrialAlert.id).where(PhoneTrialAlert.state.in_(['pending', 'sending']),
                       PhoneTrialAlert.next_attempt_at <= now()).order_by(PhoneTrialAlert.created_at).limit(10)))
    for alert_id in pending:
        with session_scope(write=True) as db:
            alert = db.scalar(select(PhoneTrialAlert).where(PhoneTrialAlert.id == alert_id).with_for_update())
            if alert.state == 'sent' or alert.next_attempt_at > now():
                continue
            alert.state, alert.attempts, alert.next_attempt_at = 'sending', alert.attempts + 1, now() + timedelta(minutes=5)
            pool = db.get(PhoneTrialPool, alert.pool_id)
            email, subject, body = pool.alert_email, alert.subject, alert.body
        with session_scope(write=True) as db:
            enqueue_email(db, email, subject, body, operation_key='phone-trial:' + alert_id)
            db.get(PhoneTrialAlert, alert_id).state = 'queued'


def maintenance():
    check_balances()
    process_alerts()

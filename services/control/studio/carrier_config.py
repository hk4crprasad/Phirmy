"""Resolve verified tenant carrier bindings without exposing their secrets."""
import json
from sqlalchemy import select
from .config import settings
from .db import session_scope
from .models import ConnectorCredential, Call, Number, Connection
from .secrets import decrypt


def twilio_client(carrier, timeout=None):
    from twilio.rest import Client
    options = {}
    if timeout:
        from twilio.http.http_client import TwilioHttpClient
        options['http_client'] = TwilioHttpClient(timeout=timeout)
    if carrier.get('api_key') and carrier.get('api_secret'):
        return Client(carrier['api_key'], carrier['api_secret'], account_sid=carrier['account_sid'], **options)
    return Client(carrier['account_sid'], carrier['auth_token'], **options)


def credentials(provider, workspace_id=None):
    if workspace_id:
        with session_scope() as db:
            row = db.scalar(select(ConnectorCredential).where(ConnectorCredential.workspace_id == workspace_id,
                            ConnectorCredential.provider == provider))
            if row:
                return json.loads(decrypt(row.encrypted_data))
            if db.scalar(select(Connection.id).where(Connection.workspace_id == workspace_id, Connection.provider == provider)):
                return {}
        if provider == 'twilio' and settings.phone_trials_enabled:
            # Platform-funded credentials are available only through an operator
            # grant, not as a fallback for arbitrary customer-owned numbers.
            return {}
    if provider == 'twilio':
        return {'account_sid': settings.twilio_account_sid, 'auth_token': settings.twilio_auth_token,
                'api_key': settings.twilio_api_key, 'api_secret': settings.twilio_api_secret}
    return {'auth_id': settings.plivo_auth_id, 'auth_token': settings.plivo_auth_token}


def callback_credentials(provider, form, call_id=None):
    # Unverified payloads only select a candidate key. Every handler must still
    # verify the provider signature and bind the canonical call leg afterward.
    provider_id = form.get('CallSid' if provider == 'twilio' else 'CallUUID', '')
    with session_scope() as db:
        call = db.get(Call, call_id) if call_id else db.scalar(select(Call).where(Call.provider_call_id == provider_id, Call.mode == 'live'))
        if call:
            return call_credentials(call)
        to = '+' + str(form.get('To', '')).lstrip('+')
        number = db.scalar(select(Number).where(Number.provider == provider, Number.e164 == to, Number.status == 'active'))
        if number:
            from .phone_trials import for_number, pool_credentials
            trial = for_number(db, number.id)
            if trial:
                return pool_credentials(trial.pool_id)
        workspace_id = number.workspace_id if number else None
    return credentials(provider, workspace_id)


def call_credentials(call):
    if call.metadata_data.get('transfer_request_id'):
        from .models import CallTransfer
        with session_scope() as db:
            transfer=db.get(CallTransfer,call.metadata_data['transfer_request_id'])
            if transfer and transfer.workspace_id==call.workspace_id and transfer.call_id==call.id:
                return json.loads(decrypt(transfer.encrypted_snapshot))['credentials']
    if call.metadata_data.get('phone_trial_id'):
        from .phone_trials import pool_credentials
        from .models import PhoneTrial
        with session_scope() as db:
            trial = db.get(PhoneTrial, call.metadata_data['phone_trial_id'])
            if not trial or trial.workspace_id != call.workspace_id:
                raise ValueError('Phone trial account binding is unavailable')
            # Past calls retain their original account even after an operator reassignment.
            return pool_credentials(call.metadata_data['phone_trial_pool_id'])
    return credentials(call.metadata_data.get('provider', 'plivo'), call.workspace_id)


def remaining_seconds(call):
    """A repeated answer callback cannot extend the first carrier deadline."""
    import math
    from .db import now
    stamp=now().timestamp()
    maximum=min(900,int(call.metadata_data.get('admitted_max_seconds',300)),
                int(call.metadata_data.get('phone_trial_seconds',900)))
    deadline=call.metadata_data.get('carrier_deadline_at',stamp+maximum)
    call.metadata_data={**call.metadata_data,'carrier_deadline_at':deadline}
    return max(0,math.ceil(deadline-stamp))


def telephony_ready(workspace_id):
    if not settings.live_calls_enabled or not settings.media_public_origin.startswith('https://'):
        return False
    if any(c.get('auth_token') and (c.get('account_sid') or c.get('auth_id'))
           for c in (credentials('twilio', workspace_id), credentials('plivo', workspace_id))):
        return True
    from .models import PhoneTrial, PhoneTrialPool
    with session_scope() as db:
        return settings.phone_trials_enabled and bool(db.scalar(select(PhoneTrial.id).join(PhoneTrialPool).where(
            PhoneTrial.workspace_id == workspace_id, PhoneTrial.enabled.is_(True), PhoneTrialPool.enabled.is_(True))))

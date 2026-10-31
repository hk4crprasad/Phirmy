"""Server-selected seven-day phone trials; carrier purchases default to disabled.

Persist purchase intent before sending it. An uncertain purchase is reconciled
by its stable provider marker, never retried as another purchase.
"""
from datetime import timedelta
from decimal import Decimal, InvalidOperation, ROUND_CEILING
import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func, text

from .job_control import get_job
from .config import settings
from .db import now, session_scope
from .models import (PhoneNumberOrder, PhoneNumberInventory, PhoneTrialPool,
                     PhoneTrial, Number, User, Notification, Job)
from .schemas import Input
from .security import principal, db_dependency, audit

router = APIRouter(prefix='/v1/workspaces/{workspace_id}/phone-trial')
PENDING = ('queued', 'acquiring', 'purchasing', 'unknown')
MARKER = 'cynerza-trial-'


class StartPhoneTrial(Input):
    """No choices: the server binds the person, workspace, pool and number."""


def allocation_lock(db):
    # Shared across pools/processes, unlike an in-memory mutex. SQLite write
    # sessions already serialize through BEGIN IMMEDIATE.
    if db.bind.dialect.name == 'postgresql':
        db.execute(text("SELECT pg_advisory_xact_lock(701346201014)"))


def reserved_slots(db, pool_id, exclude_order_id=None):
    query = select(func.count()).select_from(PhoneNumberOrder).where(
        PhoneNumberOrder.pool_id == pool_id, PhoneNumberOrder.state.in_(PENDING))
    if exclude_order_id:
        query = query.where(PhoneNumberOrder.id != exclude_order_id)
    return db.scalar(query)


def availability(db, pool):
    from .phone_trials import pool_problem
    if not settings.phone_trials_enabled or not pool:
        return 'Phone trials are not open yet.'
    issue = pool_problem(pool)
    if issue:
        return 'Phone trials are temporarily unavailable. Please try again later.'
    if pool.currency != 'USD' or pool.expires_at < now() + timedelta(days=7, minutes=5):
        return 'A full seven-day phone trial is not available right now.'
    if pool.workspaces_issued + reserved_slots(db, pool.id) >= pool.max_workspaces:
        return 'All current phone trial places have been assigned.'
    stock = db.scalar(select(PhoneNumberInventory.id).where(
        PhoneNumberInventory.pool_id == pool.id, PhoneNumberInventory.assigned_order_id.is_(None)).limit(1))
    if not stock and not settings.phone_number_purchases_enabled:
        return 'All current trial numbers have been assigned. More places will open when numbers are available.'
    return None


def allocation_status(db, workspace_id):
    order = db.scalar(select(PhoneNumberOrder).where(PhoneNumberOrder.workspace_id == workspace_id))
    if order:
        state = 'assigning' if order.state in ('queued', 'acquiring', 'purchasing') else order.state
        messages = {
            'assigning': 'We are assigning your trial number. This page will update when it is ready.',
            'unknown': 'Your number request needs a confirmation check. Please wait; no second request is needed.',
            'unavailable': 'We could not assign a trial number. Please contact support or use the browser voice test.',
            'assigned': 'Your assigned number is being prepared.',
        }
        return {'status': state, 'message': messages.get(state, messages['unavailable']), 'can_request': False,
                'offer_visible': True}
    pool = db.get(PhoneTrialPool, settings.phone_trial_auto_assign_pool_id) if settings.phone_trial_auto_assign_pool_id else None
    issue = availability(db, pool)
    return {'status': 'not_assigned', 'can_request': not bool(issue),
            'offer_visible': bool(settings.phone_trials_enabled and pool),
            'message': issue or 'Get an automatically assigned number for seven days, with a limited test-call allowance.'}


@router.get('')
def get_trial(workspace_id: str, actor=Depends(principal), db=Depends(db_dependency, scope='function')):
    actor.require('numbers:read')
    from .phone_trials import trial_status
    return trial_status(db, workspace_id)


@router.post('', status_code=202, openapi_extra={'security': [{'DashboardSession': []}]},
             responses={403: {'description': 'Signed-in owner/admin and valid CSRF required'},
                        409: {'description': 'Trial already used elsewhere, or capacity unavailable'}})
def request_trial(workspace_id: str, body: StartPhoneTrial, actor=Depends(principal), db=Depends(db_dependency, scope='function')):
    actor.require('numbers:write')
    if not actor.user_id:
        raise HTTPException(403, 'A signed-in workspace owner or administrator must start the trial')
    allocation_lock(db)
    db.scalar(select(User).where(User.id == actor.user_id).with_for_update())
    existing = db.scalar(select(PhoneTrial.id).where(PhoneTrial.workspace_id == workspace_id))
    order = db.scalar(select(PhoneNumberOrder).where(PhoneNumberOrder.workspace_id == workspace_id))
    if existing or order:
        from .phone_trials import trial_status
        return trial_status(db, workspace_id)
    if db.scalar(select(PhoneNumberOrder.id).where(PhoneNumberOrder.user_id == actor.user_id)):
        raise HTTPException(409, 'You have already requested a phone trial in another workspace')
    pool = db.scalar(select(PhoneTrialPool).where(PhoneTrialPool.id == settings.phone_trial_auto_assign_pool_id).with_for_update())
    issue = availability(db, pool)
    if issue:
        raise HTTPException(409, issue)
    order = PhoneNumberOrder(workspace_id=workspace_id, user_id=actor.user_id, pool_id=pool.id)
    db.add(order); db.flush()
    stock = db.scalar(select(PhoneNumberInventory).where(PhoneNumberInventory.pool_id == pool.id,
        PhoneNumberInventory.assigned_order_id.is_(None)).order_by(PhoneNumberInventory.created_at).with_for_update().limit(1))
    if stock:
        # Reserve limited owned inventory during enrollment, so two customers
        # cannot both be promised the account's single trial number.
        stock.assigned_order_id = order.id
        order.e164, order.provider_number_id = stock.e164, stock.provider_number_id
    from .domain import enqueue
    enqueue(db, workspace_id, 'phone_number_allocate', {'order_id': order.id})
    audit(db, actor, 'phone_trial.requested', order.id)
    return allocation_status(db, workspace_id)


def validate_number(result, account_sid, e164):
    if (getattr(result, 'account_sid', None) != account_sid or result.phone_number != e164
            or not re.fullmatch(r'\+1\d{10}', e164) or not str(result.sid).startswith('PN')
            or not result.capabilities.get('voice')):
        raise ValueError('The carrier number identity or voice capability did not match')


def stock_number(db, pool_id, e164):
    """Operator-only registration of a specifically approved, already-owned DID."""
    from .phone_trials import pool_credentials
    from .carrier_config import twilio_client
    if not db.get(PhoneTrialPool, pool_id) or not re.fullmatch(r'\+1\d{10}', e164):
        raise ValueError('Select a trial pool and an owned US number')
    if db.scalar(select(Number.id).where(Number.provider == 'twilio', Number.e164 == e164)):
        raise ValueError('This number is already registered to a workspace')
    if db.scalar(select(PhoneNumberInventory.id).where(PhoneNumberInventory.e164 == e164)):
        raise ValueError('This number is already in trial inventory')
    creds = pool_credentials(pool_id)
    matches = twilio_client(creds, timeout=10).incoming_phone_numbers.list(phone_number=e164, limit=2)
    if len(matches) != 1:
        raise ValueError('The account must own exactly this voice number')
    validate_number(matches[0], creds['account_sid'], e164)
    row = PhoneNumberInventory(pool_id=pool_id, e164=e164, provider_number_id=matches[0].sid)
    db.add(row); db.flush()
    return row


def quote_minor(pricing):
    if str(pricing.price_unit).upper() != 'USD':
        raise ValueError('Automatic US trial rental requires a USD quote')
    prices = [p for p in pricing.phone_number_prices if p.get('number_type') == 'local']
    if len(prices) != 1:
        raise ValueError('A unique local-number rental quote is required')
    try:
        value = Decimal(str(prices[0]['current_price']))
        if not value.is_finite() or value <= 0 or value > 100:
            raise ValueError('Rental quote is unavailable')
        return int((value * 100).to_integral_value(rounding=ROUND_CEILING))
    except (InvalidOperation, KeyError, TypeError) as exc:
        raise ValueError('Rental quote is unavailable') from exc


def fail_order(order_id, code, uncertain=False):
    with session_scope(write=True) as db:
        allocation_lock(db)
        order = db.get(PhoneNumberOrder, order_id)
        if not order or order.state == 'assigned':
            return
        previous_state = order.state
        order.state, order.error_code, order.lease_until = ('unknown' if uncertain else 'unavailable'), code, None
        # Keep uncertain spend reserved until a human reconciles it.
        if not uncertain:
            order.purchase_reserved = False
        from .phone_trials import queue_alert
        pool = db.get(PhoneTrialPool, order.pool_id)
        queue_alert(db, pool, 'allocation:' + order.id,
                    'Phone number allocation needs attention',
                    'Order ' + order.id + ' for workspace ' + order.workspace_id +
                    (' has an uncertain rental outcome. Reconcile this order before any replacement purchase.' if uncertain else
                     ' could not be assigned. Review the pool allowance, inventory and rental budget.'))
        if previous_state != order.state:
            db.add(Notification(workspace_id=order.workspace_id, kind='phone_trial.allocation',
                                title='We are checking your trial number' if uncertain else 'Your phone trial needs attention',
                                description='Your request is being checked. No second request is needed.' if uncertain else
                                'We could not assign your trial number. Contact support, or try your agent in the browser.',
                                href='/app/numbers'))


def finish_order(order_id, result, account_sid):
    from .phone_trials import grant_trial
    from .domain import emit
    with session_scope(write=True) as db:
        allocation_lock(db)
        order = db.get(PhoneNumberOrder, order_id)
        if order.state == 'assigned':
            return
        validate_number(result, account_sid, order.e164)
        if order.provider_number_id and order.provider_number_id != result.sid:
            raise ValueError('The inventory number identity changed')
        # Eligibility was checked before acquiring stock/sending a purchase.
        # Paused/expired pools must retain the purchased resource for operator
        # review instead of silently losing it or buying a replacement.
        pool = db.get(PhoneTrialPool, order.pool_id)
        if not pool.enabled or pool.expires_at < now() + timedelta(days=7):
            raise ValueError('The pool no longer has seven days available')
        trial = grant_trial(db, pool.id, order.workspace_id, order.e164, [], reservation_id=order.id, verify=False)
        number = db.get(Number, trial.number_id)
        number.provider_number_id, number.status = result.sid, 'active'
        number.can_inbound, number.can_outbound = False, True
        order.state, order.provider_number_id, order.lease_until, order.error_code = 'assigned', result.sid, None, None
        db.add(Notification(workspace_id=order.workspace_id, kind='phone_trial.ready', title='Your trial number is ready',
                            description='Your seven-day phone trial has started. Open Phone numbers to see your allowance.', href='/app/numbers'))
        emit(db, order.workspace_id, 'phone_trial.assigned', {'number_id': number.id})


def reconcile(order_id, client=None, creds=None):
    """Read-only provider recovery. Never issue another purchase POST."""
    from .phone_trials import pool_credentials
    from .carrier_config import twilio_client
    with session_scope() as db:
        order = db.get(PhoneNumberOrder, order_id)
        if not order or order.state == 'assigned' or not order.purchase_started_at:
            return
        pool_id, e164 = order.pool_id, order.e164
    try:
        creds = creds or pool_credentials(pool_id)
        client = client or twilio_client(creds, timeout=10)
        matches = client.incoming_phone_numbers.list(friendly_name=MARKER + order_id, limit=3)
        if len(matches) != 1 or matches[0].phone_number != e164 or matches[0].friendly_name != MARKER + order_id:
            raise ValueError('Purchase outcome needs operator review')
        finish_order(order_id, matches[0], creds['account_sid'])
    except Exception:
        fail_order(order_id, 'purchase_confirmation_pending', uncertain=True)


def allocate(order_id):
    from .phone_trials import pool_credentials
    from .carrier_config import twilio_client
    with session_scope(write=True) as db:
        allocation_lock(db)
        order = db.get(PhoneNumberOrder, order_id)
        if not order or order.state in ('assigned', 'unavailable'):
            return
        # Check purchase intent before eligibility. Even a paused account may
        # have a completed rental to reconcile; it must never be re-purchased.
        recovery = bool(order.purchase_started_at)
        if not recovery and order.lease_until and order.lease_until > now():
            return
        pool_id = order.pool_id
        if not recovery:
            from .phone_trials import pool_problem
            pool = db.get(PhoneTrialPool, pool_id)
            if pool.currency != 'USD' or pool_problem(pool) or pool.expires_at < now() + timedelta(days=7, minutes=5):
                order.state, order.error_code = 'unavailable', 'pool_unavailable'
                return
            order.state, order.lease_until = 'acquiring', now() + timedelta(minutes=3)
            stock = db.scalar(select(PhoneNumberInventory).where(PhoneNumberInventory.pool_id == pool_id,
                PhoneNumberInventory.assigned_order_id == order.id))
            if not stock:
                stock = db.scalar(select(PhoneNumberInventory).where(PhoneNumberInventory.pool_id == pool_id,
                    PhoneNumberInventory.assigned_order_id.is_(None)).order_by(PhoneNumberInventory.created_at).with_for_update().limit(1))
                if stock:
                    stock.assigned_order_id = order.id
            if stock:
                order.e164, order.provider_number_id = stock.e164, stock.provider_number_id
            stock_e164 = order.e164 if stock else None
    if recovery:
        reconcile(order_id)
        return
    purchasing = False
    try:
        creds = pool_credentials(pool_id)
        client = twilio_client(creds, timeout=10)
        if stock_e164:
            matches = client.incoming_phone_numbers.list(phone_number=stock_e164, limit=2)
            if len(matches) != 1:
                raise ValueError('Inventory ownership could not be confirmed')
            finish_order(order_id, matches[0], creds['account_sid'])
            return
        if not settings.phone_number_purchases_enabled or not settings.media_public_origin.startswith('https://'):
            raise ValueError('Number purchases are disabled or the public origin is unavailable')
        price = quote_minor(client.pricing.v1.phone_numbers.countries('US').fetch())
        if price > settings.phone_number_max_monthly_price_minor:
            raise ValueError('Number rental exceeds the configured price cap')
        choices = client.available_phone_numbers('US').local.list(voice_enabled=True, exclude_all_address_required=True, limit=5)
        choices = [x for x in choices if re.fullmatch(r'\+1\d{10}', x.phone_number)
                   and x.capabilities.get('voice') and x.address_requirements == 'none']
        if not choices:
            raise ValueError('No eligible US voice number is available')
        e164 = choices[0].phone_number
        with session_scope(write=True) as db:
            allocation_lock(db)
            order = db.get(PhoneNumberOrder, order_id)
            pool = db.get(PhoneTrialPool, pool_id)
            from .phone_trials import pool_problem
            if order.state != 'acquiring' or order.purchase_started_at:
                return
            if not settings.phone_number_purchases_enabled or pool_problem(pool) or pool.expires_at < now() + timedelta(days=7, minutes=5):
                raise ValueError('Enrollment was paused before purchase')
            reserved = db.scalar(select(func.coalesce(func.sum(PhoneNumberOrder.quoted_price_minor), 0)).where(PhoneNumberOrder.purchase_reserved.is_(True)))
            pending_balance = db.scalar(select(func.coalesce(func.sum(PhoneNumberOrder.quoted_price_minor), 0)).where(
                PhoneNumberOrder.purchase_reserved.is_(True), PhoneNumberOrder.purchase_started_at > pool.balance_checked_at))
            if reserved + price > settings.phone_number_total_budget_minor or pool.balance_minor - pending_balance - price <= pool.low_balance_minor:
                raise ValueError('Number rental budget is exhausted')
            if db.scalar(select(Number.id).where(Number.provider == 'twilio', Number.e164 == e164)):
                raise ValueError('Number is already registered')
            order.state, order.e164, order.quoted_price_minor = 'purchasing', e164, price
            order.purchase_reserved, order.purchase_started_at = True, now()
        purchasing = True  # Intent above is committed before the only POST.
        origin = settings.media_public_origin.rstrip('/')
        result = client.incoming_phone_numbers.create(phone_number=e164, friendly_name=MARKER + order_id,
            voice_url=origin + '/v1/provider-webhooks/twilio/answer', voice_method='POST',
            status_callback=origin + '/v1/provider-webhooks/twilio/status', status_callback_method='POST')
        finish_order(order_id, result, creds['account_sid'])
    except Exception as exc:
        # A known rejection confirms that no rental was accepted. Timeouts,
        # connection failures, 408/429/5xx and local post-purchase failures do not.
        from twilio.base.exceptions import TwilioRestException
        rejected = purchasing and isinstance(exc, TwilioRestException) and 400 <= exc.status < 500 and exc.status not in (408, 429)
        if purchasing and not rejected:
            reconcile(order_id, client, creds)
        else:
            fail_order(order_id, 'carrier_rejected' if rejected else 'allocation_unavailable')


async def allocation_job(job_id):
    import asyncio
    with session_scope() as db:
        order_id = get_job(db,job_id).payload['order_id']
    await asyncio.to_thread(allocate, order_id)

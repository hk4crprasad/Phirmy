"""Operate a bounded outbound beta and approved automatic-number inventory.

Run migrations first. This command never rents a number, creates a provider
account, resets trial credits or displays credentials. Recipient verification
and permission must be confirmed in Twilio before granting a test destination.
"""
import argparse
from datetime import datetime, timedelta
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'services/control'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    configure = commands.add_parser('configure', help='Capture the current private Twilio binding')
    configure.add_argument('--name', default='Private beta')
    configure.add_argument('--days', type=int, default=20)
    configure.add_argument('--expires-at', help='Actual provider expiry, ISO8601 with timezone; earlier than --days wins')
    configure.add_argument('--alert-email', help='Defaults to BETA_OPERATOR_EMAIL')
    configure.add_argument('--max-workspaces', type=int, default=10)
    configure.add_argument('--calls-per-workspace', type=int, default=3)
    configure.add_argument('--seconds-per-call', type=int, default=60)
    configure.add_argument('--low-balance-minor', type=int, default=200, help='Pause at this amount in currency cents')
    configure.add_argument('--currency', default='USD')
    grant = commands.add_parser('grant', help='Assign an already owned number and verified test destinations')
    grant.add_argument('--pool-id', required=True)
    grant.add_argument('--workspace-id', required=True)
    grant.add_argument('--number', required=True)
    grant.add_argument('--destination', required=True, action='append')
    stock = commands.add_parser('stock', help='Verify and register an already owned US number for automatic assignment')
    stock.add_argument('--pool-id', required=True)
    stock.add_argument('--number', required=True)
    destinations = commands.add_parser('destinations', help='Approve provider-verified, consenting test destinations for an assigned trial')
    destinations.add_argument('--workspace-id', required=True)
    destinations.add_argument('--destination', required=True, action='append')
    reconcile = commands.add_parser('reconcile', help='Read-only carrier lookup for an uncertain order; never purchases a replacement')
    reconcile.add_argument('--order-id', required=True)
    replace = commands.add_parser('replace', help='Reverify a replacement account/number, preserving usage and original expiry')
    replace.add_argument('--pool-id', required=True)
    replace.add_argument('--workspace-id', required=True)
    replace.add_argument('--number', required=True)
    for action in ['pause', 'resume', 'refresh-credentials']:
        command = commands.add_parser(action)
        command.add_argument('--pool-id', required=True)
    revoke = commands.add_parser('revoke')
    revoke.add_argument('--workspace-id', required=True)
    commands.add_parser('status', help='List operational state without credentials')
    commands.add_parser('check-balances', help='Read provider balances; no calls, purchases or emails')
    args = parser.parse_args()
    try:
        from sqlalchemy import select
        from studio.config import settings
        from studio.db import session_scope, now
        from studio.models import PhoneTrialPool, PhoneTrial
        from studio.phone_trials import create_pool, grant_trial, replace_binding, check_balances
        from studio.secrets import encrypt, decrypt
        if args.action == 'reconcile':
            from studio.number_provisioning import reconcile as reconcile_order
            reconcile_order(args.order_id)
            print('Read-only reconciliation finished. Review trial/order state; no replacement was purchased.')
            return
        if args.action == 'check-balances':
            check_balances()
            print('Balance check finished. Use status to review; unknown or stale balances block trial calls.')
            return
        with session_scope(write=args.action != 'status') as db:
            if args.action == 'configure':
                if not 1 <= args.days <= 20:
                    raise ValueError('Choose 1–20 days')
                expiry = now() + timedelta(days=args.days)
                if args.expires_at:
                    supplied = datetime.fromisoformat(args.expires_at)
                    if supplied.tzinfo is None:
                        raise ValueError('Include a timezone in --expires-at')
                    expiry = min(expiry, supplied)
                pool = create_pool(db, name=args.name, expires_at=expiry, alert_email=args.alert_email or settings.beta_operator_email,
                                   max_workspaces=args.max_workspaces, calls_per_workspace=args.calls_per_workspace,
                                   seconds_per_call=args.seconds_per_call, low_balance_minor=args.low_balance_minor, currency=args.currency)
                print('Configured pool:', pool.id)
                print('Expiry:', pool.expires_at.isoformat(), '— balance and number verification are required before calls.')
            elif args.action == 'stock':
                from studio.number_provisioning import stock_number
                row = stock_number(db, args.pool_id, args.number)
                print('Owned voice number added to automatic inventory:', row.id)
            elif args.action == 'destinations':
                import re
                trial = db.scalar(select(PhoneTrial).where(PhoneTrial.workspace_id == args.workspace_id).with_for_update())
                if not trial or not 1 <= len(args.destination) <= 5 or any(not re.fullmatch(r'\+[1-9]\d{6,14}', value) for value in args.destination):
                    raise ValueError('Select an assigned trial and 1–5 verified, consenting destinations in E.164 format')
                trial.destinations = list(dict.fromkeys(args.destination))
                print('Approved destinations updated; expiry and call allowance are unchanged.')
            elif args.action in {'grant', 'replace'}:
                trial = grant_trial(db, args.pool_id, args.workspace_id, args.number, args.destination) if args.action == 'grant' else replace_binding(db, args.workspace_id, args.pool_id, args.number)
                print('Trial:', trial.id, '— assigned number queued for ownership verification.')
            elif args.action in {'pause', 'resume', 'refresh-credentials'}:
                pool = db.get(PhoneTrialPool, args.pool_id)
                if not pool:
                    raise ValueError('Pool not found')
                if args.action == 'refresh-credentials':
                    old = json.loads(decrypt(pool.encrypted_credentials))
                    if old['account_sid'] != settings.twilio_account_sid or not settings.twilio_auth_token:
                        raise ValueError('Account changed: configure a new pool and replace the owned number binding instead')
                    if bool(settings.twilio_api_key) != bool(settings.twilio_api_secret):
                        raise ValueError('Supply both API key fields, or leave both empty')
                    pool.encrypted_credentials = encrypt(json.dumps({'account_sid': settings.twilio_account_sid, 'auth_token': settings.twilio_auth_token,
                                                                     'api_key': settings.twilio_api_key, 'api_secret': settings.twilio_api_secret}))
                    pool.balance_state, pool.balance_checked_at = 'unknown', None
                else:
                    pool.enabled = args.action == 'resume'
                print('Pool updated:', pool.id)
            elif args.action == 'revoke':
                trial = db.scalar(select(PhoneTrial).where(PhoneTrial.workspace_id == args.workspace_id))
                if not trial:
                    raise ValueError('Trial not found')
                trial.enabled = False
                print('Trial revoked; used allowance is retained.')
            else:
                for pool in db.scalars(select(PhoneTrialPool).order_by(PhoneTrialPool.created_at)):
                    print(json.dumps({'pool_id': pool.id, 'name': pool.name, 'enabled': pool.enabled, 'expires_at': pool.expires_at.isoformat(),
                                      'workspaces_issued': pool.workspaces_issued, 'max_workspaces': pool.max_workspaces,
                                      'balance_state': pool.balance_state, 'balance_minor': pool.balance_minor, 'currency': pool.currency}))
                from studio.models import PhoneNumberOrder
                for order in db.scalars(select(PhoneNumberOrder).order_by(PhoneNumberOrder.created_at)):
                    print(json.dumps({'order_id': order.id, 'workspace_id': order.workspace_id, 'state': order.state,
                                      'error_code': order.error_code, 'rental_reserved_minor': order.quoted_price_minor if order.purchase_reserved else 0}))
    except ValueError as exc:
        # Only application-authored validation errors above are intended for display.
        print('Trial operation could not finish. Check the command, dates, capacity and private configuration.')
        raise SystemExit(1)
    except Exception as exc:
        print('Trial operation failed:', type(exc).__name__, '— verify migrations, database access and stable APP_SECRET.')
        raise SystemExit(1)


if __name__ == '__main__':
    main()

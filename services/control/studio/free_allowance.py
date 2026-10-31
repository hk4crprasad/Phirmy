"""One Free pool per original owner across workspaces, serialized on the user.

Financial source records remain append-only. Old untagged usage is counted
conservatively, and ownership transfer never changes a workspace's sponsor.
"""
from fastapi import HTTPException
from sqlalchemy import case, func, or_, select

from .config import settings
from .db import now, session_scope
from .mail_outbox import enqueue_email
from .models import (BudgetAdmission, CallCostRecord, Installation, Invitation, Membership,
                     MeterEvent, StoredObjectMeter, TariffSnapshot, User, Workspace, WorkspaceSubscription)
from .plans import catalog, month_bounds

MONTHLY = {'conversations', 'chat_turns', 'voice_ms', 'crawl_pages'}
CURRENT = {'storage_bytes', 'widgets', 'seats'}
MICRO = 1_000_000


def sponsor(db, workspace_id):
    workspace = db.get(Workspace, workspace_id)
    if workspace.free_allowance_user_id is None:
        owner = db.scalar(select(Membership.user_id).where(Membership.workspace_id==workspace_id,
            Membership.role=='owner').order_by(Membership.created_at, Membership.id).limit(1))
        if owner is None:
            raise HTTPException(409, 'Assign an owner before using Free allowances')
        workspace.free_allowance_user_id = owner
        db.flush()
    return workspace.free_allowance_user_id


def policy():
    body = catalog()
    multiplier = 1000 if settings.app_env in {'test','development'} and settings.billing_development_allowances_enabled else 1
    free = body['plans']['free']
    return {key:value*multiplier for key,value in free['included'].items()}, free['spend_cap_minor']*multiplier


def snapshot(db, user_id, resources=None):
    start, end = month_bounds(now(), 'UTC')
    totals = {}
    wanted = set(resources) if resources is not None else MONTHLY | CURRENT
    free_tariff = or_(TariffSnapshot.content['plan'].as_string()=='free', TariffSnapshot.id.is_(None))
    if wanted & MONTHLY:
        signed = case((MeterEvent.direction=='consume', MeterEvent.quantity), else_=-MeterEvent.quantity)
        query = select(MeterEvent.resource, func.sum(signed)).join(Workspace, Workspace.id==MeterEvent.workspace_id).outerjoin(
            TariffSnapshot, TariffSnapshot.id==MeterEvent.tariff_id).where(Workspace.free_allowance_user_id==user_id,
            MeterEvent.created_at>=start, MeterEvent.created_at<end, MeterEvent.resource.in_(wanted & MONTHLY), free_tariff
        ).group_by(MeterEvent.resource)
        totals.update({resource:int(value) for resource,value in db.execute(query)})
    # Paid workspace inventories do not consume the shared Free inventory.
    free_workspaces = select(Workspace.id).outerjoin(WorkspaceSubscription, WorkspaceSubscription.workspace_id==Workspace.id).where(
        Workspace.free_allowance_user_id==user_id,
        or_(WorkspaceSubscription.plan_slug=='free', WorkspaceSubscription.id.is_(None)))
    if 'storage_bytes' in wanted:
        totals['storage_bytes'] = int(db.scalar(select(func.coalesce(func.sum(StoredObjectMeter.size_bytes),0)).where(
            StoredObjectMeter.workspace_id.in_(free_workspaces), StoredObjectMeter.state=='active')))
    if 'widgets' in wanted:
        totals['widgets'] = int(db.scalar(select(func.count()).select_from(Installation).where(Installation.workspace_id.in_(free_workspaces))))
    if 'seats' in wanted:
        # Count the owner once even if they own several Free workspaces.
        users = set(db.scalars(select(Membership.user_id).where(Membership.workspace_id.in_(free_workspaces))))
        emails = set(db.scalars(select(User.email).where(User.id.in_(users))))
        emails.update(db.scalars(select(Invitation.email).where(Invitation.workspace_id.in_(free_workspaces),
            Invitation.state=='pending', Invitation.expires_at>now())))
        totals['seats'] = len(emails)
    pending = list(db.scalars(select(BudgetAdmission).join(Workspace, Workspace.id==BudgetAdmission.workspace_id).join(
        TariffSnapshot, TariffSnapshot.id==BudgetAdmission.tariff_id).where(Workspace.free_allowance_user_id==user_id,
        TariffSnapshot.content['plan'].as_string()=='free', BudgetAdmission.state.in_(['held','unknown']))))
    held = {}
    for row in pending:
        for resource, amount in row.resources.items():
            if resource in {'voice_ms','storage_bytes'} or row.created_at>=start:
                held[resource] = held.get(resource,0)+amount
    spent = int(db.scalar(select(func.coalesce(func.sum(CallCostRecord.cost_micro_minor),0)).join(
        Workspace, Workspace.id==CallCostRecord.workspace_id).join(TariffSnapshot, TariffSnapshot.id==CallCostRecord.tariff_id).where(
        Workspace.free_allowance_user_id==user_id, TariffSnapshot.content['plan'].as_string()=='free',
        CallCostRecord.created_at>=start, CallCostRecord.created_at<end)))
    held_cost = sum(max(0,row.reserved_micro_minor-row.measured_micro_minor) for row in pending)
    limits, cap = policy()
    return {'period_start':start.isoformat(), 'period_end':end.isoformat(), 'timezone':'UTC',
        'usage':totals, 'reserved':held, 'included':limits, 'spend_cap_minor':cap,
        'provider_cost_micro_minor':spent, 'held_cost_micro_minor':held_cost,
        'basis':'One Free pool across workspaces sponsored by the original owner; legacy untagged usage counts conservatively.'}


def check(db, workspace_id, current, resources, cost):
    if current.plan_slug != 'free':
        return
    identity = sponsor(db, workspace_id)
    user = db.scalar(select(User).where(User.id==identity).with_for_update())
    if user is None:
        raise HTTPException(409, 'Free allowance owner is unavailable')
    values = snapshot(db, identity, resources)
    violations = []
    for resource, amount in resources.items():
        limit = values['included'][resource]
        if values['usage'].get(resource,0)+values['reserved'].get(resource,0)+amount > limit:
            violations.append((resource,limit))
    cap = values['spend_cap_minor']
    if cap == 0 or values['provider_cost_micro_minor']+values['held_cost_micro_minor']+cost > cap*MICRO:
        violations.append(('provider spending',cap))
    if violations:
        resource, limit = violations[0]
        email, period = user.email, values['period_start']
        from .metering import operation
        db.rollback()
        with session_scope(write=True) as notice:
            enqueue_email(notice,email,'Shared Free allowance reached',
                f'Your Free {resource.replace("_"," ")} allowance is shared across your workspaces. '
                f'The next request would exceed the configured limit ({limit}). Review Billing. Values remain DRAFT.',
                operation_key='shared-free:'+operation(f'{identity}:{period}:{resource}:{limit}'))
        raise HTTPException(429,'The Free '+resource.replace('_',' ')+' allowance is shared across your workspaces and has been reached. Review Billing.')

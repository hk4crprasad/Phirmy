"""Explicit, audited adoption of a larger Free beta catalog; never reset usage."""
from sqlalchemy import select

from . import plans
from .models import Audit, PlanCatalogSnapshot, Workspace, WorkspaceSubscription


def apply_catalog(db, *, expected_version, apply=False):
    body = plans.catalog()
    target = body['plans']['free']
    if body['version'] != expected_version or body['status'] != 'DRAFT' or target['monthly_price_minor'] != 0:
        raise ValueError('Expected a matching DRAFT zero-price beta catalog')
    # Use normal workspace lock order, matching admission. The whole batch commits
    # atomically, and a stale target or a decreasing allowance aborts the batch.
    rows = list(db.scalars(select(Workspace).join(WorkspaceSubscription,
        WorkspaceSubscription.workspace_id == Workspace.id).where(
        WorkspaceSubscription.plan_slug == 'free').order_by(Workspace.id).limit(1001).with_for_update()))
    if len(rows) > 1000:
        raise ValueError('Use a reviewed bounded migration for more than 1000 workspaces')
    report = {'version': body['version'], 'free_workspaces': len(rows), 'changed': 0,
              'unchanged': 0, 'explicit_spend_caps_preserved': 0, 'applied': apply}
    snapshot = None
    for workspace in rows:
        current = db.scalar(select(WorkspaceSubscription).where(
            WorkspaceSubscription.workspace_id == workspace.id))
        old = db.get(PlanCatalogSnapshot, current.catalog_id)
        if current.spend_cap_minor is not None:
            report['explicit_spend_caps_preserved'] += 1
        if old.content_hash == body['content_hash']:
            report['unchanged'] += 1
            continue
        previous = old.content['plans']['free']
        if any(target['included'][key] < value for key, value in previous['included'].items()):
            raise ValueError('Beta adoption must not reduce existing allowances')
        if target['spend_cap_minor'] < previous['spend_cap_minor']:
            raise ValueError('Beta adoption must not reduce the default spending cap')
        report['changed'] += 1
        if not apply:
            continue
        if snapshot is None:
            snapshot = plans.catalog_snapshot(db)
            if snapshot.content_hash != body['content_hash']:
                raise ValueError('Catalog changed during beta adoption; retry with the intended version')
        current.catalog_id = snapshot.id
        db.add(Audit(workspace_id=workspace.id, actor_id=None,
            action='billing.beta_allowance_granted', resource_id=current.id,
            data={'previous_catalog_id': old.id, 'catalog_id': snapshot.id,
                  'version': body['version'], 'included': target['included'],
                  'default_spend_cap_minor': target['spend_cap_minor'],
                  'explicit_spend_cap_preserved': current.spend_cap_minor is not None,
                  'usage_reset': False, 'pause_state_changed': False}))
    return report

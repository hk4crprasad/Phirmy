"""Browser-only, explicitly allowlisted financial operations and cost review."""
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import Field
from sqlalchemy import case, func, select

from .config import settings
from .db import now
from .models import (
    BillingFinancialEvent, BillingWebhookInbox, BudgetAdmission, Call, CallCostRecord,
    Job, Ledger, PaymentOrder, Workspace, WorkspaceSubscription,
    PaymentRefund, PaymentDispute, BillingProviderOperation,
)
from .schemas import Input
from .security import Principal, active_user, audit, db_dependency

router = APIRouter(prefix="/v1/operator/billing")
FINANCIAL_JOBS = {"invoice_pdf", "billing_refund", "billing_subscription_create", "billing_subscription_cancel"}


def operator(request: Request, db=Depends(db_dependency, scope="function")):
    if request.headers.get("x-api-key"):
        raise HTTPException(403, "Operator actions require a verified dashboard session")
    user = active_user(request, db)
    from .sessions import profile_for
    allowed = {x.strip().casefold() for x in settings.billing_operator_emails.split(",") if x.strip()}
    if user.email.casefold() not in allowed or profile_for(db, user.id).email_verified_at is None:
        raise HTTPException(403, "Verified billing operator access is required")
    return user


@router.get('/unit-economics')
def unit_economics(user=Depends(operator)):
    from .unit_economics import report
    return report()


def grouped(db, statement):
    return dict(db.execute(statement).all())


def report(db, since, ids=None):
    """Set-based aggregates: no conversation content or per-workspace queries."""
    def totals(model, value, *conditions):
        query = select(model.workspace_id, func.coalesce(func.sum(value), 0)).where(
            model.created_at >= since, *conditions
        )
        if ids is not None:
            query = query.where(model.workspace_id.in_(ids))
        return grouped(db, query.group_by(model.workspace_id))

    costs = totals(CallCostRecord, CallCostRecord.cost_micro_minor, CallCostRecord.source != "synthetic")
    unreported = totals(CallCostRecord, 1, CallCostRecord.source == "unreported")
    revenue = totals(BillingFinancialEvent, BillingFinancialEvent.details["revenue_delta_minor"].as_integer())
    fees = totals(BillingFinancialEvent, BillingFinancialEvent.details["provider_fee_minor"].as_integer(),
                  BillingFinancialEvent.kind.in_(["wallet_funding", "subscription_fee"]))
    missing_fees = totals(BillingFinancialEvent, 1,
                          BillingFinancialEvent.kind.in_(["wallet_funding", "subscription_fee"]),
                          BillingFinancialEvent.details["provider_fee_minor"].as_integer().is_(None))
    wallet_query = select(Ledger.workspace_id, -func.sum(Ledger.amount_minor)).join(
        Call, (Call.id == Ledger.call_id) & (Call.workspace_id == Ledger.workspace_id)
    ).join(Workspace, Workspace.id == Ledger.workspace_id).where(
        Ledger.created_at >= since, Ledger.amount_minor < 0, Call.mode == "live", Workspace.currency == "INR")
    if ids is not None:
        wallet_query = wallet_query.where(Ledger.workspace_id.in_(ids))
    wallet = grouped(db, wallet_query.group_by(Ledger.workspace_id))
    # Holds of any age remain liabilities; the window must not hide old unknowns.
    outstanding = case((BudgetAdmission.reserved_micro_minor > BudgetAdmission.measured_micro_minor,
                        BudgetAdmission.reserved_micro_minor - BudgetAdmission.measured_micro_minor), else_=0)
    holds_query = select(BudgetAdmission.workspace_id, func.sum(outstanding)).where(
        BudgetAdmission.state.in_(["held", "unknown"])
    )
    if ids is not None:
        holds_query = holds_query.where(BudgetAdmission.workspace_id.in_(ids))
    holds = grouped(db, holds_query.group_by(BudgetAdmission.workspace_id))
    identities = set(costs) | set(revenue) | set(wallet) | set(holds) | set(unreported) | set(fees) | set(missing_fees)
    result = {}
    for identity in identities:
        net = int(revenue.get(identity, 0)) + int(wallet.get(identity, 0))
        cost = int(costs.get(identity, 0))
        fee = int(fees.get(identity, 0))
        result[identity] = {
            "provider_cost_micro_minor": cost,
            "recognized_receipts_minor": net,
            "reported_payment_fees_minor": fee,
            "contribution_micro_minor": (net - fee) * 1_000_000 - cost,
            "outstanding_cost_micro_minor": int(holds.get(identity, 0)),
            "unreported_usage_records": int(unreported.get(identity, 0)),
            "unreported_payment_fee_receipts": int(missing_fees.get(identity, 0)),
        }
    return result


@router.get("")
def overview(days: int = Query(default=30, ge=1, le=366), after: str = Query(default="", max_length=36),
             limit: int = Query(default=50, ge=1, le=100), search: str = Query(default="", max_length=120),
             user=Depends(operator), db=Depends(db_dependency, scope="function")):
    since = now() - timedelta(days=days)
    query = select(Workspace, WorkspaceSubscription).outerjoin(
        WorkspaceSubscription, WorkspaceSubscription.workspace_id == Workspace.id
    ).where(Workspace.id > after)
    if search:
        query = query.where(Workspace.name.ilike("%" + search.replace("%", "\\%").replace("_", "\\_") + "%", escape="\\"))
    rows = list(db.execute(query.order_by(Workspace.id).limit(limit + 1)))
    metrics = report(db, since)  # Global top consumers must not depend on this page.
    empty = {"provider_cost_micro_minor": 0, "recognized_receipts_minor": 0,
             "reported_payment_fees_minor": 0, "contribution_micro_minor": 0,
             "outstanding_cost_micro_minor": 0, "unreported_usage_records": 0, "unreported_payment_fee_receipts": 0}
    def item(workspace, subscription):
        return {"id": workspace.id, "name": workspace.name, "currency": "INR", "workspace_currency": workspace.currency,
                "plan": subscription.plan_slug if subscription else "free",
                "subscription_state": subscription.state if subscription else "free",
                "operator_paused": bool(subscription and subscription.operator_paused),
                "billing_blocked": bool(subscription and subscription.billing_blocked),
                "spend_cap_minor": subscription.spend_cap_minor if subscription else None,
                **metrics.get(workspace.id, empty)}
    top_ids = sorted(metrics, key=lambda key: metrics[key]["provider_cost_micro_minor"], reverse=True)[:10]
    top_rows = db.execute(select(Workspace, WorkspaceSubscription).outerjoin(
        WorkspaceSubscription, WorkspaceSubscription.workspace_id == Workspace.id
    ).where(Workspace.id.in_(top_ids))) if top_ids else []
    top = {ws.id: item(ws, sub) for ws, sub in top_rows}
    return {"status": "DRAFT", "since": since.isoformat(), "days": days,
            "basis": "Net captured subscription fees plus settled live wallet calls; wallet top-ups excluded. "
                     "Provider costs are configured estimates; unknown usage and holds remain separate. "
                     "Non-INR wallet entries are excluded. Only reported payment fees are deducted; missing fees remain unreported. "
                     "This contribution view is not statutory revenue recognition or an invoice reconciliation.",
            "items": [item(ws, sub) for ws, sub in rows[:limit]],
            "next_cursor": rows[limit - 1][0].id if len(rows) > limit else None,
            "top_consumers": [top[key] for key in top_ids if key in top],
            "refunds_enabled": settings.billing_operator_refunds_enabled}


class Control(Input):
    paused: bool
    reason: str = Field(min_length=10, max_length=500)
    spend_cap_minor: int | None = Field(default=None, ge=0, le=1_000_000_000, strict=True)


@router.put("/workspaces/{workspace_id}/control")
def control(workspace_id: str, body: Control, user=Depends(operator), db=Depends(db_dependency, scope="function")):
    from .plans import subscription
    from .billing_accounting import lock
    lock(db, workspace_id)
    current = subscription(db, workspace_id)
    before = {"paused": current.operator_paused, "spend_cap_minor": current.spend_cap_minor}
    current.operator_paused = body.paused
    if body.paused:
        from .domain import enqueue, TERMINAL
        # A transferred carrier call outlives its AI media socket. Explicitly
        # hang up every active live leg rather than depending on socket polling.
        for call in db.scalars(select(Call).where(Call.workspace_id==workspace_id,Call.mode=='live',
                Call.transport=='pstn',Call.state.not_in(TERMINAL),Call.provider_call_id.is_not(None))):
            pending=db.scalar(select(Job.id).where(Job.workspace_id==workspace_id,Job.kind=='hangup',
                Job.state.in_(['queued','running']),Job.payload['call_id'].as_string()==call.id))
            call.state='ending'
            if not pending:enqueue(db,workspace_id,'hangup',{'call_id':call.id})
    if "spend_cap_minor" in body.model_fields_set:
        current.spend_cap_minor = body.spend_cap_minor
    audit(db, Principal(user.id, workspace_id, "admin"), "operator.billing_control", workspace_id,
          {"before": before, "paused": body.paused, "spend_cap_minor": current.spend_cap_minor, "reason": body.reason})
    return {"operator_paused": current.operator_paused, "billing_blocked": current.billing_blocked,
            "spend_cap_minor": current.spend_cap_minor}


@router.get("/dead-letters")
def dead_letters(user=Depends(operator), db=Depends(db_dependency, scope="function")):
    receipts = db.scalars(select(BillingWebhookInbox).where(BillingWebhookInbox.state == "failed").order_by(
        BillingWebhookInbox.created_at.desc()).limit(100))
    jobs = db.scalars(select(Job).where(Job.state == "failed", Job.kind.in_(FINANCIAL_JOBS)).order_by(Job.created_at.desc()).limit(100))
    return {"webhooks": [{"id": row.id, "provider_event_id": row.provider_event_id,
                         "attempts": row.attempts, "error_code": row.error_code,
                         "created_at": row.created_at.isoformat()} for row in receipts],
            "jobs": [{"id": row.id, "workspace_id": row.workspace_id, "kind": row.kind,
                      "attempts": row.attempts, "created_at": row.created_at.isoformat()} for row in jobs]}


class Review(Input):
    reason: str = Field(min_length=10, max_length=500)


@router.post("/workspaces/{workspace_id}/jobs/{job_id}/retry", status_code=202)
def retry_job(workspace_id: str, job_id: str, body: Review, user=Depends(operator),
              db=Depends(db_dependency, scope="function")):
    from .domain import owned
    job = owned(db, Job, workspace_id, job_id)
    if job.kind not in FINANCIAL_JOBS or job.state != "failed":
        raise HTTPException(409, "Only failed financial jobs can be reviewed here")
    job.state, job.error, job.cancel_requested = "queued", None, False
    job.lease_until, job.lease_token, job.available_at = None, None, now()
    job.payload = {**job.payload, "errors": 0, "polls": 0}
    audit(db, Principal(user.id, workspace_id, "admin"), "operator.financial_job_retry", job_id,
          {"reason": body.reason, "kind": job.kind})
    return {"id": job.id, "state": job.state}


@router.post("/workspaces/{workspace_id}/webhooks/{receipt_id}/retry", status_code=202)
def retry_webhook(workspace_id: str, receipt_id: str, body: Review, user=Depends(operator),
                  db=Depends(db_dependency, scope="function")):
    from .billing_accounting import lock
    lock(db, workspace_id)
    row = db.get(BillingWebhookInbox, receipt_id, with_for_update=True)
    if not row:
        raise HTTPException(404, "Webhook receipt not found")
    if row.state != "failed" or not row.encrypted_payload:
        raise HTTPException(409, "Only retained dead-letter receipts can be retried")
    row.state = "pending"
    row.attempts = 0
    row.next_attempt_at = now()
    row.lease_token = None
    audit(db, Principal(user.id, workspace_id, "admin"), "operator.webhook_retry", receipt_id, {"reason": body.reason})
    return {"id": row.id, "state": row.state}


class ReviewedRefund(Review):
    amount_minor: int = Field(ge=1, le=10_000_000, strict=True)


@router.post("/workspaces/{workspace_id}/payments/{order_id}/refunds", status_code=202)
def reviewed_refund(workspace_id: str, order_id: str, body: ReviewedRefund, request: Request,
                    user=Depends(operator), db=Depends(db_dependency, scope="function")):
    if not settings.billing_operator_refunds_enabled:
        raise HTTPException(409, "Reviewed refund exceptions are disabled")
    from .refund_routes import create_refund
    actor = Principal(user.id, workspace_id, "admin")
    result = create_refund(db, workspace_id, order_id, body.amount_minor,
                           request.headers.get("Idempotency-Key", ""), actor, reviewed=True)
    audit(db, actor, "operator.refund_reviewed", result["id"], {"reason": body.reason, "gross_minor": body.amount_minor})
    return result


@router.post("/workspaces/{workspace_id}/resolve-refund-review")
def resolve_refund_review(workspace_id: str, body: Review, user=Depends(operator),
                         db=Depends(db_dependency, scope="function")):
    from . import billing_accounting as money, plans
    money.lock(db, workspace_id)
    current = plans.subscription(db, workspace_id)
    if current.state != "refund_review":
        raise HTTPException(409, "The workspace has no subscription refund review")
    contract = db.scalar(select(BillingProviderOperation).where(
        BillingProviderOperation.kind == "subscription",
        BillingProviderOperation.provider_id == current.provider_subscription_id))
    if not contract or contract.state not in {"cancelled", "completed", "expired"}:
        raise HTTPException(409, "Confirm provider cancellation before ending refunded coverage")
    if db.scalar(select(PaymentRefund.id).where(PaymentRefund.workspace_id == workspace_id,
                                               PaymentRefund.state.in_(money.REFUND_HELD))):
        raise HTTPException(409, "Reconcile pending refunds before ending review")
    if db.scalar(select(PaymentDispute.id).where(PaymentDispute.workspace_id == workspace_id,
                                                PaymentDispute.state.in_(money.DISPUTE_HELD))):
        raise HTTPException(409, "Resolve open disputes before ending review")
    workspace = db.get(Workspace, workspace_id)
    current.plan_slug = "free"
    current.state = "free"
    current.pending_plan_slug = None
    current.period_start, current.period_end = plans.month_bounds(now(), workspace.timezone)
    money.refresh_block(db, workspace_id)
    audit(db, Principal(user.id, workspace_id, "admin"), "operator.refund_coverage_ended", workspace_id,
          {"reason": body.reason, "provider_subscription_id": contract.provider_id})
    return {"plan": "free", "billing_blocked": current.billing_blocked}

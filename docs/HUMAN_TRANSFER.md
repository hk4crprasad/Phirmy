# Human transfer and callback

Live transfer is implemented behind `LIVE_TRANSFER_ENABLED=false`. Paid activation
also remains disabled. Production additionally requires an APPROVED immutable call
tariff. DRAFT numbers and local fake-provider tests do not authorize real phone calls.

## Prepare a destination

In Integrations, an owner/admin saves a staff number, the team label read to callers,
and a duration limit. The default120seconds and configurable5–300second range are
DRAFT operating limits. Every edit creates a new revision and removes approval.
API keys cannot change the destination. The normal response exposes only its last
four digits. Destination and per-call carrier credentials are encrypted with the
existing versioned key provider and included in the rotation job's model discovery.

A verified platform operator explicitly reviews the full destination and attests
that it belongs to staff. The operator uses the existing BILLING_OPERATOR_EMAILS
allowlist and a dashboard session with CSRF. Approval is bound to the exact revision
and audited. Revocation blocks subsequent setup; the workspace kill switch ends
active parent carrier calls through durable hangup jobs.

## Request and connect

A live phone caller receives an exact team/reason/revision readback and must confirm
on a later turn. Changing the destination or disabling permission invalidates that
readback. Browser voice and widget chat retain inbox handoff and manual callback;
they cannot use a phone transfer. Platform-funded trial calls cannot transfer.

Each call can create one transfer intent and one submission job. Staff numbers
come from the approved server policy; callers and model arguments cannot choose a
number. The provider adapter redirects the existing carrier leg to signed XML
instructions. All network writes are bounded and never automatically retried.
The first valid instruction fetch can authorize one Dial. Further fetches hang up
instead of dialing again. A lost XML response can therefore end a call; this is a
conservative consequence of avoiding a duplicate paid call.

Twilio uses Call update(url, method=POST, time_limit=original admitted limit) and
Dial with timeLimit, timeout and action. Plivo transfers the A leg to aleg_url,
then uses scheduled Hangup plus Dial timeLimit/timeout/action/callbackUrl. Ten-second
ringing and a20second deadline margin are DRAFT tuning; Twilio documents an added
five-second timeout buffer. Transfer never creates a fresh overall call deadline.

## Accounting and uncertain results

The original parent wallet, included voice and carrier reservations stay active
after the AI media socket closes. Its real hangup settles the full observed parent duration using the existing
call adapter; this remains a DRAFT cost estimate, not a reconciled carrier invoice.
The new staff leg receives a separate admission-time cost hold, rounded up to a
minute for the configured maximum. Parent admission uses its actual carrier's
DRAFT rates. Staff duration comes only from a signed, account/parent-bound provider
callback and creates an immutable separate cost record. Duplicate equal callbacks
are idempotent; conflicting duration or child identity requires review.

An ambiguous write or interrupted submission becomes unknown and retains its
hold. A job retry cannot resend it. A valid provider instruction/status callback
can resolve that uncertainty. No callback means no invented zero-cost success;
operators must inspect the carrier outcome. Status and retained holds remain
visible when activation is switched off. Carrier credentials are frozen per
transfer so rotating a workspace key does not break settlement authentication.

Connection is never claimed from a queued request or HTTP acknowledgement. The
operator view reports confirmed connection only after completed staff-leg duration
is available. The workspace kill switch blocks pending submissions/instructions
and queues one parent hangup even after AI media has detached; signed final costs
can still settle while the workspace is paused.

## Manual callback

The call-me-back flow collects a caller-provided E.164 number, reads it back and
requires a later confirmation. It creates one inbox ticket and owner outbox email.
The team can mark it open, pending or resolved. The phone remains explicitly
unverified; permission covers this callback only and grants no marketing consent.
Requested timing is not a promised appointment. No automatic outbound call occurs.
`CALLBACK_REQUESTS_ENABLED=false` disables new callback proposals/execution.

## Verification and deployment

See VERIFICATION for exact completed test counts and DECISIONS for dated official
references. Provider adapters, signatures, concurrency, budgeting and browser
settings are tested locally with fake carrier boundaries; no real transfer was
made. Real phone acceptance remains gated by approved prices, activation and the
approved destination. Existing credential presence is not a claim of live acceptance.

The additive development migration adds transfer_policies and call_transfers at
revision2026-10-27-call-transfers. Production startup verifies schema; it does not
apply DDL. Apply reviewed migrations using scripts/migrate_database.py before a
production deployment. This schema has only been applied to isolated development
and disposable test databases; the supplied Supabase was not migrated.

Phase3 data-rights integration must remove encrypted staff policies and transfer
snapshots after their financial holds are resolved, while retaining immutable
financial facts. Callback queued mail is linked by Ticket.operation_key prefix.

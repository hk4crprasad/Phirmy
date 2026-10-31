# Billing and admission

## Full-app beta testing allowances - 29 October 2026

The Free beta includes 1,000 conversations, 10,000 chat turns, 7,200,000 ms
(120 minutes) of voice, and 5,000 crawl pages per month. Current inventory limits
are 1 GB of stored objects, five widgets, and five seats. These are one shared
pool per original owner across their Free workspaces, not a new grant per widget
or workspace. Existing usage and outstanding reservations still count.

The default provider-spend ceiling is INR1,500 per monthly owner pool and per
workspace; explicit owner caps and paused/blocked states remain authoritative.
Widget defaults permit 1,000 sessions and 5,000 turns per day, 100 sessions and
1,000 turns per visitor IP daily, a five-minute voice session and INR1,000 monthly
spending. Workspace chat allows 2,000 daily turns; voice concurrency stays two.
These remain bounded beta limits, not a promise to exhaust every resource quota
before a spend/rate/owner limit applies. Telephony purchases, paid activation,
live transfers and bot challenge activation are not changed.

After deploying the new config, explicitly preview and apply it to existing
Free subscriptions using the runtime container:

```sh
python scripts/apply_beta_allowances.py --catalog-version DRAFT-2026-10-29-full-beta-testing
python scripts/apply_beta_allowances.py --catalog-version DRAFT-2026-10-29-full-beta-testing --apply
```

The bounded migration audits each changed subscription, preserves immutable
catalog/tariff/usage history, explicit spending caps, holds, debt and pause state,
and skips paid subscriptions. New subscriptions use the current catalog normally.
Private environment overrides must match the new defaults before recreation.

## DRAFT unit economics and shared Free pool

Verified, allowlisted billing operators can review
`GET /v1/operator/billing/unit-economics` and the Operations panel's expandable
unit-economics report. `config/unit_economics.json` defines explicit DRAFT workload
assumptions; `config/plans.json` supplies the DRAFT rates and plan prices. The
report compares chat turns, browser voice minutes and phone minutes for every
configured model. It shows each included allowance and alternative combined
chat/voice/knowledge scenarios, price-loss flags and where a spend cap prevents
the full allowance from being delivered. Phone and browser share one voice pool.
These are arithmetic scenarios, not measured traffic, actual profit or vendor
quotes. GST, payment fees, hosting, rendering CPU, support and fixed costs are
excluded. No cache-read savings are assumed; the DRAFT scenario conservatively
includes all-input30-minute cache-write exposure where that rate is higher.
Current DRAFT allowances flag
loss exposure on every plan; Free is subsidized and Custom requires a quote.
Paid activation remains disabled pending final prices/business approval.

Free accounts share one pool across workspaces sponsored by the original owner:
monthly conversations, chat turns, voice duration and crawl pages; current
storage/widgets/team inventory; provider spending and outstanding holds. User
row locks serialize concurrent workspace admissions. The global period is the
UTC calendar month, independent of workspace timezone. Ownership changes cannot
change `workspaces.free_allowance_user_id`; a database trigger rejects resetting
it. Signup creates the anchor. Migration backfills the earliest owner; an orphan
workspace fails clearly until an owner is assigned. Ownerless test fixtures must
declare an owner rather than get an invented shared identity.

New meter events carry the tariff identifying their plan. Shared queries include
historical Free usage even after an upgrade, downgrade, member removal or
workspace deletion, using retained immutable financial records. New paid usage
is excluded. Legacy untagged usage counts conservatively rather than granting a
reset. Storage and team inventory in currently paid workspaces are excluded.
The same team member counts once across Free workspaces. Unknown holds remain
reserved across month boundaries; actual measurements release unused provider
budget. Denial rolls back the attempted work and enqueues one deduplicated,
encrypted billing email to the sponsor. Existing per-workspace caps and operator
kill switches still apply. Development multipliers remain explicit and ignored
in production.

Billing shows the shared aggregate only to the original sponsor's browser
session. Other workspace members and scoped API keys see their workspace data,
without the sponsor's usage across other workspaces. Other members may still
receive an allowance denial, which explains that Free is shared.

Commercial prices and all provider-rate estimates in `config/plans.json` are
**DRAFT**. Checkout requires `PAID_ACTIVATION_ENABLED=true`, an APPROVED catalog,
and configured Razorpay credentials. The checked-in flag is false and catalog
is DRAFT. Signed webhooks remain processable when checkout is disabled.

Catalogs and tariffs are content-addressed, immutable snapshots. Usage events
and provider cost lines cannot be updated or deleted. Costs use integer
micro-paise (1,000,000 micro-paise = 1 paise); retail amounts use paise. Fish TTS
uses submitted UTF-8 bytes; audio duration and character counts are separate
observations. Reported LLM input/output/cached tokens are retained. Missing final
usage is unreported, not estimated or relabelled zero-cost provider usage.

New tariff schema3 pins current provider prices separately from the subscription's
retail terms. Existing tariff snapshots remain unchanged. Cache reads, ordinary
input and30-minute/12-hour cache writes are disjoint cost buckets within total
input. The adapter requests30-minute writes and reserves their maximum input
rate before sending. Legacy Responses tariffs turn off writes; an uncontrolled
legacy Chat cache contract is rejected before provider I/O. Unpriced or
inconsistent write facts keep an unknown hold and pause spending for operator
review. Missing final usage also keeps the hold; a displayed zero monetary line
with source `unreported` is unknown cost, not free usage. DRAFT rates require
commercial review before activation.

## Admission

Workspace row locks serialize replicas. PostgreSQL concurrency acceptance is
`scripts/verify_billing_postgres.py`; SQLite uses BEGIN IMMEDIATE for writes.
Monthly plan windows use the workspace timezone, including DST. Seats count
members plus unexpired pending invitations. Widgets count installations. A
voice session holds its complete admitted duration, then releases unused minutes
when measured duration is recorded. Crawl attempts reserve a page before fetch;
failed/unknown attempts conservatively keep a slot until the period ends.

Before model requests, UTF-8 input plus protocol overhead and a strict output
cap reserve the configured worst-case cost. Models that omit a token cap cannot
run in a metered workspace. STT duration is reserved before connecting and the
PCM sample budget is enforced before sending audio. Every TTS text chunk grows
its hold before forwarding. Carrier duration is bounded at dispatch and answer;
answer replays cannot extend the first deadline. Known final usage releases the
unused hold; missing or uncertain usage keeps it. No timeout automatically frees
an unknown provider expense. A provider overrun records the full observation,
pauses new workspace work and alerts the owner; it is never truncated to fit a
reservation. DRAFT configured rates cannot certify an actual vendor invoice.

Workspace and widget spend checks include measured costs and outstanding holds.
Owners receive deduplicated 80%/100% emails through the encrypted outbox. A denial
rolls back pending application changes before persisting only the alert. Public
clients receive an allowance/spend message. Budget holds, unknown requests and
effective limits are available in the scoped billing usage API.

The explicit `BILLING_DEVELOPMENT_ALLOWANCES_ENABLED` flag multiplies resource
allowances and the default spend cap by 1,000 in test/development only. It does
not change measured costs, tariffs or wallet money. Production ignores it. The
usage response exposes that multiplier; production limits are tested without it.

## Storage inventory and uncertain writes

Uploads reserve their exact content-addressed bytes in a committed transaction
before object-provider I/O. A later parsing/request rollback cannot hide an
abandoned object. An uncertain write retains its hold; an identical retry reuses
it and records the object once. Confirmed object deletion emits a release.

Existing workspaces must complete an inventory before production uploads are
accepted. New workspaces have an initially empty, complete inventory. Select the
intended environment explicitly, then inspect a read-only scan:

```sh
uv run python scripts/reconcile_storage.py --workspace-id WORKSPACE_ID
```

Use `--apply` to backfill legacy/orphan object sizes and reconcile holds for
objects actually found. Local storage and Azure paginated prefix inventories
implement the same interface. The scan budget defaults to 100,000 objects;
exceeding it fails without marking the inventory complete. Scans never delete
objects or treat absence in a possibly concurrent/partial listing as proof of
deletion. Unknown provider expenses and absent uncertain storage writes require
operator reconciliation with provider evidence; they remain held meanwhile.

No supplied remote database or private object account has been reconciled by
this change. Acceptance used local objects and fake Azure inventory properties.

## Retail tariffs

New live calls carry nonzero, immutable plan retail rates and provider rates.
The DRAFT Free/Starter/Growth policies include their voice allowance without a
second wallet debit; DRAFT Custom demonstrates metered wallet settlement.
`voice_billing` is configurable as included or wallet. Wallet mode requires both
approved catalog and paid activation, and reserves only affordable bounded
seconds before connecting. Included outbound calls retain the existing caller
budget liquidity hold and release it without a minute debit. Beta trial credit
is explicit. Synthetic PSTN calls use configurable development credit (DRAFT
600 paise/minute), while simulated browser audio does not spend purchased money.

Settlement reads the original tariff, including its immutable transport/trial
classification. Later metadata/plan edits or disabling checkout cannot rewrite
already-admitted terms. Legacy schema1 calls retain their original rates and
reservations; historical free calls cannot acquire a new charge on upgrade.

Model-rate entries are **DRAFT conservative estimates, not vendor price claims**.
They are configuration by model identity, pinned inside each tariff. Real model
cost records retain model identity even during simulation; only explicitly
synthetic requests cost zero. Production refuses an unmapped model before I/O;
test/development can use the marked DRAFT base estimate for fake custom models.
No model availability claim follows from a configured price-map entry. Final
rates, currencies/FX assumptions and retail policies require commercial review.


## Payments, refunds and invoices

Merchant details and tax policy live in `config/billing_business.json`. All
checked-in values are DRAFT; activation additionally requires APPROVED business
and catalog plus configured merchant credentials. First save the workspace
billing profile, then review the signed 15-minute quote before checkout. Changing
profile or commercial configuration invalidates the quote. Only INR is accepted.
Never replace a provider receipt after an uncertain outcome to force another
charge. Subscription creation and cancellation are durable worker operations;
unknown creation/cancellation reconciles read-only. Reuse the original
idempotency key to recover cancellation after a failed job.

Subscription fees grant captured coverage, not wallet credit. A small mandate
authorization grants neither. Failed renewal blocks new paid work during DRAFT
seven-day read/export grace and then downgrades to Free. Cancellation retains
already-paid coverage. Self-service new plans start after old coverage ends.
Top-up refunds are limited to unspent available credit, exclude reservations and
open disputes, and persist a hold before provider I/O. Subscription refunds and
spent-credit exceptions require operator review. Processed refunds emit credit
notes with original invoice reference. Overlapping disputes/refunds cannot debit
more than the original net amount. Spent reversals become an explicit adjustment;
new funds settle that adjustment before available credit grows. Unknown holds
never expire merely because a retry budget ends.

Webhooks require raw-body HMAC and X-Razorpay-Event-Id. A durable encrypted inbox
acks before processing, retries with leases and retains dead letters for review.
`RAZORPAY_WEBHOOK_PREVIOUS_SECRETS_JSON` accepts at most three objects with
`secret` and ISO `valid_until`; expired entries cannot validate a receipt. Secret
rotation must preserve the old secret only for the intended retry window.
Disabling paid activation does not discard money already captured or signed
refund/dispute events. API keys can read allowed billing resources but cannot
mutate checkout, profile, subscriptions or refunds.

Invoice numbers are serialized per business entity and Indian financial year;
DRAFT uses a distinct DRF series. Final documents require the stored approved
live quote. PDFs use the networkless content sandbox and local multilingual
fonts, private scoped objects and encrypted outbox attachments. Financial PDFs
are not customer uploaded-storage quota. Invoice financial snapshots and money
events are immutable. Delivery metadata and retries are separate. GSTIN checks
are local checksum/state checks, not a registry lookup. An accountant must approve
registration, SAC, rates and tax treatment before live activation.

Useful isolated acceptance commands: `uv run pytest -q tests/test_payment_reconciliation.py
tests/test_billing_subscriptions.py tests/test_gst_invoices.py`; `uv run python
scripts/verify_payment_reconciliation_postgres.py`; and, with the local production
web server running, `PYTHONPATH=services/control uv run python
scripts/verify_billing_browser.py`. The PDF accessibility test needs `pdftotext`
from poppler-utils. Browser acceptance uses a fake provider and isolated local
database, never an actual merchant account.


## Operator review

Set `BILLING_OPERATOR_EMAILS` only for verified support/operator accounts. The
empty default denies every account. The restricted view appears in Operations;
its API is `/v1/operator/billing`. Workspace ownership alone does not grant
platform financial access. API keys cannot access it. Mutations require CSRF,
allowed Origin and a reason. Search/cursor pages and global top consumers show
DRAFT estimated costs/contribution, outstanding holds and unreported usage/fees.
Wallet funding is excluded from receipts. The report is in INR and excludes
non-INR wallet entries; it does not implement FX or statutory revenue recognition.

Pause spending or set a cap from the workspace control dialog. Pauses deny new
admission and close active media at the next safety check. Resume preserves all
financial reviews and holds. Dead-letter webhook/job retries preserve original
provider identities and uncertain-write state; resolve the underlying evidence
before retrying. Payloads, credentials and raw financial webhook bodies are
never included in this view.

`BILLING_OPERATOR_REFUNDS_ENABLED=false` additionally gates reviewed spent-credit
or subscription refunds. Enable only after approving the DRAFT refund policy.
A subscription refund queues provider cancellation and holds coverage in review;
a terminal cancellation and reconciled refunds are required to end coverage and
move to Free. Duplicate/refunded captures cannot restore the plan. Spent wallet
refunds create an adjustment rather than a negative wallet. These actions use
the existing durable refund worker; they never directly claim provider success.

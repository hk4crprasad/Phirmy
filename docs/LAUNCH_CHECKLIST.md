# Public launch checklist

Status on 25 October 2026: **implementation in progress, not ready for public launch**.
The user accepted Phase 1 items 1 and 2. Remaining items are active implementation
work; DRAFT configuration and fake providers will cover missing commercial or
external settings. Only live acceptance requiring a specific external credential
may remain blocked; a pending item is not a deferral or a completion claim.


## Revised execution order — 25 October 2026

The latest user checkpoint changes the remaining order. Continue each step with
checks and an honest update; incomplete buildable work remains active work.

1. **Done.** Fake scheduling/model profiles declare their model identity; invalid
   profiles fail clearly before provider use or metering in every environment.
   No model is invented for tests. Full Docker run: **623 passed, 2 skipped,
   0 failed in433.23s**. All six voice/widget booking cases, dictation and document
   upload passed. Two alternate scheduling-provider branches were intentionally
   inapplicable; four old pytest cleanup warnings were non-fatal.
2. **Done; hosted CI execution unaccepted.** `sandbox` marker and `--run-sandbox`
   opt-in; CI rejects omitting the flag and its workflow installs prerequisites
   and runs the real integrations. Docker-free full run:603passed26skipped0failed
   in403.19s, zero Docker invocations. Final Docker full run:627passed2skipped0failed
   in445.27s. The first integration run found a timing-sensitive concurrency test
   (626passed1failed2skipped); an actual overlap barrier fixed it. Runtime
   isolation stays mandatory. Four old temporary-directory cleanup warnings remain.
3. **Done; deployment acceptance pending.** Four public assets cache60s with
   ETag/304; HTML remains no-store. Shared five-second frame-policy cache,
   proof-expiry bound and transaction/bulk invalidation; API authorization stays
   current. Redis outage denies unfenced mutations; read/API outage falls back
   safely. Native built Next+isolated API+Redis verified warm pages make zero
   policy API calls, revocation and outage behavior, four conditional304s and
   zero page errors. Regression611passed26skipped0failed306.62s with Docker
   unavailable; focused38passed and final8cache cases passed. Type/build pass.
4. **Done; production migration and pricing approval pending.** Restricted
   operator unit-economics report compares chat/browser/phone and full allowance
   costs for each model, with loss and cap-delivery flags. Current DRAFT numbers
   flag every plan; paid activation remains off. Original-owner Free allowances,
   inventories and spending are shared across workspaces under a user lock, with
   immutable sponsorship and UTC monthly boundaries. Sponsor-only aggregate
   disclosure; unknown holds survive month changes. Focused48passed; PostgreSQL
   cross-workspace concurrency, migration/backfill and reset protection passed.
   Actual Chromium billing/economics/model switch/kill checks passed, zero errors.
   Final Docker-free regression623passed26skipped0failed359.55s; type/build pass.
5. **In progress.** Phase6 voice latency now precedes the remaining Phases3–5.
   Stage instrumentation and call-detail display are implemented; measured
   synthetic baseline12turns:2331.229ms p50/2391.771ms p95, p50 target missed.
   Immediate safe deltas/flush/bounded TTS credit now measured423.657ms p50/
   468.694ms p95 across12synthetic turns; target passed in the fixture. CI target
   assertion configured; hosted result unaccepted. OpenAI explicit cache/write
   metering and completed/incomplete/tool events implemented and focused-tested.
   Persistent reuse/prefetch and live quality comparison remain work.
   No live-provider latency result. Paid phone activation remains closed.
6. **Pending.** Finish Phases3,4,5,7. Phase3 item1 is done; item2 work is preserved
   in a local WIP ref while the revised priority is executed, not marked done.

## Phase 1 — security and abuse

1. **Implemented; deployment acceptance pending.** Atomic Redis sliding-window
   limiter with bounded, thread-safe local fallback and a warning; separate IP
   and actor admission limits for upload, crawl/recrawl, generation, tool tests,
   key creation, invitations and payment mutations; per-email 10-attempt,
   15-minute sign-in limit. Explicit proxy trust, no wildcard or /0 networks,
   Uvicorn pre-processing disabled, exact Caddy gateway address in beta Compose.
   Real Redis concurrency/expiry and ASGI spoofing tests pass. Actual public
   gateway deployment and outage behavior under production load are unaccepted.
2. **Implemented; production migration pending.** API keys cannot mutate keys,
   team or billing; developer mutation scopes require a browser session as well.
   No key can mint or expand another key. Optional timezone-aware expiry,
   last successful use, per-key minute limits and UI controls/columns. Legacy
   privileged keys are denied without rewriting their stored scopes. SQLite and
   disposable PostgreSQL upgrade checks preserve credentials; migrate the real
   database before starting revision `2026-10-24-key-security`.
3. **Implemented and tested; live credentials pending.** Turnstile sends token
   and trusted remote IP, checks hostname/action/age and fails closed in
   production. Installation/global-IP day quotas and atomic monthly spending
   reservations are independent of workspace limits. Voice calls and decoded
   dictation are bounded; owner 80%/100% alerts survive denial through the outbox.
   Reservation numbers and pinned Phase2 tariffs remain DRAFT safeguards,
   not measured provider invoices. Email is optional by default; unverified leads
   have no stored marketing choice. Scoped, expiring, attempt-limited outbox OTP
   proof gates consent. Promotional consent remains disabled behind a legal
   review flag with DRAFT wording. Backend and actual browser acceptance pass.
   Official Cloudflare server docs200 were read25October; official client source
   was read after rendered403. Only live acceptance needs TURNSTILE_SITE_KEY/
   TURNSTILE_SECRET_KEY; external delivery needs SMTP_HOST/SMTP_USER/SMTP_PASSWORD
   and sender settings. No implementation is deferred for those missing values.
4. **Implemented and tested.** Uniform HTTP 202 signup (new/existing) with no
   session or account IDs, equivalent Argon2 work and a common padded/jittered
   response window; uniform recovery responses and timing. Email verification
   gates workspace creation and sensitive actions in production; only explicit
   local development/test mode can bypass verification. Owned workspace creation
   is capped under a user row lock (default five). Signup preserves a pending
   initial workspace until email proof. All account and phone-alert email is
   queued transactionally with encrypted payloads, leased worker delivery,
   bounded backoff/dead letters, fencing and stable message IDs. SMTP outages do
   not fail HTTP requests. Verified SMTP TLS and fake delivery tests pass;
   actual external SMTP delivery requires configured SMTP credentials, not more
   implementation. QA scripts now bootstrap via signup → sign-in → me rather
   than treating registration as authentication.
5. **Implemented and tested.** No hard-coded Supabase host. Authenticated
   version/key IDs, backward reads of original Fernet and earlier IDs, local and
   pinned-version Azure Vault provider interface, bounded leased/checkpointed
   re-encryption jobs, CLI and closed operator API. Original timestamps and old
   keys remain available; no automatic key retirement. Global/tenant scope,
   errors/recovery, actual dispatcher/CLI and restricted-role PostgreSQL tests
   pass. Immutable tool versions permit only leased ciphertext updates and keep
   metadata/audit guards. No real key/data rotation was performed. Only optional
   live Vault acceptance requires configured URL/version and secrets/get identity.
6. **Implemented and tested.** Per-response nonces and strict-dynamic script
   CSP (no production unsafe-inline/unsafe-eval scripts), dynamic Next rendering,
   explicit nonce on theme bootstrap, dashboard framing denied and widget
   external framing closed pending domain proof. Inline style attributes remain
   allowed for the existing UI; this does not permit executable inline scripts.
   HSTS includes subdomains. API bodies have declared/actual byte limits,
   chunked/timeout protection and no compressed-body bypass. Production API docs
   and OpenAPI require a verified browser session. Liveness is minimal; readiness
   checks DB, Redis, Qdrant and fresh active worker heartbeats shared in the DB.
   Production missing dependencies fail readiness. Backend tests and actual
   production Chromium pass; an injected parser-created script is blocked while
   dashboard controls work, with unique nonces and zero page errors.
7. **Implemented and tested.** Workspace-scoped, expiring DNS TXT/meta/well-known
   ownership challenges with encrypted random values, verified origin allowlists,
   revocation and token rotation. Public config/session/resume/voice checks and
   iframe policies consult current proof; publishable keys and legacy unrestricted
   flags cannot bypass it. Saving a website or preview never grants foreign-origin
   access. The platform's own trusted preview origin remains usable. Production
   proof requires HTTPS; public-IP pinning, same-origin redirects, TLS, byte and
   time limits protect HTTP proof checks. Permissions/challenges are reloaded
   after network waits to reject rotation, membership removal or role demotion.
   Dashboard proof/create/check/revoke and frame-policy updates passed in a real
   browser with the fake DNS provider confined to the separate QA process.
8. **Implemented and tested.** Immutable platform instruction hierarchy; owner,
   visitor and retrieved content in delimited lower-priority data messages.
   Known credentials are removed from model context, arguments and streamed
   output, including split tokens. Public endpoint fields require an explicit
   allowlist and private PII is removed. Side effects require a persisted,
   scoped, expiring read-back and a subsequent visitor confirmation; only an
   explicitly approved GET policy can run without confirmation. Unknown write
   outcomes cannot be retried automatically. Atomic per-conversation/call tool
   budgets count attempts and survive turns. Handoff intent classification only
   proposes a ticket; unrelated human words and negations cannot create one.
   Red-team tests cover injection, forged confirmation, tool abuse, PII, policy
   tightening, concurrent budgets and replay. Browser chat/voice acceptance is
   recorded in docs/VERIFICATION.md.
9. **Implemented and tested.** Mandatory network-isolated credential-free content
   service, separate job UIDs, inaccessible broker socket, read-only root,
   capped memory/CPU/PIDs/tmpfs and process-group/UID cancellation. No in-process
   parsing or rendering fallback. PDF page/operator/stream expansion limits;
   DOCX ZIP member/size/ratio/path/XML limits and declared/explicit/estimated page
   budgets (OOXML does not contain authoritative layout pagination). Rendering
   retains parent-authorized pinned GETs, robots, delays and resource budgets.
   Actual container probes and malicious-file/browser timeout/recovery tests
   pass, along with existing rendering lifecycle and ingestion regressions.
   See FILE_SAFETY.md for exact limits and deployment requirements.

## Phase 2 — monetisation and cost control

Implementation and local acceptance are complete. Full backend605passed2skipped,
frontend typecheck/build, PostgreSQL and native-browser checks passed. Plans and
provider rates are DRAFT configuration. Checkout requires both an explicit activation flag and
an APPROVED catalog; both remain closed in the checked-in configuration.

1. **Implemented and tested.** Configuration-defined Free/Starter/Growth/Custom
   plans, immutable catalog/tariff snapshots, measured conversation/turn/minute/
   page/storage events and per-call LLM/STT/TTS/carrier cost records. Provider
   usage includes cached input tokens, UTF-8 TTS input bytes and observed audio
   durations. Interrupted model streams without final usage remain explicitly
   unreported; costs are DRAFT estimates, never vendor invoice claims. Storage
   deletion emits releases without rewriting history. Workspace billing usage
   and call-cost APIs are scoped; read-only queries do not create subscriptions.
2. **Implemented and tested.** Admission-time conversation/turn/voice/page/
   storage/seat/widget allowances; bounded model, STT, TTS and carrier holds;
   per-workspace and per-installation spend checks; clear allowance messages and
   deduplicated 80%/100% owner outbox alerts. Unknown provider/storage outcomes
   remain held. Exact-byte uploads are reserved before external I/O; legacy
   production storage fails closed until a complete inventory backfill.
   Development allowances are explicit and ignored in production. See BILLING.md.
3. **Implemented and tested.** New live calls snapshot nonzero plan retail and
   provider rates at admission; legacy zero-rate labels are removed from new
   call creation. Included plan minutes debit quota, wallet-mode calls reserve
   affordable duration, and synthetic calls use separate configured development
   credit. Settlement uses original immutable terms after plan/flag edits. Model
   identity and pinned model rates are recorded; production blocks unmapped
   model pricing before I/O. Historical calls retain their original terms.
4. **Implemented and tested behind closed paid activation.** Razorpay top-ups
   and receipt-first subscriptions; exact raw HMAC/event-ID inbox, failed/refund/
   dispute reconciliation, unknown-write recovery and immutable money facts.
   Configurable DRAFT tax/business details, GSTIN local validation, isolated
   multilingual invoice/credit-note PDFs and outbox attachments; unspent-wallet
   refund flow, configurable DRAFT dunning/downgrade and captured-only coverage.
   Billing UI includes quotes, subscriptions, usage, refunds and scoped invoices.
   Official current payment docs were reachable and read. **Live acceptance
   deferred only for Razorpay merchant keys/webhook signing secret and SMTP
   credentials.** Final prices/business/GST/SAC/legal policies require owner and
   accountant review; checked-in values stay DRAFT and paid activation is false.
   Actual fake-provider browser, PDF and PostgreSQL concurrency/fencing passed.
5. **Implemented and tested.** Empty-by-default operator allowlist, verified
   browser/CSRF access, global spend/contribution/top-consumer view, literal
   search/cursor pages and audited per-workspace pause/cap. Unknown costs and
   missing provider fees remain visible; wallet funding is excluded from revenue.
   Pauses deny admission and stop active media. Restricted dead-letter retries
   and separately disabled reviewed refund exceptions retain financial guards.
   DRAFT policies and cost assumptions require commercial review. Native browser
   pause/resume/access-removal and PostgreSQL aggregate checks passed.

## Phase 3 — compliance and trust

Implementation is in progress. Legal text and policy numbers remain DRAFT for
lawyer review; implemented acceptance evidence does not imply legal approval.

1. **Implemented and tested.** Five versioned, clearly labelled DRAFT legal
   pages; required unchecked signup acceptance with immutable content snapshots,
   server timestamps and source. Existing-account signup cannot alter evidence.
   New Google accounts require an Origin-checked, signed browser intent bound
   into OAuth state; stale policy is rejected. Native browser, backend and
   PostgreSQL tests pass. Final wording requires lawyer input; placeholders
   remain DRAFT. Live Google acceptance needs GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET.
2. Account deletion, workspace deletion/grace period, visitor/contact export and
   deletion, configurable conversation/message/transcript/lead/recording
   retention with audited purges.
3. Call consent evidence/DNC imports, default recording and AI announcements,
   recipient-region calling windows, campaign compliance acknowledgement,
   per-workspace phone approval replacing the test-destination gate.
4. Widget AI disclosure, privacy link and consent; email collection off by default.

## Phase 4 — owner experience and product focus

Pending implementation after preceding phases; existing beta UI is not acceptance of this scope.

1. Lead/ticket/handoff/job-failure emails, instant/digest preferences and Slack/
   WhatsApp adapter interfaces.
2. Unified product/email/user-agent/metadata branding; customer-specific names
   and gift-store logic confined to explicit fixtures/development.
3. Preview-led public landing/pricing/how-it-works/FAQ/legal pages, metadata/OG/
   favicon/robots/sitemap, privacy-respecting funnel analytics.
4. URL → preview → save → verify → platform-specific snippet → installation
   detection → test lead → next-day summary; Advanced grouping for Models,
   Tools, Numbers and Developers.
5. Unanswered-question reports, feedback, per-assistant golden evaluations and
   knowledge-gap suggestions.
6. Cursor pagination/search/filters for calls, leads, conversations, tickets and
   contacts; replace fixed 200-row lists.

## Phase 5 — reliability and scale

Pending implementation after preceding phases; a passing local environment is not distributed
production readiness or a tested backup/restore strategy.

1. Remove blocking DB I/O from async handlers/media/carrier sockets; pooler-aware
   sizing and bounded timeouts.
2. Redis call/shared state, stateless multi-replica API, separate voice/media
   service and graceful active-call shutdown.
3. Alembic forward/rollback migrations, model-drift CI, composite indexes,
   N+1 removal and timezone-correct daily stats.
4. Provider timeout/backoff/circuit-breaker/fallback behavior and health metrics;
   current official provider documentation required first.
5. JSON request/call-correlated logs, latency/error/queue/provider/cost metrics,
   error tracking/alerts/status page, job/webhook dead-letter UI.
6. CI lint/ruff/type/backend/frontend/build/browser checks, dependency/container
   scanning, staging, tested database/object/Qdrant backup and restore.
7. Committed 100-chat/20-voice load tests with measured p50/p95 and bottleneck fixes.
   **Not run in this checkpoint; no load-capacity claim.**

## Phase 6 — voice latency

In progress before remaining Phases3–5 under the revised order. Current Fish and
OpenAI guides are reachable and were read on25 October2026. **Measured synthetic
baseline:2331.229ms p50/2391.771ms p95 across12turns; p50 target missed. No live
provider latency measurement or production target acceptance is claimed.**

1. **Part implemented.** Immediate safe text deltas, documented sentence/turn/tool
   flush, balanced PCM, producer failure monitoring and owned-task cleanup.
   Playback clears before cancellation cleanup. Call-owned setup now overlaps
   speech/retrieval. Documented stop/finish closes the physical socket; see the
   recorded protocol adjustment instead of a false cross-turn reuse claim.
2. **Part implemented.** Documented Responses text/tool/completed/incomplete
   events, explicit none/low voice effort, stable tenant-separated cache prefix,
   separate DRAFT write pricing/admission and immutable old tariffs. Incomplete
   output cannot authorize tools or replay. Synthetic tests pass; no measured
   cache hit or live effort/quality comparison yet. Full Docker suite:
   **700passed2skipped0failed502.03s**; typecheck/build and browser-connection
   cleanup checks pass. Phase6 remains in progress.
3. Stable-interim prefetch, parallel retrieval/setup, greeting cache, warm
   connections, transcript deltas and no blocking DB work in audio paths.
   **Part implemented:** bounded per-call LLM clients with authorization recheck,
   explicit cleanup and real localhost TCP keepalive proof. Fish setup overlaps
   retrieval. Static per-version greetings now cache completed PCM with tenant,
   exact-disclosure and personalization fences; replay has no new Fish cost.
   Core browser/Plivo/Twilio admission/context/settlement now run off-loop with
   cancellation-safe ownership and billing cleanup. Full Docker suite752passed,
   2skipped,0failed; typecheck/build/native client tests passed. Tool-specific
   async SQL and the broader HTTP audit remain active. Custom HTTP tool queue/
   claim/settlement is now off-loop with cancellation/no-replay checks
   (131passed1skipped). Scheduling availability/readback/confirmation/reconciliation
   now also passes off-loop SQL and cancellation checks (139passed2skipped).
   Calendar connector SQL remains active. Bounded stable-interim
   retrieval now reuses only exact final queries with fresh knowledge access;
   cancellation preserves embedding accounting.140passed2skipped. Dashboard and
   public voice negotiate stable Unicode transcript patches; old clients keep
   working.114passed3skipped, native client checks and typecheck/build passed.
4. **Part implemented.** Monotonic final transcript/admission/retrieval/LLM/TTS/
   transport timings persist per call; detail UI separates synthetic/live and
   failed/interrupted samples. Repeatable synthetic benchmark exercises actual
   media/admission/metering with fake SDK/MessagePack boundaries. CI regression
   gate now asserts1.5s p50/2.5s p95 after backend tests. Local synthetic target
   passed; hosted execution and full live-provider acceptance remain unaccepted.
5. **Part implemented.** Interruption and recognition disconnect wakeups/cleanup
   tested, including a real local Twilio socket with fake provider and STT cost.
   Silence check-in/idle-close tested; full suite752passed2skipped. Human
   transfer is implemented behind a disabled flag, approved destination/revision
   and later caller confirmation, with signed one-shot Twilio/Plivo adapters,
   parent/staff cost fences, unknown-outcome protection and a workspace kill switch.
   Full Docker788passed2skipped; PostgreSQL concurrency and browser checks passed.
   Real carrier acceptance remains gated by approved pricing/activation/destination.
   Confirmed manual callback requests now collect phone,
   require later readback confirmation, create an inbox ticket and owner outbox
   email, and support owner resolution. No automatic dial or promised time.
6. Paid phone activation only after workspace approval and all prior gates.

## Phase 7 — code health

Pending implementation after preceding phases to preserve the requested sequence: feature
modules for workspace/studio, frontend tests, dead/duplicate code and wildcard
removal, backend formatting, maintained consolidated handoff/progress docs and
correction of contradictory billing copy. The appended verification checkpoint
records current evidence without rewriting historic results as current.

## External actions and publication

- Review/save the environment draft's install script, startup instructions and
  documentation-domain additions in environment settings, then publish the
  prepared development environment. Saving the draft is not publication or a
  public application deployment.
- Restore a supported route to the supplied Supabase instance before validating
  remote development or applying reviewed production migrations. Existing
  credentials were found; do not request duplicate secrets or change `.env`.
- Recheck official documentation after network changes. Direct requests to
  Cloudflare and Fish documentation are now reachable; remaining provider
  contracts will be rechecked before integration work.
- Supply approved commercial plan/invoice details securely as appropriate.
- Complete remaining items and their acceptance checks before public launch.

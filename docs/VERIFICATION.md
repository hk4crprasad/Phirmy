# Verification record

## Sarvam voice, widget mic and Phirmy refresh — 29 October 2026

Full isolated backend: **799 passed, 35 skipped (335.43s)**. Targeted Sarvam /
voice / billing / tool suite: **90 passed (55.92s)**. Next build and typecheck pass.
Native VoiceConnection tests cover denial, missing/busy devices, duplicate start,
close during permission/worklet, and blocked embedding policy. Cross-origin
Chromium test verifies real synthetic microphone capture through dictation and
AudioWorklet PCM with synthetic API boundaries; zero page errors. Sarvam editor
desktop/mobile save preserves GPT text config. Live synthetic Sarvam tool round
trip returned speech at **1385.7ms after final transcript**; no actual booking or
carrier call. Details and reproduction: [SARVAM_VOICE.md](SARVAM_VOICE.md).

Phirmy MainPage production build/typecheck pass; **25 browser tests passed in
26.6s**, including responsive widths, WCAG axe, all four narrated walkthroughs,
contact validation/idempotency/failures, new product navigation and actual local
cookie/privacy pages with preference expiry/reset/blocked storage. Desktop/mobile
visuals inspected. No new SMTP message, Supabase mutation or provider purchase.
35 unavailable backend checks remain unverified; physical mic/echo and live phone
acceptance are separate deployment work. MainPage CI40818685104 succeeded in53s.
Public https://phirmy.com desktop/mobile Chromium checked the new homepage, menu,
cookie settings/persistence, direct policy route and contact form: zero page errors,
zero form submissions. Only MainPage/contactAPI deployed; voice backend not deployed.

## Phirmy contact page — 27 October 2026

Standalone MainPage contact route and all build CTAs now connect to the public
contact API, forwarding to user-confirmed support@phirmy.com through the encrypted
email outbox and existing SMTP config. Production build/typecheck passed; **18
Chromium browser tests passed in35.4s**, including contact form/success accessibility
at390/1440, required consent, retries with same idempotency key, failures and all
homepage controls. **72 targeted backend tests passed in49.85s with real sandbox
enabled**, no skips/failures: contact route/concurrency/rate limits, fake SSL and
STARTTLS SMTP headers/MIME, retry, account mail, identity, key rotation, callbacks,
GST invoice PDF/outbox attachments, and widget protection.

One actual browser enquiry (clearly labeled delivery verification) returned202
and was encrypted in isolated data/mainpage-contact/enquiries.db. No page errors.
**Real SMTP acceptance not achieved:** host lookup failed EAI_AGAIN. General public
DNS failed too, including an approved probe outside the sandbox. This is not
reported as missing/bad credentials or inbox delivery. The single enquiry remains
queued for bounded retry. No supplied Supabase, existing queues, main branch, or
private.env changed. This is not a new full backend audit acceptance run.


## Phase 6 — scheduling SQL checkpoint, 27 October 2026

Initial existing scheduling set57passed2skipped30.69s. New SQL/cancellation focused
set63passed2skipped42.79s. Final broader scheduling/custom-tool/red-team/callback/
voice regression **139passed2skipped64.17s**, zero failures, after consistent
workspace→booking final-result locking. SQL hooks cover both providers through
availability→prepare→confirm→reconcile. Cancellation before HTTP closes unused
submission; canceled result commit preserves one confirmed appointment and one
provider POST. Existing no-replay/consent/tenant tests remain green.
No live booking or new latency measurement. Latest FULL Docker suite remains
788passed2skipped at948e6f5; later SQL checkpoints have the targeted evidence above.


## Phase 6 — HTTP tool SQL checkpoint, 27 October 2026

Focused **57passed16.61s**; broader custom-tool/red-team/voice/callback/transfer/
website regression **131passed1skipped68.73s**, zero failures. SQL execution hooks
reject database operations on the audio event loop. New tests prove one request
under concurrent consumers, cancellation during a durable queue transaction,
unknown state/no replay after request cancellation, and successful result retention
when cancellation arrives during client close. Fake HTTP transports only.
Latest completed FULL Docker suite remains788passed2skipped at948e6f5; this
backend-only SQL change has targeted regression above, not a new full-suite claim.


## Phase 6 — live transfer implementation checkpoint, 27 October 2026

Final **FULL actual Docker content sandbox + Redis:788passed2skipped0failed in
490.38s (8m10.38s)**. Mandatory --run-sandbox --strict-markers used; the two skips
remain provider-inapplicable scheduling parameter cases. Earlier full run was
intentionally interrupted after250passed2skipped153.99s to fix the newly identified
post-transfer kill-switch gap; that partial run is not counted as full acceptance.

Focused transfer23passed22.05s; preceding expanded23passed16.98s and14passed8.98s.
Final transfer/kill/billing/phone regression **72passed48.80s**. Before kill changes,
broader60passed38.82s. Tests cover exact readback/revision, feature/pricing gates,
forged/foreign signatures, deadline/cap admission, frozen key rotation, unknown
submission/no replay, one-shot XML, callback conflicts, separate parent/staff costs
and workspace kill after AI detaches. No real carrier was called.

Actual disposable PostgreSQL:24 concurrent claims authorize1submission;24 concurrent
instruction fetches authorize1staff Dial. Parent reservations survive media close
and immutable11s child/20s parent cost rows remain separate. Container removed after
test. Script scripts/verify_transfer_postgres.py; log /tmp/phase6-transfer-postgres.log.

Actual Chromium: staff destination form/last4 masking/approval required/live flag
off; widget callback readback→confirmation→owner inbox resolution, zero page errors,
zero carrier calls. Artifact artifacts/human-transfers/browser.json. TypeScript,
Next production build and native shipped-browser voice checks passed. The safe
local API/worker/web were restarted with all real provider keys and transfer
activation disabled; /healthz,/readyz and frontend200. Supabase/private.env untouched.

Latest12-turn normal-path synthetic benchmark with transfer activation off:
**373.147ms p50/409.488ms p95**, target passed, one model client/12requests and
12Fish sockets all closed. artifacts/voice-latency/transfers-disabled.json.
This does not measure live transfer or internet provider latency.

Implementation is behind LIVE_TRANSFER_ENABLED=false and paid activation. Real
carrier acceptance requires approved prices/activation/destination; this is not a
claim of live transfer or production latency acceptance. Remaining voice tool SQL
and the original compliance/product/reliability/code-health phases are still active.

## Phase 6 — callback checkpoint, 27 October 2026

Initial focused45passed14.51s. Broader callback/red-team/voice/widget/business/
scheduling regression **146passed3skipped81.48s**. After tightening callback-word
routing, final targeted **54passed1skipped25.60s**, zero failures. Typecheck and
production build passed. Skips in these fast runs include sandbox/provider cases;
latest FULL actual Docker suite remains752passed2skipped at72842c1.

Actual widget HTTP flow collects phone→readback→later confirmation→one ticket and
owner resolution; retrying the message/confirmation does not duplicate anything.
Actual voice-session flow marks the readback before permitting the later turn.
Tests prove negative intent, invented phone/time, forged scope, feature revocation,
cancellation and unverified/non-marketing labeling. Outbox row persisted; no real
SMTP, phone call or automatic callback was made. No new latency claim.


## Phase 6 — core media lifecycle checkpoint, 27 October 2026

Final **FULL suite with actual Docker content sandbox and Redis:752passed,
2skipped,0failed in429.77s (7m09.77s)**. Command used --run-sandbox --strict-markers,
the owned real content socket and disposable Redis6399; no sandbox skip was used.
The two skips are provider-inapplicable scheduling parameter cases (Cal.com host
approval and Calendly follow-up event read). All test data/provider stubs remained
isolated; the supplied Supabase/private credentials were not used.

TypeScript and Next production build passed. Native shipped-browser voice tests
passed transcript patches/Unicode/sequence/epoch fences, incomplete follow-up,
fatal cleanup and microphone/audio closure. Focused lifecycle13passed6.37s;
earlier socket regression47passed25.87s. Real local browser/Plivo/Twilio sockets
were instrumented to reject SQL on their event loops. Cancellation after committed
admission, constructor failure and duplicate handshake tests verify ownership and
settlement. Silence sends one check-in then closes the idle call.

Same12-turn synthetic fixture measured **371.302ms p50/418.463ms p95**, target
passed, one model client/12requests/12Fish sockets all closed. Artifact:
artifacts/voice-latency/media-lifecycle.json. No live provider measurement.

This verifies core socket admission, context loading and teardown offload, not all
async HTTP or tool-specific scheduling/connector/HTTP-tool code. Those still need
the wider reliability pass. Phase6 remains open for transfer/callback and live
provider acceptance; synthetic timings do not establish production latency.


## Phase 6 — recognition disconnect checkpoint, 26 October 2026

Focused62passed27.87s, native disconnect set7passed2.79s, final broader regression
**180passed3skipped81.70s**, zero failures. Tests cover clean/exception/malformed
recognizer termination waking a blocked client receive, TTS/model cleanup, normal
shutdown cancellation, receive timeout/cancellation, and STT allowance before send.
An actual authenticated local Twilio WebSocket (fake provider boundary) receives
PCM, loses recognition, closes, persists failed state and records a nonzero STT
cost. This is not a real carrier call. No new latency number claimed.


## Phase 6 — greeting cache checkpoint, 26 October 2026

Focused checks: **44passed11.82s**. Broader voice/scheduling/widget/accounting
regression: **161passed3skipped65.65s**, zero failures. Tests cover tenant/version/
voice/exact announcement separation, TTL/LRU/entry and byte limits, invalid PCM,
personalized and failed-playback exclusion, and a real media replay with identical
PCM/transcripts plus no additional Fish socket or cost record. Recording disclosure
changes require new synthesis; repeated silence prompts are never cached.
No new latency measurement is claimed for cache hits. Latest synthetic normal-path
benchmark remains368.356ms p50/429.452ms p95; latest full Docker suite remains
700passed2skipped at6186189. Frontend unchanged from the verified transcript build.


## Phase 6 — Fish connection checkpoint, 26 October 2026

Focused connection/media/accounting checks:46passed17.73s. Final broader voice,
model, scheduling, widget, billing and release regression: **156passed3skipped
in62.07s**, zero failures. An earlier command named a nonexistent test file and
collected no tests; the corrected run above completed. Tests prove empty setup
overlapping retrieval, cancellation before/after connection, producer cleanup,
premature/error finish and invalid PCM rejection, disabled-preconnect behavior,
and fresh physical sockets after documented stop/finish (no replay).

Same12-turn synthetic fixture: **368.356ms p50/429.452ms p95**, target passed.
Artifact artifacts/voice-latency/fish-preconnect.json. One fake model client,
12model requests/12Fish sockets, all closed. No live provider latency claim.
Current official Fish protocol rechecked200; its stop/finish closes the socket.
DECISIONS records why independently completed turns retain that boundary.
Latest full Docker suite remains700passed2skipped at6186189.


## Phase 6 — interim prefetch checkpoint, 26 October 2026

Focused checks: **36 passed in16.55s**. Voice/retrieval/accounting regression:
**140 passed, 2 skipped in60.50s**, zero failures. Nine new tests cover debounce,
exact final matching, snapshot fences, two-request limits across resets, expired/
revoked knowledge, actual media reuse/timing, cancellation during admission,
unknown usage after a started embedding request, and reported usage settlement
when vector-cache writes are canceled. Tests use isolated data/fake providers.

Normal final-only synthetic path:12turns, **425.384ms p50/454.522ms p95**;
artifact artifacts/voice-latency/prefetch-normal-path.json. Target passed, but this
fixture does not measure interim-prefetch savings or live provider performance.
Latest full Docker suite remains700passed2skipped at6186189. No frontend change
in this checkpoint; preceding transcript typecheck/build passed.


## Phase 6 — transcript patch checkpoint, 25 October 2026

Final voice/transcript/scheduling/widget regression: **114passed3skipped77.54s**.
Earlier focused set:45passed15.27s. Tests include actual authenticated browser
WebSockets negotiating both legacy/full and delta-v1 greetings; Unicode append
and revised STT hypotheses; stable identities through segmented finals; actual
model/Fish pipeline emitting patches plus one final matching its timing record;
and100fragment serialized wire size below one-third of the legacy stream.
Native Node tests of the shipped TypeScript pass Unicode revisions, duplicate/
gap/epoch fences, handshake request and existing error/resource cleanup.
Typecheck and production build passed.

The actual local synthetic benchmark now enables delta-v1 and measured12turns:
**444.298ms p50/502.299ms p95**, target passed, one model client/12requests and
12Fish sockets, all closed. Artifact:artifacts/voice-latency/transcript-deltas.json.
No live-provider measurement or network bandwidth/latency extrapolation. The
latest complete Docker suite remains700passed2skipped at6186189; full phase
verification follows remaining voice work.

## Phase 6 — LLM keepalive checkpoint, 25 October 2026

Final voice/model/scheduling/metering regression: **123passed2skipped74.94s**.
Connection-specific checks including both real-TCP scenarios: **9passed6.20s**.
An earlier broader widget/phone/tariff regression passed193tests3skipped111.83s;
that run preceded the native TCP test and bounded terminal-drain fix. The native
test first failed with two connections for two turns; after draining the SSE
tail, the real installed SDK uses one localhost TCP connection. A missing tail
is bounded and discarded, causing a fresh connection without replay. Also
verified rotation/active-client limits, tenant guard, preserved SSRF transport,
disabled-pool cleanup, repeated cancellation, profile disablement on the next
turn and barge-in closure of the old stream while retaining a healthy client.

Same12-turn synthetic fixture: **430.061ms p50/480.276ms p95**, target passed;
one fake model client for12model requests,12Fish sockets, all resources closed.
Artifact:artifacts/voice-latency/llm-keepalive-final.json. No live network latency
or persistent Fish socket claim. The latest full Docker result remains the
preceding OpenAI checkpoint's700passed2skipped; full phase acceptance will run
after the remaining voice work. Primary safe isolated API/worker/web were
restarted at6186189; health/ready/frontend returned200 with local Redis/content
sandbox, Qdrant explicitly disabled in development. No remote database touched.

## Phase 6 — OpenAI contract checkpoint, 25 October 2026

Focused request/cache/tool/incomplete/cancellation/economics/streaming checks:
**47passed15.46s**. Native Node exercise of the shipped TypeScript connection
passed incomplete-answer follow-up, fatal-error cleanup, one microphone stop and
one audio-context close. Browser boundaries are deterministic fakes in that
check; it is not a live microphone/provider test. Typecheck and production build
passed. Disposable PostgreSQL admission and immutable-ledger acceptance passed:
24requests10accepted14denied; shared Free3workspaces24requests9accepted15denied
plus one consumed turn. Sponsor backfill/reset rejection and schema checks pass.

The same12-turn synthetic fixture measured **426.834ms p50/693.015ms p95** with
the explicit voice/cache/completion contract; `--assert-target` passed. This is
actual local media/admission/metering with fake SDK/socket boundaries, not live
Fish/OpenAI latency, a cache-hit measurement or an effort/quality comparison.
Artifact:artifacts/voice-latency/openai-contract.json. Other tests were running
locally at the same time; these numbers are measurements, not a capacity claim.

An initial broad run had668passed2failed26skipped375.54s. The two economics
failures came from editing its configuration while pytest had already loaded
the old schema. The final full suite on the stable backend tree, with actual
Docker integrations and Redis, passed **700tests,2skipped,0failed in502.03s**.
`--run-sandbox` used the isolated content service; no supplied remote database
or live provider was used. A fresh owned pytest temporary root avoided the old
root-owned garbage cleanup warnings. Final backend log:
`/tmp/phase6-openai-full-docker.log`.

## Phase 6 — incremental speech checkpoint, 25 October 2026

Same12-turn synthetic fixture as the baseline: **423.657ms p50/468.694ms p95**,
both targets passed with `--assert-target`. A preceding run measured414.344ms/
473.207ms; the final run also includes producer-failure monitoring and DB offload.
No live-provider latency was measured. Existing privacy filtering and actual
admission/metering/framing remained enabled. All fake provider streams closed.
Artifacts:artifacts/voice-latency/incremental-final.json and baseline.json.

Final focused regression: **147passed2skipped59.70s**, four pre-existing cleanup
warnings. New checks prove a short unpunctuated fragment reaches Fish while the
model still streams; sentence/turn/tool flush controls; failed-producer wakeup;
playback failure closes providers;200single-byte deltas use two128-byte grants;
only200actual bytes settle; cancellation observes its pending grant transaction;
clear precedes slow cleanup without losing a newer task pointer; and retrieval/
profile DB work runs off the audio loop. The simple PCM metering fake was updated
to ignore flush controls, preserving its original100ms audio assertion.

Backend CI now runs the synthetic target assertion after the full real sandbox
suite. Hosted result is unconfirmed; broad/full phase acceptance follows the
remaining reuse, OpenAI, caching, prefetch and product-flow work. See
[voice measurement contract](VOICE_LATENCY.md).

## Phase 6 — instrumentation and measured baseline, 25 October 2026

Actual synthetic benchmark,12sequential turns through the media, admission,
metering and MessagePack transport code: **2331.229ms p50 /2391.771ms p95** from
server receipt of final transcript to first audio transport write. The1.5s p50
target is missed; p95 is under2.5s in this fixture. These are measured synthetic
results, **not live Fish/OpenAI latency or browser speaker-playback latency**.
Configured fake delays:40ms retrieval,180ms first model token,50ms subsequent
tokens,40ms Fish connect and120ms first synthesized audio;38word chunks plus a
final sentence ending. Actual local DB, budget holds, text guard and framing
overhead remain in the measurement. All fake model/socket resources closed.

Reproduce:
`uv run python scripts/benchmark_voice_latency.py --iterations 12 --output artifacts/voice-latency/baseline.json`.
The script isolates SQLite/objects and provider settings; no Docker or external
provider requests. `--assert-target` explicitly fails a miss. Baseline runs do
not pass that option; the mandatory CI gate will follow the streaming fix.

Instrumentation tests:8passed3.93s. Existing media/model/scheduling/metering/
release/deletion regression:113passed2skipped59.43s, with four pre-existing pytest
cleanup warnings. Tests cover monotonic durations, missing audio versus zero,
tenant scoping, idempotent persistence, cancellation/provider cleanup, provider
failure, source-separated summaries, greeting exclusion and telemetry outage.
Typecheck and production build passed. Full phase suite follows remaining voice
changes; no claim that Phase6 is complete.

## Revised checkpoint step 4 — 25 October 2026

Final Docker-free full regression: **623 passed, 26 skipped, 0 failed in359.55s**,
real Redis configured, zero Docker shim invocations. The environment disconnected
while this run was active; the completed log was recovered after reconnection.
Four warnings concern the same pre-existing root-owned pytest garbage directory.
The earlier full run had622passed1failed26skipped316.86s: the page-download
concurrency test relied on a30ms overlap window. Replacing it with a real overlap
rendezvous preserved the requirement; both crawler concurrency checks passed
2tests2.63s before the final full rerun. Focused billing/Free/economics/operator
checks:48passed28.64s. Earlier billing/platform regression:52passed1skipped26.03s.
Typecheck and production build passed.

Disposable PostgreSQL acceptance ran the actual cross-process transaction path:
24 spend requests admitted10/rejected14 at the workspace cap. Across three
workspaces of one sponsor, a ten-turn shared pool with one prior consumed turn
admitted9/rejected15 of24 concurrent requests. Sponsor backfill, schema drift
detection, immutable sponsor reset rejection and immutable accounting passed.
No supplied database was used. Reproduce:scripts/verify_billing_postgres.py.

Actual Chromium on the production build and isolated API/fake gateway passed
shared Free aggregate display, DRAFT economics/loss flags, model selection,
operator pause/resume/access removal, receipt-verified checkout and real isolated
invoice PDF download; zero page errors. The QA selector was corrected to use the
combobox's accessible name rather than implicit-label text containing options.
Artifacts:artifacts/billing/unit-economics-browser.png and
artifacts/unit-economics/draft-report.json. Arithmetic scenarios are not measured
traffic, final prices, actual profit or provider pricing acceptance.

## Revised checkpoint step 3 — 25 October 2026

Docker-free full regression with real Redis: **611 passed, 26 skipped, 0 failed
in306.62s**, zero Docker shim invocations; four pre-existing cleanup warnings.
Focused cache/origin/deletion/header checks:38passed23.73s. Final cache set,
including recovery:8passed6.49s (overlaps the focused run). Typecheck and final
production build passed.

`scripts/verify_widget_cache_browser.py` ran real isolated API/SQLite/objects,
shared Redis, built Next on ephemeral ports and actual Chromium. All four public
assets returned short public caching plus ETags and conditional304. HTML stayed
no-store; a warm widget page made zero policy API calls and used a fresh CSP
nonce. Revocation invalidated the next page, and a guarded cache plus simulated
policy API failure returned self-only framing. Legal page hydration emitted zero
page errors. Artifact:artifacts/widget-cache/results.json. A first QA-script run
needed the standard CSRF header, and its outage assertion was corrected to parse
the CSP directive without requiring an optional trailing semicolon; final pass
uses the same actual product behavior.

Backend tests cover cached reads without SQL, origin revoke, proof expiry, nested
savepoint and outer rollback/commit, bulk agent archive, fencing a delayed old
loader, fail-closed invalidation outage, and scoped dry-run crash recovery.
Neither the cache nor test selection replaces live API origin/key authorization.
GitHub Actions status lookup via `gh` returned403, so no hosted CI result is
claimed. The step2 workflow was pushed to its triggering audit branch.

## Revised checkpoint step 2 — 25 October 2026

- Docker-free full suite: **603 passed, 26 skipped, 0 failed in403.19s**. PATH
  contained a Docker shim that exits97 and records calls; DOCKER_HOST pointed
  at a nonexistent socket. Recorded Docker invocations: **zero**. The24 sandbox
  cases and two alternate scheduling branches were explicitly skipped.
- First full real-sandbox run:626passed1failed2skipped550.80s. The renderer
  concurrency test observed peak1 instead of2 because its30ms overlap assumption
  was not deterministic under concurrent test load. It now waits for actual
  overlap; the targeted renderer/selection run passed4tests9.52s.
- Final full real-sandbox run: **627 passed, 2 skipped, 0 failed in445.27s**,
  real Redis enabled. Actual parser, renderer, dictation, document upload and GST
  PDF checks ran. Both full runs emitted four warnings from pre-existing,
  root-owned pytest garbage directories; current sandbox shutdown restores its
  mount ownership. No safety prerequisite failure was converted into a skip.

The three new subprocess selection tests prove default-local skip, missing-flag
CI rejection, and explicit sandbox failure when Docker is unavailable. CI's new
workflow is configured to run the complete suite; a hosted GitHub run is not
claimed here. Logs were retained locally under `/tmp/revised-step2-*.log`.





## Revised checkpoint step 1 — 25 October 2026

**623 passed, 2 skipped, 0 failed in433.23s** with Docker available and the real
isolated content service. Real Redis test endpoint was enabled. Focused model/
scheduling/widget/platform run:121passed2skipped93.68s. This includes all six
reported booking cases and successful actual WAV decoding/dictation and document
upload/promotion. The two skips are alternate scheduling-provider branches.
Four warnings refer to cleanup of an old root-owned pytest temporary directory;
no sandbox, dictation or document check was skipped due to missing Docker.

New profile-contract tests exercise production/test modes and five invalid model
forms, prove no provider client starts, and preserve an explicit fake model in
billing. This full run covers committed legal work plus the model fix. Paused,
uncommitted data-rights work is held separately and is not a completion claim.
No live provider request, payment, production migration or latency result is
implied by these tests.

## Phase 3 item 1 — 25 October 2026

32 focused legal/account/identity/operator tests passed13.16s. Typecheck and
production build passed. Actual Chromium visited all five legal pages with
strict CSP and correct titles, received404 for an unknown document, proved an
unchecked signup sends no request, then checked acceptance and observed its
versioned server record after actual local signup. Zero page errors. This used
the isolated local development API; SMTP/provider keys remained disabled.

Disposable PostgreSQL verified signup records plus update rejection for legal
policy and acceptance tables; existing inbox takeover, duplicate-capture,
invoice sequence and operator aggregate checks also passed. New Google account
claims were faked in tests. No live Google or legal approval claim is made.
Full Phase3 backend run is pending completion of remaining Phase3 items;
Phase2's605passed2skipped remains the latest completed full-phase run.

## Phase 2 complete / item 5 — 25 October 2026

**605 passed, 2 skipped in428.41s** with real Redis on the disposable local
instance. The two skips are irrelevant alternate scheduling-provider branches;
no credential-dependent implementation test was skipped. Four warnings concern
cleanup of an old root-owned pytest sandbox directory, not failures or a weakened
sandbox. Frontend typecheck and production build passed. Focused operator/
scheduling/red-team compatibility:89passed2skipped56.12s. Final tariff currency,
website, widget and operator checks:21passed14.61s (overlapping coverage).

The first full run exposed eight legacy fake model profiles missing the model
identity required by metering, plus a test origin inherited from the local setup
helper. Fakes now declare their model; pytest pins its own application/API
origins. The successful full run above includes those fixes and a regression
ensuring non-INR wallets cannot enter newly priced INR calls. Operator tests also
caught and closed the general job-cancel API-key path for financial jobs.

Native Chromium passed actual production Next UI and isolated API checkout,
subscription capture, sandbox PDF download, paid-flag changes, operator pause/
resume and operator access removal with zero page errors. Synthetic gateway,
not real merchant credentials. Actual local invoice/EML evidence is covered by
backend tests. Disposable PostgreSQL passed aggregate arithmetic/missing-fee
handling, receipt lease takeover rollback, duplicate captures and12 concurrent
unique invoice numbers. Billing contribution remains DRAFT estimates.

The safe local API/worker restarted with additive migrations against local
SQLite/objects; minimal health and dependency readiness passed. Redis/Qdrant
are explicitly disabled for the development preview, not falsely reported as
connected. The onboarding install draft now checks Poppler and clears payment/
operator credentials and flags for isolated development. No private .env,
supplied database, live provider or main branch was changed. No load capacity,
production migration, real payment or voice latency claim follows from this run.

## Phase 2 item 4 — 25 October 2026

Focused payment/subscription/metering/invoice suite: **52 passed in27.82s**.
Final payment/subscription currency regression: **34 passed**.
Final cancellation-recovery and separate DRAFT/live invoice-series suite:
**21 passed in30.75s**. Prior integrated reconciliation/business/sandbox suite:
**71 passed in32.74s**. These overlap; they are not a combined suite count.
Four cleanup warnings concern an old root-owned pytest sandbox directory;
current repeated sandbox start/stop acceptance passed. Full phase suite follows
item5. Frontend typecheck and production build passed.

Native Chromium, actual production Next UI, real isolated FastAPI routes/worker
and fake gateway passed top-up (11800 gross/10000 credit), signed subscription
capture, actual sandbox invoice PDF download, stale open-review disable when
paid activation changes, and zero page errors. PDF/EML tests read Devanagari
text with Poppler. No actual SMTP or Razorpay request was made.

Disposable PostgreSQL proved a replaced worker cannot commit financial writes,
four competing receipts yield one wallet credit/invoice, and twelve concurrent
workspaces receive unique consecutive invoice numbers. Synthetic commercial
approval was temporary test configuration. Checked-in prices/business stay
DRAFT and paid activation false. No supplied database/private configuration was
changed; these checks provide no live payment or voice latency measurement.

## Phase 2 item 3 — 25 October 2026

105 related accounting/admission/phone/runtime/business tests passed58.81s.
Final10 tariff tests passed6.71s: included minutes, wallet activation guard,
immutable settlement after edits, affordable duration, synthetic credit, pinned
model pricing, unknown-production-model refusal, read-only quote and backward
legacy rates. Disposable PostgreSQL passed additive model-column migration and
concurrent admission/immutability acceptance. External providers were fakes;
there was no real customer debit or voice latency measurement.


## Phase 2 item 2 — 25 October 2026

97 related regressions and58 admission/phone/business cases passed. Final
carrier/admission run38passed29.52s; corrected dispatcher responsiveness and
admission run16passed9.73s; storage/account run23passed10.59s; final widget/
admission27passed12.64s. A broader86-case run had one timing-test failure from
including dispatcher startup; the test now measures from the injected blocking
query entry, preserving its0.5s bound. Disposable PostgreSQL admitted10 and
rejected14 of24 competing reservations and enforced immutable history.
Provider I/O used fakes; no live calls, payments or private object writes.


## Phase 2 item 1 — 25 October 2026

Configuration/immutable usage/provider cost implementation passed35 final focused
cases in13.17s, after91 related platform/website/provider/deletion and54 beta/
number/widget regressions. Tests run against isolated SQLite/local storage and
the actual sandbox service, using fake external providers. Typecheck and Next
production build passed. No real payment or speech/model charge was performed.
No latency claim follows from these accounting checks.


## Phase 1 completed implementation — 25 October 2026

Full isolated suite with actual disposable Redis: **513 passed,2 skipped in276.46s**.
The two skips are provider-specific scheduling cases that do not apply to the
other parametrized provider; no credential-required Redis check was skipped.
The final14 key tests passed in16.33s, including actual CLI and dedicated worker
cases added after the full run's collection. Typecheck and production build
passed. Disposable PostgreSQL key acceptance passed: backwards reads, versioned
rewrite, parallel checkpoints, restricted no-CREATE runtime role, immutable
metadata/audit and current-lease-only ciphertext updates. Worker PostgreSQL
upgrade/idempotence/key-preservation/concurrency/expired-owner fencing also passed.

Versioned keys retain all legacy reads and authenticated timestamps. No supplied
database was migrated or re-encrypted, no private configuration changed and no
Azure key was provisioned/accessed. Live provider acceptance still needs the
specific settings in LAUNCH_CHECKLIST; implementation uses flags/fakes rather
than deferring buildable work. Phase2 paid activation remains disabled.

## Phase 1 item 3 — 25 October 2026

128 integration tests passed in94.39s; final46 focused passed in46.79s. Coverage:
Turnstile protocol and fail-closed checks, trusted IP, fake single-use/revocation,
independent installation/IP/workspace quotas, concurrent spending admission,
idempotent retry, outbox alerts surviving denial, email OTP scope/attempt/expiry/
replay and verified-only consent, and actual isolated audio decoding/duration.
Production frontend typecheck/build passed. Actual Chromium
`scripts/verify_widget_protection_browser.py` passed: shared fake Turnstile client
and provider only in its separate QA process, real API/outbox/OTP/consent, optional
email, owner protection UI and cap denial/alert; zero page errors. Evidence:
`artifacts/widget-protection/browser.json`. Current local readiness200.

This is fake-provider acceptance, not live Cloudflare/SMTP acceptance. Exact
missing settings are recorded in DECISIONS.md; implementation is complete and
no real provider charge, message or remote database change occurred.

## Phase 1 item 9 — 25 October 2026

Real content-isolation suite:14passed in36.59s. Existing renderer lifecycle,
platform ingestion, website assistants and HTTP hardening:59passed in68.29s.
Actual container probes confirm nonzero distinct childUIDs, no capabilities,
no-new-privileges, no application files/credentials/network/broker socket access,
and enforced cgroup memory/CPU/PID limits. Real PDF/DOCX/ZIP attack fixtures and
Chromium infinite-script cancellation/recovery pass. Lightweight health remains
responsive during a running browser job. Missing service fails readiness.

Actual HTTP upload → dedicated worker → isolated parser → published snapshot
passed with a fresh synthetic local account. Local readyz200 includes the content
service. Frontend typecheck and production build passed. No remote database or
private configuration changed. Reusable install/start instructions were saved
to the environment draft; settings Save/Publish remains a separate user action.


## Public launch security checkpoint — 24 October 2026

Phase 1 is **partial**, not launch acceptance. [Full item-by-item status and
reasons for remaining deferrals](LAUNCH_CHECKLIST.md),
[behavior and reproduction](SECURITY_CHECKPOINT.md), and
[dated official references](DECISIONS.md).

Current-instance checks: frozen `uv sync --frozen` and `npm ci` succeeded and were
repeated successfully. Node 24.19.0, Python 3.12.14, uv 0.12.23, system Chromium.
Frontend `npm run typecheck` and `npm run build` passed. Actual production
Chromium created a key with expiry and a 25/minute policy and verified expiry,
limit and last-use columns with zero page errors. Both production frontend and
development frontend home/API proxy requests passed. API session/CSRF, queued
TXT upload, dedicated worker completion and retrieval of its actual content
passed using isolated persistent SQLite/local objects. No paid provider or
private Supabase mutation was involved.

Final full backend suite: **421 passed, 2 skipped in 142.09s**. The two skips are
intentional provider-specific scheduling cases. The focused security suite also
passed **25 tests**, including an actual disposable Redis server
with shared concurrent windows, expiry, bounded outage fallback, reconnect,
opaque identities/log redaction, real trusted-proxy IP rotation/email lockout,
spoofed forwarding, scope escalation, key policy and SQLite migration preservation.
STUDIO_TEST_REDIS_URL was set for these checks; that test was not skipped.

Disposable PostgreSQL 17 passed old worker-schema upgrade, old key-policy column
upgrade with hashes preserved, repeated migrations, missing-column rejection,
last-use writes under a runtime role without CREATE, eight unique concurrent
claims, one KB owner, expired recovery and stale-owner fencing. Evidence
`artifacts/workers/postgres.json`; the script removes only its own container.
Base/beta Compose configuration validated with synthetic interpolation values;
the changed gateway topology was not deployed or live-tested.

The supplied PostgreSQL read-only check failed with **network/address route
unavailable**; remote schema/provider acceptance remains unverified. Official
Cloudflare/Fish/OpenAI/Deepgram documentation requests returned HTTP 403. No
provider streaming integration was changed. No 100-chat/20-voice load test or
voice-latency measurement was run, and no p50/p95 or paid-launch claim is made.

Saved environment draft: complete install script, complete API/worker/web startup
instructions and specific documentation-domain additions. The install script
reproduces frozen dependencies and preserves a modified local helper rather than
overwriting it. This is **saved draft/current-machine validation**, not a
publication, public deployment, or validation in a newly restored task. Private
`.env`, dependency declarations and lockfiles remain unchanged.

## Worker pool and concurrent ingestion — 24 October 2026

[Setup, migration, tuning and reproduction](WORKERS.md). Full isolated backend396passed2intentional skips (104.22s). New coverage verifies independent job/webhook progress, lease heartbeat/recovery/fencing, shared-resource fairness, pages saving behind a blocked first request, global renderer/index ceilings and canceled/failed batches. Stop and prior knowledge preservation remain covered. Actual Python3.13/Chromium API image builds; a disposable API with dispatch disabled and separate worker completes a queued document, publishes knowledge, passes liveness/SIGTERM and removes test data. Base/beta Compose configuration validates. Disposable PostgreSQL17 verifies old-table upgrade, missing-column rejection, repeated migration, no-CREATE runtime role, eight simultaneous distinct claims, one owner per KB, expired recovery and stale-owner rejection.

Controlled original93ae9d4→current benchmark: five pages5.051s→2.978s; eight queued250ms jobs9.067s→0.822s. Identical5pages20chunks, unchanged recrawl0additional uploads, real250ms start gate. Synthetic boundary latency; public-site speedup is not guaranteed. Evidence artifacts/workers/{before,after,postgres,docker}.json; scripts/benchmark_workers.py, verify_workers_postgres.py, verify_workers_docker.py. Schema2026-10-24-worker-pool adds jobs.lease_token (still64tables/147paths), production migration required. Tracked.env/frontend/Supabase unchanged; no paid provider/customer crawl or remote deployment. Cloud local provider-enabled API and separate worker are running.

## Renderer closed-target lifecycle — 24 October 2026

24focused tests pass: `tests/test_renderer_lifecycle.py` and `tests/test_website_assistants.py`. Real Chromium verifies pending/queued fetch cleanup after successful HTML capture, timeout, caller cancellation and external page closure, while genuine snapshot errors remain visible. Browsers disconnect, pending fetches finish cancellation before return, and event-listener stderr/asyncio errors stay absent. Existing same-origin JS/blocked external and POST/crawl Stop/static-fallback/knowledge checks pass. A controlled run against pre-fix rendered_html fails the new regression (fetch remains active after return); before evidence is `artifacts/renderer-lifecycle/before-result.json`. No customer site/provider call, env/schema/UI change or remote migration. [Renderer implementation notes](CRAWLING_PERFORMANCE.md).


## Agent deletion — 24 October 2026

[Scope, migration and reproduction](AGENT_DELETION.md). Full isolated backend378passed2intentional skips; production build/typecheck passed. Deletion cases cover confirmed full graph, shared KB/content-addressed storage, vector workspace/snapshot filter, Redis cache keys, billing/minimal call scrubbing, provider failure/retry, blocked active work, tenant/role guards, normal published-version immutability and blocked attachment/recrawl of deleting knowledge. Disposable PostgreSQL17 passes repeated migration, no-CREATE runtime role, normal-delete protection and authorized purge. Browser acceptance passes list/editor confirmation/cancel, mobile, shared-data preservation, worker completion/Operations and archive alternative with zero page errors. Evidence artifacts/agent-deletion/. No customer agent, Supabase or actual cloud object was deleted in QA; vector/cache boundaries are synthetic, local object storage is real. New schema revision2026-10-24-agent-deletion,64tables, OpenAPI147paths; production migration required. Private.env unchanged.


## Same-origin polling and portable embeds — 24 October 2026

Reproduced same-origin browser GET /v1/public/conversation403 (missing Origin), while POST polling returns200 and delivers operator replies. Both widget clients now use POST and stop polling on terminal session rejection. Keyed widgets accept unlisted HTTP/HTTPS and opaque null origins by default, with optional strict origin restriction in the dashboard. Tokens remain bound to their starting origin; bad keys and cross-origin replay still fail.76focused live-widget/branding/website/platform tests and57scheduling tests passed, with2intentional provider skips. Production build/typecheck passed; OpenAPI retains145paths, no env/schema changes.

Actual browser regression through Next rewrite covers React tester, same-origin installer, independent HTTP HTML and opaque-origin sandbox HTML, including operator replies and no repeat requests after disable; zero page errors. Managed Chromium blocks direct file:// with ERR_BLOCKED_BY_ADMINISTRATOR, so direct disk-file navigation is not claimed tested. API and real sandbox tests cover its Origin:null behavior without weakening browser policy. Evidence artifacts/widget-polling/results.json/screenshots and scripts/verify_widget_polling_browser.py. [Feature details](WIDGET_LIVE_INBOX.md).


## Apple-design audit — 24 October 2026

[Findings and reproduction](APPLE_DESIGN_AUDIT.md). Installed requested skill and lock. Production build/typecheck passes. Dashboard before/after96layout checks each pass24routes across desktop/mobile/light/dark, no overflow/errors; dialog focus/scroll, rail persistence, landscape, reduced motion and notification recovery also pass. Focused browser checks cover actual selected conversation styling, preserved reading/document position, keyboard rings, reversed notification order, mobile touch targets, high-contrast toolbar, reduced-motion modal and glass contrast fallback. Actual isolated local API data; only notification-order responses are held deliberately. No paid providers or external customer actions. Screenshot evidence: artifacts/apple-design/; private.env/schema/browser trust unchanged.


## Widget email, microphone and live handover — 24 October 2026

[Feature/API guide and reproduction](WIDGET_LIVE_INBOX.md). Full isolated suite361passed2intentional skips; final109focused live-widget/branding/platform/scheduling tests passed2intentional skips after ownership, notification and stream-retry refinements. Production build/typecheck passed. Actual configured Deepgram browser MediaRecorder transcription (synthetic microphone file), actual Qdrant/LLM₹699answer, email-first/unchecked marketing/lead evidence, live inbox takeover/operator reply/incoming visitor messages, reload/mobile, return to AI, resolve and bell notifications all passed with zero page errors. Screenshots were inspected; email composer visibility, mobile resize scrolling and microphone icon corrected. Evidence: artifacts/widget-live/ and scripts/verify_widget_live_browser.py.

Existing isolated website/widget/navigation/history/current-page/mobile/crawl Stop browser regression passed with zero page errors. Actual Aurely separate-origin chat/source URL dispatch/six citations/resume/mobile/key-origin rejection passed; remote page/thumbnails still hit documented browser certificate trust limitation. Both scheduling adapters passed actual OAuth/meeting-selection/publication/WebSocket read-back/confirmation/history UI against synthetic providers, zero page errors/no external booking. Aurely has no connected calendar, so real booking remains untested until connection. No email/phone/payment/customer action occurred. Private.env/browser trust unchanged; actual OpenAPI145paths,64tables/revision unchanged.


## Ten widget material designs — 24 October 2026

Production build/typecheck passed. Final focused branding suite: **21 passed in5.14s**. All ten material designs passed real production-dashboard save/public embed configuration, preview/embed style markers, retained embed key/name/tone, distinct computed material properties, actual LLM/Qdrant-grounded₹699answers, desktop/mobile/dark bounds and anonymous visitor checks; zero page errors. The separate-origin demo is left on Minimalism. Existing isolated website/widget/navigation/history/crawl Stop regression also passed, zero page errors; its provider boundaries remain synthetic. No new API path/schema change. Private.env and browser trust unchanged.

Styles: Minimalism, Glassmorphism, Claymorphism, Skeuomorphism, Neobrutalism, Bento grid, Neumorphism, Aurora, Editorial, Monochrome. [Controls, implementation and reproduction](WIDGET_CUSTOMIZATION.md). Script: scripts/verify_widget_designs_browser.py through explicit provider-dev.sh; it requires the retained local QA SQLite database and ten real chat requests. Actual screenshots/results: artifacts/widget-designs/index.html, all-designs.png, results.json and each {preset}-{dashboard,desktop,widget,mobile}.png. Screenshots were visually inspected; no screenshot generation or trust exceptions were used. Remote source thumbnails still face the documented browser certificate limit and disappear gracefully; storefront images and the uploaded widget logo are served locally/from the app.


## Complete widget controls — 24 October 2026

[Widget customization](WIDGET_CUSTOMIZATION.md) documents the live editor and API. Full isolated suite346passed2intentional skips; final11focused branding/logo tests passed after transactional-save refinement. Dashboard edit/save/reopen/cancel/upload/preview and mobile checks passed against actual local API/storage, then the anonymous separate-origin demo reflected saved branding and returned the actual grounded₹699answer; zero page errors. Existing website/widget/Stop regression passed. Uploaded logos, theme validation, tenant/object/key protection and per-widget tone config are covered. Production build/typecheck passed. Actual OpenAPI142paths, no schema migration. Screenshots/results: artifacts/widget-customizer/. Private.env and declined browser trust settings unchanged.


## Aurely widget in standalone HTML — 24 October 2026

Created a dedicated Aurely installation bound to the separate3200demo origin and embedded real app widget.js on a static storefront. Actual fresh visitor-browser checks passed: real₹699/imitation answer with6citations, reload resume without duplicate session, close/reopen, mobile light/dark without horizontal overflow, no dashboard/demo cookies, bad origin403 and bad key403, zero page errors. Product card dispatched the correct source URL to a new tab. Cloud Chromium rejects the remote proxy certificate, so destination rendering and remote thumbnails remain an environment limitation; failed thumbnails now disappear gracefully. Automatic review rejected a persistent shared-CA trust change and the user declined it; verification was not disabled and trust settings were not modified.

Reproduction/examples: examples/aurely-widget-demo/README.md, scripts/setup_aurely_widget_demo.py (repeatability verified) and scripts/verify_aurely_widget_demo.py. Screenshots/public results: artifacts/aurely-widget-demo/. No new crawl or backend schema/API change; source-site installation unchanged; private.env preserved.


## Real Aurely site, native app crawler — 24 October 2026

Actual UI URL→crawl→Azure→embeddings→Qdrant→published agent→grounded answer passed for https://aurelyjewellers.in/:48indexed pages,83passages,18products, about190seconds;36pages used guarded Chromium. All46sitemap URLs are represented after canonical normalization. Four private/auth pages were excluded by robots. Qdrant hybrid query passed; connected LLM returned₹699 and imitation jewellery for the specified bangle, matching source evidence. Zero browser page errors. Screenshots and results: artifacts/aurely-app/. [Report and reproduction](AURELY_CRAWL_TEST.md).

Explicit proxy mode fixes managed-cloud local DNS failure without weakening TLS/private-address checks: verified HTTPS public DNS, validated-IP CONNECT, original origin/Host/SNI and inherited proxy. Separate-origin, policy-denial and private/multicast rejection regressions pass. Direct mode remains the default outside the configured cloud.env. No Firecrawl data was used in this app crawl. Earlier native-crawl blockers below are historical; Supabase DNS/TCP is separate and remains unverified.


## Crawl Stop, loading, Redis and live integrations — 24 October 2026

See [crawl/storage/cache evidence and limits](CRAWLING_PERFORMANCE.md). Full isolated backend325passed2intentional skips; production build/typecheck and actual website/widget/mobile Stop browser acceptance passed with zero page errors. Additional targeted transport/render/retry cases cover redirect gating, SSR browser avoidance and429 retry. PostgreSQL17+TLS64-table integration passed; batched five-assistant list10queries including auth. Controlled synthetic latency benchmark1.77× faster with concurrency4 vs1.

Actual configured Azure storage, text-embedding-3-small1536 embeddings, Qdrant semantic/tenant/revision isolation and cleanup, Azure gpt-6-luna streaming/tool round trip, Fish drama-3 and Deepgram nova-3 all passed after network changes. A synthetic site used actual Azure/Qdrant/LLM services through the whole knowledge/widget path and reused its revision on recrawl. Actual synthetic-input spoken LLM answer plus Azure stereo recording/download passed; physical microphone/phone not exercised. Redis warm vector cache/TTL and failure fallback verified. Existing Azure history was inspected read-only, not removed.

Supabase/native external DNS still unavailable. Firecrawl CLI is installed/authenticated but its API receives proxy403; all-domain access is authorized/saved in the draft and not claimed applied/published. Live Aurely submission422beforecrawl, zero pages. Current provider-enabled API uses explicit localSQLite data/cloud-providers, preserving supplied remote/private.env settings. No remote migration, public deployment, phone purchase/call or payment occurred.


## Progressive loading — 24 October 2026

Production build/typechecking and the full isolated backend suite passed (**315 passed,2 intentionally skipped in78.08s**). New selective-bootstrap tests cover every page's exact resources, scope denials/redaction, exclusion of unrelated queries and UTC activity/count accuracy. Legacy full bootstrap still passes existing tests. Isolated PostgreSQL17 verifies the SQL summary and existing restricted runtime/migration/concurrency checks; remote Supabase was untouched.

Focused browser acceptance uses actual API data with deliberately held responses: navigation before page resources, real summary before activity, loaded-page reuse, one identity request and zero full bootstraps for Overview→Agents→Overview, no duplicate page requests,503 retry,15-second timeout recovery, profile independent of summary and stale-response/workspace isolation all pass with zero browser errors. Local encoded JavaScript sample fell from196907 to161298bytes (~18%). The shell appeared in846ms in the latest local run under concurrent QA load. Held-response timing proves ordering and is not public-host latency acceptance. Evidence: `artifacts/dashboard/loading-before.json`, `loading-results.json`, `summary-before-activity.png`.

Beta regression passed core account/agent/variable/contact/profile/session/mobile flows. OAuth consent/callback/meeting selection and real WebSocket booking simulation passed both provider adapters; website onboarding/crawl/widget/navigation/history checks passed. Those provider/model boundaries remain synthetic, with no paid calls, real meeting or external email. Missing-page display passed after correcting the shared-layout boundary, but the later theme run stopped at the synthetic signup quota (429). A repeated dashboard audit was stopped at the user's request to reduce testing; no final full theme/96-route acceptance is asserted for this update. Prior full visual verification remains below. No private configuration/schema/production deployment changed.

## Dashboard readability and UI fixes — 24 October 2026

Production frontend build/typechecking passed. Final `verify_dashboard_browser.py` ran against the production frontend and isolated development API:24 pages × desktop/mobile × light/dark =96 layout checks, no page overflow or browser errors. Larger nav/body text, collapsed rail persistence, short landscape navigation, small-screen dialog scrolling/close/focus, reduced motion and notification loading/failure/retry passed. External failure was deliberately injected only for the notification-recovery test; ordinary application data came from the actual isolated API. Screenshots were visually reviewed. Evidence: `artifacts/dashboard/results.json`.

Full beta regression also passed signup, agent creation/publication, variables, notifications/read state, sidebar persistence, contacts/campaign drafts, profile/devices, JWT/concurrent-tab refresh and mobile drawer focus/overflow with zero page errors. Earlier in this pass, the theme verifier passed local fonts, theme persistence, loading/404, Remotion controls and reduced motion. An intermediate beta run caught the new sidebar width overriding the collapsed rail; the explicit collapsed widths were corrected before the final passing production runs.

Changes are frontend-only: shared readable type/spacing, larger controls, responsive card/action layouts, sticky topbar, bounded dialogs/notifications, semantic mobile-close contrast, fresh notification state on workspace change, truthful notification pending/error states and replacement-safe toast timers. No backend/schema/provider changes, paid actions or deployment. Private `.env` is unchanged. Existing unrelated `.agents/` and `skills-lock.json` remain excluded.

## Scheduling OAuth and public preview correction — 23 October 2026

- Full isolated backend suite: **288 passed,2 intentionally skipped in86.37 seconds**. The new OAuth route/refresh tests cover Cal confidential/public and Calendly PKCE, browser/session/state/CSRF/role guards, code replay, scopes, encrypted non-disclosure, connection replacement, parallel rotation, lost refresh, revoked access and preserved booking confirmation. The preview checks cover the exact reported catalog question, unrelated FAQ rejection, discovered/partial/missing links, source-specific answers, actual configured-model invocation at the synthetic model boundary, history validation and honest inference failure. Targeted commands: `uv run pytest -q tests/test_scheduling_oauth.py` (51passed) and `uv run pytest -q tests/test_preview_answers.py tests/test_business_platform.py` (43passed).
- Production frontend build passes after the answer/link changes and Send-icon contrast correction. `scripts/verify_preview_browser.py` exercises real preview routes/cookies/database against a synthetic website and model, verifies the exact catalog link and a follow-up answer, then checks desktop/mobile light/dark, visible contrasting Send control and no overflow/errors. This is not a live Nature Nuskha or Aurely result. Artifact: `artifacts/preview/browser-results.json`.
- `QA_SCHEDULING_OAUTH=1` with `scripts/verify_scheduling_browser.py` passes actual application start/redirect/callback cookies, encrypted connection, meeting selection, agent publication, WebSocket read-back/confirmation, both adapters and one simulated booking POST each, history and responsive themes. Only external consent/token/profile/model/booking boundaries are synthetic; no provider request, meeting, call or email was made. Artifact: `artifacts/scheduling-oauth/browser-results.json`.
- Full beta browser regression passes account creation, agent creation/publication, structured variables, notifications, sidebar persistence, contacts/campaign draft, profiles/devices, JWT/tab refresh and mobile focus/overflow with zero page errors. Artifact: `artifacts/beta/results.json`.
- Isolated PostgreSQL17 repeatably upgrades59→64 tables and starts production under a restricted role without schema CREATE. Two simultaneous OAuth refresh requests produce one simulated token exchange; parallel booking confirmation produces one simulated booking POST and confirmed final state. Existing number-budget/admission checks still pass. Temporary container/volume removed; remote Supabase untouched. Artifact: `artifacts/automatic-numbers/postgres-results.json`.
- Exported OpenAPI has140 paths and includes dashboard-only OAuth security/history input. Schema revision and64 tables are unchanged. Every previous private `.env` byte is preserved, with five OAuth settings appended and mode0600 retained. `.agents/` and `skills-lock.json` remain unrelated/excluded.

Register the real provider apps, fill the client placeholders and complete public HTTPS/provider acceptance before enabling customer use. Cal.com approval and Calendly plan/scope requirements still apply. No live activation or full new API image build is claimed. The user's uploaded Chromium build log ends in SIGKILL/exit137; its resource cause is unconfirmed and separate from the preview's keyword-selection bug. See [OAuth activation](SCHEDULING_OAUTH.md).

## Website assistants and interactive widgets — 23 October 2026

- Full isolated backend suite: **217 passed, 2 intentionally skipped in71.86 seconds**. New website tests exercise ingestion, nested sitemaps, robots exclusions, structured products/variants/specifications, deduplication, pinned facts, failed-index isolation, tenant/corpus/action boundaries, current-page context, persisted resume and key rotation. Actual guarded Chromium executes permitted same-origin JavaScript while external/POST/websocket requests are blocked. Both scheduling adapters pass public-chat availability/read-back/resume/confirmation; text-to-voice continuation uses the same persisted booking and transcript.
- Final production frontend compilation and route builds pass. The independent-origin browser runs a real local HTTP website and actual temporary API/worker/database, not fabricated app API responses. URL setup, automatic product extraction, appearance, indexed pages, agent testing, navigation, resumed history, product-specific current-page evidence, usage and desktop/mobile/dark themes pass with **zero page errors**. Visual inspection caught and corrected mobile control clipping and the initial generic-page ranking. Evidence: `artifacts/website/browser-results.json` and screenshots; reproduce with `scripts/verify_website_browser.py` and system Chromium wrapper as documented in WEBSITE_ASSISTANTS.
- Full beta account/agent/variable/profile/contacts/campaign/notification/session/mobile regression and the existing separate-origin widget/catalog/ticket acceptance pass, zero page errors. No calls, email, purchases, real meetings or payments occur in these checks.
- Temporary PostgreSQL17 upgraded **59→64 tables**, repeated initialization and accepted production startup under a role lacking schema CREATE. Existing parallel phone admission/allocation and one-shot booking checks pass. Only the QA container/volume was removed; no external Supabase migration ran.
- Real Aurely Jewellers app-path check returned422 before queuing: DNS resolution failed for aurelyjewellers.in, its www alias and control domains example.com/github.com; normal proxy probes failed too. Zero pages/products extracted. Reusable isolated scripts/verify_live_website.py and artifacts/website/aurely-live-results.json record the result. Public reference-site access fails in the current cloud. Production-model/embedding/speech/calendar/website acceptance remains dependent on deployment access. The API image build passed dependency installation using the existing cloud CA secret, then hit the workspace disk limit while apt attempted to install Chromium. Native system-Chromium rendering passed; a complete updated API image build remains unaccepted on this host. No TLS/egress safeguards were weakened. Private `.env` remains unchanged.

Current schema revision **2026-10-23-website-assistants**, **64 tables**, contract **138 paths**. See [feature setup and limits](WEBSITE_ASSISTANTS.md). Older checkpoints below retain their historical counts.

## Direct call-agent scheduling — 23 October 2026

- Full isolated backend suite: **203 passed,2 skipped in53.61 seconds**. New coverage includes both provider contracts, real VoiceSession read-back/yes turns, required caller evidence/answers, timezone-aware offers, exact-slot/connection/event freshness, later unqualified consent, tenant/call/role boundaries, concurrent confirmation, interruption, unknown response recovery without another POST, provider error/approval handling and exact recovery markers. The two skips are provider-specific tests exercised for their applicable provider. All provider/model operations are simulated.
- Production frontend compilation, TypeScript and all route builds passed. The scheduling browser exercised real signup, encrypted connection APIs, event-selection dialogs, per-agent scheduling settings/publication and actual WebSocket text simulations for Cal.com and Calendly. Each created exactly one mocked provider booking only after the read-back and a later yes. The real API supplied history and status. Both themes/desktop/mobile had zero page errors and no horizontal overflow. Source times are displayed in Asia/Kolkata even when the browser timezone differs. A missing accessible name on the new platform selector was corrected; integration actions wrap and mobile booking records expose status/actions without sideways scrolling. Evidence: `artifacts/scheduling/browser-results.json` and screenshots.
- A temporary PostgreSQL17 database upgraded **59→63 tables**, accepted repeatable initialization and started production with a runtime role lacking schema CREATE. Existing phone admission/allocation checks still passed. Two simultaneous confirmations shared one persisted intent and **one simulated booking POST**, resulting in confirmed/submitting responses and a final confirmed record. `scripts/verify_number_allocation_postgres.py` reproduces this with local generated credentials and mocked providers; `artifacts/automatic-numbers/postgres-results.json` records it. Temporary container/volume removed. No real Supabase migration or external TLS acceptance occurred.
- Full beta browser regression passed signup, agents/publishing/variables, notifications, contacts/campaign drafts, profile/devices, JWT/concurrent-tab refresh and mobile navigation with zero page errors. Private `.env` is byte-for-byte unchanged; this feature uses encrypted per-workspace scheduler credentials.

Latest schema revision **2026-10-23-agent-scheduling**, **63 tables**, actual OpenAPI **132 paths**. Setup, supported event types, provider API versions/scopes and dated evidence are in [agent scheduling](AGENT_SCHEDULING.md). Calendly source inspection used a third-party snapshot of its published OpenAPI because the live docs domains were blocked; this limitation is recorded. Public real-account booking/plan access, notifications, physical speech/PSTN and provider cancellation/refresh acceptance remain pending. No meeting or notification was sent to a real person.

## Automatic trial numbers and carrier research — 23 October 2026

- Full isolated backend suite: **150 passed**, including25 new automatic-allocation cases. Covers empty-body enrollment, person/workspace/role/CSRF/key boundaries, duplicate clicks and workers, owned stock without a purchase, seven-day grants, provider quote/currency/price/budget/balance/expiry checks, cross-pool cumulative budget, ambiguous purchase recovery without another POST, wrong marker/account rejection and optional API-key authentication. Existing21 phone-trial regressions also pass. No external carrier, account creation, email or payment operation ran.
- The full beta browser also passed signup/create/publish/variables, notifications, contacts/campaign drafts, profile/devices, JWT/tab refresh and mobile navigation with zero page errors. Final Next production compilation, TypeScript and all route builds passed. The updated phone browser passed mobile one-click enrollment without a number picker, actual temporary-API job/status refresh, owned-stock assignment through a mocked read-only SDK, three real local call admissions, expiry/exhaustion and both themes/viewport sizes. No page errors or horizontal overflow. Queue workers for outbound calls were not run. Screenshots/results: `artifacts/phone-trials/`, including `automatic-offer-mobile.png`.
- Temporary PostgreSQL17 upgraded **59→61 tables** repeatably and accepted production startup with a restricted runtime role and no schema CREATE. Two concurrent call admissions returned202/429 with one reservation. Two concurrent automatic-number orders under a115-cent quote/150-cent total budget made exactly **one simulated purchase**; states were assigned/unavailable. Evidence: `artifacts/automatic-numbers/postgres-results.json`; reproducible script `scripts/verify_number_allocation_postgres.py`. Temporary container/volume removed. This is loopback PostgreSQL, not external Supabase/TLS/pooler acceptance.
- Actual OpenAPI export has **128 paths**, including GET/POST phone-trial; enrollment correctly declares dashboard-session-only authentication. Private env comparison verifies every earlier value preserved, six added settings, purchases off and mode0600. Existing unknown `.agents/` and `skills-lock.json` work is preserved and excluded from this commit.
- Official Twilio skills were installed as requested. [Research with pinned first-party sources](FREE_NUMBER_RESEARCH.md) records current documented one-number trial limits, Vapi inbound-only restrictions and Telnyx's conditional Professional evaluation. Proxy-blocked public documentation sites are recorded as an evidence limitation. No undocumented carrier funding arrangement is asserted for Nutaan.

Schema revision: `2026-10-23-auto-phone-numbers`. Real entitlements, inventory/pricing, rental billing, signed public callbacks/media, SMTP delivery and remote migration/grants remain unaccepted. The feature is prepared and disabled by default; these tests do not establish a live seven-day carrier subsidy. See [activation instructions](PHONE_TRIALS.md).

## Bounded phone beta — 23 October 2026

- Full isolated backend suite: **125 passed in 31.14 seconds**, including 21 phone-trial cases. Coverage includes zero-wallet/idempotent admission, destination and concurrency guards, fixed lifetime allowance, expired/stale/low/revoked pauses, queued expiry, pinned account credentials and provider time limits, owned outbound-only numbers, inbound/campaign rejection, isolation from unassigned numbers, exact-currency balances, durable SMTP retry/notices, replacement without expiry/usage reset and actual operator CLI configure/grant/status/pause commands. No carrier call or email was sent.
- The production frontend compiled, typechecked and built all routes. The phone-trial browser ran against the built frontend and a temporary SQLite API with its dispatcher disabled: real operator grant and three actual API admissions, remaining allowance, exhausted/expired states, desktop/mobile in both themes and no overflow or page errors. It holds bootstrap pending to prove the custom loader remains until workspace data is ready. No response payloads were fabricated; requests were forwarded to the isolated API. Queued calls never executed. Evidence: `artifacts/phone-trials/results.json` and screenshots.
- Final regression against the updated isolated development API and built frontend passed signup, agent/knowledge setup/publication, variables, notifications, contacts/campaign drafts, profiles/devices, JWT/tab refresh and mobile navigation. The theme verifier also passed ten desktop screens, eight mobile routes in both themes, local fonts, loading/404, tour controls and reduced motion, with zero page errors.
- A temporary PostgreSQL17 database upgraded from the prior 56-table layout to **59 tables**, with repeatable migration and schema checks. Production startup succeeded under a restricted runtime login without schema CREATE permission. Two parallel admissions produced **202/429** and one reserved call. This was isolated loopback transport, not an external TLS/pooler acceptance. Evidence: `artifacts/phone-trials/postgres-results.json`; temporary container/volume removed.
- The installed Twilio SDK supports `time_limit` and `balance.fetch`. Production Compose syntax passed using a temporary signing placeholder, preserving disabled trial activation. The running API still matches the committed **127-path** OpenAPI contract; trial status extends the existing authenticated summary.

Final browser regression exposed an existing first-load race: account readiness could render workspace controls before bootstrap data arrived. `Studio` now waits for the selected workspace's successful bootstrap, preventing early agent dialogs with empty knowledge choices. Failure still offers the custom retry/sign-in recovery screen.

The private `.env` only gained `PHONE_TRIALS_ENABLED=false` and blank `BETA_OPERATOR_EMAIL`; earlier values and mode0600 were preserved. Public deployment, real SMTP, Twilio credits/numbers/calls, provider balance acceptance and remote schema/grants remain pending. No real provider account, number rental, payment, call or external email was created by this work. See [phone trial setup and launch needs](PHONE_TRIALS.md).

## Main database pooler configuration — 23 October 2026

The user selected the main Supabase project for both application and schema maintenance. Private `.env` now has `DATABASE_URL` and `MIGRATION_DATABASE_URL` for the same IPv4 transaction pooler with TLS; eight superseded or duplicate keys were removed without changing other provider values or Google/SMTP placeholders. Production Compose selects the correct app/maintenance URLs and excludes the maintenance connection from API runtime. It was validated with a temporary signing placeholder without deployment.

The full isolated backend suite passed: **104 tests in 23.18 seconds**. A temporary PostgreSQL17 container accepted the actual database engine options, applied the schema twice, passed the read-only revision check and retained **56 application tables**. Twelve parameterized queries passed with zero prepared statements and UTC timezone. Evidence: ignored `artifacts/database-config/local-postgres-results.json`. The temporary container and its volume were removed.

These local results do not establish remote transaction-pooler acceptance. Read-only probes of the supplied pooler addresses, including `scripts/check_database.py` using the final configuration, returned **network/address route unavailable** in this cloud. No remote schema/data changes occurred. Runtime still uses the supplied project owner; restricted-role setup and the other public release gates remain pending.

## Neutral interface and route states — 23 October 2026

The user supplied Fish Audio light/charcoal and ElevenLabs neutral references. The interface now uses warm light and charcoal palettes with small teal accents across home, auth, workspace, docs, public chat and 404. Existing licensed DM Sans/Manrope WOFF2 assets remain local; no font-service imports were added.

Executed checks for this frontend change:

- `npm run typecheck` and `npm run build` passed. The Docker web image built successfully with the frozen lockfile and optional trusted build CA.
- `scripts/verify_theme_browser.py` passed against development and the built production web image with an isolated development API. It checks Light/Dark/device selection, persistence across reloads, cross-tab synchronization and device changes; actual pending account loading and recovery; custom unknown root/workspace routes; Remotion chapter shortcuts/play/pause/transcript/Escape/focus; ten desktop screens and eight mobile routes in both themes without overflow; and reduced-motion still art/no automatic tour playback. Zero page errors.
- Every observed WOFF2 request used the application's own origin and completed successfully. Source scan found no Google Fonts/font CDN imports. The public installation script uses system fonts without a font download.
- Existing full beta browser passed signup/create/publish/variables, notifications, sidebar persistence, contacts CSV/campaign draft, profile/devices, expired access and concurrent-tab refresh, and mobile focus/overflow. The external-widget browser passed catalog/ticket, origin denial and cookie isolation with zero page errors.
- Host API/frontend were restored after production builds. Temporary image QA containers were removed; persistent Qdrant/application data was retained. Tracked `.env` is unchanged by this visual pass.

Evidence is in ignored `artifacts/theme/results.json`, desktop/mobile/loading/404/tour screenshots, plus the existing beta/embed result files. The Remotion tour is a paused, lazy-loaded 16-second illustrated Player with an accessible transcript, not a live provider demonstration or an exported video. Root unknown paths return404; Next's streamed workspace notFound may retain200 with noindex. These changes do not activate Google/SMTP/phone services or alter the public deployment gates recorded below. See [design system](DESIGN_SYSTEM.md).

22 October 2026. These are executed checks; provider adapters are not described as live acceptance.

## Expanded beta — current cloud evidence

The results below are from the 22 October 2026 cloud checkout. Older Supabase/provider/site timings later in this document are historical evidence from another host; they were not repeated here.

| Check                   | Executed result                                                                                                                                                                                                                                                                         |
| ----------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Dependency setup        | Frozen uv sync and npm ci completed; reusable installer exercised                                                                                                                                                                                                                       |
| Full isolated suite     | **104 passed**; temporary SQLite, local objects, external provider keys cleared                                                                                                                                                                                                         |
| Auth/activation         | OIDC RSA signature/audience/nonce/email verification, state/PKCE/linking, one-use email, TLS SMTP/errors, JWT rotation/replay/CSRF, profile/device controls                                                                                                                             |
| Agent/integrations      | Recent widget history and variables, durable usage, public voice origin/concurrency/revocation, webhook HMAC/retry/rotation, tenant Twilio signatures, contacts CSV/permission/campaigns, Google availability/sync/idempotency/cancellation                                             |
| Production frontend     | Next compilation, TypeScript and all routes passed after final cross-tab refresh change                                                                                                                                                                                                 |
| Beta UI                 | Actual signup/create/publish/variables, notifications/read state, sidebar persistence, contacts CSV review/import/export/campaign draft, profile/devices, expired access refresh, concurrent-tab single rotation, mobile focus/Escape and six routes without overflow; zero page errors |
| Existing browser flow   | Signup, fixture knowledge, text simulation, persisted support ticket and catalog chat; zero page errors                                                                                                                                                                                 |
| Independent-site widget | Cross-origin catalog/ticket, unlisted-origin denial, no dashboard cookies; zero page errors                                                                                                                                                                                             |
| Docker                  | API and web images built and ran with no real provider credentials; complete beta browser flow passed against built web/API images                                                                                                                                                      |
| PostgreSQL schema       | Isolated PostgreSQL17: additive migration applied twice, read-only check passed, **56 tables**; restricted runtime role signed up/created agent with no startup DDL and no schema CREATE permission                                                                                     |
| Gateway                 | Actual Caddyfile validated; local HTTP override routed app/docs/API and upgraded WebSocket; internal services excluded from inherited cloud proxy                                                                                                                                       |
| Production Compose      | Overlay config --quiet passed using explicitly fake syntax-validation values; no deployment performed                                                                                                                                                                                   |
| Host services           | Local QA API/frontend restarted and healthy; authenticated persistent Qdrant healthy; actual OpenAPI matches tracked contract at 127 paths                                                                                                                                              |
| Private configuration   | Tracked .env unchanged; setup/start instructions, missing variable metadata and provider domains saved to cloud draft                                                                                                                                                                   |

Evidence: ignored `artifacts/beta/browser-results.json`, `schema-results.json`, `gateway-results.json`, desktop/mobile screenshots, plus `artifacts/embed-results.json` and existing browser results. Temporary QA containers are removed after checks; persistent Qdrant/application data is preserved. Optional injected build CA remains verified through a BuildKit secret.

Current blockers: the supplied Supabase read-only probe still reports **network/address route unavailable**. Google OAuth and SMTP credentials are absent; user will supply them. Current cloud Azure/provider access is blocked. Public DNS/TLS/WSS, physical microphone, actual carrier/calendar/email/payment actions, remote migrations/restore/load and paid-call pricing remain unaccepted. The local PostgreSQL check did not test public TLS or database per-tenant RLS. No live calls, mail deliveries or provider purchases occurred. See [beta deployment](BETA_DEPLOYMENT.md) for activation.

| Check                                     | Result                                                                                                                                                                                                                                                                                     |
| ----------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Full `uv run pytest -q`                   | **74 passed**, temporary SQLite/local objects with external credentials cleared                                                                                                                                                                                                            |
| Preview tests after final category filter | 3 passed,12 deselected                                                                                                                                                                                                                                                                     |
| `npm run build`                           | Next production compilation, TypeScript and all8 route builds passed                                                                                                                                                                                                                       |
| Supabase readiness                        | Actual connection/TLS/dedicated schema passed                                                                                                                                                                                                                                              |
| PostgreSQL integration                    | **45 application tables**, actual auth/isolation/source query/pinned agent/concurrent once-only settlement/append-only protection/booking idempotency+conflict/anonymous schema denial passed                                                                                              |
| First-minute browser                      | Real palsona.in first cited answer **6.91s**, no signup, one primary button, follow-up, keep handoff and mobile overflow checks passed; zero page errors                                                                                                                                   |
| Agent-platform browser                    | Website preview→signup→same published agent, cURL import/schema, tool draft access, explicit mock without network, model protocol/cap selection, invitation link, operations/campaigns/integrations/numbers/billing/developers navigation, docs and mobile checks passed; zero page errors |
| Existing dashboard browser                | Signup, knowledge query, browser text simulation, persisted follow-up ticket, catalog chat and mobile screenshot passed; zero page errors                                                                                                                                                  |
| Separate-origin widget browser            | Catalog facts, persisted ticket, unlisted-origin denial, no dashboard cookies, mobile passed; zero page errors                                                                                                                                                                             |
| Compose config                            | `docker compose config --quiet` passed; actual image/container runtime remains unverified (previous daemon permission denial)                                                                                                                                                              |
| Private configuration                     | Local env mode0600; user explicitly chooses tracking in private repo. Env/Git/runtime data excluded from shareable source ZIP                                                                                                                                                              |

PostgreSQL/browser checks intentionally retain named synthetic QA rows; latest PostgreSQL workspace `e3a1ba87-257c-472b-ad09-4ff224accad9`. No remote tables were dropped/truncated, unrelated schemas changed, purchased credit spent or PSTN call placed.

Regression coverage includes tenant/auth/CSRF/key roles, immutable publication, canonical sources/robots/private-address and DNS-at-connect pinning, document promotion, fact grounding, durable ticket confirmation, widget isolation, accounting races, campaign budget/concurrency/retry/window, local/remote booking boundaries, payment capture tampering/replay, invitation/reset identity and expiry, stereo WAV/retention, both LLM protocols and tool round trips, fragmented tool calls, parameter fallback before streaming, no replay after partial text, HTTP execution/revision pinning/redaction/deduplication, Plivo/Twilio signatures/canonical legs/replay media stop/clear behavior, and nonblocking dispatcher polling.

Browser-test corrections: Next development tools and its empty route-announcer alert sit outside application main. Assertions now scope product button/error checks to main. Tool/model/invitation assertions use actual accessible labels and wait for hosted DB operations. These fixes do not suppress application errors; zero pageerror events are still required.

Artifacts/screenshots and JSON results are in ignored `artifacts/`. Current contract export has103 API paths. The old `packages/contracts/openapi.json` remains a blueprint. Font/source screenshots were inspected at desktop/mobile sizes.

No real microphone→Deepgram→LLM→Fish call, Azure/Qdrant/embedding transaction, carrier connection, external CRM/calendar/SMS action, payment capture or public deployment was executed. Contract tests use offline mocks. Provider keys come later; acceptance sequence and remaining production limits are in `AGENT.md`, `IMPLEMENTATION_STATUS.md` and `DEPLOYMENT.md`.

## Provider activation follow-up

77 offline tests passed in19.58s after Azure prefix/model-alias/Fish model changes; frontend production build passed. Real Azure Blob/embeddings and Fish→Deepgram streaming passed. Azure LLM returns404 DeploymentNotFound on both Responses and Chat; Qdrant not configured. Full evidence and reproducible paid smoke commands: [provider acceptance](PROVIDER_ACCEPTANCE.md). This updates the earlier no-provider-key checkpoint above.

Live app media acceptance passed: real Fish greeting, correctly framed synthetic audio, Deepgram recognition, committed support ticket and audible confirmation, two-channel Azure recording/download, zero media errors; first audio3034ms. Physical microphone and LLM-generated reply remain unverified. artifacts/live-session-results.json records the evidence.

Razorpay mode follow-up: full isolated suite81 passed in17.05s. Both mode-specific credential pairs saved privately, test selected, correct pair used by provider auth/checkout/signature verification. Regression checks cover mode selection, cross-mode legacy fallback rejection and incomplete-pair isolation. No external payment request was made. API restarted.

## Azure deployment resolved and full LLM voice accepted

The user deployed the exact gpt-6-luna target. scripts/verify_providers.py now passes all5 real provider checks: Azure Blob, Azure Responses streaming/function-call round trip, embeddings1536, Fish drama-3 and Deepgram nova-3. Model follow-up first token1847ms; Fish standalone first audio953ms in this probe. No parameter changes or alternate model were required.

scripts/verify_live_voice.py --llm passed against the running app and Supabase: synthetic spoken question, Deepgram final transcript, lexical synthetic fixture retrieval, gpt-6-luna grounded answer, actual Fish response audio, two non-silent stereo Azure recording channels and authenticated download. Answer: “The engraving limit is 20 characters.” Zero media errors. Greeting first audio3837ms; final-transcript-to-reply-audio7015ms. These are one-run observations, not latency guarantees. Physical microphone, Qdrant, PSTN and interruption/disconnect acceptance remain. The existing81-test application suite/build evidence is unchanged; this pass changed acceptance tooling/docs only.

## Green palette and decorative motion

22 October 2026: production build, TypeScript and all route builds passed after the login particle and hero motion changes. Chromium checks at 1440×900 and 390×844 verified green canvas pixels on the off-white login panel, actual canvas movement, sign-in fields/signup toggle, and no horizontal overflow on either page. Hero transforms changed on19 elements with23 CSS animations. Reduced-motion preference produces a still login scene and disables all hero animation; an offscreen mobile hero pauses and resumes when visible. Zero page errors. Screenshots and results: `artifacts/brand-motion/`. These were local visual checks; no signup, preview request or paid provider action was submitted.

## Preview conversation regression

Full isolated suite **85 passed in25.74s**, and Next production compilation/TypeScript/all route builds passed. New API regressions cover bare greetings, punctuation/case, thanks, social prefixes before actual questions, absent evidence and words beginning with “hi”. Conversation/missing-evidence replies return no citations; real excerpts retain their source. `scripts/verify_first_minute.py` passed against the refreshed local API and real palsona.in: first result **2.94s**, no signup, greeting/thanks and unknown-evidence labels without source links, actual source follow-up, latest-reply scrolling, mobile overflow and keep handoff. Zero page errors. Results: `artifacts/first-minute-results.json`; final conversation screenshots: `artifacts/first-answer-mobile.png`. One expiring preview was created in Supabase; no account, paid LLM request or phone call was made. This flow remains a lexical/extractive page preview, not an LLM conversation.

## Self-hosted Qdrant acceptance

22 October2026: Qdrant v1.19.2 actually runs in rootless Podman as the healthy `voice-studio-qdrant.service`. REST is loopback-only; unauthenticated collection access is rejected and authenticated requests succeed. Service and application env files retain mode0600. User lingering/default-target startup is configured. Named data/snapshot volumes persist independently of container lifecycle.

`scripts/verify_qdrant.py` passed with actual Azure text-embedding-3-small1536 vectors: semantic ranking, mandatory tenant/snapshot isolation, and complete synthetic-point cleanup. All14 existing published snapshots were backfilled, resulting in29 points. Reindexing one revision left the point count unchanged. Actual application `retrieve` returned qdrant-hybrid/answerable passages; stopping Qdrant produced an explicit transport failure; restarting preserved all29 points and restored retrieval. No source/database rows were dropped or rewritten. Indexing consumed real embedding requests; no voice/phone/payment requests were made.

Full isolated suite **85 passed in24.07s**. Compose `--quiet` validation and setup/reindex/verifier Python compilation passed. The actual in-container readiness probe is healthy; Docker daemon access remains denied, so full API/web Docker images were not built or run. Evidence: `artifacts/qdrant-results.json` and `artifacts/qdrant-deployment-results.json`. Production capacity, snapshot backup/restore drills and high availability remain unaccepted.
# Phase 1 item 8 — 25 October 2026

Actual Chromium acceptance (`scripts/verify_tool_safety_browser.py`) passed against
the production frontend and isolated local API: unrelated human wording causes
no ticket, chat and real WebSocket simulation both require later confirmation,
each persists one ticket, zero page errors. Providers/SMTP/phone/payments were
disabled; this is not a live speech measurement. Evidence:
`artifacts/tool-safety/browser.json`. Frontend typecheck and production build
passed. Red-team suite:24 passed, including strict classifier schema tests.
Final integration run:129 passed in83.79s (red-team, business/platform/custom
runtime, HTTP hardening, widget live and website assistants).

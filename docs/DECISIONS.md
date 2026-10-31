# Implementation decisions

## Phase 6 — scheduling SQL offload, 27 October 2026

Cal.com/Calendly availability, readback preparation, confirmation and GET-only
reconciliation now use session-local worker-thread transactions. Preserve context,
expiry, exact caller details, credential revision, current availability and later
uninterrupted readback checks. No endpoint, payload, version header or retry policy
changed. Workspace→booking locks serialize final success, failure and uncertainty;
cancellation cannot overwrite a confirmed result. A canceled committed claim before
HTTP records a known unused failure. Started submissions remain unknown until
provider evidence; they never automatically POST again. Provider result storage and
uncertainty updates are durable through cancellation.

Current official Cal.com booking-controller source read200 on27 October2026:
https://raw.githubusercontent.com/calcom/cal.com/main/apps/api/v2/src/platform/bookings/2024-08-13/controllers/bookings.controller.ts
It still declares POST /v2/bookings and the explicit2024-08-13 version header.
Rendered Cal.com/Calendly docs rechecks returned URLError; no live Calendly contract
re-verification is claimed. Existing wire contracts remain unchanged and fake
provider regressions cover both. SQLAlchemy session-per-thread reference above.


## Phase 6 — custom HTTP tool SQL and cancellation, 27 October 2026

Custom HTTP tool queue/claim/finalization now use independent sessions inside
worker threads. Workspace then execution locks permit one network consumer.
Preserve public destination validation, exact revision, arguments, headers,
execution identity, response bounds and redaction; no endpoint/wire contract or
retry setting changed. A completed response remains authoritative even if client
close is canceled. Cancellation before submission records a known unused failure;
a possibly submitted request records unknown and is never replayed automatically.
Observe admission/claim transaction outcomes and finalize through cancellation.

SQLAlchemy session-basics documentation read HTTP200 on27 October2026:
https://docs.sqlalchemy.org/en/20/orm/session_basics.html . It specifies Session
per thread and a local context manager; sessions are not shared concurrently across
tasks. Scheduling and Google Calendar tool sections still require the same pass.


## Phase 6 — live transfer contract and cost fences, 27 October 2026

Official references actually read (HTTP200), before integration changes:

- https://www.twilio.com/docs/voice/api/call-resource — update an active call with
  a URL or TwiML; Python update time_limit preserves the original total ceiling.
- https://www.twilio.com/docs/voice/twiml/dial — new bridged leg, timeout buffer,
  timeLimit, action, DialCallSid and DialCallDuration.
- https://docs.plivo.com/docs/voice/api/calls — transfer(legs=aleg, aleg_url), POST
  call resource and documented call transferred response; both legs are billed.
- https://docs.plivo.com/docs/voice/xml/routing — Dial, timeLimit, callbackUrl,
  hangup DialBLegBillDuration and scheduled Hangup. Earlier guessed Dial URLs404;
  this current combined routing reference was located and read successfully.
- https://raw.githubusercontent.com/plivo/plivo-python/master/plivo/resources/calls.py
  — current transfer/update mapping, read for contract verification.
- Installed Next16.4.2 client-components guide for the destination/review component.

LIVE_TRANSFER_ENABLED defaults false, paid activation stays false, and production
requires an APPROVED tariff. A caller cannot supply a destination: owner/admin
policy revisions require verified platform-operator approval and an explicit staff
verification attestation. Existing BILLING_OPERATOR_EMAILS is the operator boundary;
no extra credential requirement was invented. API keys cannot change policy or
approve it. Destination/credential snapshots use versioned encryption. Readback
consent binds the team and policy revision; changed/revoked permission fails closed.

One transfer intent/submission per call; workspace→transfer locks and one-shot XML
fetch prevent duplicate paid dials. Unknown submission is never replayed. Frozen
carrier credentials authenticate later settlement after key rotation. A queued or
acknowledged request never claims a connected human. Signed parent-bound duration
settles a separate immutable staff-leg record; original parent voice/wallet/carrier
holds remain until real hangup. Parent admission now selects the actual carrier's
DRAFT rate (fixes the prior hard-coded Plivo choice for Twilio).

DRAFT defaults120seconds,5–300configurable,10second ringing and20second deadline
margin. Original admitted deadline never extends. Staff cost reserves a rounded
minute bound. The workspace kill switch explicitly queues a single parent hangup,
including after AI media detaches; pending transfer setup also rechecks pause/block.
A first full-suite run was intentionally interrupted to add this newly found
kill-switch case; its partial count is not a completed-suite result.

See HUMAN_TRANSFER for behavior, conservative lost-XML handling and migration.
No real carrier transfer or paid activation was performed. Phase3 retention must
purge transfer ciphertext once financial holds permit; financial facts stay immutable.

## Phase 6 — confirmed manual callback requests, 27 October 2026

A call-me-back flow collects an explicit visitor-provided E.164 number, reads back
exact details, and saves only after a later confirmation through existing scoped,
encrypted ToolConsent. It creates one normal inbox ticket plus one outbox email
per owner, atomically and idempotently. Existing inbox open/pending/resolved states
support team follow-up. Phone is labeled caller-provided/unverified; permission
is for this callback only, never marketing consent. Preferred time is copied from
visitor evidence and remains a request, never an appointment promise.

Callback means manual team follow-up, not an automatic outbound call. No phone
provider is invoked and no call time is promised. The separate live-transfer
adapter remains active work. CALLBACK_REQUESTS_ENABLED disables new proposals and
execution; revocation after readback fails closed. The explicit request_callback
tool is available in the assistant editor. Natural call-me-back wording remains
subject to intent classification; a support ticket about a callback function is
not rerouted. Phone collection can be canceled or interrupted by another question.

No new provider API was changed. Existing verified email outbox is the transport;
SMTP is never called in the request. Installed Next16.4.2 client-components guide
was reread for the editor option. During Phase3 rights integration, purge queued
callback outbox rows using the exact Ticket.operation_key prefix; delivered owner
email is subject to the published data policy. Do not lose this provenance link.


## Phase 6 — media transaction offload and durable lifecycle, 26 October 2026

Browser, Plivo and Twilio socket admission, session context loading and final
settlement now run in worker threads. Claim local ownership before yielding and
lock workspace before call, matching accounting lock order. A second connection
cannot settle the first connection's call after failing its handshake. Plivo now
accepts only connecting/ringing legs, matching Twilio's single-owner state fence.

Shield initialization until its committed result is observed. A cancellation after
admission still creates an observable session or sets the committed flag, then
settles failed and releases ownership. A constructor failure also settles the
admitted call. The common finalizer cancels recognizer/idle tasks, interrupts
responses, closes all provider owners and bounded STT transport, then settles
usage/cost and finishes recordings off-loop. Final ownership release/socket close
runs even when settlement raises. Failed admission never closes another active
call's financial reservation. No provider request format changed.

SQLAlchemy execution hooks in actual browser/Plivo/Twilio socket tests reject any
SQL executed on a running event loop. Separate cancellation and constructor-failure
tests demonstrate the commit/cleanup guarantees. This completes core socket SQL
offload; tool-specific scheduling/connector/HTTP execution and general async HTTP
handlers still need the broader Phase5 audit. Do not describe all async code as
nonblocking based on these socket tests.

## Phase 6 — recognition disconnect and carrier STT accounting, 26 October 2026

An unexpected normal end, malformed response or exception from recognition now
signals the media owner. Browser, Plivo and Twilio input receives race this signal,
cancel their pending receive and enter failed-call cleanup immediately. Do not
wait30–45seconds for another client message, leave TTS running, or treat missing
recognition as successful silence. Intentional shutdown cancellation is normal.
Provider exception payloads never become client error text. The owner remains
responsible for interruption, connection closure and financial settlement.

Twilio input now uses the same admitted-duration check and measured PCM counter as
browser/Plivo, and records STT cost at settlement. This fixes an existing bypass;
no media encoding or authentication contract changed.

Official Twilio media messages and Plivo audio-streaming docs rechecked HTTP200 and
read26 October2026:
https://www.twilio.com/docs/voice/media-streams/websocket-messages and
https://docs.plivo.com/docs/voice/xml/audio-streaming/ . Twilio documents server
socket close ending a bidirectional stream and continuing following TwiML (our
following instruction is Hangup). Deepgram close-stream/audio-keep-alive/listen-live
rechecks returned403; their contents were not read or assumed. Existing verified
interim/endpointing contract remains unchanged; disconnect signaling is local
transport lifecycle handling, with no invented provider message or parameter.


## Phase 6 — static greeting cache, 26 October 2026

Cache only completed static greeting PCM in process memory, keyed by workspace,
immutable agent version and a digest of exact spoken text/voice/model/PCM settings.
The exact text includes any AI and recording announcement. Any declared or bound
runtime variables, unresolved template marker or missing version disables caching.
Silence prompts, answers and confirmation readbacks never enter this cache.

DRAFT memory policy: at most64 clips, 4MB total, 512KB per clip, one-hour TTL; LRU
eviction and a lock cover concurrent calls/threads. No new persistent audio object
or customer query is stored. VOICE_GREETING_CACHE_ENABLED=false bypasses it.
Only a fully delivered successful greeting enters the cache. Interrupted/failed
or oversized generation does not. Replay still emits transcripts, normal audio
frames and recording data, but makes no Fish request or TTS reservation/cost row.
Session admission and voice duration accounting still apply. No new provider
contract; Fish references and completion boundary are recorded below.


## Phase 6 — early Fish connection and completion contract, 26 October 2026

Official Fish pages rechecked HTTP200 and read on26 October2026:

- https://docs.fish.audio/api-reference/endpoint/websocket/tts-live.md
- https://docs.fish.audio/features/realtime-streaming.md
- https://docs.fish.audio/developer-guide/best-practices/real-time-streaming.md

The protocol explicitly says stop drains remaining synthesis, emits finish, and
closes the connection. Flush has no documented generation ID or per-turn completion
acknowledgement. Generic best practices recommends connection reuse, but does not
supply that missing boundary. Under the original request's rule to follow official
docs when they conflict with the prompt, retain stop/finish before declaring a
readback complete. One physical socket across independently completed user turns
is therefore not claimed. A silent interval cannot establish complete consent.

A call-owned adapter opens a generation during SpeechStarted or concurrently with
safety/retrieval, sends only start with empty text, and leases that same socket to
the response. All model/tool rounds within the response share it. Immediate text,
flush, balanced PCM24k and existing limits remain. Finish closes it; the next turn
uses a fresh early-opened generation. VOICE_FISH_PRECONNECT_ENABLED=false disables
early opening. No background reconnect, text replay or unbounded pool. Barge-in
cancels the producer and receiver, closes the socket and clears queued playback.
Failures during retrieval also close unused connections. Call close owns a socket
opened during an unfinished utterance. Setup spans retain real duration even when
setup precedes final STT; trace offsets clamp at zero with a preconnected marker.

Reject invalid odd-length PCM and premature/error finish. Owned cleanup is bounded
and durable; TTS cost settlement still runs if cleanup is interrupted. Tests fake
the provider boundary and prove overlap, empty setup, no replay and resource closure.

## Phase 6 — bounded interim retrieval, 26 October 2026

Stable interim speech can prefetch read-only knowledge retrieval. DRAFT defaults
are a 250ms debounce, at most two requests per utterance, two active requests
across utterances, and a five-second result lifetime. VOICE_PREFETCH_ENABLED
can disable it. Only the exact normalized final query and snapshot IDs match;
normalization preserves case and punctuation. Recheck published workspace-owned
knowledge and passage contents before reuse. Changed, deleted, stale or foreign
knowledge cannot enter the final answer. No speculative model or tool execution.

Already-started embedding requests may finish after a hypothesis changes so
reported usage is settled; they still count against the active limit. Call close
owns cancellation and cleanup. Cancellation while admitting a provider request
observes the transaction and releases an unused hold. Started requests retain
unknown-usage holds unless actual tokens were reported. Settlement and owned
client cleanup are durable through cancellation. Disable automatic embedding
POST retries: an ambiguous paid attempt must not replay against one reservation.

Official OpenAI embedding guide read HTTP200 on25 October2026:
https://developers.openai.com/api/docs/guides/embeddings . Model, dimensions and
prompt_tokens contract are unchanged. Installed OpenAI SDK retry/close behavior
and official README were read for the preceding keepalive work. Deepgram interim,
endpointing and SpeechStarted references below remain the observation contract.

The ordinary final-only synthetic benchmark does not exercise interim reuse;
its numbers demonstrate regression behavior, not measured prefetch savings.


## Phase 6 — negotiated transcript deltas, 25 October 2026

New browser clients request `transcript_mode=delta-v1` in client.start. The server
acknowledges it in server.ready; clients without the request retain full partial
frames. Both dashboard and public voice reconstruct bounded patches. Every
utterance keeps one turn ID and sequence; patches retain a Unicode code-point
prefix and replace the rest. This supports both append-only assistant deltas
and corrected STT hypotheses without confusing UTF-8 bytes or JS UTF-16 indices.
Send one authoritative final transcript. Final assistant IDs match timing IDs.
Reject sequence gaps, invalid prefix bounds and stale epochs; duplicates do not
repeat text. A final full transcript repairs an interrupted patch sequence.

Deepgram is_final finalizes a segment; speech_final or UtteranceEnd finalizes the
utterance. Accumulate finalized segments before the current hypothesis and keep
its identity through the final user transcript. The existing endpointing and
audio parameters are unchanged. No speculative tool/LLM work was introduced.

Official references read on25 October2026 (HTTP200):

- https://developers.deepgram.com/docs/interim-results — hypotheses can be revised.
- https://developers.deepgram.com/docs/endpointing — speech_final and endpointing.
- https://developers.deepgram.com/docs/speech-started — VAD SpeechStarted event.
- Installed Next16.4.2 server/client-components and TypeScript guides were read
  for the shared browser module and client event handlers. No new dependency.

## Phase 6 — call-scoped model keepalive, 25 October 2026

Each voice call owns at most two SDK clients keyed by endpoint, credential hash
and the public-only transport policy. No client is shared across calls or
workspaces. Idle entries can be evicted on key rotation; active entries are not
evicted. Resolve enabled profiles and credentials again for every turn before
leasing a client. Keep custom-endpoint SSRF guards, redirect restrictions and
timeouts. `VOICE_LLM_KEEPALIVE_ENABLED=false` restores temporary clients.
Browser, Plivo and Twilio call cleanup explicitly close the pool after canceling
streams; repeated cleanup cancellation still observes close completion.

Reusing an SDK object alone did not preserve the connection: a real local TCP/SSE
test observed two connections for two requests when stopping at response.completed
before the final SSE tail. Drain the terminal tail for at most250ms after validated
completion/incompletion. Successful drain permits HTTP keepalive; a missing tail
discards the connection without replaying generation or changing authoritative
completed output/usage. A stalled or broken tail never authorizes more tools.
The real SDK/local-server test now proves one connection for two normal turns,
and two discarded/reopened connections when tails stall. Provider performance
and internet TLS reuse are not measured by this local protocol test.

Official references read on25 October2026:

- https://raw.githubusercontent.com/openai/openai-python/main/README.md — async
  client lifetime, explicit awaited close and HTTP resource management; installed
  openai3.35.1 async client/stream source also inspected.
- https://developers.openai.com/api/docs/guides/streaming-responses — terminal
  semantic events. Completion authority is separate from HTTP transport draining.
- https://www.twilio.com/docs/voice/media-streams/websocket-messages and
  https://www.twilio.com/docs/voice/twiml/stream, plus
  https://docs.plivo.com/docs/voice/xml/audio-streaming/ and
  https://raw.githubusercontent.com/plivo/plivo-python/master/plivo/xml/streamElement.py.
  Carrier wire formats are unchanged; these paths now close their call-owned
  model client resources. Older www.plivo.com documentation URLs failed; current
  docs.plivo.com and the official SDK source were reachable with HTTP200.

## Phase 6 — Responses cache and completion contract, 25 October 2026

Official gpt-5.6 voice requests use Responses with explicit `none` reasoning by
default, or an explicitly selected `low`. The independent pro mode is not sent.
Custom endpoints retain their researched API contract. Stable platform policy
is a developer input-text block; static business guidance remains untrusted user
content. Dynamic UTC date, visitor variables, evidence and history follow the
cache prefix. Personalized guidance is not selected as a cached prefix. Caching
uses explicit breakpoints,30-minute lifetime, `store=false` and a keyed workspace
identifier. `VOICE_PROMPT_CACHE_ENABLED=false` removes breakpoints; explicit mode
without breakpoints disables cache reads and writes. No padding is added to reach
the documented minimum cacheable length, and no cache hit or quality improvement
is inferred from synthetic tests.

Cache writes carry a premium. New DRAFT rates include30-minute1.25x and12-hour2.5x
write costs, rounded up to integer rate units. Admission reserves the highest
possible30-minute input rate before I/O. Reported ordinary input, cached reads
and writes are disjoint portions of total input. Preserve total input and both
write lifetime facts without double-counting charges. The adapter requests only
30minutes; a total-only write count therefore uses that lifetime. Missing or
inconsistent usage retains an unknown hold. Unexpected unpriced writes retain
token facts, keep the hold and pause spending for operator review.

Existing tariffs remain immutable. New tariffs separately pin current provider
prices and the subscription's existing retail catalog, so updating provider
write costs does not change a customer's retail contract or old call costs.
Legacy Responses tariffs disable cache writes; legacy Chat Completions cannot
disable these writes reliably and fail before I/O until configured or switched
to Responses. DRAFT plan economics conservatively include all-input30-minute
write exposure rather than assume cache-read savings. Actual cache prefixes can
be smaller or ineligible; this is an exposure scenario, not measured traffic.

Process bounded tool-call streaming events as progress only. Execute tools only
from validated completed output, never provisional argument deltas or incomplete
responses. Flush speech at tool progress without flushing a credential guard's
pending tail. Incomplete responses keep measured usage, record interrupted
history and a failed timing denominator, and ask for a shorter follow-up without
automatically replaying. Cancellation observes durable admission and settlement
transactions, including repeated cancellation. Preflight failures release unused
holds without inventing a provider charge.

Official references read on25 October2026 (HTTP200):

- https://developers.openai.com/api/docs/guides/prompt-caching — explicit input
  breakpoints, minimum length,30m/12h lifetimes, cache-write premiums and usage.
- https://developers.openai.com/api/docs/guides/reasoning,
  https://developers.openai.com/api/docs/guides/latest-model and
  https://developers.openai.com/api/docs/guides/migrate-to-responses — model
  tiers, explicit effort and the independent pro mode.
- https://developers.openai.com/api/docs/guides/streaming-responses and
  https://developers.openai.com/api/docs/guides/function-calling — added tool
  items, argument delta/done, completed and incomplete events.
- Installed official openai3.35.1 request/usage/event types support native
  prompt_cache_options and input-text breakpoints. Its typed request supports
  30minutes; the adapter does not send undocumented12-hour overrides.

## Phase 6 — immediate streaming and admission credit, 25 October 2026

Forward every credential-filtered delta immediately; let Fish buffer its own
context. Emit the SDK's documented FlushEvent separately at sentence/turn ends
and before tool work. Keep controls out of transcript and cost counters. Acquire
bounded configurable UTF-8 credit before wire submission, using existing durable
caps/holds. A local credit window removes per-delta SQL without permitting spend
past admission. Credit is conservative, not a promised minimum usable allowance.
Canceling a thread await does not stop its transaction, so cleanup waits for the
grant's outcome before settling. Playback clear is independent and immediate.

Explicit async-generator closure prevents a failed playback consumer from leaving
the model/Fish sender alive. Monitor sender and receiver together, propagate text
producer failure without waiting for remote audio, reject premature finish, and
drain owned tasks. Keep DB/profile/confirmation work off the audio event loop.
The current measured synthetic target passes; no corresponding live measurement
or completed connection-reuse/cache claim is made.

Additional official references actually read on25 October2026:

- https://docs.fish.audio/developer-guide/best-practices/real-time-streaming.md,
  https://docs.fish.audio/features/text-to-speech.md,
  https://docs.fish.audio/api-reference/sdk/python/resources.md and
  https://raw.githubusercontent.com/fishaudio/fish-audio-python/main/README.md.
  Also read installed official1.3.0 types and realtime helpers. The generic best
  practices page suggests5–10word batching for smoothness, while the canonical
  realtime guide explicitly says no client batching is necessary. Follow that
  voice-specific guide and this user's immediate-delta requirement. The best
  practices page recommends connection reuse, but stop still closes and flush
  has no documented generation acknowledgement; resolve reuse without weakening
  confirmation or interruption guarantees.
- Installed CPython contextlib.aclosing documentation for deterministic async
  generator cleanup. Existing asyncio.to_thread/shield contracts govern the
  durable transaction cancellation boundary; no provider retry was introduced.

## Phase 6 — instrumentation first, 25 October 2026

Persist monotonic per-turn stage timings in a dedicated tenant/call-scoped table
to avoid overwriting concurrent call metadata. The target starts when the server
receives a final transcript and ends after its first audio transport write. It
does not include upstream speech endpoint detection or physical speaker playback.
Missing audio remains null. Summaries separate live/synthetic/development sources
and exclude greeting, failed and interrupted turns from completed-turn percentiles,
while showing the failure/interruption denominators. Call detail reads the latest
50records; source contents and credentials are never stored in timing records.
Telemetry persistence failure logs a sanitized warning and does not mask billing
settlement or cleanup. The synthetic benchmark keeps actual admission, meter,
credential filtering, provider event parsing and framing; only provider boundaries
are fake. Its measured baseline misses p50; the CI target is not declared passed.

Official references read on25 October2026, now reachable with HTTP200:

- https://docs.fish.audio/llms.txt,
  https://docs.fish.audio/features/realtime-streaming.md and
  https://docs.fish.audio/api-reference/endpoint/websocket/tts-live.md. Former
  Python/JS WebSocket guide URLs redirect to realtime-streaming. The reference
  includes the complete AsyncAPI schema; direct asyncapi.yml failed and is not
  claimed separately read. Start once with empty text, send each text delta,
  flush buffered text without ending the session, PCM and balanced mode are
  documented. Stop produces finish and closes the socket; no per-turn flush
  acknowledgement is documented. Connection reuse must account for this.
- https://developers.openai.com/api/docs/guides/reasoning,
  https://developers.openai.com/api/docs/guides/latest-model,
  https://developers.openai.com/api/docs/guides/migrate-to-responses,
  https://developers.openai.com/api/docs/guides/streaming-responses and
  https://developers.openai.com/api/docs/guides/prompt-caching. Confirmed5.6
  sol/terra/luna, none/low/medium/high/xhigh/max efforts, medium omitted default
  independent of pro mode, semantic Responses events. Explicit caching uses a
  supported input content block; top-level instructions cannot carry a breakpoint.
  Cache writes have a premium and reported write tokens; account for these in
  the upcoming caching/admission change rather than assuming writes are free.
  Full function/tool event handling remains the next implementation work.

## Revised checkpoint step 4 — 25 October 2026

Use explicit DRAFT workload assumptions to evaluate every configured model's
chat/browser/phone allowance exposure. Include knowledge embedding/storage and
combined scenarios, without double-counting the shared voice pool. Show loss
versus the plan price and allowance delivery stopped by a hard cap. Current
DRAFT values fail the allowance economics check on all plans. This is a pricing
review input, never actual margin, vendor pricing evidence or approval to sell.
No provider contract was changed to produce this arithmetic report; actual
cost/meter records and operator spend/contribution/top-consumer/kill views remain.

The shared Free pool is anchored to an immutable original user, not current
memberships or a mutable workspace setting. Serialize admission on that user and
sum immutable tariff-tagged usage/costs plus outstanding holds across their
workspaces. Pin tariffs on all new meter events; count old untagged facts
conservatively. A paid upgrade does not erase earlier Free use, and new paid use
does not consume the Free pool. Current inventories only include Free workspaces.
Use one UTC monthly boundary so timezone changes cannot extend the allowance.
The existing immutable financial records survive content/workspace erasure; the
privacy work must preserve this minimal billing sponsor link in retained shells.

Sponsor-only shared usage is a separate disclosure boundary from workspace
billing access: a transferred workspace's member or API key must not learn the
original sponsor's other workspace spending. The response includes that aggregate
only for the matching authenticated sponsor browser. Orphan legacy workspaces
fail closed until an owner exists; no fallback test identity is synthesized.
Commercial/legal values remain DRAFT and paid activation remains off.

## Revised checkpoint step 3 — 25 October 2026

Public loader/worklet/CSS assets use a60-second public cache with revalidation;
HTML remains private/no-store. A five-second Redis framing-policy cache avoids
the API call on warm widget page loads. Claims are fenced against origin changes,
proof expiry bounds the TTL, and workspace-serialized ORM/bulk mutation guards
remain until the outer transaction ends. API widget authorization is never cached.
Redis failure falls back for reads, while unfenced mutations fail before SQL.
Noeviction is required to retain guards; the deployment config was updated and
web joined the internal Redis network. A scoped, dry-run-default crash-guard
recovery command takes the same database lock. See [cache behavior](WIDGET_CACHE.md).
The web Docker build now copies shared config required by both legal and cache
modules; private env files are not copied by that change.

References actually read on25 October2026:

- Installed Next16.4.2 Proxy/runtime and CSP documentation: Proxy uses Node by
  default and cannot declare a runtime override. Public static-file handling
  preserves an explicit Cache-Control header and supplies ETags/conditional304.
- https://raw.githubusercontent.com/redis/node-redis/master/README.md and
  `packages/client/lib/client/{index.ts,socket.ts,commands-queue.ts}` in that
  official repository: bounded connect/socket/command timeouts, offline queue
  rejection, error listeners, EVAL and current command options. Installed/pinned
  official `@redis/client`6.3.0 types/source were checked against that interface.
- https://raw.githubusercontent.com/redis/docs/main/content/develop/programmability/eval-intro.md
  for atomic Lua execution; https://raw.githubusercontent.com/redis/redis/7.4/redis.conf
  for noeviction behavior; official redis-doc `commands/hset.md` for hash fields.
- https://raw.githubusercontent.com/sqlalchemy/sqlalchemy/main/doc/build/orm/session_events.rst
  and installed SessionEvents source for before_flush, bulk do_orm_execute and
  outermost after_transaction_end (including rollback/close and savepoints).

## Revised checkpoint step 2 — 25 October 2026

The local default deliberately skips `sandbox` integrations. `--run-sandbox`
opts into the real Docker boundary and fails if it cannot start. CI refuses to
run without that flag; the new backend workflow installs Chromium and Poppler,
requires Docker, starts Redis and runs the complete suite. This supersedes the
earlier instruction that every local pytest invocation must start Docker. Runtime
parsing, rendering, audio and PDF processing still have no in-process fallback.
Dictation's authorization/size tests now run separately from actual audio decoding.
Readiness aggregation uses an explicit health-only fake in its unit tests, while
the actual broker readiness check remains mandatory in the integration run.

Selection tests launch separate pytest processes with a failing Docker shim to
prove the local skip, CI rejection and explicit-opt-in failure contracts. A full
integration run also exposed a timing-sensitive renderer concurrency assertion:
it relied on overlapping two 30ms delays. The test now waits for an actual second
renderer before continuing, retaining its concurrency requirement on busy hosts.

Official maintainer references actually read on 25 October 2026:

- https://raw.githubusercontent.com/pytest-dev/pytest/main/doc/en/example/markers.rst
  and https://raw.githubusercontent.com/pytest-dev/pytest/main/doc/en/reference/reference.rst
  for custom markers, option registration and collection selection.
- Current READMEs at https://raw.githubusercontent.com/actions/checkout/main/README.md,
  https://raw.githubusercontent.com/actions/setup-python/main/README.md and
  https://raw.githubusercontent.com/astral-sh/setup-uv/main/README.md. Workflow
  action versions are pinned to commit IDs verified against official repository
  tags with `git ls-remote`; the GitHub REST API returned403 and was not read.
  The workflow has no optional or continue-on-error sandbox step. Hosted CI is
  not claimed as run merely because its configuration was written.





## Revised checkpoint step 1 — 25 October 2026

Billing requires a declared model identity. Tests now supply the same profile
contract as production. Turn rejects absent, null, empty, whitespace-only and
non-string model IDs with clear HTTP409 before provider client creation, in both
production and tests. Inventing a fallback would hide misconfiguration and lose
trustworthy per-model cost accounting, so it is deliberately not supported.
Eleven profile-contract cases cover this behavior. The six reported scheduling
cases already had corrected fake profiles from C5; the new full run verifies them
along with actual isolated dictation and document processing. Dictation now
asserts HTTP success before reading text, preserving a useful error diagnosis.
No provider transport or model availability/pricing claim changed.

The user prioritised fast tests, public cache behavior, economics/free-tier abuse
control and voice instrumentation before remaining compliance/reliability work.
Phase3 item2 was paused and preserved as stash35e5fbb9423f51261254344dbd24520e2775ada9
and local ref `refs/codex/paused-data-rights`; no private config or user changes
were discarded. It remains unfinished, with known failures documented in AGENT.

## Phase 3 item 1 — 25 October 2026

Five public legal documents share `config/legal.json`: Terms, Privacy, Cookies,
Acceptable Use and DPA. Every section is explicitly DRAFT for lawyer review;
no approved contract, executed DPA or jurisdictional certification is claimed.
Changing status to APPROVED while leaving DRAFT text is rejected. Counsel must
supply the final entity, jurisdictions, lawful bases, subprocessors, retention
exceptions, statutory rights and contractual commitments. This input does not
block implementation or fake-provider acceptance.

Password signup requires explicit acceptance of the current Terms and Privacy
notice. Immutable policy snapshots and acceptance records retain content hash,
version, status, server timestamp, source and keyed peer-IP hash, never raw IP.
An existing-account signup cannot create or update that user's legal evidence.
Public historical snapshots remain readable by content hash; authenticated users
can inspect their own evidence without receiving the IP hash.

New Google accounts have the same acceptance requirement. An Origin-checked
anonymous POST records a short-lived signed HttpOnly signup intent; OAuth start
copies it into encrypted, expiring state and clears the intent cookie. The
callback requires matching current policy before creating a new account. Existing
identity sign-in and explicit identity/calendar linking retain their checks.
Provider consent is not represented as acceptance of the application's terms.
OAuth parameters, PKCE, nonce, token verification and scopes were not broadened.

Native browser testing caught streamed unknown legal pages returning200. The
closed route set is now checked in Proxy before streaming, returning a real404
with the same security headers. Signup's required checkbox starts unchecked and
both password and Google registration require it. QA account helpers explicitly
fetch and accept the current policy, keeping tests consistent with the public
contract rather than bypassing it.

Official references read on 25 October 2026:

- Installed Next16.4.2 dynamic segments, metadata, CSP and notFound guides:
  https://nextjs.org/docs/app/api-reference/file-conventions/dynamic-routes,
  https://nextjs.org/docs/app/api-reference/functions/generate-metadata,
  https://nextjs.org/docs/app/guides/content-security-policy,
  https://nextjs.org/docs/app/api-reference/functions/not-found — awaited params,
  nonce rendering and request-time checks before a response starts streaming.
- https://raw.githubusercontent.com/googleapis/google-auth-library-python/main/docs/user-guide.rst
  — current official user-credential guidance delegates interactive OAuth to
  google-auth-oauthlib; provider credentials and application acceptance differ.
- https://pypi.org/pypi/google-auth-oauthlib/json — current1.5.0 metadata revealed
  the maintainer source moved to google-cloud-python. The published wheel's
  SHA256 was verified before reading its Flow source; no package was installed.
- https://raw.githubusercontent.com/googleapis/google-cloud-python/main/packages/google-auth-oauthlib/google_auth_oauthlib/flow.py
  — current official state binding, verifier/S256 challenge and authorization
  flow source read HTTP200. Existing provider transport remains unchanged.

https://developers.google.com/identity/openid-connect/openid-connect and
https://accounts.google.com/.well-known/openid-configuration returned URLError;
they were not read. Old standalone oauthlib repository paths returned404. These
failures do not prevent the fully tested local acceptance guard. Real Google
provider acceptance still needs GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET; this item
used fake verified claims while preserving all existing signature/nonce tests.

Verification:32 focused legal/auth/operator tests passed13.16s; frontend
typecheck/build and native Chromium five-page/signup/404 acceptance passed with
zero page errors. Disposable PostgreSQL verified immutable legal evidence along
with financial concurrency regressions. Full Phase3 suite follows items2–4.
The remote main independently merged PR#1 as04246a8 during this work; it was
preserved. Changes continue only on audit.

## Phase 2 item 5 — 25 October 2026

Operator billing requires a browser session, CSRF on mutations, explicit
`BILLING_OPERATOR_EMAILS` allowlisting and an actually verified email even in
development. The default allowlist is empty. API keys cannot use these routes,
including when a browser cookie is also present. Global workspace search/cursor
pages and global top consumers use grouped queries without conversation data.

The DRAFT contribution view uses net captured subscription fees plus settled
live wallet calls, minus configured provider cost estimates and reported payment
fees. Top-up funding is a liability and never revenue. Synthetic debits and
non-INR wallet entries are excluded; no FX conversion is invented. Missing final
provider usage, missing payment fees and outstanding cost holds are explicit.
Holds of any age remain visible outside the report window. This is a cash-based
operating contribution estimate, not statutory revenue recognition, actual
vendor invoice reconciliation or a certified profit statement.

A workspace kill switch and optional monthly cap are audited with a reason.
Admission stops immediately; the media safety watcher closes active sessions
within its existing one-second database check. Resuming cannot clear billing
adjustments, disputes, unknown holds or refund review. General job retry/cancel
routes now also enforce browser billing access for financial jobs, closing an
indirect knowledge-key mutation path. Reviewed retries preserve original receipt
IDs, dispatch intent and provider idempotency, so ambiguous writes still reconcile.

Reviewed subscription/spent-credit refund exceptions additionally require
`BILLING_OPERATOR_REFUNDS_ENABLED`, false by default. Existing refund/signature/
amount/dispute guards and original provider identity remain enforced. Subscription
refund review queues cancellation of future billing and pauses new usage. After
provider cancellation and refund settlement, the operator can end refunded
coverage and move the workspace to Free. Replayed captured/refunded payments and
late active state cannot restore coverage or remove the review. This conservative
policy is DRAFT pending commercial/legal approval. No direct wallet balance edits
or automatic forgiveness are provided. Non-INR wallets cannot enter newly priced
INR wallet calls.

The existing official Razorpay cancellation, subscription state and idempotent
refund references read for item4 apply to these adapters; no new provider
transport contract was introduced. Terminal cancelled subscriptions cannot be
reactivated, matching the current cancellation reference. Existing Next installed
server/client/CSP documentation was reused for the restricted UI. Acceptance uses
fake providers, temporary approval config and disposable local databases only.

## Phase 2 item 4 — 25 October 2026

Razorpay receipts are encrypted and durably acknowledged before reconciliation.
Raw-body HMAC, event IDs, hash-conflict detection, expiring previous webhook
secrets, conditional lease fencing and immutable financial facts handle retries,
out-of-order capture/failure/refund/dispute delivery and worker takeover. Refund
and dispute overlap cannot reverse the same customer credit twice. Uncertain
writes retain their money holds. Wallets stay nonnegative; spent reversals create
an explicit adjustment that blocks new spending without taking funds reserved
for existing calls. Wallet funding is a liability, not subscription revenue.

Subscription creation persists a receipt before dispatch. An ambiguous creation
uses read-only metadata reconciliation and never blindly repeats the POST.
Checkout signatures bind payment ID to the server-stored subscription ID; GET
verification and signed captured fees grant coverage. Authorization holds grant
neither credit nor coverage. Old payments cannot buy later periods. Cancellation
retains paid coverage, failed renewal blocks new spending during configurable
DRAFT seven-day export/read grace, and expiry downgrades to Free without quietly
rolling the paid period forward. DRAFT policy permits a new subscription after
prior paid coverage ends; prorated plan changes are not offered. Unknown
cancellations reconcile with GET, including after dead-letter recovery.

Plans and merchant legal name/address/GST registration/SAC/rates/refund/dunning
rules remain DRAFT in configuration. New checkout requires the paid flag plus
approved catalog and business details; fulfillment of previously authorized
money remains enabled when checkout is disabled. The signed, expiring tax review
pins buyer/seller/prices; changed details require another review. GSTIN validation
is local syntax/checksum/state validation, not government registry verification.
Only INR checkout is implemented. Lawyer/accountant approval and actual merchant
credentials are required for live acceptance, not for building or testing it.

Immutable financial-year invoice snapshots include GSTIN, SAC, place of supply,
CGST/SGST or IGST, original invoice references and balanced minor-unit rounding.
DRAFT documents use a separate DRF sequence and cannot consume live numbering.
PDFs render with local multilingual fonts in the existing networkless,
credentialless sandbox; private scoped downloads and encrypted email outbox
attachments deliver them. The billing feature UI supports reviewed checkout,
subscriptions, cancellation/reconciliation, usage, refunds and invoice downloads.
The Razorpay script is loaded only for checkout; strict dashboard CSP permits
its exact documented origins. Widget policy was not broadened.

Official references read on 25 October 2026:

- https://razorpay.com/docs/llms.txt (current index), and canonical base
  https://razorpay.com/docs/build/llm-docs/ with these paths:
  `webhooks/validate-test.md`, `webhooks/best-practices.md`,
  `webhooks/payments.md`, `webhooks/refunds.md`, `webhooks/disputes.md`,
  `webhooks/subscriptions.md`: raw-body signatures, five-second acknowledgement,
  duplicate IDs/out-of-order delivery, retry secret handling and entity states.
- https://razorpay.com/docs/build/llm-docs/api/refunds/create-normal.md and
  https://razorpay.com/docs/build/llm-docs/api/refunds/normal-refunds-idempotent.md:
  X-Refund-Idempotency, identical-body retries, receipt and pending/processed states.
- https://razorpay.com/docs/build/llm-docs/api/refunds/fetch-with-id.md:
  authoritative refund identity, payment, amount and status reconciliation.
- https://razorpay.com/docs/build/llm-docs/api/payments/subscriptions/create-plan.md,
  https://razorpay.com/docs/build/llm-docs/api/payments/subscriptions/create-subscription.md,
  https://razorpay.com/docs/build/llm-docs/api/payments/subscriptions/cancel-subscription.md,
  https://razorpay.com/docs/build/llm-docs/api/payments/subscriptions/fetch-all-plans.md,
  https://razorpay.com/docs/build/llm-docs/api/payments/subscriptions/fetch-subscriptions.md:
  monthly amount/currency, quantity/count, notes, cancellation and bounded pagination.
- https://razorpay.com/docs/build/llm-docs/payments/subscriptions/integration-guide.md
  and https://razorpay.com/docs/build/llm-docs/payments/payment-gateway/web-integration/standard/integration-steps.md:
  Checkout URL/options and mandatory server-side signature verification.
- https://razorpay.com/docs/build/llm-docs/payments/subscriptions/update.md and
  https://razorpay.com/docs/build/llm-docs/payments/payment-gateway/web-integration/standard/troubleshooting-faqs.md:
  plan-change limits reviewed; no provider proration API or CSP exceptions inferred.
- Installed official Playwright Python generated API/source for `page.pdf`,
  `set_content`, JavaScript disable and browser context controls:
  https://github.com/microsoft/playwright-python/blob/main/playwright/async_api/_generated.py.
  Rendered playwright.dev API returned URLError and was not read.
- Installed CPython 3.12 `email/message.py` for `add_attachment` multipart/MIME
  handling: https://github.com/python/cpython/blob/3.12/Lib/email/message.py.
- Installed Next 16.4.2 server/client and CSP guides (URLs in earlier decisions)
  reviewed for feature boundaries and the existing nonce policy.

CBIC https://cbic-gst.gov.in/CGST-rules.html and the actual Checkout JS download
returned URLError. No government tax-compliance certification, live SDK charge,
SMTP delivery or real Razorpay transaction is claimed. Current official payment
integration documentation was reachable. Legal/SAC/pricing values stay DRAFT.

Verification includes actual isolated PDF generation and multilingual text,
MIME attachment creation, native Chromium fake-gateway checkout/download with
zero page errors, and disposable PostgreSQL lease-takeover rollback, four
competing capture receipts producing one credit, and twelve unique concurrent
invoice numbers. Exact final test results are maintained in VERIFICATION.md.


## Phase 2 item 3 — 25 October 2026

New call creators no longer write live-unpriced-testing, capped-beta-widget or
development-browser-free. Admission snapshots nonzero plan retail/provider and
model rates, mode, transport and trial status. Price changes never rewrite old
calls. DRAFT Free/Starter/Growth include admitted minutes without another wallet
debit; DRAFT Custom exercises configurable metered-wallet pricing. Wallet mode
requires approved prices and the disabled-by-default paid flag; affordable
seconds are reserved before connection. Included outbound calls retain their
existing budget liquidity hold. Synthetic PSTN credit remains DRAFT600paise/min
from configuration; browser simulation is explicit development. These are
unapproved commercial policies, not a launch offer.

Per-model provider estimates are configuration, with DRAFT base/relative values,
not an assertion of vendor prices or model availability. A production model
without configured rates fails before I/O. Cost lines retain model identity;
call tariffs pin the full model map. Historical schema1 calls keep admitted
legacy terms and reservations, including zero rates; upgrade cannot add a new
charge. The nullable cost-model migration is additive and checked at startup.
Read-only tariff quotes do not create subscriptions. BILLING.md documents policy.

Verification:105 tariff/meter/admission/phone/carrier/runtime/business regressions
passed58.81s;10 final tariff/legacy cases passed6.71s. Disposable PostgreSQL
verified missing-model-column rejection, additive repair,24 concurrent admission
and immutable history. Pricing changes added no provider transport behavior;
prior official OpenAI usage/Fish pricing references remain applicable. No real
payment, private config or supplied database was changed.


## Phase 2 item 2 — 25 October 2026

Admission serializes on the workspace before quota/cost reservation. Model input
uses a conservative UTF-8 byte bound plus8192 protocol tokens; output is capped
at1200 by default. No omitted token cap is permitted for metered models. Audio
is bounded before Deepgram; each Fish text chunk reserves before forwarding.
Unknown outcomes retain their hold; provider overruns record full measured cost
and pause the workspace. Plan/window and installation caps include outstanding
holds. Replays do not add quota or money. Alerts at80/100 use the account outbox
and survive denial without committing unrelated work.

Storage writes commit exact-byte reservations before object I/O; abandoned
objects remain counted. Local/Azure inventory adapters and a bounded dry-run/
apply CLI backfill legacy/orphan objects without deleting or inferring absence.
Production legacy storage fails closed until inventory completion; fresh
workspaces start empty/complete. Development allowance multiplier1000 is explicit
and ignored in production; it never zeroes real provider cost. Failed/unknown
crawl attempts conservatively retain their page slot until the period ends.

Carrier dispatch supplies a provider time_limit; answer replays share a fixed
first deadline. Plivo emits scheduled Hangup before Stream. Twilio inbound
requires an accepted time_limit update before serving its stream. Rendered
Plivo Hangup documentation was unreachable (URLError); current official SDK
source was readable HTTP200. Live acceptance requires configured carrier
credentials and public signed-callback/media URLs; no real call was placed.
Official references actually read25October2026:
- https://raw.githubusercontent.com/plivo/plivo-python/master/plivo/resources/calls.py
- https://raw.githubusercontent.com/plivo/plivo-python/master/plivo/xml/hangupElement.py
- https://raw.githubusercontent.com/twilio/twilio-python/main/twilio/rest/api/v2010/account/call/__init__.py
- Installed azure-storage-blob official ContainerClient.list_blobs docstring/source:
  lazy continuation tokens, prefix filtering, property sizes, results_per_page;
  https://github.com/Azure/azure-sdk-for-python/blob/main/sdk/storage/azure-storage-blob/azure/storage/blob/_container_client.py

Disposable PostgreSQL admitted10/rejected14 of24 concurrent requests at an exact
10-reservation budget and rejected financial-history deletion. Backend focused
runs97 and58 cases passed, plus38 final carrier/admission cases. One broad-run
responsiveness check included unrelated dispatcher startup; its clock now begins
when the injected blocking query enters, preserving its0.5s responsiveness bound.
The corrected focused run16passed9.73s. No live remote inventory/provider charge.


## Phase 2 item 1 — 25 October 2026

Configuration is validated and content-addressed; subscriptions pin catalogs and
operation/call tariffs pin the applicable rates. Money uses integer micro-paise
for costs and paise for retail values. All checked-in numbers are DRAFT, including
conservative Fish list-price/FX estimates. Paid checkout requires both explicit
PAID_ACTIVATION_ENABLED and APPROVED catalog status. Webhook processing is not
disabled by that checkout guard, preserving earlier payment reconciliation.

Immutable usage records reflect actual turns, conversations, connected duration,
crawled pages and known stored byte sizes. Object deletion releases current
storage without changing history. Real provider calls in development still
produce nonzero cost estimates; explicitly synthetic providers may cost zero.
OpenAI final usage includes cached input tokens; missing final usage is marked
unreported. No token estimate is substituted. Fish costs use UTF-8 input bytes,
not characters or generated audio duration. Audio duration remains separately
measured for operations. Existing agent deletion retains anonymized financial
records when cost lines exist.

Official sources read: https://docs.fish.audio/developer-guide/models-pricing/pricing-and-rate-limits.md (current pricing
reference), https://developers.openai.com/api/docs/guides/streaming-responses
and the official openai-python chat_completion.py / create_embedding_response.py
types. Fish pricing and OpenAI streaming references returned readable HTTP200.
Interrupted Chat streams may never report the final include_usage chunk.

Verification:91 related platform/provider/website/deletion cases passed,54 beta/
number/widget cases passed; final metering/business run35 passed in13.17s.
Frontend typecheck and production build passed. No live provider was charged;
no private configuration or supplied database was changed. Admission limits,
real retail tariff activation and extended billing remain the next separate items.


## Phase 1 item 5 — 25 October 2026

Ciphertext now carries an authenticated version/key ID, with unchanged legacy
APP_SECRET-derived reads. Default app-v1 retains the same material; no silent
key generation/retirement or private configuration change occurs. Rotation uses
a new logical ID/material, authenticated original timestamps, bounded leased
checkpoints and an append-only audit. Damaged/missing-key records block without
being skipped or revealing plaintext. Active-ID changes block the old job.
Only ciphertext in immutable HTTP tool versions can change under a current
scoped rotation lease; all metadata and deletion guards remain in place.

Local private keyring and Azure Key Vault implement the same provider protocol.
Vault IDs are pinned immutable secret versions, never latest; bounded key cache,
native identity and explicit failure handling. Active material is warmed before
API/worker readiness. The global operator allowlist is empty by default and is
separate from workspace/API-key permissions. ENCRYPTION.md has the tested CLI,
safe cutover order and key-retention/restore requirements. All encrypted columns
plus webhook signing secrets are covered; global outbox/OAuth data only in global
jobs. No live key or real database was rotated.

Official sources read25October2026:
- https://raw.githubusercontent.com/pyca/cryptography/main/docs/fernet.rst —
  authenticated encryption,32-byte key format, rotation, timestamp and retention
  semantics. New envelope binds its ID inside authenticated plaintext.
- https://raw.githubusercontent.com/Azure/azure-sdk-for-python/main/sdk/keyvault/azure-keyvault-secrets/README.md
  and https://raw.githubusercontent.com/Azure/azure-sdk-for-python/main/sdk/keyvault/azure-keyvault-secrets/azure/keyvault/secrets/_client.py
  — native identity, secrets/get and explicit version retrieval. Locked
  azure-keyvault-secrets4.11.3 added; frozen dependency sync passed. Fake Vault
  tests exercise pinning/cache/failure. Live acceptance requires a configured
  vault URL, immutable key version and authorized native identity, not more code.

Validation:14 encryption cases passed, including the actual CLI and dedicated
dispatcher;20 key/deletion regressions passed before two extra maintenance cases.
Disposable PostgreSQL verified backward reads, concurrent migration checkpoints,
restricted no-CREATE role, immutable metadata/audit and lease fencing. Full Phase1
testing found the new widget foreign keys missing from agent deletion; cleanup
now removes scoped quotas, proposals, OTP/consent/outbox data before parent rows,
with an expanded end-to-end regression. Private config/Supabase remain untouched.

## Phase 1 item 3 — 25 October 2026

Production always requires Turnstile; its opt-in setting is for development/test.
No fake provider or bypass endpoint exists in the product. Siteverify sends
secret/response/remoteip/idempotency_key over verified HTTPS with a5s timeout,
accepts only boolean success, exact hostname/action and a token timestamp within
300s (10s clock skew). Missing keys, network failure, malformed/replayed/expired
tokens fail closed. Origin/key/agent state is rechecked after provider I/O. A
server-owned proof marker prevents legacy sessions bypassing a newly enabled
challenge on chat/resume/voice/email. Trusted peer IP is used, never arbitrary XFF.

Independent installation and global hashed-IP counters use UTC days. Owner
quotas may tighten platform IP ceilings. Installation row locks and conditional
IP updates make admission atomic; operation identities make replay free.
Monthly UTC reservations stop requests before provider work and queue owner
80%/100% alerts. Denials commit only alert/admission bookkeeping before raising,
so rollback cannot discard the alert; this occurs before message/call creation.
Default sessions100/day, requests500/day, IP sessions20/day, IP requests100/day,
monthly cap INR100, chat/dictation reserve INR1 and voice reserve INR10 are
**DRAFT safeguards**, not commercial prices or measured costs. Phase2 will bind
admission to configured immutable tariff snapshots. Voice is bounded to60s by
default (owner10–300s), enforced by the media deadline.

Dictation is decoded in the credential-free sandbox and only its canonical
mono16kHz WAV is sent to Deepgram. A5MB compressed upload cannot conceal an
unbounded provider request: decoded audio is capped at30s with process/resource
limits. Invalid/long media is rejected before transcription. The documented WAV
REST path/model/language remain the same; raw user media is never forwarded.

Email collection is off by default. Shared addresses remain visibly unverified;
unverified marketing choices are ignored and not stored. Codes are six random
digits, HMAC-bound to challenge/email, expire10min, allow five attempts, are
invalidated on resend and sent only in encrypted outbox payloads. Codes never
enter chat/model context or HTTP responses. Proof and consent are scoped to the
current conversation/origin/key, serialized and replay-safe. Consent has version/
time/origin/IP evidence only after proof. Marketing consent is disabled by
default (WIDGET_MARKETING_CONSENT_ENABLED=false); wording/version are DRAFT pending
legal review. Fake delivery/provider tests cover the complete enabled path.
Existing unverified lead metadata cannot establish consent.

Official references read25October2026:
- https://developers.cloudflare.com/turnstile/get-started/server-side-validation/
  — rechecked HTTP200: POST contract,2048character tokens,300s validity, single use,
  remoteip and UUID idempotency keys; hostname/action checks retained.
- https://raw.githubusercontent.com/cloudflare/cloudflare-docs/production/src/content/docs/turnstile/get-started/client-side-rendering/index.mdx
  — exact api.js URL, explicit render/ready/remove callbacks. Rendered client
  page403; no proxy/cache of provider script. React and standalone use a shared
  helper; CSP retains strict executable-script policy.
- https://raw.githubusercontent.com/deepgram/deepgram-python-sdk/main/README.md
  and https://raw.githubusercontent.com/deepgram/deepgram-python-sdk/main/src/deepgram/listen/v1/media/client.py
  — prerecorded file/WAV contract; rendered prerecorded guide403.
- https://raw.githubusercontent.com/FFmpeg/FFmpeg/master/doc/ffmpeg.texi
  and https://raw.githubusercontent.com/FFmpeg/FFmpeg/master/doc/protocols.texi —
  pipe-only input, bounded duration/audio output and protocol whitelist options.
  Fixed argv/no shell, one decoder thread,10s timeout in the isolated service.

Validation:128 integration tests passed in94.39s; final46 focused passed in46.79s.
Typecheck/build passed. Chromium uses fake Turnstile only in the separate QA
process against real routes/SQLite/outbox: challenge, optional email, OTP and
consent, owner cap UI and denial/alert behavior; zero page errors. The browser
found a nested form submitting the appearance dialog; protection now uses an
explicit button without nesting a form. Missing settings were inspected by
presence only: Turnstile keys and SMTP host/user/password are absent. Only live
acceptance/delivery awaits them; implementation/tests are complete. Private
configuration and the remote database were not changed.

## Phase 1 item 9 — 25 October 2026

Untrusted parsing/rendering is mandatory in a separate credential-free service,
never a low-UID process sharing the application's filesystem/network. The
application receives only a Unix socket, never Docker control. The service has
no network, credentials, application/data mounts or public ports. Each content
job gets a distinct UID/GID and clean environment. The broker needs only
SETUID/SETGID/CHOWN/KILL to launch jobs, remove files and terminate all processes
under that job's UID, including descendants that changed process groups. Children
have no capabilities, cannot access the broker socket and cannot read later job
directories. UIDs are not reused within a broker lifetime. Read-only filesystem,
256MB tmpfs,1GB memory/no swap,1.5CPU,192PIDs plus parser address-space and job
CPU/file/descriptor/time budgets bound failures. Exact limits: FILE_SAFETY.md.

PDFs use pypdf6.21.1's locked configuration plus per-page and total decoded-stream
budgets before extracting text. DOCX is bounded ZIP/XML extraction, avoiding
eager expansion by python-docx. Reject DTDs/entities, malformed packages, excess
members/ratio/expanded bytes and unsafe paths. OOXML has no reliable physical
pagination; the200-page budget uses declared pages, explicit breaks and a
conservative400-word/page estimate, with independent text/node/byte limits.
This is documented rather than claiming Word-equivalent layout pagination.

Browser GETs are fulfilled only through the parent pinning/robots/TLS policy.
Pending parent fetches are canceled on result/error/disconnect; browser processes
and job files are cleaned before the next job. Health has a separate lightweight
broker response so a busy renderer does not make readiness fail merely because
the job queue is occupied. Missing isolation fails readiness and rejects content.

Official references read25October2026:
- https://raw.githubusercontent.com/py-pdf/pypdf/main/pypdf/_configuration.py
  and https://raw.githubusercontent.com/py-pdf/pypdf/main/pypdf/filters.py —
  current stream/object/decoding limits; also inspected installed pinned APIs.
- https://raw.githubusercontent.com/py-pdf/pypdf/main/docs/user/extract-text.md —
  extraction can expand memory enormously; check decoded page content first.
- https://raw.githubusercontent.com/python-openxml/python-docx/master/src/docx/opc/phys_pkg.py
  — eager ZIP member reads motivate independent bounded extraction.
- https://raw.githubusercontent.com/python/cpython/3.12/Lib/zipfile/__init__.py —
  bounded stream reads, member metadata and CRC behavior.
- https://raw.githubusercontent.com/docker/docs/main/content/manuals/engine/network/drivers/none.md
  and https://raw.githubusercontent.com/docker/docs/main/content/manuals/engine/containers/resource_constraints.md
  — no-network driver and cgroup memory/CPU limits; rendered Docker pages403.
- https://raw.githubusercontent.com/docker/docs/main/content/manuals/engine/cli/proxy.md
  — build proxy arguments, not runtime ENV. Cloud build-only proxy DNS pinning
  and the configured CA bundle retain TLS/lockfile checks. No verification disabled.

Real container tests verify no app files/credentials/network/capabilities/broker
access, nonzero distinct job UIDs, actual cgroup limits, parsing, ZIP/PDF bombs,
rendering, cancellation and subsequent recovery. Existing renderer lifecycle,
platform ingestion, website assistants and HTTP hardening:59passed. Typecheck
and production frontend build passed. Local API readyz200 includes the isolation
service. Old images created during this task were removed after the VFS Docker
driver filled the workspace; PostgreSQL images and volumes were preserved.


## Phase 1 item 8 — 25 October 2026

The platform instruction channel is immutable. Owner guidance, visitor text,
retrieved pages, variables and endpoint results are structured untrusted data in
lower-priority messages. This reduces instruction confusion; it does not claim
that prompting alone prevents injection. Server authorization remains decisive.
Known provider credentials are stripped before context construction, tool
arguments and output, with a streaming suffix guard for fragmented keys.
Private endpoint data defaults to no public response fields; owners can allow
specific fields. PII redaction and an immediate intersection with current tool
policy prevent an older published revision from retaining revoked disclosure.

Each conversation/call has a durable atomic budget (default eight attempts).
Writes require a scoped encrypted proposal, full argument read-back, delivery
receipt and a later explicit visitor confirmation. Confirmations expire after
five minutes, bind exact arguments and attachment revision, and are idempotent.
An unrelated later Yes is insufficient. A claimed write with uncertain outcome
is never automatically re-executed. Existing scheduling read-back protocols are
retained. Only an explicitly approved GET/non-side-effecting tool can bypass
confirmation; metadata declaring a write harmless cannot authorize it.

Handoff classification has a closed boolean schema and cannot act. Development
without a model uses a conservative request grammar. Both paths propose the
same confirmation protocol. Human-related descriptions and negations do not
create tickets. The dashboard exposes read-only policy/public field controls;
chat exposes a separate confirmation button, and voice uses a later spoken turn.

Official reference read on 25 October 2026:
https://developers.openai.com/api/docs/guides/agent-builder-safety.md — untrusted
data must not enter privileged instruction messages, structured boundaries,
tool approvals and leakage controls. This generic safety guidance is used for
the server trust boundary, not as a guarantee of model obedience. The official
developer domain is now reachable (200); older 403 notes are historical.

Production Chromium chat and WebSocket simulation passed with providers disabled:
unrelated human wording creates no ticket, each request first shows a read-back,
confirmation persists exactly one ticket, and zero browser page errors. A CSP
regression in multi-port local voice was found and fixed using the actual request
host and explicit API origins; executable script policy remains strict.


## Phase 1 item 7 — 25 October 2026

Domain ownership is a server requirement for each configured external origin,
including keyed widgets previously allowed on any origin. `null`, wildcard and
unlisted origins cannot be verified or used. The exact platform origin is a
trusted preview exception, and the localhost/127.0.0.1 alternate is local-dev
only. Saving crawled or preview knowledge does not prove site ownership or grant
foreign-origin sessions. Configuring an unverified origin keeps that origin
inactive while platform preview remains usable; authenticated metadata reports
unverified origins explicitly. The old optional restriction checkbox is removed.

Proofs use 256-bit random values, encrypted at rest, with a24h challenge and90day
verified lifetime. Three adapters use DNS TXT, root HTML meta, or the fixed
/.well-known/voice-studio-verification.txt file. Production requires HTTPS.
HTTP proof retains existing public-IP pinning/TLS, rejects cross-origin redirects
and limits body/time; DNS has a3s resolver lifetime. Challenges are per workspace
and exact normalized origin. Revocation rotates the challenge and immediately
closes sessions, resume, voice checks and subsequent iframe policies. It cannot
retract information previously served while a site was verified.

DNS/network I/O runs without retaining a writer lock. Because sessions use
expire_on_commit=False, the identity map is explicitly expired afterwards before
membership/role/challenge rechecks. Regression tests prove a revoked/demoted
operator and a replaced challenge cannot use cached authority across that wait.
Verification responses are not accepted merely for being truthy; only True grants
proof. Read sets are request-scoped and reused within workspace metadata batches.

Reference read on25October2026:
https://raw.githubusercontent.com/rthalley/dnspython/main/dns/resolver.py —
resolve(qname, rdtype, lifetime, search) contract. Added locked dnspython2.9.0
through uv with existing pins retained. Existing safe_fetch provides the pinned
HTTP/SSRF/redirect/TLS boundary; no verification bypass was introduced.

Validation:68 related backend cases passed, typecheck/build passed. Actual browser
scripts/verify_origin_ownership_browser.py creates a challenge, displays DNS proof,
checks it through the real authenticated endpoint with a fake provider only in
its separate QA process, observes public access/frame policy becoming valid,
revokes proof, and observes denial. No production fake-provider endpoint exists.
Zero browser page errors. Evidence artifacts/origin-ownership/browser.json.
Schema NOW2026-10-25-origin-ownership; private env and remote DB untouched.

## Phase 1 item 6 — 25 October 2026

Use a random nonce per response and Next16.4.2 proxy.ts to forward CSP/nonce to
the renderer. Root layout is dynamic and the theme bootstrap receives its nonce;
static HTML would reuse nonces and is deliberately not used. Production scripts
have no unsafe-inline/unsafe-eval. Inline style attributes remain allowed because
existing UI components depend on them. Dashboard framing is denied; widget
frames initially allow only the platform itself and will gain verified external
origins in item7. Policy lookup errors never grant an external frame ancestor.

API request bodies are bounded before parsing (1MB ordinary, 21MB multipart),
including undeclared/chunked bodies; total receive time is capped and compressed
request encodings are rejected. Exact webhook bytes are preserved. API docs and
OpenAPI require verified browser identity in production; developer API keys do
not grant personal browser access. Health reveals only status. Readiness fails
closed on missing production DB/Redis/Qdrant/worker; explicit disabled local
development services are reported as such. A leased worker writes a shared DB
heartbeat every5s; a stale/stopped worker fails readiness across containers.

Official references read on 25 October 2026:
- Installed Next16.4.2 docs: https://nextjs.org/docs/app/guides/content-security-policy
  and https://nextjs.org/docs/app/api-reference/file-conventions/proxy — nonce
  forwarding, dynamic rendering and the current proxy convention. No production
  eval allowance was added to accommodate test tooling.
- https://redis.io/docs/latest/commands/ping/ — PING/PONG readiness contract.
- https://raw.githubusercontent.com/qdrant/qdrant/master/src/actix/api/service_api.rs
  — /readyz returns200 when ready and503 otherwise. The rendered
  https://qdrant.tech/documentation/guides/monitoring/ returned403; authenticated
  header behavior already used by the repository is retained.

Validation: 48 related backend checks passed, one explicitly unrun optional
real-Redis case skipped; final HTTP/worker focused run19passed. Typecheck/build
passed. Actual production Chromium verifies changing nonces, functional dashboard
interaction, parser-injected inline script blocked, widget framing policy and
zero page errors. artifacts/http-security/browser.json records the result.
Live local /readyz passes with DB/worker and clearly disabled-development Redis/
Qdrant; production dependency checks use fake clients and fail closed. Schema
revision NOW2026-10-25-http-readiness adds worker_heartbeats; no remote migration.

## Continued launch implementation — 25 October 2026: Phase 1 item 4

The user accepted only items 1 and 2 and directed implementation of every
remaining item. Work and per-item commits are on `audit`; do not push `main`.
Unapproved business/legal/plan values must be DRAFT behind disabled activation
flags with fake providers in tests, rather than deferring implementation.

Registration now returns the same HTTP 202 notice without cookies or IDs for new
and existing addresses; it never silently authenticates or changes a password.
Both branches hash the submitted password, queue one encrypted email and use a
common 500ms floor plus 0–20ms jitter. Recovery uses the same work/floor on both
existence branches; unknown addresses queue a non-delivering record. Rate limits
still apply. This is equivalent work and a shared timing distribution, not a
claim that database/network scheduling can be perfectly constant-time.

Production always requires verified email for workspace creation/sensitive
mutations. Development/test bypass remains explicit; the pending initial
workspace is created after proof. Five owned workspaces is a configurable safe
default, serialized on the user row. Signup clients and QA scripts now perform
explicit sign-in; no test fabricates an authenticated signup response.

All SMTP is worker-only through the transactional encrypted email outbox. Claims
use row locks and lease tokens; retries back off, exhausted attempts become dead
letters, stale senders cannot finalize another lease. Stable Message-ID provides
recipient-side deduplication assistance; SMTP has at-least-once delivery when a
provider accepts a message before a connection/process loss. We do not claim
exactly-once SMTP delivery. Phone alerts mark queued separately from sent.
The acceptance run also found a recovery ordering race: expired running jobs now
precede queued siblings, preserving recovery/fencing of the existing owner.

References read on 25 October 2026:
- https://raw.githubusercontent.com/python/cpython/3.12/Lib/smtplib.py — current
  official 3.12 STARTTLS/SMTP_SSL and send_message interfaces. The rendered
  https://docs.python.org/3/library/smtplib.html returned HTTP 403; verified TLS
  contexts are retained and covered with a fake SMTP provider.
- https://developers.cloudflare.com/turnstile/get-started/server-side-validation/
  now returns readable official documentation: HTTPS POST siteverify; secret and
  response required, remoteip optional (we will supply it); 2048-character,
  five-minute, single-use tokens. Item 3 implementation follows items 4/6/7/8/9.
- https://docs.fish.audio/llms.txt is reachable and its canonical index was read;
  specific streaming contracts will be read before Phase 6 implementation.
- Installed Next 16.4.2 server/client-component guide was reread before the
  registration UI change; the CSP guide is being read for item 6.

Verification: 97 related backend cases passed; final outbox/worker focused run
18 passed, frontend typecheck/build passed, disposable PostgreSQL upgrade,
restricted-role and worker fencing acceptance passed. Full-suite validation is
required at the Phase 1 boundary. Schema revision `2026-10-25-account-outbox`
adds pending registration and email outbox tables. No private configuration or
remote database migration was performed.

## Public launch checkpoint — 24 October 2026

These decisions supersede older statements below where they conflict. Public
launch remains blocked; see LAUNCH_CHECKLIST.md. Private configuration was not
edited. The default remote database remains configured; its read-only check
reported an unavailable network/address route. Cloud local acceptance explicitly
uses isolated SQLite/local objects and disabled providers/SMTP/calls/payments.

- Shared rate windows use Redis server time and atomic Lua; fallback is bounded
  and thread-safe with a warning, not claimed to enforce cross-process quotas
  during outages. Default APP_SECRET must be stable across replicas.
- Only an explicitly trusted Caddy gateway may set client forwarding. Disable
  Uvicorn's independent proxy processing; never trust all proxy addresses. Beta
  Compose pins the gateway IPv4 on a dedicated edge network.
- Developer, team and billing mutations are browser-only, including for legacy
  privileged keys. Key policy defaults to 60 requests/minute and no expiry;
  callers may select expiry and a 1–600 per-minute limit. Existing credentials
  survive migration. Production migration and gateway deployment are unaccepted.
- Sign-in email admission counts every attempt (10/15min), avoiding an existence
  distinction in the limiter. This is not uniform signup/recovery timing, which
  remains work. No commercial prices, legal language or provider contracts were
  invented; paid launch remains gated on approved plans and preceding phases.

References actually read on 24 October 2026 (official maintainer sources used
because several rendered documentation sites returned HTTP 403):

- https://redis.io/docs/latest/develop/programmability/eval-intro/ — direct 403;
  read https://raw.githubusercontent.com/redis/docs/main/content/develop/programmability/eval-intro.md
  for Lua atomicity, server execution and cache/restart semantics.
- https://raw.githubusercontent.com/redis/redis-py/master/redis/commands/core.py
  and https://raw.githubusercontent.com/redis/redis-py/master/redis/client.py —
  EVAL argument/return and existing Redis client interface.
- https://raw.githubusercontent.com/redis/redis/7.4.8/README.md — local disposable
  Redis build guidance; TLS-enabled build, no verification disabled.
- https://www.uvicorn.org/settings/ — direct 403;
  read https://raw.githubusercontent.com/Kludex/uvicorn/main/docs/settings.md
  and https://raw.githubusercontent.com/Kludex/uvicorn/main/uvicorn/middleware/proxy_headers.py
  for disabling automatic proxy handling and explicit address/network trust.
- https://raw.githubusercontent.com/caddyserver/website/master/src/docs/markdown/caddyfile/directives/reverse_proxy.md
  — incoming X-Forwarded headers ignored by default; explicit upstream proxy/CDN
  trust must not be inferred from arbitrary headers.
- https://raw.githubusercontent.com/pydantic/pydantic/main/pydantic/types.py —
  AwareDatetime timezone requirement.
- https://raw.githubusercontent.com/sqlalchemy/sqlalchemy/main/doc/build/core/type_basics.rst
  — database-agnostic DateTime/Integer types; existing UTCDateTime wrapper retained.
- Installed Next 16.4.2 documentation
  `node_modules/next/dist/docs/01-app/01-getting-started/05-server-and-client-components.md`
  (https://nextjs.org/docs/app/getting-started/server-and-client-components), and
  `01-app/02-guides/content-security-policy.md`
  (https://nextjs.org/docs/app/guides/content-security-policy) — client interaction
  boundaries and CSP constraints reviewed before UI work. A strict nonce CSP is
  not implemented or claimed by this checkpoint.

Required provider references attempted but **not read** (HTTP 403 on each):
https://developers.cloudflare.com/turnstile/get-started/server-side-validation/,
https://docs.fish.audio/llms.txt,
https://developers.openai.com/api/docs/guides/reasoning,
https://developers.deepgram.com/docs/getting-started-with-live-streaming-audio.
No corresponding provider integration was changed. Draft documentation-domain
additions are saved for environment-settings review; saving does not apply them
to the running instance. Recheck after the network change before integration
work; then research the remaining Twilio/Plivo/Razorpay and specific model/Fish
streaming references required by the request. Do not treat remembered or prompt
assertions about model names, reasoning defaults, FlushEvent or session reuse
as verified provider behavior.

Current user choices override the earlier reconstruction kit.

- Public entry delivers source-backed value before account creation. The measured first answer was 6.91s; no voice/model provider is needed for this one-page extractive preview. Saving claims its actual sources into the new workspace.
- Preserve gpt-5.6-luna as default while allowing documented/tested OpenAI-compatible profiles. API-specific caps and reasoning settings replace model-family guesses. Temperature is omitted by default.
- Fish direct MessagePack TTS with owned cancellation; Deepgram recognition; separate browser/Plivo/Twilio media contracts. Fish Agents screenshots inform capabilities, not a dependency on Fish's hosted agent product.
- PostgreSQL transactions/metadata in Supabase; Azure private object storage; Qdrant + text-embedding-3-small for vectors. Local objects/lexical retrieval are explicit development modes.
- Opaque server sessions/Argon2 with CSRF/roles/scoped keys, password reset and identity-bound invitations. Social OAuth remains deferred.
- Custom HTTP tools are declarative data. Parse cURL without a shell, pin published revisions, encrypt headers, validate schemas and public destination sockets, and record durable execution outcomes. Unknown side effects are never automatically replayed.
- Durable database jobs with one dispatcher instead of Temporal. Campaigns now support bounded concurrency/retry/windows; only busy/no-answer outcomes automatically retry.
- Remote connector/payment status follows provider evidence. Local bookings, queued jobs, accepted SMS and synthetic credits never imply remote completion or purchased balance.
- Keep Next and Python control/media as separate processes. Sites' Worker runtime cannot host this long-lived Python media backend. No public deployment has been performed.
- Startup additive DDL is a development checkpoint; reviewed migrations, least privilege, RLS and multi-process recovery are production work.

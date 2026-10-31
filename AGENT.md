# Prepared shareable distribution on OpenPhirmy branch — 31 October 2026

User requested cleaning the OpenPhirmy branch for public/hackathon download by removing
all publishing and deployment artifacts: private .env, deployment scripts/manifests (deploy/,
compose.yaml), server Nginx configs (MainPage/deploy/, MainPage/nginx.conf, deploy/nginx-platform*.conf),
and GitHub Actions deployment workflows (.github/workflows/). The branch now represents a clean,
credential-free, shareable application codebase with complete local development instructions (.env.example).

# Full-project code review, UI audit, and Phase 1-4 bug fixes — 30 October 2026

User requested full project exploration, bug check, UI check, images/JSONs inspection,
and fixing all identified bugs from Phases 1 to 4 following the code-review and autofix skills.
CodeRabbit PR review threads: no open PRs on GitHub (PRs #1 and #2 merged); coderabbit CLI
not present on host. Conducted full static, dynamic, contract, and test review.

Phase 1 (Crash prevention & defensive access): Guarded against null/undefined `user.name` in
`overview.tsx` and `studio.tsx`; added safe `URL` parser in `first-minute.tsx`; guarded
optional durations in `call-latency.tsx`; guarded optional relations and tools in `tool-studio.tsx`,
`website-assistants.tsx`, `model-studio.tsx`, and `workspace-pages.tsx`; added `index` fallback
for table row keys in `ui.tsx`; added `onError` handler for launcher logo in `widget-customizer.tsx`.

Phase 2 (Accessibility & test portability): Fixed WCAG 2.1 AA color contrast violation in
`MainPage/src/editorial.css` (.mega-links small #68716a -> #4b5a4e, 7.1:1 contrast); updated
`MainPage/playwright.config.ts` and `scripts/verify_legal_browser.py` to auto-detect installed
Chromium instead of failing on hardcoded `/usr/bin/chromium`. All 25 MainPage browser tests PASS.

Phase 3 (Branding, assets & caching): Updated visible customer/developer branding to Phirmy
in `account-action.tsx`, `verify-email.tsx`, `docs/page.tsx`, `legal/[document]/page.tsx`,
`widget.js`, `agent-journey.tsx`, and backend transactional emails (`config.py`, `auth_routes.py`,
`identity_routes.py`, `account_routes.py`, `invoices.py`, `test_business_platform.py`). Copied
Phirmy brand images to `apps/web/public/brand/` and linked icon in `layout.tsx`. Removed hardcoded
third-party URL `palsona.in` in `workspace-pages.tsx`. Added `Cache-Control` header to public
widget logo endpoint `chat_routes.py`.

Phase 4 (Commercial & config alignment): Re-aligned `starter` and `growth` plan allowances in
`config/plans.json` so paid subscriptions never downgrade limits compared to the beta Free tier.
Removed unused imports in `overview.tsx`, `studio.tsx`, `auth_routes.py`, and `identity_routes.py`.

Verification: Next.js typecheck + production build PASS; MainPage build + 25 Playwright tests PASS (22.2s);
backend 44 beta smoke tests PASS (33.77s); 39 public contact and widget branding tests PASS; 23 business
platform tests PASS; 16 plan/allowance tests PASS; database schema readiness check PASS.
Preserved tracked private .env; no secrets printed.

# Formatted voice replies and automatic spoken language — 30 October 2026

User reported plain replies synthesize but Markdown catalog replies fail, then
requested Auto under Agents > Spoken language. Read-only failed-call inspection
confirmed generated text with synthesis failing before audio, without printing
customer text or provider errors. Bounded synthetic live probe confirmed a
markup-only input is rejected. Added speech_text.py: bounded streaming Markdown /
link / HTML presentation cleanup, skips symbol-only chunks, keeps native scripts,
product facts, prices and decimals. Normalize BEFORE speech budget accounting;
transcripts retain the original model text. Voice-only instructions ask for
concise plain speech and exact facts; text chat is unchanged. Existing audio
pacer, interruption, tool confirmation and budget guards remain intact.

Added Auto to editor and agent contract. Sarvam ASR's detected language reaches
the session; supported ASR code or native script resolves a concrete TTS language
(English fallback). The reply model receives the selected spoken language. TTS
reconnects only when language changes; never sends literal auto. Existing explicit
English etc. stays selected; user can choose Auto, save and publish. Typed
romanised text without ASR language falls back to English; persona language
support still applies. No DB migration or private configuration change.

Focused voice tests: other streaming/greeting/LLM modules passed in the prior
combined run; repaired only assertions that assumed original chunk boundaries
while retaining exact disclosure/PCM and pacing requirements. Sarvam module
22 passed in 30.78s after repairs. Frontend typecheck + production build passed;
isolated desktop/mobile browser checks saved Auto, preserved GPT and had zero JS
errors. Synthetic formatted list through real Sarvam returned 384960 PCM bytes,
13 audio chunks, 73 submitted characters, markup removed and prices preserved.
No user turn replay, crawl retries, full suite or allowance changes. Targeted
recognition-language and markup assertions: 2 passed in 1.28s. GitHub deployment
40936169553 SUCCESS: 44 quick beta checks passed in 41.72s; release 27f607a is
live. API /readyz 200 with all five checks OK, app /signin 200 and all Phirmy
containers healthy. Physical phone microphone acceptance remains with the user;
refresh, choose Auto, save/publish and start a NEW voice session.

# Voice Lab playout overflow fix — 30 October 2026

User mobile screenshot:reply text succeeds then Playout buffer exceeded its limit
at4s. Root:media.respond initialized next_send before firstTTS byte; delayed
synthesis or midstream gaps became a catch-up burst, tripping1sVoiceLab/1.5sWidget
guards. Added AudioPacer rebasing on actual availability/latewakeups,160msahead,
20ms and finalpartial frames paced BEFORE send. Keeps everyPCMbyte, guardlimits,
interruption/cancellation, transcript and accounting paths. Shared media engine
also covers widgets/carriers/cached greetings. VoiceLab now unlocksAudioContext
atStartclick beforeawaitmicpermission (MDNautoplayguidance), usesexistingmicerror
helpers and validatesPCMwireformat. Friendlyoverflowerror; trueoverflow stillends.
Read apps/web/AGENTS.md and installedNextuse-clientguide; webapp-testing applied.
Focused31existing/newpacing checks PASS47.93s; added actualdelayed2sPCM WebSocket
regression,3pacingchecks PASS5.03s. VoiceConnection transcript/miccleanup JSchecks
PASS; frontendtypecheck+productionbuild PASS. No full suite. CIquickbeta now40
expected through3newSarvam tests, no broadergate. New isolatedbrowser verifier
scripts/verify_voice_playout.py --serve usesclearedproviders/disposableSQLite,
actualVoiceLab/WebAudio and realAudioPacer. Legacytiming reproducedoverflowafter
50frames/~1.014squeue. Fixeddesktop/mobileeachplays151frameswithmaxqueue224/209ms,
includingfirstbyte1.25s andmidstream2.2spauses;zeroJSerrors/provider/production
requests. Evidenceignoredartifacts/playout. Mobileviewport isnotphysicalphone
mic/echoacceptance. DocsSARVAM_VOICE updated. GitHub40933074426 SUCCESS:40focused
beta checks and deploy, release1d8200d live. Publicapi/readyz200/all5checksok and
app/signin200. User should refreshVoiceLab and startaNEW microphone test onphone;
do not auto-replay the prior turn. No user
messages replayed, no crawls retried, no privateconfig/allowancechanges.

# Full-app beta testing allowances rollout — 29 October 2026

User requested generous allowances for EVERY beta user, voice_ms and whole app.
Raised Free defaults/catalog DRAFT-2026-10-29-full-beta-testing:1000conversations,
10000chat turns,7200000voice_ms(120min),5000crawl pages/month;1GBcurrentstorage,
5seats/5widgets. One original-owner pool across Free workspaces retained. Raised
bounded default provider cap5000->150000minor(INR1500); no wallet credit, tariff
rates/retail prices/paid plans changed. Widget defaultcap100000minor(INR1000),
1000sessions/5000turns/day,IP100sessions/1000turns/day,voice300s(5min). Workspace
2000turns/day; concurrency2unchanged. Bot challenge remains OFF by user choice;
phones/purchases/paidactivation/transfers remain OFF. Existing owner caps and
custom widget policies remain authoritative. Production inspection:1workspace,
1Free subscription/noexplicitcap, no customWidgetProtection rows, notpaused.
Added explicit dryrun-by-default apply_beta_allowances.py --catalog-version ...
--apply, bounded1000existingFree subscriptions; locks workspace order, guards
catalog version/DRAFT/freeprice/nondecreasinglimits, audits changes, preserves
usage/holds/pauses/debt/explicitcaps and skipspaid. Immutable snapshots retained;
new subscriptions use current defaults. Included operator script inAPIimage.
Focused32tests PASS14.55s: migration dryrun/apply/idempotency/new+existing/paid/
lower-limit rejection plus shared quota/concurrency/accounting. Add4migration
tests to existing focusedbeta gate(37total), no full suite. Updated localprivate
.env and server runtime.env/migration.env ONLY7nonsecretlimit keys,all0600;
never printed secrets. GitHub40930125532 SUCCESS:37focusedbeta checks and deploy,
release5dbbd87 live. MainPage run40930125376 was independently cancelled during
npmci; no mainpage/contact publication ran, platform then acquired shared runner.
Migration dryrun1candidate/noexplicitcaps, applied1existingFree workspace with
audit, no usage reset. Live rollback-only DB verification confirms workspace and
sharedowner limits,150000minorprovidercap,300svoice,2000dailyturns andwidget
defaults. Public plans shows new catalog/included values; paidactivationfalse.
Readyz200/allok. No account/provider/email/crawl activity initiated to verify.
Do not replay chats or retry user's crawl jobs. No provider requests for tests.

# Hackathon presentation brief PDF, no pricing — 29 October 2026

User asked to remove pricing/commercial detail and focus on open technologies,
then explicitly changed output to PDF ONLY for a friend to make PPT. Later asked
for dedicated tech-stack and tech-flow content. Created output/pdf/Phirmy Hackathon
Brief.pdf,8A4pages with existing Phirmy logo: title/description, problem/existing
solutions/contribution, built/solved work, dedicated Technology stack table,
Technical flow diagram plus separate text/voice/ingestion paths, open technologies/
USP/model flexibility, feasibility/impact/demo/future, and clickable sources.
Hackathon Doc.md now matches the concise PDF content; old pricing tables and
commercial sections removed. Highlight integrated Sarvam105B and actual open
frameworks. Do not claim unintegrated Nemotron/GPT-OSS/NVIDIA ASR are already used
or that all hosted services/private project are open source. Candidates are
explicit future work. No new research/provider requests, secrets, runtime changes,
or full tests. PDF visually rendered/inspected; extraction verifies8pages,
tech headings/flows,13source links and no pricing. No PPT generated. Build scratch
and page PNGs under ignored artifacts/hackathon; temporary generator deps isolated
under/tmp, no project dependencies changed. Commit docs/PDF with[skip ci] to avoid
an app deployment for a presentation asset. User can use PDF pages4/5 in slides.

# Hackathon submission expanded after web research — 29 October 2026

User requested formal hackathon terms plus deep search before rewriting. Reworked
Hackathon Doc.md into20sections: title, description, problem, users/use cases,
existing solutions, contribution, built features, solved engineering problems,
USP, architecture, stack/models, flexibility/open-source scope, feasibility,
challenges, privacy, impact metrics, evidence/demo, future scope and business model.
Reviewed official Chatbase/Botpress/Voiceflow/Vapi/Retell/LiveKit/Pipecat/Sarvam
product docs: RAG, chat+voice widgets and model choice already exist. USP is a
positioning hypothesis around the implemented combination, no exclusivity or
unsupported speed/cost/market claims. Competitors' published features are not
independent benchmarks. Firecrawl CLI authenticated; research artifacts ignored
under.firecrawl/. Full current Sarvam pricing superseded stale search snippets:
0.49INR ASR/min,1INR/1000Bulbulv4characters,15/60INR per1Minput/outputtokens.
Illustrative workload60saudio+600chars+2000input+200output=1.132INR beforetax/
infra/embeddings/carrier/support, not measured invoice or retail price. No plan or
tariff edits. Retained honest model-candidate status and public-source/licence
limits; Riva needs an adapter. Browser constraints fromMDN, RAG injection caveat
fromOWASP. Source links inline; project evidence linked to dated repo documents.
No newly claimed customer outcomes or hackathon-period build history. Doc-only
format/local-link/arithmetic/diff checks; no app tests/provider calls/production
changes, secret reads or user workflow retries. Commit/push this documentation.

# Hackathon showcase document — 29 October 2026

Created root Hackathon Doc.md at user request: Phirmy pitch, actual website/RAG/
widget/voice/tools/workspace features, architecture diagram, current models,
model-profile switching scope, open technologies, demo flow and future work.
Checked implementation against source/current production checkpoints. Kept honest
boundaries: hosted GPT/embeddings/speech and private repo with no root licence do
not establish an entirely open-source product. No evidence of project Nemotron or
GPT-OSS use; described as candidates requiring streaming/tools/usage/tariff checks.
Sarvam mode pins its own voice LLM; text-profile selection does not replace it.
Official NVIDIA research: Nemotron3Ultra free prototype endpoint available;
older Llama3.1Ultra253B and GPT-OSS120B free endpoints marked deprecated. Model
pages advertise free development API for NemotronASRStreaming, ParakeetTDT0.6B,
ParakeetCTC1.1B and Canary1B; subject to limits/terms, not unlimited production.
Riva gRPC needs an adapter, not a Sarvam WebSocket URL substitution. Official
Sarvam docs verify v4 recognition and Apache2.0 listing for105B family; no blanket
speech-model open-source assertion. TinyFish auth expired; used web primary
sources instead. Source links embedded in shareable doc, no private config read
or included. Documentation-only formatting/diff checks; no tests, inference,
production changes, user message replay or crawl retries requested/performed.

# GPT gateway cache usage pause fixed in production — 29 October 2026

User widget Connected but reply blocked:workspace paused. Production inspection:
affected workspace operator_paused=true, billing_blocked=false, debt0/disputes0,
no manual pause audit. One OpenAI-compatible Azure gpt-6-luna Responses cost record
had3156input/28output/0cached/3153cache_write_tokens, no lifetime split. Parser
incorrectly gated lifetime normalization on api.openai.com host, so actual gateway
usage became unreported and tripped unpriced-cache auto-pause. Reserved hold exists.

Read OpenAI Docs skill and current official prompt-caching guide: GPT-5.6+ default
30m when request/breakpoint TTL omitted. Separate recognized GPT usage from optional
host-gated request parameters. Known compatible GPT totals now normalize documented
30m default; explicit lifetime breakdown remains authoritative, malformed/unknown
models stay unreported. Admission reserves cache-write rate for compatible GPT;
extra request options remain disabled for custom hosts. No tariff/rate/cap change.
Focused37tests PASS8.28s (gateway,cache accounting,voice requests,response events).
Added3gateway regression cases to quickbeta CI (33expected); no full suite.

GitHub40882083890 SUCCESS (33focusedbeta checks+deploy), releasee64cbb8 live.
Reviewed ONLY affectedworkspace's1unreportedcost record against documented default
and pinned tariff. Appended source=reconciled_default_30m cost line with audit;
original record remains immutable/unreported0; added only the missing30m cache
MeterEvent (no duplicate input/output events), completed originalunknownhold.
Computed408425000micro-minor DRAFT cost, below original2825600000reserved hold.
No tariff/cap/wallet changes. Confirmed no manual pause/debt/dispute then cleared
operator_paused with billing.automatic_pause_cleared audit. Admission reserve(0)
PASS in rollback-only transaction; no durable probe/session/message/provider call.
Public readyz200/allok. User should refresh/resend themselves; do not replay their
messages or retry crawls automatically. Billing history intentionally retains the
original unreported record and links the append-only reconciliation in audit.

# Bot challenge explicitly disabled for beta by user — 29 October 2026

User explicitly requested no bot protection until they choose to enable it and
add keys in.env. This overrides the earlier automatic production requirement.
bot_challenge.required() now respects ONLY WIDGET_BOT_CHALLENGE_ENABLED.
Set false in tracked private.env and server runtime.env/migration.env, all0600;
blank real-key fields in root.env/.env.example for later owner setup. No fake keys.
To enable later: configure real TURNSTILE_SITE_KEY/SECRET_KEY, set flagtrue and
recreate services. Enabled mode still rejects missing keys/bad/replayed proof and
requires a fresh verified session; disabling does not disable installation origin,
public-key, quotas, rate limits or spending checks. Authenticated dashboard preview
fix retained, with CSRF, role/membership and verified account boundaries.
Focused9checks PASS5.29s, including production toggle off/on behavior and existing
bot replay/origin guards. User controls re-enabling; do not ask for keys again or
silently turn it back on. Do not retry user's crawl jobs.
Deployment40880292234 SUCCESS (30focusedbeta checks, no full suite);
release6dd3fd8 live. Production required()==false and actual public widget
configuration challenge.required=false verified read-only; readyz200/allok.
No public session/customer message/provider call created by verification.
User should refresh Test agent and click New session.

# Authenticated widget dashboard preview fix — 29 October 2026

User screenshot Test agent blocked by awaiting bot-protection configuration.
Root cause: bot_challenge.required() ALWAYS requires Turnstile in production,
even when WIDGET_BOT_CHALLENGE_ENABLED is false. Both real keys remain absent.
Earlier audit calling this optional hardening was inaccurate: public embeds need
Turnstile configured. Asked user to add TURNSTILE_SITE_KEY/SECRET_KEY privately;
never use test/dummy keys or disable protection silently.

Fix: WidgetChat has explicit dashboardPreview flag only at authenticated dashboard
call sites (website assistant test, legacy installation test, workspace live
preview). Setup uses existing authenticatedFetch, CSRF/session refresh and
X-Studio-Preview header. Public iframe/app/widget never sets this flag. Backend
only honors the header after app Origin, real verified user session, CSRF,
workspace membership, widget:write permission and existing installation key/origin
validation. Workspace API keys cannot obtain preview bypass. Subsequent bounded
widget capability has server-stored bot proof and dashboard user provenance;
normal widget/session quotas and spending still apply. Public requests always
retain production Turnstile requirement. No global security/env flag changed.

Focused8checks PASS5.50s (5preview +3existing bot/origin checks), Next typecheck/
production build PASS. Added5preview cases to quick beta CI (29total expected),
not full suite. Do not retry crawl or send customer/provider messages to verify;
user chose manual retry. .env keys still absent at last presence-only check.
Public embedding remains pending real Turnstile configuration; signed-in preview
fix is independent and deployment now in progress.

# Beta crawl/storage allowances increased — 29 October 2026

User retried crawl, hit429crawl_pages at14/20; requested a decent beta allowance.
Confirmed current subscriptionFree25pages/month,16consumed+existingholds. Raised
Free defaults to1000crawl pages/month and500000000bytes storage (500MB); catalog
version DRAFT-2026-10-29-beta-allowances. Other entitlements/provider rates/spend
caps unchanged; paidactivation remains disabled. Installed validated config into
both live API/worker, then moved ONLY the affected Free workspace subscription to
new immutable catalog snapshot, with billing.beta_allowance_granted audit event.
Old snapshots/tariffs/usage/costs preserved. Both workspace admission and shared
Free owner pool verified1000pages; provider cap unchanged5000minor. No jobs retried,
no usage reset, no purchased plan/charge, no crawl/provider request initiated.
New workspace defaults use new catalog; other preexisting pinned subscriptions
are not silently rewritten. User will Retry. Focused quota/legacy tests only.
Validation:2quota/legacy tests PASS1.67s; GitHub40878037871 SUCCESS with
24focusedbeta checks+deploy; release45304f3 live/all readinessok. Production
workspace and shared owner pool both verified1000pages/500MB after replacement.

# Legacy workspace storage inventory fixed — 29 October 2026

User reported3failed crawl jobs:503 Storage inventory requires reconciliation.
One preexisting workspace lacked StorageInventoryState after production migration;
new workspace creation already initializes it. Ran real Azure reconcile(apply=True)
inside production API:1existingobject97673bytes inventoried/metered, no deletions.
All3failedjobs refer to1knowledgebase. User explicitly said they will retry:
DO NOT requeue, cancel, delete or mark those jobs complete. No job state changed.
Permanent deployment fix: include scripts/reconcile_storage.py in API image;
new --pending mode bounded to1000uninitializedworkspaces, dryrun default. Deploy
runs it with restricted runtime credentials after schema/grants and before new
API/worker startup. Completed Azure listing required before ready marker; no
bypass of storage accounting or usage caps. Focused regression checks cover legacy
write guard, pending idempotency/dryrun/skip and provider failure retaining guard.
No full suite requested; use focused beta deployment checks only.
Verification:3targetedstorage tests PASS1.83s. GitHub40872571934 SUCCESS
(focused24beta checks+deployment); release48d0392 live. API readyz200/allok;
production --pending dryrun reports0uninitializedworkspaces after deployment.
Original3failedcrawl jobs left untouched for user Retry; no crawl executed by AI.

# Phirmy production live — 29 October 2026

Core beta deployed via GitHub Actions run40829506872 SUCCESS. Release
26411e5ac260d1a05b195ba618277eff616ce085 recorded on server; hosted verify
24passed, local focused24passed39.56s. User explicitly rejected full-suite wait:
platform pipeline now push/main/manual -> allowlisted offline identity/media/Sarvam
checks -> deploy; full backend/sandbox runs PR/manual only. Docs/MainPage-only
changes do not redeploy platform. Do not reintroduce broad release gates or rerun
all tests for routine beta changes unless a relevant failure requires it.

Public https://app.phirmy.com/signin, app/backend/healthz, api.phirmy.com/healthz,
api/readyz and phirmy.com all200, verified TLS. /readyz worker/database/Redis/
Qdrant/content_sandbox allok. Actual WSS upgrade api/v1/media with app Origin
succeeds, empty session token rejected without provider use; untrusted Origin403.
Chromium desktop1440/mobile390 sign-in, create-workspace view and forgot-password
pass, zero JS errors/no overflow, Google option configured, API/WSS CSP verified.
No account created, email sent, OAuth completed or live-provider/carrier call made
by public acceptance. Evidence artifacts/production/public-results.json and
{desktop,mobile}-signin.png; private verification script there. Build/typecheck PASS.
Phirmy visible dashboard/auth/metadata branding replaces old Voice Studio labels.

Both DNS names point20.40.52.17. Nginx fronts loopback18100/API,13100/web; private
Docker Redis/Qdrant no published ports; network172.31.240.0/24. Compose6services
healthy. Certbot app+api cert expires2027-01-27, renewal dry-run PASS and nginx
reload deploy-hook installed. Existing phirmy.com/contact service preserved.
Stable APP_SECRET preserved. Runtime phirmy_runtime DB role has no owner/DDL powers;
migration/backup credentials separate under /etc/phirmy-platform, all0600/dir0700.
Schema2026-10-27-call-transfers migrated and checked; alltable grants refreshed.
Backup archive verified and original64tables restored into network-disabled
throwaway PG successfully, then removed. Private Azure database upload verified.
Daily phirmy-backup.timer installed for03:10UTC+jitter, database/vector scripts
in /opt/phirmy-platform/operations. See docs/PRODUCTION_DEPLOYMENT.md for commands,
rollback, credential syncing and operational limits. Never prune unrelated volumes.
Disk remains94% used/~12GiB free; unused build cache cleanup recovered11GiB earlier.

Earlier mail MX issue now resolves correct Hostinger targets; SPF/DMARC present;
actual inbox delivery still needs user acceptance. Google sign-in+Calendar client
split, real OAuth consent, physical mic/live Sarvam from deployment, owner-reviewed
application legal/business information remain product acceptance tasks. Phones,
trials/purchases and live payments remain off; no new phone/payment acceptance.
Published knowledge snapshots0 at deployment, so no published vector data to move;
old local Qdrant emptycollection snapshot saved privately. New vector jobs handled
by deployed worker. MainPage PHIRMY_APP_URL variable now https://app.phirmy.com;
manual MainPage run40829902884 SUCCESS publishes login link after app readiness.
Live Chromium homepage Log in -> app.phirmy.com/signin PASS, zero JS errors.
Actual phirmy-backup.service first run PASS: database archive + private Azure
upload verified, exit0; timer enabled/active. All requested hosting work complete.

# Beta deployment gate narrowed at user request — 29 October 2026

User objected to repeated full-suite delays. Cancelled the latest full run and
changed platform CI to focused offline identity/media/Sarvam checks before deploy.
Full backend/sandbox CI now runs on PR/manual only; platform pushes/main/manual
run allowlisted --beta-smoke checks with no Docker build on hosted verification.
Full tests must still use --run-sandbox; beta mode rejects any other module/marker.
Public readiness, HTTPS/browser/WebSocket checks remain required after deployment.
Production preflight all6services healthy; schema migrated, restricted grants
applied, DB backup restored in separate disposable network-disabled PG successfully;
private Azure backup upload verified. Certificates installed for both domains and
renewal dry-run passed. Public maintenance503 in place until CI activates routes.
Mail MX now correct Hostinger targets; SPF/DMARC present; no email sent. MainPage
PHIRMY_APP_URL GitHub variable set, publish after app acceptance. Core branding
changed to Phirmy. FFmpeg CI synthetic decoder now passes with bounded stack/arena;
legacy synthetic benchmark provider isolation fixed and local3turnPASS. No actual
OAuth/provider/phone/payment request in deployment verification so far.

# Cynerza production deployment in progress — 29 October 2026

User authorized full app/API hosting with GitHub CI/CD on existing Cynerza host.
DNS app.phirmy.com and api.phirmy.com now points to20.40.52.17; Certbot issued
both names in app.phirmy.com certificate, expiry2027-01-27. Existing Phirmy main
site/contact preserved. Cleared only unused Docker builder cache older7days,
recovering11GB; never prune data volumes or unrelated application images.
New isolated Compose uses loopback18100/API,13100/web, private Redis/Qdrant;
network172.31.240.0/24 verified unused. Runtime credentials installed0600 under
/etc/phirmy-platform; no migration owner in runtime.env. New phirmy_runtime
Postgres role verified no superuser/create/bypassRLS/schema-create powers; local
private.env updated to this role and public API/media origins api.phirmy.com.
Existing stable APP_SECRET preserved. Migration/database backup credentials remain
separate. Private DB archive created; isolated restore check in progress.
Deployment workflow waits for successful Backend and sandbox tests on latest main,
then builds images, backs up, migrates/grants, waits readiness and installs Nginx.
No successful full platform release yet. Old CI has4host Chromium launch timeouts
and2sandbox audio failures. Host tests now explicitly choose Playwright's installed
binary; bounded FFmpeg output/native thread settings added. Require CI green.
Local shell/Python syntax passed, remote Compose parse/sandbox image build passed;
preflight API/web builds underway. New files in deploy document actual topology.
Do not claim full acceptance until GitHub deployment and public browser checks pass.

# Production environment prepared — 29 October 2026

User requested only production.env configuration. Updated private tracked.env:
APP_ENV production; PUBLIC_HOST app.phirmy.com; APP_ORIGIN, PUBLIC_API_ORIGIN
and MEDIA_PUBLIC_ORIGIN https://app.phirmy.com; SESSION_SECURE true;
DEV_SEED_ENABLED false; REQUIRE_EMAIL_VERIFICATION true. Filled APP_SECRET
from the EXISTING data/.session-secret, preserving encryption/signing identity.
All other parsed values (including user-added OAuth credentials and disabled
phone/payment settings) preserved; file permissions0600. Local Settings()
production validation passed, with no provider/DB requests, tests, restart or
deployment. No credentials printed. Environment takes effect on next startup;
localhost development now requires explicit development overrides. This resolves
only the environment-mode/origin/stable-secret items in the prior beta review.
Hosting, DNS/TLS, restricted DB role/migrations/backups, email acceptance, legal
configuration and optional phone/payment gates remain. Commit/push includes the
private.env per the user's explicit tracked-private-configuration instruction.

# Beta readiness review — 29 October 2026

User asked to check.env and say what is still needed; no credential tests requested.
Static-only report: docs/BETA_READINESS.md. Google/Cal.com/Calendly/SMTP and core
AI/storage/Redis credentials are present; not validated. Deployment remains local
origins/old PUBLIC_HOST, development/insecure-cookie/seed settings, blank APP_SECRET
with existing data/.session-secret to preserve, owner DB runtime role, undeployed
full stack. Target app.phirmy.com. App legal docs still DRAFT; phone number/carrier
acceptance and paid webhook/commercial approval separate. Prior SMTP MX issue not
rechecked. No provider/DNS/DB requests or tests; private.env untouched and excluded
from report commit. Do not treat this audit as release acceptance or authorization
to publish/enable phone/payments. Full report records remaining gates and defaults.

# Phirmy homepage + Sarvam voice and microphone audit — 29 October 2026

PUBLIC ACCEPTANCE: implementation12a7db3 pushed normally. Existing deployment
CI40818685104 SUCCESS (53s), including build/typecheck/static publish and isolated
contactAPI health. Public https://phirmy.com Chromium PASS: new hero/rollout note,
desktop/mobile fit, product navigation, native cookie settings and persistence,
direct /legal/cookies, contact form rendered, zero page errors. No form submitted
or email sent. Evidence artifacts/mainpage/live-editorial-{desktop,mobile}.png and
live-editorial-results.json. A concurrent user commit987fb91 to the tracked private
configuration was preserved; the implementation commit did not include.env.
Full voice backend remains local/source-only pending deployment and phone acceptance.

User expanded minimal smoke-call task to BOTH browser/widget voice and phone,
latest Sarvam speech/voice chat with tools; GPT remains text chat. Then requested
widget microphone permission/bug audit and a Sarvam-reference MAIN PAGE refresh.
Brand is explicitly **Phirmy**, not Nutaan. Homepage work is standalone MainPage,
not the platform's FirstMinute page. Show implemented features only; roadmap and
rollout clearly separate. No new dependencies for this pass. Preserve user .env
key edit, never print/stage it incidentally; root tracked.env choice remains.

Sarvam runtime defaults: saaras:v4 realtime WS fast/VAD250ms, bulbul:v4-flash WS
PCM16/24k, sarvam-105b-conversations V1 SSE with tools/no thinking. V2 does not
list conversations. Browser/Plivo/Twilio share engine; old configurations normalize
in memory. Text GPT selection unchanged. Explicit VOICE_PROVIDER=legacy rollback.
Persistent TTS per call, fresh generation socket on interruption, matching final
flush events, utterance dedup, bounded tool deltas and existing confirmation /
idempotency / budget controls. Sarvam per-second STT, Unicode-char TTS and token
pricing snapshots; old pinned tariffs fail rather than silently reprice.
New docs/SARVAM_VOICE.md records configuration, endpoints, lifecycle and sources.

Live synthetic pipeline PASS: generated “Please check my booking status.” →
9partials/final → real model → local read-only lookup_demo_booking once → real
model continuation → spoken “Your booking status is confirmed.” First audio
1385.7ms after final transcript incl tool round trip; single sample, not SLA or
zero-latency claim. Long incremental two-flush speech + manual dictation PASS.
No customer booking or actual carrier call. Physical mic/echo and owned-number
carrier acceptance remain pending; backend is not publicly deployed by this task.

Widget: explicit visitor action requests mic; no capture on load/opening voice.
Native permission pending UI, useful denial/device/policy errors and retry;
double starts/pending late grants/unmount/worklet cancellation release resources.
Dictation epochs prevent stale results or late capture after close. Domain origin
verification and iframe microphone delegation retained; HTTPS and parent policy
must allow access. Transcript scroll stays in panel; compact voice controls fit.
Native VoiceConnection lifecycle checks PASS. Independent-origin Chromium test
uses REAL synthetic-device capture/MediaRecorder/AudioWorklet PCM and synthetic
media/transcribe boundary: no prompt on load, denial+retry, missing device,
close while permission pending, dictation, iframe policy, track cleanup, host
microphone=() denial, zero page errors. Full Chrome executable required: this
machine's headless-shell returns NotSupportedError for getUserMedia.
Repro isolated server scripts/run_sarvam_browser_qa.py (runpy test env, disposable
SQLite, cleared real keys, worker off, proof stub limited to127.0.0.1:3201).
Checks scripts/verify_widget_microphone.py + verify_sarvam_browser.py PASS after
final compact fix. Editor saved Sarvam config while preserving GPT; mobile/desktop
screenshots in ignored artifacts/sarvam. Never run test setup against Supabase.

MainPage: warm/sage editorial hero, serif display type, compact Phirmy emblem,
accessible product dropdown, asymmetric feature layout, light Remotion showcase
with initial poster, responsive footer wordmark. Existing contact flow, all four
narrated tours, React Bits, lazy WebGL/video, reduced motion and pause preserved.
No invented customer logos, metrics, products or fake live calls. Rollout note
separates implemented features from public rollout/paid activation. Unconfigured
dashboard links replaced with working contact/setup links.
Local /legal/{cookies,privacy,terms} pages now work. Public site has no optional
analytics/ad trackers: notice says so, Manage/Got it, native accessible settings
dialog with actual categories, 180day local-only preference, reset/reopen,
expiry/storage errors, no advance consent for future trackers. Phirmy branding
throughout new copy. Sources and operational notes in MainPage/README.md.

Verification: FULL isolated backend799passed35skipped335.43s; unavailable Docker /
external service checks remain skipped (not passed). Targeted90passed55.92s incl
15Sarvam tests with browser/Plivo/Twilio application sockets, tools and confirmations.
Next typecheck/build and native connection checks PASS. MainPage final build /
typecheck +25Chromium tests PASS26.6s incl desktop/mobile360..1440, axe accessibility,
contact success/errors/idempotency, narration/seek/pause, menu focus, consent
persistence/reset/blocked storage/direct legal URLs. Fixed footer contrast and
initial empty demo frame; tests wait for final queued frame event on pause.
Visuals inspected in artifacts/mainpage/editorial-*.png. No new email sent.

Commit/push follows project instruction; existing mainpage-deploy CI automatically
publishes MainPage and isolated contactAPI only. Check CI/public-page acceptance
after push; do not imply full platform/voice backend deployment. Previous mail
MX/inbox delivery follow-up remains unresolved and unrelated to this change.

# Sarvam first live call passed — 29 October 2026

User confirmed key added. Ran `.venv/bin/python sarvam_chat.py` once with the
real environment key; exit0 and exact reply `Hello!`. No key printed, no retry
or additional provider probe. Original minimal smoke-call goal achieved.
Revisited official https://docs.sarvam.ai/api/getting-started/welcome: Saaras is
speech recognition, Bulbul is speech synthesis, chat completion is separate.
Next ask which voice experience to build first (browser, phone, or both), taking
existing GPT chat / Sarvam voice-with-tools preference into account. No migration
or latency acceptance performed. User's private key edit is preserved locally.

# Minimal Sarvam setup — 29 October 2026

User explicitly requests one chat smoke call, then stop for key confirmation
before executing it. Installed sarvamai0.1.40 with uv pip in existing .venv
(pip module absent), recorded dependency in pyproject.toml/uv.lock. Root script
sarvam_chat.py uses existing python-dotenv, SARVAM_API_KEY from environment/root
.env, SarvamAI.chat.completions with sarvam-105b-conversations, no reasoning,
128 output tokens and no retries. Missing key exits before client creation;
provider errors do not print raw exceptions. No Sarvam request made yet.
Added blank SARVAM_API_KEY to existing private .env, preserving prior bytes and
0600 mode. Added .env ignore rule; existing tracked file remains tracked per
repository instructions. Syntax/import/SDK signature/lock/diff checks passed.
Official docs read: https://docs.sarvam.ai/api/getting-started/welcome and
https://docs.sarvam.ai/api/api-guides-tutorials/chat-completion/overview.
TinyFish fetch failed expired credentials; direct official docs worked.

NEXT: tell user to paste key into .env; wait for explicit confirmation, then run
`.venv/bin/python sarvam_chat.py` and show reply. No dummy keys or keyless probes.
After successful call, discuss build scope using official Sarvam docs. User has
already specified GPT for AI chat and Sarvam/Saaras replacing Deepgram for voice,
WebSockets and tools with lowest practical latency. Voice migration has NOT been
implemented; do not promise zero latency. Existing runtime/providers untouched.

# Hostinger SMTP and live contact API — 28 October 2026

User supplied support@phirmy.com Hostinger credentials and explicitly requested
live phirmy.com test. Private tracked.env updated silently (465/SSL). Config also
installed /etc/phirmy/smtp.json root:phirmy-contact0640; never print credentials.
Hostinger authentication over verifiedTLS PASS from server. Deployed only minimal
contact runner+8shared modules under /opt/phirmy-contact. Dedicated phirmy-contact
system user+systemd service, loopback8102. Persistent encrypted SQLite outbox/key
/var/lib/phirmy-contact; no Supabase/platform APIs/workers deployed. APP_ENV=contact
is isolated mail-only mode; hosted middleware strictly allows HTTPS Phirmy origins.
Nginx /api/contact now proxies with loopback-only trusted headers; nginx -t PASS.
CI includes exact source paths and deploy/contact.sh with pinned mail requirements.
No private root.env copied in sparse checkout or source bundle. Data/key survive CI.
18isolated contact API tests PASS2.42s; production browser form202/receipt,zeroerrors;
verification reference cc167cd7-a499-45cb-8b6a-6f407e5a50cd, outbox sent/attempts1.
Owner-authorized verification only; do not resend just to check delivery. Inbox
arrival not yet confirmed at this checkpoint; invalid-origin403 verified.
Single-process rate limits reset on restart. Full product backend remains unhosted.
CI40712008686 SUCCESS48s, including build/typecheck/static publish/contact deploy.
Post-CI service active, healthz ok, original outbox still sent/attempts1.
Screenshots artifacts/mainpage/live-contact-smtp.png.
Delivery blocker: both1.1.1.1/8.8.8.8 resolve malformed MX targets
mx1.hostinger.com.phirmy.com.phirmy.com(priority5) and
mx2.hostinger.com.phirmy.com.phirmy.com(priority10). Cloudflare nameservers
erin/zac; no connected Cloudflare tool. User must correct root(@) MX to
mx1.hostinger.com priority5 and mx2.hostinger.com priority10 (TTL Auto/default),
per https://www.hostinger.com/support/4407237-hostinger-email-mx-records/.
Read-only IMAP INBOX search did not find verification Message-ID. SMTP acceptance
is confirmed, mailbox arrival is not. Recheck DNS/inbox after user fixes MX;
do not send duplicate verification automatically.

# React Bits motion pass — 28 October 2026

User explicitly requested React Bits skill for MainPage animations/text/components.
Read installed skill; fetched live TS-CSS registry source using its rb-add script:
Threads/ShinyText/RotatingText/Magnet in components/react-bits/new. Source props
inspected before wiring; existing motion dependency sufficient, license preserved.
Lazy desktop Threads hero backdrop, view-triggered dark-green headline shine,
rotating conversation phrases with fixed SR text, bounded magnetic hero/finalCTA.
Existing BlurText/SpotlightCard preserved. MotionAccents lifecycle gates background
on viewport/visibility/desktop finepointer/pause/reducedmotion. Mobile static art.
Build/typecheck PASS;19existing browser tests PASS19.7s. Desktop/mobile screenshots
inspected. Focused motion tests2PASS5.9s (21total across suites). CI40709514954 SUCCESS43s.
Public Chromium confirmed rotating phrase, Threads canvas and headline shine,
zero page errors; pause removes canvas. Changes committed/pushed main.
User's untracked react-bits skill folder preserved outside this implementation.

# Remotion scene rebuild — 28 October 2026

User explicitly requested using installed Remotion skills properly. Read router,
create/video-layout, markup/sequencing/compositions, captions/transcription/display,
render, audio-visualization and local-font references. Preserved user-added skills,
skills-lock and tool folders outside this task's commit.
Named scene Sequences now group audio+captions, with question/answer/outcome
components, frame-driven staggered titles, spring confirmation, calendar slots,
actual voice audio spectrum. Remotion media/fonts/captions dependencies pinned
4.0.538. Existing directed Drama3 audio retained (no additional Fish generation).
Local Remotion Whisper WebGPU small.en transcribed12clips; source-relative Caption
JSON + inline editable arrays; official BasicCaptions copied unchanged. Captions
inside video; desktop1000x640/mobile600x900; transcript remains accessible.
Studio opened/checked zero page errors; CLI rendered voice and three booking
frames; mobile screenshot found inherited title color, fixed inline color.
Build/typecheck and19browser tests PASS19s before final title-color fix;
Final build/typecheck and targeted narration test PASS. CI40707236749 SUCCESS49s.
Public Chromium verified new scene, embedded captions and decoded/running Web Audio
with zero page errors. Mobile final title contrast inspected. No MP4 export requested.

# MainPage visual refresh + directed Fish narration — 28 October 2026

User requested readable, refreshing MainPage for younger builders and actual Fish
voice using private.env; explicitly corrected narration to use Drama3 audio tags.
Implemented larger/darker type, forest/mint accents, builder copy, redesigned
three-beat responsive conversation films (desktop1000x520/mobile600x680), captions,
mute and transcript. Twelve real prerecorded clips use configured drama-3/voice;
performance scripts include natural-language directions, [pause], <emphasis>.
Official https://fish.audio/drama-3/ verified; initial untagged takes superseded.
Generator MainPage/scripts/generate_narration.py reads .env privately, caches
paid takes, normalizes -16LUFS/-1.5dBTP, validates full decode, derives timing.
No secrets in shipped assets. Live calls are not made; audio explicitly illustrative.
New generated MP3s and manifest in MainPage; cached raw takes ignored artifacts.
Playback pause/seek/scenario/mute tested in actual Chromium; no autoplay.
Build/typecheck PASS;19 browser tests PASS18.9s including axe and responsive
360/390/768/1024/1440. Desktop/mobile screenshots inspected under artifacts/mainpage.
Publish retains old hashed audio for open sessions. CI40704717879 SUCCESS26s. Public phirmy.com Chromium smoke verified
new caption and playing decoded narration, zero page errors.
Contact backend still unhosted (503); unrelated paused audit remains paused.

# MainPage TLS — 28 October 2026

User confirmed Cloudflare DNS complete and authorized planned Certbot setup.
Both names resolve to20.40.52.17. Certbot nginx issued/installed phirmy.com +
www.phirmy.com certificate, expiry2027-01-26; HTTP301→HTTPS. Public HTTPS
homepage/www/contact200 with certificate verification0. nginx -t PASS;
certbot.timer enabled+active. Certbot renewal dry-run SUCCESS for both names.
CI40701716319 SUCCESS26s, including verified HTTPS smoke checks after publish.
MainPage/deploy/nginx.conf now mirrors live Certbot config (paths only, no keys).
Publish script checks HTTPS locally using --resolve with full TLS verification.
Only MainPage remains hosted; contactAPI503 and app routes still require backend.

# MainPage HTTP hosting — 28 October 2026

User authorized deploying ONLY MainPage to cynerza@20.40.52.17, with CI/CD
runner label cynerza and HTTP Nginx phirmy.com; explicitly defer SSL until DNS.
Started /home/cynerza/github/1/actions-runner/run.sh before deployment setup.
Nginx site /etc/nginx/sites-available/phirmy serves /var/www/phirmy/current;
other virtual hosts preserved. Workflow .github/workflows/mainpage-deploy.yml
runs on main pushes affecting MainPage or workflow, plus manual dispatch.
Sparse checkout excludes private root .env. Atomic releases preserve old assets.
No backend deployed: /api/contact intentionally returns JSON503; support email
remains available. Dashboard/legal/docs require a future real PHIRMY_APP_URL
repository variable; currently existing same-origin links have no hosted app.
Runner configured as phirmy-actions-runner.service using requested run.sh.
Verified: local locked install/build/typecheck PASS; both CI deployment runs
40700923650 and40700947668 SUCCESS (latest26s). External HTTP checks with
Host/domain pinned to server: homepage/contact/www and JS/CSS assets200,
contactAPI explicit503 as intended. nginx -t PASS; runner enabled+active.
Initial hosting changes committed/pushed main. Cloudflare DNS and TLS completed
in the follow-up recorded above; no Cloudflare settings changed by agent. Paused audit remains paused.

# AI continuation handoff — Voice Studio

## Active request: Phirmy contact page — 27 October 2026

Homepage build CTAs now open MainPage `/contact`. User explicitly corrected the
recipient to **support@phirmy.com**, with website phirmy.com. New responsive
contact form, interest radios, consent, direct mail link, clear errors and a
personalized success screen. No visitor auto-reply or marketing subscription.
`POST /api/contact` proxies to control `/v1/public/contact`; fixed support recipient,
UUID-v4 idempotency (including concurrent conflict), origin/field/consent checks,
honeypot and IP/email/global quotas; encrypted existing EmailOutbox. Mail uses the
existing root .env SMTP settings, authenticated From, visitor Reply-To, escaped
branded HTML plus plain text, existing retries/dead letter. New email-validator
package pinned in uv.lock. Endpoint/schema added to implemented API contract.

Actual configured SMTP values are present. **Live SMTP delivery remains blocked
by environmental DNS**: EAI_AGAIN for SMTP host AND general public host, also in
an approved probe outside the sandbox. No credential failure is inferred and
no inbox receipt claimed. One clearly labeled verification enquiry went through
actual Chromium → proxy → API → encrypted outbox (HTTP202, zero page errors).
Its record remains pending for bounded retry in isolated local contact DB. No
second verification message should be sent just to retry; retain its reference
from /tmp/phirmy-contact-verification-receipt.json and inspect its outbox status.

Local contact runner `scripts/run_mainpage_contact.py` binds127.0.0.1:8102 and
uses only `data/mainpage-contact/enquiries.db`, plus its private0600 encryption
key. SMTP copied privately from existing.env; no Supabase or other queue worker.
Runner session26032; Vite3200 proxies to8102; regular app8100/3100 unaffected.
Production uses the normal control API+outbox worker; MainPage/nginx.conf shows
same-origin proxy, size cap and exact trusted-forwarding setup. Set VITE_APP_URL
to real dashboard origin for existing legal/docs links. Nothing publicly deployed.

Verification: 18 browser tests passed35.4s (contact/home/mobile/axe, retries,
consent and all tours); 72 backend tests passed49.85s with real sandbox enabled
(contact/account mail/identity/key rotation/callbacks/invoices/widget protection).
A pre-existing Watch CTA visibility race was fixed: consume pending play only
from observed visibility, not a potentially stale rect. Final frontend build
also rerun after adding footer contact link. New form screenshots in
artifacts/mainpage/contact-*.png. These are targeted checks, not a new FULL audit
suite. Paused connectors.py WIP remains excluded from this commit; audit stays
paused. Private .env/main/Supabase unchanged.


## Active request: Phirmy MainPage — 27 October 2026

The user explicitly paused the audit ("keep it here") and requested a separate
`MainPage` homepage for Phirmy, using the three supplied silver/charcoal brand
images, React Bits, and the Remotion skill. This request supersedes the old
continue-until-audit-complete instruction until the user resumes that work.

Implemented standalone Vite/React app in `MainPage/`, with its own dependencies,
lockfile, README and browser tests. Existing Next homepage/dashboard routes are
not replaced. `npm run dev` there serves port3200; `npm run studio` serves the
four editable Remotion compositions at3201. Public app-link origin is configured
with VITE_APP_URL at build time; dev defaults to same-host3100. Production without
that variable expects the app routes at the same origin. No live call, booking,
lead submission, payment, analytics or provider API request is made by this page.

Features: supplied original brand images, local licensed fonts, neutral metallic
art direction, React Bits BlurText/SpotlightCard with preserved upstream license,
responsive marketing sections, four distinct18s/30fps Remotion scenarios (support,
voice, leads, booking), accessible Player controls/transcripts, keyboard tabs,
mobile navigation, native FAQ, reduced-motion change subscription, ambient pause,
offscreen/hidden playback pause, lazy Player loading. Official Remotion skill
and relevant references read from remotion-dev/skills; details in MainPage/README.

Verification: production build+TypeScript PASS; **11 Chromium browser tests
passed in24.1s**, including all walkthroughs, pause/seek/restart, watch CTA,
offscreen pause, responsive360/390/768/1024/1440, mobile navigation, dynamic
reduced-motion and axe WCAG2A/2AA/2.1AA desktop/mobile checks. Studio actual
Chromium opened AppointmentBooking with zero page errors. Screenshots in
`artifacts/mainpage/`. No public deployment or video export performed.

Audit remains paused at f5d6b33. Existing uncommitted calendar SQL edits in
`services/control/studio/connectors.py` are preserved and excluded from the
MainPage commit. Before this task, `/tmp/phase6-calendar-sql-initial.log` reported
47passed with4warnings; new SQL/cancellation tests and audit documentation still
pending. Paused rights work remains pinned at refs/codex/paused-data-rights.
Main/private.env/Supabase remain unchanged. Resume audit only when requested.


## Phase 6 scheduling SQL checkpoint — 27 October 2026

5e04394 HTTPToolSQL pushed audit; targeted131pass1skip68.73s. Scheduling availability/
prepare/confirm/GETreconciliation DBwork nowoffloop, local sessions; workspace→booking
locking forresult/unknown/failure updates. Durablebookingsuccess survivescanceled
commit; canceledcommittedclaim beforeHTTP recordsfailed/not-sent; startedPOST
remainsunknown andneverreplays. Context/expiry/caller/revision/recheck/readbackguards
preserved, no wireAPI/header/retrychange. Cal.comcurrentmainbookingcontroller200/read,
CalendlyrendereddocsURLError (notclaimedreverified). Focused63pass2skip42.79s;
FINALbroader139pass2skip64.17s afterlockfix. No frontend/schema/newlatencychange.
LatestFULL788pass2skip490.38s still948e6f5.

NEXT calendarconnector voice SQL: connectors.agent_calendar_action readonlycred
read +recorded_action currentlyDBsessionheldacrossnetwork. Split queue/snapshot/
finish intoindependentthread sessions; route releasesinjectedDBtransactionbefore
network, preserveexactremoteeventID/freebusy/one-shotConnectorAction semantics.
CurrentofficialGoogleSDKfreebusy/events docs200/read27Oct cached
/tmp/voice-sql-ref-google-{official-sdk,events}.txt (actualfreebusyfile name
/tmp/voice-sql-ref-google-official-sdk.txt). RenderedGoogle docsURLError. Then
Phase6fullverification andoriginalPhases3/4/5/7 withpinnedrightsWIP35e5fbb.
Main/private.env/Supabase unchanged. Runtime/draftrefresh stillneededasbelow.


## Phase 6 HTTP tool SQL checkpoint — 27 October 2026

948e6f5 humantransfer pushed audit, FULLDocker788pass2skip490.38s. Latest12turn
synthetic373.147ms p50/409.488ms p95 no liveclaim. NewHTTPTool perform/invoke queue,
claim/finalization offloop withthread-local sessions andworkspace→executionlocks.
Durableobservequeue outcome; cancelbeforeI/O closesunusedexecution, afterI/O
unknown/no replay; completedHTTPbody remainsauthoritative duringcanceledclose.
ExistingSSRF/revision/schema/redaction/responsecaps/wirecontract unchanged.
Focused57pass16.61s; broader131pass1skip68.73s. Five newSQLhook/concurrency/cancel
checks. LatestFULL still948e6f5, notthischeckpoint. No frontend/schemachange here.
SQLAlchemy sessionbasics official200/read27Oct records Session perthread.

NEXT scheduling.py availability/confirm/refresh DBblocks offthread +agent_action
prepare; scheduling_oauth.ensure_access alreadyoffloads claim/finish. Then calendar
connectors.agent_calendar_action/recorded_action, no sharedDBsession overnetwork.
Concrete /tmp/voice-sql-next.md. Fixture tests/test_agent_scheduling.py scheduler
paramCal.com/Calendly, helpersprepare/confirmed_context easySQLhook acceptance.
Cal.comcurrentmainofficialcontroller +GoogleSDKfreebusy200/readcachefiles below;
renderedCal.com/Calendly/GoogleURLError. PreservewireAPI/reference guards, no POST
replays. ThenfullPhase6 checks and originalPhases3/4/5/7 withpausedrightsWIP.

PrimaryAPI61494/worker73112/Next80523 remains pre-killtransfercode; restartfromnew
committedHEAD afterthisSQL pass safehelper+Redis6399+LIVE_TRANSFER_ENABLED=false.
Recoverydraftstill72842c1; refreshbeforefinish. Main/private.env/Supabase untouched,
rightsWIPref35e5fbb preserved, noagents. Continue audit; do notstoppartialfinal.


## Phase 6 human transfer checkpoint — 27 October 2026

2912a4c callbacks pushed audit. Human transfer implemented behind defaultfalse
LIVE_TRANSFER_ENABLED +paidactivation; production requires APPROVED immutabletariff.
NewTransferPolicy owner/adminbrowserstaffnumber revision +verifiedplatformoperator
approval via BILLING_OPERATOR_EMAILS/CSRF; everyedit revokesapproval. Usercannotpick
number. LaterToolConsentreadback binds revision/team. NewCallTransfer encrypted
credential/dest snapshot, oneintent/job percall, locked singlewrite/no auto-replay,
unknownholds retained, signedone-shotXML only1Dial; conflictingcallbackduration/
childidentity409. Frozenkeysallowfinalcallbacksafterrotation. TwilioURLredirect+
originaltime_limit; PlivoalegURL/DialcallbackBillDuration, deadline/ringingbounds.
Parent state staysconnected for existing active-call gates; mediafinalize retains
parent wallet/voice/carrierholds until realhangup, staffleg separatecost. Parent
admission nowactualcarrier ratherthanhardcodedPlivo. DRAFT120default5–300limit,
10sring20smargin, staffcosthold roundedminute. See HUMAN_TRANSFER +DECISIONS refs.

Operator kill nowqueuesonehangupjob foractivelivePSTN legs evenwhenAI socketgone;
pause/block also rechecked beforetransferproviderwrite andsignedXML. Firstfullrun
INTERRUPTED250pass2skip153.99s tofixthis gap; notfullacceptance. FINAL FULL real
Docker+Redis **788passed2skipped0failed490.38s**. Two skips provider-inapplicable
schedulingparams, no sandbox skip. Finalkill/billing/phone72pass48.80s; focused23pass
22.05s. RealdisposablePG24claims→1submission,24XMLfetches→1Dial, parent/childcosts
separate. ActualChromiumsettings/last4/approval/flagoff +widgetcallback→ownerresolve,
0pageerrors,0carriercalls. Typecheck/build/nativeNodevoicepass. Latest12turnsynthetic
373.147ms p50/409.488ms p95; targetPASS,allfakeprovidersclosed, no liveclaim.
Logs/tmp/phase6-transfer-{final-full-docker,postgres,browser,benchmark,kill}.log.

Schema2026-10-27-call-transfers adds2tables; onlyisolatedlocalSQLite/disposablePG
migrated, NOTSupabase. PrimaryAPI61494/worker73112/Next80523 restartedpre-killfix
uncommittedtransfercode withsafehelper+Redis6399+LIVE_TRANSFER_ENABLED=false;
health/ready/frontend200. Restartaftercommit forfinalkillcode. Networkdraft last
recovery72842c1 needsrefresh; savingnotpublication. Main/private.env unchanged.

NEXT remainingvoice toolSQL offload (http_tools/scheduling/connectors); concrete
notes /tmp/voice-sql-next.md. CurrentCal.com officialmain bookingcontroller200/read
/tmp/voice-sql-ref-calcom-official-source.txt; GoogleofficialSDKfreebusy200/read
/tmp/voice-sql-ref-google-official-sdk.txt. RenderedCal.com/Calendly/Google docs
URLError27Oct; no contractchange assumed. Fetch/readGoogleevents insert and
Calendly officialcurrentrefifreachable beforetouching; DBoffload mustpreserve
existingwirecontract/consent/replayguards. ThenPhase6finalchecks/liveacceptance
limits, restorepausedrightsWIPrefs/codex/paused-data-rights35e5fbb andcomplete
originalPhases3/4/5/7. Rightsintegrates callbackoutboxprefix and transferciphertext/
activeholds/financialshell; newCallTransferFK can affectcallpurge. Do notloseWIP.
Noagents. Continue; no partialfinal. Push normalfastforwardaudit only.

## Phase 6 callback checkpoint — 27 October 2026

72842c1 core lifecycle pushed audit; FULL Docker752pass2skip429.77s belongs tothat
commit. API86480/worker18336/Next61319 restarted72842c1 safehelper isolateddata+Redis
6399; health/ready/frontend200. Recoverydraft refreshed to72842c1, NOTpublished.

New confirmed manualcallback flow: explicitE164phone, phonecollection/readback,
laterToolConsent confirmation, oneinboxticket+owneroutbox atomically/idempotently.
Unverifiedphone/callbackonlypermission/nonpromisedtime labels; noautomaticdial.
Flag CALLBACK_REQUESTS_ENABLED, editor tooloption. No callbackword-only routing:
supportticketaboutcallbackfunction stayssupport. Phone/time evidencechecks and
cancel/unrelatedquestion handling. Existinginbox open/pending/resolved flow.
Final54pass1skip25.60s afterwordingfix; precedingbroader146pass3skip81.48s;
initial45pass14.51s. ActualwidgetHTTP andvoice-sessionconfirmation tested; type/
buildpass. Newfrontendbuild meansNextrestartneededaftercommit. No livemeasurement.

NEXT livehumantransfer fulladapter+boundedtwo-legcost+signedcallbacks/unknownstate
behindflag/fakeproviders, thenremainingtool-specificSQL/livePhase6, thenoriginal
Phases3/4/5/7. CurrentPlivoDial docs FOUND/read20027Oct:
https://docs.plivo.com/docs/voice/xml/routing cached/tmp/phase6-transfer-plivo-routing.txt.
DialtimeLimit/timeout/action pluscallbackUrl hangup DialBLegDuration/BillDuration;
A/B legs separatelybilled. Calls.transfer aleg_url/current TwilioCallupdate+Dial
refs cached asbelow. No integrationcodeyet. Callbackprivacy: queuedEmailOutbox
operation_key starts exact Ticket.operation_key + colon; integratepurge withrights
WIP. Keep pinnedstashref35e5fbb, main/private.env/Supabase unchanged. Noagents.


## Phase 6 core media lifecycle checkpoint — 27 October 2026

7448940 disconnect checkpoint pushed audit. Browser/Plivo/Twilio admission,
context loading and settlement offloaded to threads. Workspace→call lock order;
localowner claimed beforeyield. Shield initialize until commit/session outcome
observed: canceled setup/constructorfailure stillsettles admittedcall; invalid
reused handshake cannot settle someone else's call. Shared media_lifecycle cleanup
owns all tasks/providers, durable settlement/recordings, finally ownershiprelease.
Plivo nowconnecting/ringing only; bothcarriers enforceadmittedduration andSTTusage.

FULL actual Docker+Redis **752passed2skipped0failed429.77s**. Two skips are
provider-inapplicable scheduling params, no sandbox skip. Typecheck/build/native
Node voice checks pass. Focused13pass6.37s plus earlier47pass25.87s. Actualsocket
SQLhooks fail if SQL executeson eventloop; cancellation/constructorfailure/
duplicatehandshake/silence tests pass. Latest12turn synthetic371.302ms p50/
418.463ms p95 targetPASS,1modelclient12requests12Fishsocketsallclosed. No liveclaim.
Logs /tmp/phase6-audio-{full-docker,client,benchmark}.log.

NEXT transfer/callback flow with flags/fakes; remaining tool-specific asyncSQL
(scheduling/connectors/http_tools still have blocking DB sections), live/provider
acceptance, then originalPhases3/4/5/7. Do not claim all async paths offloaded.
Transferresearch officialTwilio Call resource/Dial200 andPlivo /docs/voice/api/calls
200 +rawSDKcalls.py200 cached /tmp/phase6-transfer-*.{ref,txt}. Twilio updatecall
URL/twiml/timeLimit; DialtimeLimit/timeout/action DialCallDuration; Plivo transfer
aleg_url fetchesXML, bothlegs separatelybilled. Plivo guessed/dial URL404: find
currentDial docs beforeimplementation. No integrationchange made fromthatresearch.

Current primaryruntime stillf001902 (API PID1232299,worker1232375; inspectbefore
restart); frontendbuildchanged.next. SafehelperisolatedSQLite/localobjects,
Redis6399, allrealkeys cleared. Next restartaftercommit. Network draft additions
saved revision9, activationnotproven. Preserve main/private.env/Supabase andpaused
rightsWIP35e5fbb pinnedrefs/codex/paused-data-rights. Noagents. Continue audit.

## Phase 6 recognition disconnect checkpoint — 26 October 2026

ec128b6 greeting cache pushed audit. Recognition unexpected EOF/exception/badJSON
sets provider_failure; all3socket loops race it against incoming receive and clean
up as failed immediately. Normal cancellation/shutdown notfailure. Rawprovider
errors not forwarded. Actual local Twilio WS test proves disconnect→closed/fail/
STTcost. FixedTwilio bypass: recognition_audio enforces admittedduration and counts
PCM, record_audio_usage calledatsettlement. No carrier format/auth changes.
Focused62pass27.87s; native7pass2.79s; final180pass3skip81.70s. Twilio/Plivo official
rechecks200/read; attemptedDeepgram3refs403, no undocumented API changes. Latest
fullDocker700pass2skip still6186189. NEXT audioSQL offload (including durable
admission outcome/settlement oncancel), transfer/callback, full/livePhase6, then
originalPhases3/4/5/7. Preserve main/private.env/Supabase/pinnedrightsWIP.


## Phase 6 greeting cache checkpoint — 26 October 2026

083f8e2 Fish setup pushed audit. Static greeting cache now keys workspace/version/
exact spoken text/voice/model; runtime variables (declared or bound), missing
version/unresolved templates exclude. Includes exact AI/recording announcements.
Bounded transient memory64entries/4MB/512KBclip/1hTTL DRAFT; flag disables. Only
successful full greetings cached, no silence/answers/readbacks. Replays preserve
transcript/PCM/recording with no fresh Fish request/reservation/cost. Call allowance
admission still applies. No provider contract change. Tests44pass11.82s focused,
161pass3skip65.65s broader; no new measured cache-hit latency claim.

NEXT remaining audio-loop SQL offload, recognition disconnect/cleanup, human
transfer/callback with feature flags/fakes, fullPhase6 checks/live acceptance,
then originalPhases3/4/5/7. LatestfullDocker700pass2skip at6186189; runtime still
f001902 isolatedsafehelper. Main/private.env/Supabase/pinnedrightsWIP unchanged.


## Phase 6 Fish connection checkpoint — 26 October 2026

b0a83a7 prefetch pushed audit. FishCall now owns empty-started generations and
opens during SpeechStarted or response safety/retrieval. Every response/toolround
uses the prepared socket. Documented stop/finish closes it, next turn opens early.
No invented flush ack/quiet-time confirmation; original reference-rule permits
docs-driven adjustment, recorded DECISIONS. VOICE_FISH_PRECONNECT_ENABLED flag.
Durable bounded setup/stream/close cleanup and TTS settlement. Odd PCM and premature
finish rejected. Explicit adapter fakes replace old media.speech_stream patches.

Final156pass3skip62.07s; focused46pass17.73s. Same12turn synthetic368.356ms p50/
429.452ms p95,1modelclient12requests12Fishsockets allclosed. No live claim. Latest
fullDocker700pass2skip still6186189. CurrentFish3refs rechecked20026Oct; protocol
unchanged. Main/private.env/Supabase/pinnedrightsWIP preserved. Primary runtimes
stillf001902; environment network draft saved requires review/save/publication.
NEXT static greeting cache (candidate /tmp/voice_greetings.py), audio DB offload,
provider disconnect tests, transfer/callback, full voice verification, thenPhases
3/4/5/7. No agents. Continue; do not stop at checkpoint. Push audit normally.


## Phase 6 interim prefetch checkpoint — 26 October 2026

f001902 transcript checkpoint is pushed audit. Bounded InterimPrefetch now owns
250ms debounce, max2 requests/utterance and max2 active across resets, five-second
TTL; all DRAFT configurable and feature-flagged. Exact normalized final query +
snapshot IDs only, published/tenant/current passage revalidation. No model/tool
speculation. Already-paid embeddings finish for usage; close owns all tasks.
Embedding admission/settlement/client-close durable through cancellation;
max_retries=0 avoids ambiguous unreserved POST replay. Nine new tests.
Focused36pass16.55s, regression140pass2skip60.50s. Normal-path synthetic12turns
425.384ms p50/454.522ms p95; DOES NOT measure interim-prefetch savings. Latestfull
Docker700pass2skip still6186189. No frontend edits since verifiedf001902.

Network draft revision updated: preserves previous custom hosts, adds Microsoft
docs/GitHub API/Fish API/Deepgram API/configured Azure endpoint hostname. Saved,
requires publication; runtime access NOT proven. No secret values saved/printed.
API37777/worker24803/Next26635 restartedf001902 isolated SQLite/localobjects,
Redis6399, real keys cleared; health/ready/frontend200. Inspect before restarting.

NEXT finish Fish connection lifecycle/parallel setup and static greeting cache,
remaining audio DB offload, transfer/callback, full/live voice verification, then
originalPhases3/4/5/7. Fish stop/finish closes socket; no documented flush ack.
Never invent a quiet-time consent-completion guarantee. Pinned rights WIP at
refs/codex/paused-data-rights unchanged. Preserve main/private.env/Supabase.


## Phase 6 transcript checkpoint — 25 October 2026

c142a59 pool pushed audit. New delta-v1 handshake in dashboard/public voice;
server.ready advertises selected mode; absent request keeps legacy fullpartials.
Transcript helper stableturnID, seq and Unicode-codepoint retain+delta supports
assistant append and STT revisions. Finalassistantid=Trace.turn_id; onefullfinal.
Shared browser TranscriptStream bounds memory/text, ignoresduplicates, rejects
gaps/badprefix/staleepoch, finalrepairs. VoiceLab resets state onnewcall. Deepgram
finalsegments accumulate before interim; speech_final/UtteranceEnd sameuserturnID.
Endpoint/audio parameters unchanged. DECISIONS records current official docs.

Final114passed3skip77.54s; focused45passed15.27s. Native Node shippedTS codec+
connection checks pass Unicode/revisions/seq/epoch/legacy+newhandshake/resource
cleanup. ActualTestClientWebSockets negotiatebothmodes.100fragmentwiretest <1/3
legacyserializedbytes. Typecheck/buildpass. Same12turn syntheticdelta-v1 now
444.298ms p50/502.299ms p95, targetPASS,1modelclient/12requests/12Fishsockets,
allclosed; no liveprovider claim. Latest FULLDocker700pass2skip is6186189 code.

NEXT Phase6 stable-interim prefetch/parallel setup, static per-version greeting
cache, remaining audio SQL offload, persistentFish contract resolution, human
transfer/callback, liveacceptance and phasefullverification. Credential presence
checked without printing values: OpenAI/Fish/voiceID/Deepgram/embedding/vector
configured inprivate.env; LLM endpointfamilyAzure. Do not inventmissingkeys or
use suppliedSupabase. For livechecks, isolatedDB/localobjects and selectivekey
bindings only, bounded billedinput; no realphonecalls. Azure rendered docs
reasoning/responses URLError and guessed old MicrosoftDocs rawpaths HTTPerror;
find current official path before changing Azure contract. OpenAIembeddingguide
read200 cached /tmp/phase6-official-adapter-2.txt for upcoming prefetch work.

Primarysafe API/worker/web still6186189 asbelow; frontendbuildchanged.next so
restartafterthischeckpoint beforepreview. Draftsavedrecovery6186189 notpublished.
PinnedrightsWIPunchanged; aftervoice originalPhases3/4/5/7 stillrequired. Noagents.

## Phase 6 LLM keepalive checkpoint — 25 October 2026

6186189 pushed audit; final FULL Docker700passed2skip502.03s belongs to that
OpenAI checkpoint. New call-owned LLM pool max2 endpoint/keyhash/public-policy
entries, no cross-call/workspace sharing. Resolve profiles EVERY turn; no cached
permissions. FlagVOICE_LLM_KEEPALIVE_ENABLED can disable. Existing custom SSRF
transport remains. Browser/carrier/Twilio cleanup closes pool after interruption;
durable_await now shields async close through repeated cancellation too.

Native real-SDK localhost TCP/SSE test caught 2connections/2turns despite reused
SDK object. Added <=250ms terminal tail drain after authoritative completed/
incomplete event: normal2turns now1TCP connection, missing tails discard/open2
connections without generation replay. Final123passed2skip74.94s; final9pool
cases6.20s inclnormal/missing-tailTCP. Earlierbroader193pass3skip111.83s preceded
drainfix. Same12turn synthetic430.061ms p50/480.276ms p95, targetPASS,1modelclient/
12requests/12Fishsockets, allclosed. No live measurement or Fish reuse claim.

Primary API36147/worker77640/web48602 restarted from6186189 with safe helper,
SQLite/localobjects, Redis6399, providerkeys blank. Health/ready/frontend200;
newtimingtable migrated normally locally. Environment draft recovery refreshed
and saved, NOTpublished. Pinned rights WIP untouched. Next transcriptdeltas/
interim prefetch/parallel setup/static greeting/audio DB/transfer callback and
persistentFish contract resolution, then originalPhases3/4/5/7. Continue all
authorized work. No agents. Commit/push normal audit. Do not reset/force main.

## Phase 6 OpenAI checkpoint — 25 October 2026

Immediate speech bd8f9c3 is pushed. OpenAI checkpoint now verified: official5.6
voice forces Responses with explicit none/low effort. Explicit30m cache uses a
stable developer policy and optional static USER guidance; dynamic date, visitor
variables/evidence/history follow. Personalized guidance is not cached. Keyed
workspace cache key, store=false, VOICE_PROMPT_CACHE_ENABLED switch. No padding,
no measured cache hit or live quality claim. Tool delta/done state is bounded;
only completed output authorizes tools. Incomplete preserves usage, interrupts
history and records failed timing; public voice permits same-call follow-up.

DRAFT cache-write rates30m1.25x/12h2.5x, disjoint input/read/write accounting and
maximum30m admission. Existing tariffs immutable. Schema3 NEW snapshots pin
current provider catalog separately from subscription retail terms. Legacy
Responses disables writes; legacy Chat fails before I/O. Unknown/unpriced usage
retains holds/facts; unpriced writes pause spending. DRAFT economics now prices
all-input write exposure without assuming cache savings. Durable thread helper
observes even repeated cancellation; preflight failures release unused holds.

FINAL FULL actual Docker+Redis:700passed2skipped0failed502.03s, fresh owned pytest
root avoids old cleanup warnings. Focused47passed15.46s. Typecheck/build pass;
Node shipped connection fake-browser check proves incomplete follow-up and
fatal mic/audio cleanup. Real disposable PG admission/immutability/shared Free
acceptance passed. Same12turn synthetic fixture426.834ms p50/693.015ms p95,
--assert-target passes; no live provider measurement. Initial broad668pass2fail
26skip375.54s was mixed code/config edited during its run; final stable run green.

NEXT finish Phase6: bounded per-call LLM clients, persistent Fish lifecycle,
interim retrieval prefetch/parallel setup, static per-version greeting cache,
transcript deltas, remaining audio DB offload and transfer/callback. Candidate
LLM pool/tests prepared ONLY at /tmp/phase6-next (not yet in repo); official SDK
README/current async close source read200. Deepgram interim/endpoint/SpeechStarted
and Twilio media message/Stream docs read200, cached /tmp/phase6-official-*.txt.
Plivo old www URLs failed; current docs.plivo.com/docs/voice/xml/audio-streaming/
and raw SDK streamElement.py read200. Read relevant text before touching those
integrations and add URLs/date to DECISIONS when implementing. Fish raw audio
events have no generation ID/flush ack; finish only at stop and closes socket.
Do not claim a quiet timeout proves spoken consent was fully presented.

Then restore pinned rights WIP refs/codex/paused-data-rights and complete original
Phases3/4/5/7, preserving known visitor/reschedule fixes below. Do not stop at a
checkpoint. Main/private.env/Supabase unchanged. Primary runtime is still step4
code; restart safe isolated API/worker/web after commit (new timing table additive
normal dev startup). No agents authorized. Push normal fast-forward audit only.

## Phase 6 incremental speech checkpoint — 25 October 2026

Instrumentation a1a1e08 pushed audit. Removed80char/punctuation batching; forward
eachsafeLLMdelta, actualSDKFlushEvent atsentence/turn andbeforetoolwork. Control
eventsnottext/transcript/billedbytes. PCM/balanced unchanged. SpeechBudget uses
configVOICE_TTS_RESERVATION_BYTES512 windows, checksrealcapsbeforeforward, local
counterperdelta, exactactualbytes settle, unusedholdsrelease. Shieldedgranttask
observedbeforecancelsettlement; clearbeforeawaitcleanup, detacholdtaskfirstto
avoidlosingnewTaskpointer orcancelingcleanup twice. Audioiteratoraclosing on
consumerfailure; sender/recv raced, prematurefinish rejected, ownedtasksdrained.
KnowledgeSQL/ranking+profileReads+confirmationfinalDB offloadedthreads. Socket
admission/constructor/finalDB broaderblockingwork remainsPhase5/pipelinework.

Final synthetic12samefixture423.657ms p50/468.694ms p95 (--assert-target PASS);
priorincremental414.344/473.207. Baseline2331.229/2391.771. Actualmedia/admission/
metering/MessagePack; fakeprovidersONLY, no liveFish/OpenAImeasurements. NewCIstep
assertstargetafterfullsandboxsuite; hostedunconfirmed. Final147pass2skip59.70s,
10newstream/budget/threadchecks; oldPCMfakeignoresFlushpreserving100msassert.
DocsVOICE_LATENCY/VERIFICATION/DECISIONS/checklist updated. Committhischeckpoint,
then OpenAIeffort/cache/writebilling/incomplete/tool events and persistentFish/
LLMconnectionreuse/prefetch/greetingcache/transcriptdeltas/transfercallbackstill
ACTIVE. Phase6NOTdone. KeepvoicebeforePhases3/4/5/7, paidphoneflagoff.

ResearchcanonicalFishguidesHTTP200; bestpracticesgeneric5–10wordbatchcontradicts
realtimeguideno batching, followlatter. Connectionkeepalive recommended butraw
protocolstartonce/text/flush/stop; stopfinishcloses, NOdocumentedflushack. Plan
persistentcontinuousstreamcarefully; neverinventack ormarkspokenconfirmation
presentedonmerequiettimeout. Barge-in mustclose/canceloldFishgeneration andclear
queuedaudio. Existingfullreadback+next-turnencryptedconsentmustremainstrong.
OpenAIcache breakpointinput_text blockwithinDevelopermessage, top.instructions
unsupported; writepremium+cache_write_tokensneedpropernewDRAFTrates/reservations
andoldtariffcompat (do not enable unpricedwrites). Docsfiles /tmp/*phase6.ref/.txt.
PinnedrightsWIPstash/refstilluntouched. Primaryruntimesstillcommittedstep4; fresh
instrument+streamcodeonlytestprocesses, newVoiceTimingtablemigrationpendinglocal
startup. Nevertouchprivate.env or suppliedSupabase. Noagentsauthorized.

## Phase 6 instrumentation and baseline checkpoint — 25 October 2026

Step4 fed9f9f pushed audit. Environment restored and finalstep4fullfast recovered:
623passed26skip0fail359.55s; docs/handoff committed. PrimaryAPI/worker/web restarted
safe isolatedstep4 (sessions19639/72347/32431), Redis6399; QA3112 stopped. Never
claim phase-specific environment incompatibility: outage was entireexecsession.

Voice instrumentation now implemented FIRST, before changing buffering/provider
contracts: new VoiceTimingRecord tenant/callFK (CASCADE onphysicalcall purge),
schema2026-10-25-voice-stage-timings, ContextVar Trace monotonic perturn, lifecycle
source/status, DBpersist thread onlyonce/turn, sanitizeronmetricfailure. Actual
media recognizes final receipt, retrieval/safety/admission, LLMrequest/firsttoken,
Fishconnect/text/firstbyte/firstframe. APIcall detail voice_timing latest50 with
nearest-rank source-separated complete-STT quantiles, failure/interruptioncounts;
noaudioNULL andgreetings excluded. NewCallLatency feature component inCallDialog.
No Fish/requestparameters or80char/punctuation buffering changed yet.

Measured baseline script12turns:2331.229ms p50/2391.771ms p95, p50 targetMISSED.
SyntheticVoiceProviders fakes onlySDK/WS/retrievalboundaries; actualLLMwrapper,
promptguard/admission/cost/MessagePack/mediaframe code runs. Fake delays .04
retrieval/.18firsttoken/.05tokens/.04Fishconnect/.12firstaudio,38words+done.
Artifactartifacts/voice-latency/baseline.json. Scriptsbenchmark_voice_latency.py
andvoice_latency_fixture.py. --assert-target failsonmiss; CIgateNOT yetadded.
8timingtests3.93s;113legacyregression+2skips59.43s, type/build pass. Fullphase
suite later. Commitinstrumentcheckpoint thenimmediateFishdelta/flush/session/
barge fixes and OpenAIvoiceeffort/cache/incomplete/toolstream implementation.

Providerrefs currentHTTP200 listedDECISIONS; readable /tmp/openai-{cache,stream,
functions}-phase6.txt nowgenerated with.venvPython/bs4. Explicitcache breakpoint
oninput_text block insidedeveloper message (top-levelinstructions unsupported);
modeexplicitwithoutbreakpoint disableswrites. Cachewritepremium requiresrate+
reportedwrite-tokenmeter/hold updates, legacytariffs mustnotgetunpricedwrites.
Fishstopcloses, flushhasnoperturnack; inspectofficialSDK/bestpractices before
persistent-session design. KeepallprovidedFakes/syntheticresults separatefromlive.
Next latencyrealcode thenPhases3/4/5/7; pinnedrightsWIPref remainsuntouched.

## Revised step 4 complete — 25 October 2026

Step3 9311040 pushed audit. Step4 now verified: DRAFT workload configuration and
restricted operator economics report/UI compare every configured model's chat,
browser voice, phone and combined allowance exposure, with loss/cap-delivery
flags. All current DRAFT plans flag loss exposure; paid activation remains off.
Original user sponsors Free workspaces through immutable Workspace field
free_allowance_user_id. New schema2026-10-25-shared-free-allowance adds/backfills
earliest owner and DB reset protection. User row locks serialize shared quotas,
inventories and provider cap; UTC monthly pool, old unknown holds retained.
Meter events now pin tariffs; historical Free facts survive upgrades/ownership,
new paid usage excluded, old untagged facts conservative. Only sponsor browser
receives cross-workspace aggregate; members/API keys retain workspace-only data.
No extra financial ledger tables: existing immutable usage/cost/tariffs retained.

Verification: focused48passed28.64s, prior52passed1skip26.03s, type/build pass.
Full fast first622pass1fail26skip316.86s exposed another old30ms crawl overlap
assumption; actual event rendezvous fixed it, targeted2pass2.63s. FINAL fast
623passed26skipped0failed359.55s, Docker shim0calls+realRedis. Four old cleanup
warnings. Session disconnected during finalrun; recovered its completed result
after environment restored. Actual PostgreSQL:24spend10accept14deny; threeWS
sharedFree24requests9accept15deny plus1used=10cap; sponsorbackfill/reset/migration/
immutablefacts passed. Actual Chromium billing/Free/economics/model switch/kill/
checkout/PDF passed0errors, fakegateway isolated. Docs updated, commit/push audit.

NEXT step5 Phase6 voice instrumentation FIRST, then protocol improvements and
measured synthetic latency, BEFORE remaining Phases3/4/5/7. Environment currently
restored, no phase-specific incompatibility. Main/private.env/Supabase unchanged.
Paused rights WIP ref below still required after voice; do not lose it.

Official Fish/OpenAI docs now HTTP200 on25Oct. Cached /tmp/fish-index-recheck.ref,
fish-python-ws-recheck.ref (redirect realtime guide), fish-realtime-guide-phase6.ref,
fish-live-protocol-phase6.ref (full embedded AsyncAPI); raw asyncapi.yml HTTPerror.
OpenAI /tmp/openai-{reasoning,latest-model,migration}-recheck.{ref,txt},
openai-{cache,stream,functions}-phase6.ref. Render .ref HTML via installed bs4 for
readabletext if needed; defaultsystemPython lacksbs4, use .venv/bin/python.
Latest-model verified5.6 sol/terra/luna, effortsnone..max defaultmedium independent
promode, Responsesexplicitcache. Cachewrites cost1.25x uncached: research precise
reported cache_write_tokens/options/breakpoint before updating holds/metering.
Fish startonce emptytext, eachdelta, flush immediate, balancedlowestTTFA, PCM.
stop sendsfinish thencloses socket; flush lacks documented turncompletion ack.
Design persistentcall session/cancellation using actualprotocol, no inventedack.
Existingmedia.text_chunks still80char/punctuation gates, providers.speech_stream
newWSperturn, so Phase6NOT implemented yet. Instrument stages before changing.

PrimaryAPI/worker lastrestarted committedstep3 (sessions21119/32205), web65674;
ownedRedis6399 noeviction+persistenceoff, actualhealth/ready200 beforeoutage.
SeparateQA Next3112 session95311. Step4 frontend build changed output; restart
primary after commit with isolated helper+REDIS_URL6399 on all processes. Local
SQLite may need safe additive step4 migration through normal dev startup; never
run fixture resets on it/Supabase. Reinspect PIDs/listeners after restore.

## Revised step 3 COMPLETE — 25 October 2026

Step2 bdf061e pushed audit; gh workflow-status read403, no hosted result claimed.
Public four assets cache60s/must-revalidate, actualETag304; HTML stillno-store.
New widget_frame_cache.py Redis hash loadclaim+CAS, five-second TTL boundedproof
expiry, persistent transactionguards serializedWS beforeflush/bulk Agent/
Installation/OriginVerification/Workspace edits. Outerend releasesonlyown guard;
savepoints retained. RealAPI authnevercached. ConfiguredRedis outageblocks
unfencedwrites503; readsfallthroughDB/API; unavailableAPIselfonlyCSP. noeviction
required/checked, Composechanged; webjoinsRedisdefaultnetwork; sharedserver
namespaceconfig. DryrunrecoveryCLI holdsWSlock. New@redis/client6.3.0 official
sourceverified, connect/socket/commanddeadlines/offlinequeuebounded. Dockerweb
buildCOPYconfigfix (legalalreadyrequiredoutsideapp). DocsWIDGET_CACHE refs.

Verification:focused38pass23.73s, final8Redis6.49s inclrecovery; FULLfast611pass
26skip0fail306.62s Dockerunavailable/shim0calls+realRedis. Type/buildpassed.
NativeisolatedAPI+Next ephemeralports+actualChromium fourcacheableassets/four304,
warmwidget0policyAPIcalls/freshnonce, revocationnextrequest, guard+APIoutageself
only, legalhydration0errors. QAartifactartifacts/widget-cache/results.json.
Primarypreviewneedsrestartafterbuild; no DBschema/privateenv changes thisstep.

NEXT revised4 addDRAFTunit economics phone/browser/chat allowance-lossflags and
cross-workspaceper-userfreeallowances (operatorview/killalreadydone). ThenVOICE
Phase6instrumentfirst BEFORErestoredrightsWIP/Phases3–5/7. Do notstopatpartialfinal.

## Revised step 2 COMPLETE — 25 October 2026

Step1 e28e924 pushed audit. Local pytest now skips marker `sandbox` unless
`--run-sandbox`; CI=true/1 without flag errors. Real runtime remains failclosed.
24 sandbox cases marked; dictation split authorization and actual FFmpeg path;
health aggregation unit tests fake health only. Three subprocess contract tests
prove skip/CI rejection/missing-Docker failure. New backend GitHub workflow pins
current official action SHAs, installs Chromium/Poppler, requires Docker/builds
runtime, real Redis service, full --run-sandbox --strict-markers. Hosted run not
yet claimed. Fast FULL603passed26skipped403.19s Docker shim97+badDOCKER_HOST,
zero Docker invocations. Initial Docker626pass1fail2skip550.80s:30ms renderer
overlap flaky. Replaced delay with actual two-renderer rendezvous; focused4pass
9.52s. Final FULL627passed2skipped0failed445.27s actualDocker+Redis. Four old
root-owned pytest garbage cleanup warnings only. Docs updated. New counts include
split dictation+three policy probes. No private config/remote DB/main changes.

NEXT revised3 static headers and brief safely-invalidated frame-policy cache,
then4 economics/free-user abuse,5 voice FIRST,6 remaining Phases3/4/5/7. Paused
rights WIP ref below remains intact. Step3 preparatory files/dependency may be
uncommitted separately from step2; do not accidentally include in step2 commit.




## Revised user order / step 1 COMPLETE — 25 October 2026

Latest user explicitlyreprioritized:1fixredtests+FULLDocker suite/exactcounts incl
6bookingcases missingmodel,dictation,documentupload;2opt-in sandboxpytestmarker
localfastskipmandatoryCI;3publicstaticassetcache+briefsecureframepolicycache;
4operatorview(alreadyC5)+NEWper-plan unit economics DRAFT phone/browser/chat
allowance-lossflags+cross-workspaceper-userfreeallowanceabusecontrol;5Phase6voice
latency BEFOREPhases3–5, instrumentfirst/useprovidedFish/OpenAIrefs/reportonly
measured;6thenPhases3/4/5/7(originalfullscope). Do notstopatcheckpoint/partialfinal.

Phase3item1 b532421 committed/pushed andverified32tests/nativebrowser/PG. Existing
missingmodelstubfixes alreadyC5 4dc5473 (FULL605pass2skip428.41sPhase2); userwants
explicitbehaviorregressionandfreshfullcurrenttree. llm.Turn nowfailsHTTP409clear
nonemptymodelerror inallenvs, no inventedfallback; fakesmustdeclaremodel. Added11
contracttests in test_custom_runtime.py. Focused121passed2skipped93.68s; FULL623passed2skipped0failed433.23s withDocker
andrealRedis. Dictation/uploadand6bookingcasespass. Fouroldpytestcleanupwarnings.
Docsupdated, commitstep1 thenstep2 opt-in sandboxmarker+mandatoryCI.

UNCOMMITTEDPhase3item2rightsWIP saved SEPARATELY to avoidmixingrevisedwork:
stash35e5fbb9423f51261254344dbd24520e2775ada9, pinnedlocalref
refs/codex/paused-data-rights. Do notdrop/lose it. Restoreandresolveaftervoice when
returningtoPhase3. Stash containsdetailedAGENTWIPentry+config/newprivacy modules/
models/guards/workers/test5. Two knownfailures: Conversation has NO.visitor field
(realvisitor data in ConversationContext.variables['_widget_lead']); WIP wrongly
uses.visitor inDomain/Privacy modules. Fixwithproperdedicatedmarker/actualcontext
schema, notguessing. Accountdeletecancel+reschedule reusedcanceledchildkey
'account:'+row.id; needkeyalsoincludeaccountdue timestamp/newrequestgeneration.
WIPdataflagfalseandnoactualerasureeverrun againstprimaryDB. SomeWIPguards baseline
15tests14pass1failConversation.visitor; newrights5tests4pass1reschedulefail. Entire
WIPpreserved beforelateststep1work, no originaluserchangesstashed (.envunchanged).

PrimarylocalAPI/worker/webstillcommittedlegalb532421inmemory (noautoreload), safe
SQLite data/cloud-local/studio.db+localobjects,providercredentialsblank/paidfalse.
Sandboxstudio-content-localhealthy; Dockeravailable. OwnRedis6399 session62605.
Noagentsauthorized, auditonlyfastforward. Remote mainindependentlymergedPR#1 as
04246a8; preserveit; neverrevert/force main. Onboardingdraftsavedinstallscript+safe
helper includesPoppler/payment/operatorclears; notpublished. Allprices/legalDRAFT.

## Phase 3 item 1 complete — 25 October 2026

C5 4dc5473 pushed audit. Main independentlymergedPR#1 as04246a8 (observedvia
lsremote+fetchonly); preserve it, no mainwrite/revert. Legal config/legal.json
DRAFT fivepages /legal/{terms,privacy,cookies,acceptable-use,dpa}, sharedfrontend
JSON+validatedbackend. Required unchecked currentversion signupacceptance;
LegalPolicySnapshot/LegalAcceptance append-only tables, hash/timestamp/source/
keyedIPhash no rawIP. Existing-accountsignup cannotacceptnewpolicy forowner.
Historical publicsnapshots andown acceptanceAPI. NewGoogle signup Originchecked
POST/signup-intent signed600sHttpOnlycookie copiedinto encryptedOAuthstate,
cookiecleared, callbackcurrentpolicyguard beforeaccountcreation; existing signin/
link/calendar checks retained. No providertransportparamschanged. CurrentGoogle
OAuthlib1.5.0 source moved tomonorepo; officialmetadata+SHAverifiedwheelandraw
source read200, URLs inDECISIONS; renderedOIDCguide/discoveryURLErrornotread.
Next installeddynamicparams/metadata/CSP/notFounddocsread. Unknownlegalroute
Proxyguard returnsreal404 beforestream; same strictheaders. QAhelpers explicitly
acceptcurrentpolicy; directsignupfixtures updated. Tests32pass13.16s, type/build,
actualChromium5pages/404/uncheckednoPOST/checkedserverversion0errors, PGlegal
immutability+financialregressions pass. FullPhase3checks afteritems2–4. Nolegal
wording approved, noactualGoogle/SMTP. LegalpolicyAPPROVED withDRAFTtextinvalid.

LOCALAPI/workernowPhase3legal (sessions98292/1109); web74645 currentlegalbuild;
DBsqlite/objects isolated, providerkeys/paid/operatorflagsfalse, .envuntouched.
NativeQAcreatedone local legal-browser workspace only. Sandbox unchangedready,
Redisown6399 session62605. Noagentsauthorized. UserlatestContinue preserves
fullscope; no checkpoint/partialfinalstop. NEXTPhase3item2full rights/retention,
then3callsconsentDNCwindows/complianceack/workspacephoneapproval,4widgetvisible
AI/privacy/consentemailoff. ThenDphases4/5/7 andE6original. Full original70lines
inattachments pathalreadyrecordedbelow. Budget controls/immutabilitymustremain.
Existingagent_deletion module offersfencedstorage/Qdrantpurgepatterns. Financial/
legal/audit lawfulretention exceptionsDRAFT mustdocument, neverdropalltriggers.
Localonly fakeproviders wherecredentialsabsent; externalcredential deferrals only
forliveacceptance, neverbuildablecode. Pushnormalfastforwardauditonly.

## Phase 2 complete / item 5 — 25 October 2026

C4 b59eb36 pushed audit. C5 operator billing: empty BILLING_OPERATOR_EMAILS,
actually verified browser+CSRF only, APIkeys reject even withcookie. DRAFT INR
contribution/net subfees+settled livewallet -estimatedprovider/reportedfees;
walletfunding excluded, missingusage/fees+all-age holds explicit. Globaltop10,
workspacecursor/literalsearch, auditedkill/cap. Admission/watcher stop; resume
cannotclear financialblock/holds. Generaljobcancel/retry nowalso billingwrite
forfinancialjobs (closed indirect KB-key path). Restricted deadletter receipt/
job reviewretries preserve original dispatch/idempotency. Operatorrefundexceptions
BILLING_OPERATOR_REFUNDS_ENABLED false; subrefund queuesfuturebillingcancel,
refundreview remains acrosslateactive/refundedcapture replay, endcoverageFree
onlyafterterminal providercancel+settledrefund. INRwallet mismatchesblocked.

FULL605passed2irrelevant alternate-provider skips428.41s realRedis. Fourwarnings
oldrootpytestgarbagedirectory only. Initialfullfailedon8oldfakemodelprofiles+
helperorigininheritance; fakesnowexplicitmodel andpytestpinsownorigins. Focused
89passed2skipped56.12s,21currency/widget/website/operator14.61s. Typecheck/build
pass. Native actualNext+isolatedAPI/sandbox fakegateway topup11800/10000credit,
signedsubscription/PDF/paidflag/operatorpause-resume/accessremovalpassed0errors.
PGaggregates+missingfees/leasefencing/4receipts1credit/12uniqueinvoicespassed.
Docs DECISIONS/BILLING/VERIFICATION/checklist honest. .env/main untouched.

PRIMARY LOCAL API/worker nowlatest Phase2; sqlite data/cloud-local/studio.db,
privateobjects local, providercredentials cleared, paid/operatorflagsfalse,
health+ready pass. CurrentAPI session1829 worker30770, productionweb10282
(latestbuild mayneedrestartafter cosmeticoperatorCSS). Mandatory updated
sandbox studio-content-local ready. Redisown6399 persists, session62605.
~9.8GBfree. Popplerinstalledrequiredtest. Onboardingdraft revisionupdated via
update_environment_config_draft afterreadrevision5: installscript Popplercheck,
clearsRazorpay/operator values; savednotpublished, preservesstart_skill. Local
helper andinstallscript matched; never edit/print.env or suppliedDSN/keys.

NEXT D Phases3/4/5/7 then E6 exactlyoriginalprompt. Read originaluploaded70lines
/workspace/attachments/a04a0fd7-d18d-4726-b794-08da11e2f2d6/Pasted text.txt.
Noagentsauthorized, no firstblocker/partialfinal. Perphase shortplan/fullpytest/
typecheck/build; tests+commits peritem on auditonly, main0fc290c. Defaultbrand
Voice Studio, commercial/legal/provider-rate values DRAFT, flags/fakeproviders
forbuildablework. Only liveacceptance credentials maydefer, explicitlynamed.
Phase3 plan: versionedDRAFTlegalpages+requiredsignupacceptance; fullselfserve
account/workspace grace deletion+visitor/contact export/delete+retentionpurges;
consent evidence/DNC/recipientwindows/campaignack+verifiedworkspacephoneapproval;
widgetAI/privacy/consentemailoff. Existingagent_deletion.py offersfenced object/
vector purge patterns but financial/audit immutability must be preserved with
explicitlydocumented lawful retention, not weaken/deletealltriggers. NoPhase3
codewrittenyet; onlyreadprep. Runtimeproviders/shutdown/backup/load+E6unchanged.

## Phase 2 item 4 complete — 25 October 2026

C3 ac681e0 pushed audit; C4 now verified. Receipt-first encrypted webhook inbox,
raw HMAC+eventID, conditional final lease fencing rolls back money on takeover.
Monotonic refunds/disputes/capture, overlapping reversals capped original net,
nonnegative wallet+explicit adjustment, existing call backing preserved. Durable
refund idempotency+unknown holds, subscription create unknown lookup/no replay,
mandatory checkout signature+GET, captured coverage/auth hold separate, cancelled
paid coverage retained, DRAFT7day dunning/no silent renewal/Free downgrade.
Cancellation same-key dead-letter recovery is read-only after unknown POST.
Business/GST/prices DRAFT+paid flag false, approved merchant/catalog required;
INR only, signed expiring profile/tax review. Immutable FY invoice+credit notes,
separate DRF numbering, actual isolated local-font PDF/private download/outbox
MIME attachments. Billing feature UI actual native-browser fake-provider passed:
11800 gross/10000 credit, signed sub, PDF download, open review disabled on flag
off, zero page errors. 52focused27.82s+21cancel/series30.75s; prior71integrated
32.74s (overlap). PG lease takeover rollback/four receipts onecredit/twelve
unique concurrent invoice numbers passed. Typecheck/build passed. Full Phase2
suite afterC5. Docs BILLING/DECISIONS/VERIFICATION/checklist updated. New PDF
test needs poppler-utils; installed here. Sandbox start/stop idempotent verified;
old pytest garbage root-dir4warnings unrelated to current helper (no failures).
API/worker still item5 code in memory, production web latestC4. No .env/private
DB/provider changes. Current sandbox studio-content-local updated PDF/Noto.

NEXT C5 operator empty-allowlist browser/CSRF verified-only spend/margin/top
consumers/workspace kill + financial review/refund exceptions/deadletters, then
fullPhase2 pytest/type/build, restart safe isolated local API/worker. Afterthat
D Phases3/4/5/7 and E6. No agents; no partial-final stop; main stays0fc290c.
References actually read current official Razorpay documents plus local official
Playwright/CPython/Next APIs, URLs/date in DECISIONS. Missing live merchant/SMTP
credentials only block live acceptance, not build or fake tests. Final prices/
business/GST/SAC/legal policy approval required; all checked-in values DRAFT.


## Phase 2 item 3 complete — 25 October 2026

Item2c2d59f0 pushed audit. New tariffs.py invoked all voice admissions, removes
newcall zero-rate legacy labels. Live rates nonzero plan snapshots; Free/Starter/
Growth includedvoice (no second wallet debit),Custom walletmode DRAFT, paidflag
stillfalse+catalogDRAFT. Wallet duration affordable/held, syntheticPSTN600from
config and browser0 explicitdev. Preserve original tariff acrossmetadata/plan/
flag edits and legacy schema1 calls/rates/holds. Modelrate maps DRAFT conservative
estimates notvendoravailability/pricing; productionunknownmodelblockedpreI/O.
CostRecordmodelnullable additiveDDL+startupcheck; schema plan-tariffs. Tests105
58.81s+10legacy6.71s pass, PGmodelcolumnrepair+concurrency+immutability pass.
Noenv/remoteDB/providerchanges. API/workerstillitem5inmemory. Phase2notcomplete.
NEXTC4 Razorpayrefund/failed/dispute/subscriptions/GSTPDF/email/billingUI thenC5
operator cost/margin/kill, fullsuite/type/build. Razorpayofficialindexnow200 at
/tmp/razorpay-index-current.ref; canonical llm-docs paths forresearch. ThenD
phases3/4/5/7 andE6, allbuildablefakes/flags/DRAFT notdeferred. Main0fc290c only
auditpush. Noagentsauthorized. Userdoesnotwantpartialfinals/checkpointstop.


## Phase 2 item 2 complete — 25 October 2026

Item131b55fb pushed audit. Durable BudgetAdmission cost/resource holds before
model/STT/TTS/carrier, quotas conversations/turns/voice/crawl/storage/seats/widgets.
Workspace+installation spend holds,80/100 encrypted outbox alerts; deny rolls
back unrelated changes then persists alert only. Unknown stays held, overrun
records actual and pauses. VoicePCM/wall/provider duration bounds; Plivo
scheduled Hangup, Twilioinboundacceptedtime_limit beforestream; providerSDK
HTTP200 sources read. Exactbyte storage holdcommitbeforeI/O +legacy inventory
CLI/adapters; productionmissinginventory503, newworkspaceemptyready.
Explicittest/devallowancemult1000 ignoredproduction; realprovidercostunchanged.
BILLING.md documentsconservativefailedcrawl/unknown holds and dryrun/apply.
Tests97regression+58additional+38finalcarrierpassed;16correctedtiming/admission
passed;23storage/account and27finalwidget/admission passed. PG24concurrent
10held14denied+immutability pass. Schema budget-admission.
API/worker stillitem5codeinmemory, safehelpernewdevflag+paidfalse, environmentdraftsavedwithnewflag.
NEXTC3 real plan retail tariffs thenC4Razorpay/GST/UI C5operator; phasefulltests/
frontendcheck/build afterward. D phases3/4/5/7 thenE6 unchanged. Neveredit.env
or suppliedDB; noagentsauthorized. Fullscope continues; no partialfinal.


## Phase 2 item 1 complete — 25 October 2026

Audit only, item5f16ef92 pushed. New DRAFT config/plans.json validates/pins four
plans and nonzero provider rates. Immutable PlanCatalog/Tariff/Meter/CallCost
records; exact UTF8 Fish byte pricing, OpenAI cached+reported usage, interrupted
usage explicitly unreported; real dev expenses nonzero, only synthetic zero.
Storage current-object meter plus append-only add/release, page/conversation/
turn/audio/carrier integration; billing usage/call cost APIs. Read-only usage
never creates catalog/subscription. Paid checkout now requires new flagAND
APPROVED config; both off/DRAFT. Webhooks need signature config but not checkout
flag. Tests35final13.17s,91and54prior regressions; typecheck/build pass. No remote
DB/env/provider charges. API/worker still item5inmemory; restart after phase.
NEXTC2 admission/limits/hard caps/alerts then C3real retail tariffs, C4Razorpay/
GST UI, C5operator view; full phase checks. Then D phases3/4/5/7 and E6.
Reusable environment draft resaved with cipher helper overrides, not published.
All missing commercial/legal values must be implemented DRAFT+flags+fake tests,
not deferred. No delegation authorized. See launch checklist/decisions.


## Phase1 / item5 complete — 25 October 2026

Audit only; item3a732f2c pushed. Fullsuite513passed2nonapplicableprovider-skips
276.46s withREALdisposableRedis6399;14keymaintenancecases16.33s (twoaddedafter
fullcollection), typecheck/buildpass. NewPGscriptverify_key_rotation_postgres.py
passeslegacyread/versionedrewrite/parallelcheckpoint/restrictednoCREATE/
immutablemetadata+audit/currentleasecipheronly; workerPGupgrade/fencingallpass.
API/worker stillitem3inmemoryuntilrestartbelow; newSchema2026-10-25-versioned-keys.
Newcipher vs1:keyid:Fernet authenticatesIDinsidepayload, originallegacyFernet
andapp-v1readrootstableAPP_SECRETunchanged. Localkeyring andpinnedversionVault
adapter (azure-keyvault-secrets4.11.3/frozenlock), boundedcache/failclosedwarmup.
Leasedboundedreencryptjobs/checkpoints/audits/global+tenantscope/CLI/operatorAPI
closedallowlist. Immutabletoolheaders onlyciphertextunderrealrunninglease;
metadata/deletion/auditremainimmutable. PreserveauthenticatedFernet timestamps,
stoponbadrecord/key/activechange, noautomaticretirement. Allencrypted_*columns
plusalreadyencryptedWebhookEndpoint.secret scanned (don'tplaintextmigratethat).
CLItestsrealisolatedsubprocess anddispatcherdrivejob; noactualkey/DBrotated.
FullrunfoundnewwidgetFKsnotinagentpurge: nowscopedquota/proposals/OTP/consent/
pendingoutboxremovedbeforeparents, regressionverifiescompletecleanup. Tests
andlocalhelperexplicitlyclearnewCipher/TurnstileflagstokeepnativeQAnonproduction.
ENCRYPTION.md+DECISIONSsourcesreadFernet,AzureVaultclient/README. Privateenvand
Supabaseunchanged. Install/startdraftsavedearlier; latesthelperinstallmustbe
resavedaftercipherlocaloverrides. NEXTPhase2CfullDRAFTplan/meter/cost/admission/
tariffs/Razorpayrefundfailed/dispute/GST/operatorview; paidflagFALSE. Provider
docfetchpendingtoolsession72043 savesRazorpayrefs /tmp. ThenDPhases3/4/5/7 and
EPhase6referencesresearched. Continueautonomously; noagentspermissiongiven.

## Item3 complete — 25 October 2026

Audit only. Prior item9ed46508 pushed. ServerTurnstile single-use token+trustedIP,
exacthost/action/300sage,5sHTTP timeout, productionalwaysrequired/failclosed;
post-providerpermissionrecheck and legacyproofmarker forresume/chat/voice/email.
Fakeproviders onlytestprocess. Durableinstallation+globalhashedIP UTCdayquotas,
atomicmonthlyspendreservations DRAFTdefaults, replayidempotent, 80/100owneroutbox
alerts persistdenial beforemessage/callwrites. Voicecapdefault60s enforcedmedia;
dictationFFmpeginsandbox pipeonly1thread10stimeout -> canonical16kmonoWAV<=30s,
malformed/longmediarejectedbeforeDeepgram. Existingdictationfixture nowrealWAV.
Emailoptionaldefaultoff. UnverifiedleadsstoreNOmarketingchoice. OTP6digitsHMAC,
10min/fiveattempts/resendinvalidate/origin+session/keybound; encryptedoutboxonly,
nevermodelcontext/HTTPcode. Consentonlyafterproof; marketingflagdefaultFALSEand
wording/versionDRAFTpendinglegal. APIleadverification derivesfromproofrecords,
noteditableevidence. React+vanillaclients/sharedbothelper, OTPUI, ownerquotacapUI.
SchemaNOW2026-10-25-widget-protection. No privateenv/remoteDBchanges. Turnstile
site+secret/SMTPhost+user+password absent (presenceonlychecked); onlyliveacceptance
awaitsthem. Allimplementationcomplete. 128integrationpassed94.39s, final46passed
46.79s, typecheck/buildpassed, actualChromiumfakeprovider/realrouteOTP/consent/
ownerzerocap+email passedzeroerrors. NestedformUIbugfound/fixedseparatebutton.
API/worker/web restarted, latestPIDsdiscover; localcontentsandboxnowFFmpegimage.
Onlyownoutdatedsandboximages/buildcachecleaned; DockerVFSdisk~10GBfree, don't
prunepostgresimage/volumes. Reusableinstall/startdraftsaved, onlyuserSave/Publish
activates; no needpausecode. NEXTB:item5keyIDs+backwardsreads+reencryptjob+provider
interface, thenfullPhase1suite/type/build/PG, thenC/D/E. OfficialFernet/KeyVault
sources fetched /tmp/fernet-rotation.ref /tmp/azure-vault-secrets.ref; READbefore
changingcrypto/provider. Don'tstopatfirstblocker; fake+flag+DRAFTallbuildablework.

## Item9 complete — 25 October 2026

Item8commit a77eab5 pushed audit. Mandatory separate content isolation via Unix
IPC; no app Docker socket/mounts/credentials/network. Broker four capabilities
SETUID/SETGID/CHOWN/KILL, distinct nonroot per-jobUIDs20000..59999, no childcaps,
socket inaccessible tochildren. Read-only root,1GB/noSwap,1.5CPU,192PIDs,256MBtmpfs,
parse512MBAS,20CPU seconds,30srender/40sbroker/45sclient deadlines. Kill entire
jobUID incldetachedsessions andclearjobfiles. PDFstream/page/decode andZIP/XML
budgets; DOCX200page budgetdeclared/explicit/conservative400words/page estimate,
not physicalWordlayout. Application-side pinned GET/robots/budgets retained;
inflight fetch canceled/drained onresult. Lightweight health bypassesjobqueue.
Actualcontainer14tests passed, including health/readiness and deadline recovery;
59existing renderer/platform/website/HTTP tests passed, typecheck/build passed.
Local API/worker restarted using /workspace/.setup/nutaan-local.sh with socket
/tmp/studio-content-local/content.sock; readyz200 includes content_sandboxok.
DockerVFS filled32GBduringdebugbuilds: removed ONLY ownold sandboximages/build
cache; postgresimage/volumes preserved, now~17GBfree. Runtimefingerprint builds
staleimages automatically; envDOCKER_CONFIG writable/.setup/docker and build-only
STUDIO_SANDBOX_BUILD_NETWORK=host plusresolvedproxyaddresses fixes cloudDockerDNS,
TLS/lockfilechecks preserved. Fourcaps are brokeronly; parser/browser hasnone.
Reusableinstall/startdraft updated/saved, stillneedssettingsSave/Publish; no need
pause coding forthis. No privateenv/remoteDB changed. Nextitem3Turnstilecontract
officialdocs200 at /tmp/launch-turnstile-doc.html; OTP/consent and installation
quotas/spend/outbox, then5keys, thenC/D/E. Continuewithoutstopping forbuildablework.

## Item8 complete — 25 October 2026

Audit only; main remains0fc290c. Immutable platform prompt, structured untrusted
data channels, credential/PII stripping (including streamed key fragments),
atomic conversation/call attempt budget8, server-encrypted scoped five-minute
confirmation receipts, approvedGET-only bypass, idempotent confirmed writes and
unknown-outcome no-retry. Intent classification only proposes handoff; strict
boolean schema and conservative model-free request grammar. ToolStudio policy/
public response field UI, chat confirmation button, voice later-turn read-back.
Current tool policy immediately narrows pinned older versions. Test-generated
fixture identities never grant cross-tenant scope. SchemaNOW2026-10-25-tool-safety.
Redteam24passed; typecheck/build passed, actual Chromium chat+WebSocket simulation
require confirmation and each creates exactlyone ticket, unrelated human wording
creates none, zero pageerrors. CSP actualHost fix retains strict script policy
while allowing explicitly configured local API WebSocket. See artifacts/tool-safety.
Final integration129passed in83.79s. Next9: credential-free,
network-isolated low-privilege parser/browser service with hard resource budgets,
then3Turnstile/OTP/quotas/spend,5keys,remainingC/D/E. No private env/remote DB changes.

## Item7 complete — 25 October 2026

Audit only; item4commit73fcebf, item6commit528115f. Item7 origin proof is mandatory
for every configured external widget origin. DNS TXT/meta/fixed well-known file
adapters; encrypted 256bit challenges24h, verified90days, HTTPS production,
public-IP/TLS/same-origin/bounded HTTP proof,3s DNS. Platform-origin preview stays
trusted; foreign/public keys/unrestricted flags/null/wildcards never bypass proof.
All public config/session/resume/voice paths and frame policies enforce fresh
proof. Revocation rotates tokens. Preview saving cannot activate foreign sites.
Widget Website tab has create/check/revoke proof UI, loading/expired challenge
states and clear platform-preview exception. New locked dependency dnspython2.9.0.
Metadata batches reuse request-scoped verified-origin sets. Permissions and
challenge state are expired/rechecked after external I/O to close stale identity
map races (membership deletion, role demotion, challenge rotation all tested).
68 related backend tests, typecheck/build and actual ownership dashboard Chromium
flow pass; fake DNS is injected solely in the separate QA test process against
the real endpoint/local SQLite, never the running product server. Zero pageerrors.
SchemaNOW2026-10-25-origin-ownership, no remote/private config changes. Next item8:
untrusted-source hierarchy/delimiting, side-effect confirmations and tool budgets,
intent+confirmation handoff, red-team tests. Then9 sandbox,3 protection,5 keys,
remaining phasesC/D/E per latest user. OpenAI developer index/reasoning/streaming
pages now reachable200; safety/model-spec alternate hosts still403. Research
actual relevant developer docs before provider changes; don't defer buildable work.

## Item6 complete — 25 October 2026

Work stays on audit, never main. Item4 committed73fcebf. Item6 adds strict nonce/
strict-dynamic production script CSP via Next16proxy.ts and dynamic root layout,
explicit theme nonce, DENY dashboard framing, widget external framing closed
until item7 proof. Existing inline CSS attributes remain allowed. HSTS subdomains,
bounded/timed/chunked API bodies, compressed-body rejection, exact webhook bytes,
verified-browser-only production docs/OpenAPI, minimal health and shared DB worker
heartbeats/readiness checks. Missing production Redis/Qdrant fails readiness;
local disabled-development services are explicit. Worker heartbeat DB failures
are retried, and stopped workers are marked. Schema NOW2026-10-25-http-readiness.
48 related tests passed/1 optional realRedis skipped; final19focusedpassed,
typecheck/build and scripts/verify_http_security_browser.py production Chromium
all pass (unique nonce, working dashboard, injected HTML script blocked, zero
pageerrors). Current API/worker/web restarted with isolated helper, readyz200.
No private env/remoteDB changes. Next: item7 domain proof across session/voice/
framing/activation paths, then8 safety,9 process sandbox,3 widget anti-abuse,
5 versioned keys; continue all requested phases without deferring buildable work.

## Active launch implementation — 25 October 2026

Latest user request supersedes the earlier deferrals: items 1/2 accepted; implement
A: Phase1 items4,6,7,8,9 then3; B:item5; C:Phase2 DRAFT plans/billing disabled;
D:Phases3/4/5/7; E:Phase6 researched streaming. Do not stop at first blocker or
leave implementable work deferred. Use fake providers and DRAFT configuration
behind disabled paid flags. Never edit private configuration. Work/commit/push
ONLY audit; main intentionally remains at 0fc290c until user verifies audit.

Item4 implemented: uniform signup202 without auth/IDs; equivalent Argon2 +
500ms/0–20ms jitter floor; uniform recovery; verified production workspace and
sensitive actions; capped owned workspaces; pending initial workspace until proof.
Encrypted transactional email outbox, worker leases/retry/fencing/dead letters,
verified TLS and private local spool. Phone alerts track queued vs delivered.
SMTP credentials are required only for external live delivery, not implementation.
QA scripts use scripts/qa_accounts.py to exercise signup202 → signin200 → me200.
User sessions are no longer created by signup. Initial workspace appears only
after proof when verification is enforced. Frontend handles the new contract.
Recovery race found in PG acceptance: expired running jobs now precede queued
siblings; new regression covers an older queued sibling and expired newer owner.

97 related tests, final18 focused tests, typecheck/build and disposable PG17
migration/runtime/no-CREATE/concurrency/fencing checks passed. Full suite is due
at Phase1 boundary. Schema NOW2026-10-25-account-outbox (two new tables). Private
.env unchanged; real Supabase untouched. Provider docs: Cloudflare and Fish now
reachable; contracts/ref dates in docs/DECISIONS.md. Next action item6 HTTP/CSP/
readiness, then7 domain proof,8 LLM safety,9 sandbox,3 widget protection,5 keys.
Keep updating LAUNCH_CHECKLIST and commit each item, with meaningful tests.

## Cloud setup and first public-launch security checkpoint — 24 October 2026

The user supplied a seven-phase public-launch request. **It is not complete;
Phase 1 is partial.** Read docs/LAUNCH_CHECKLIST.md for every numbered item and
remaining reason/gate; docs/SECURITY_CHECKPOINT.md describes implemented behavior.
Do not advance to paid launch or claim Phases 1–7 accepted. Ask only for commercial
decisions: an asynchronous question requested approved plan prices/quotas/overage
rates and invoice business/GST details; no answer has arrived. Never invent them.
The latest user explicitly forbids editing private configuration files; this
supersedes older permissions below. `.env` and all private values are unchanged.

Implemented shared Redis atomic sliding windows/server time/HMAC identities,
bounded locked local outage fallback with throttled warnings, independent IP and
actor limits at authenticated cost admission, 10-attempt/15-minute email sign-in
limit, explicit proxy trust with wildcard and /0 rejection. Use Uvicorn
--no-proxy-headers so application TRUSTED_PROXY_IPS is authoritative. Beta Compose
has a separate edge network, fixed gateway IPv4 and exact /32 API trust; topology
is configuration-validated, not live deployment acceptance. Existing Caddy input
forwarding sanitization remains. A CDN needs its own reviewed trust policy.

Keys cannot perform developer/team/billing mutations (even legacy stored scopes)
or mint/expand other keys. Optional aware expiry, last successful use, per-key
1–600 requests/minute (default60), UI controls/columns. API-key scopes/hashes are
not rewritten. Removed the embedded Supabase project hostname; split password
config must explicitly provide a host. Schema revision NOW
2026-10-24-key-security/64tables: nullable api_keys.expires_at/last_used_at and
requests_per_minute NOT NULL DEFAULT60. Existing migration maintenance workflow
must run before production startup. Supplied Supabase was NOT migrated.
Versioned encryption/rotation and the rest of Phase 1 remain unfinished.

Frozen Python/npm installation and repeat installation passed. Typecheck/build,
25 focused security tests including real disposable Redis, actual production
Chromium key expiry/limit/last-use controls (zero page errors), isolated API +
dedicated worker TXT completion/retrieval and web proxy passed. Disposable PG17
passes key-column upgrade/hash preservation/repeat migration/missing-column
rejection/runtime last-use writes with no CREATE plus prior worker concurrency
and fencing checks. Final full suite421passed2intentional provider-specific
scheduling skips (142.09s); detailed evidence in docs/VERIFICATION.md. No load/voice-latency/paid-provider
or public launch acceptance was performed.

Cloud instance default Supabase read-only check failed: network/address route
unavailable. Existing credentials were found; do not request duplicate tokens or
print values. Local development explicitly uses
/workspace/.setup/nutaan-local.sh (outside checkout): SQLite/local objects in
ignored data/cloud-local, lexical retrieval, no providers/SMTP/calls/payments,
development-only unverified signup. API8100 has in-process dispatch disabled,
dedicated host worker shares the helper, web3100 production frontend is running.
The dev frontend was also smoke-tested; Next rewrote tracked next-env.d.ts to
.next/dev imports. Stopped that process and restored only its generated change;
saved initial-readiness startup uses build + start to preserve tracked files.
These local overrides are never deployment settings and do not change .env.

Environment draft saved install_script/start_skill plus documentation allowlist
additions; needs environment-settings review/save and Publish. Publication and
restoration in a new task have not been validated. Saved startup instructions
use existing isolated checkout, no Git worktrees unless explicitly requested,
explicit working directories and API/worker/web readiness checks. Install script
preserves a modified local helper and uses frozen lockfiles. Dependencies/files
can be snapshotted; processes must restart after publication.

Required official provider docs returned HTTP403 (Cloudflare/Fish/OpenAI/Deepgram).
Redis/Uvicorn/Caddy/Pydantic/SQLAlchemy maintainer sources and installed Next16.4.2
guides were read; actual URLs/date and denied URLs are in docs/DECISIONS.md.
Do not change remaining integrations before reading their current official
contracts; in particular do not assume Fish flush/reuse or model-family defaults
from the prompt. Recheck docs after settings changes. No provider integration was
changed here. Continue Phase1 item3 then remaining Phase1 requirements, with
tests/docs for each behavior and full phase checks; keep production disabled.

## Concurrent worker pool and ingestion pipeline — 24 October 2026

Latest request: set up workers, make crawl/scrape and other jobs faster, overlap fetch through upload. Compose now runs a separate worker service (python -m studio.worker_main), with API WORKER_ENABLED=false. Local development retains an optional in-process dispatcher by default. Four top-level job slots, independent webhook delivery and maintenance, 250ms poll; settings WORKER_CONCURRENCY1–16, CRAWL_CONCURRENCY4(1–8), RENDER_CONCURRENCY2(1–4) and INDEX_CONCURRENCY2(1–8). Renderer/index limits are shared across that worker's simultaneous jobs. Sitemaps seed the queue; page pipelines fetch/render/extract/upload concurrently and persist whichever finishes first, including discovering further links. Parsing, source/checkpoint transactions, SDK uploads and common job lifecycle DB waits run in threads; some legacy handler/API DB access remains synchronous. Qdrant uses pooled HTTP and bounded concurrent32-chunk embed/upsert batches; failure cancels siblings and never promotes incomplete knowledge. Concurrent collection creation requires compatible read-back. Stop drains children/renderer routes; existing source/blob/snapshot/agent reuse remains.

Queue claims lock one candidate at a time with PostgreSQL SKIP LOCKED, allowing genuinely concurrent claims. Resource row locks + active-job checks serialize KB/store/campaign mutations while permitting unrelated jobs. Job.lease_token UUID fencing is checked under row lock by handler/checkpoint/publication transactions and final failure/success writes. A20second heartbeat renews three-minute leases; expired jobs resume pending URL/source checkpoints. Webhooks have exclusive delivering claims and three-minute recovery with existing at-least-once event IDs. Worker health is a five-second /tmp heartbeat; SIGTERM drains tasks. Browser orphan cleanup stays in the API: standalone workers must not infer call ownership from their own empty in-process owners map. Keep one API and one dedicated worker service by default (four job slots); general maintenance replica coordination, external-side-effect reconciliation and distributed media/rate limits still need acceptance before unattended replica scaling. This supersedes older instructions to run one serial API/dispatcher.

Schema revision NOW2026-10-24-worker-pool,64tables/OpenAPI147paths. Adds nullable jobs.lease_token; initialize_database upgrades existing tables, and verify_database_schema rejects a missing column/revision. Production must run scripts/migrate_database.py with a migration-capable connection to the same DB before starting the new release. Compose beta overlay applies production settings to worker too; worker entrypoint verifies schema without DDL. API/worker must share .env/database/volume/object-store/signing/network settings. Private tracked.env unchanged, all credentials preserved. Supabase untouched; do not claim a remote migration. See docs/WORKERS.md for exact build/migration/up, local-dev, tuning and verification commands.

Validation: Full isolated backend396passed2intentional skips (104.22s). Actual API image builds with Python3.13/system Chromium, and disposable Docker API + dedicated worker pass queued TXT upload (API does not claim it), shared local objects/SQLite, knowledge promotion, heartbeat, clean SIGTERM and cleanup. Both Compose configurations validate (beta uses synthetic interpolation placeholders). Disposable PostgreSQL17 passes upgrade from a table missing lease_token, missing-column startup rejection, repeated migration, no-CREATE runtime role, eight simultaneous unique claims, one owner per KB, expired-lease recovery and stale-owner fencing. No paid providers, customer crawl, supplied Supabase, customer deletion or remote deployment in these checks. Frontend unchanged; no new frontend build required.

Controlled benchmark comparing original93ae9d4 source with identical workload: five synthetic fetch/render/upload/index pages5.051s→2.978s (about1.70×); eight queued250ms jobs9.067s→0.822s (about11×, including shorter polling). Both crawls produce5pages20chunks and unchanged recrawl adds0raw uploads. Peak renders/uploads1→2, top-level jobs1→4. Public sites remain bounded by real250ms/robots pacing and network/content; do not promise these speedups universally. Reproduce scripts/benchmark_workers.py; before source was extracted to an isolated temporary tree without.env. Regression tests cover head-of-line progress, shared render/index limits, vector/text alignment, batch failure/Stop, job/KB/store fairness, heartbeat, stale writes and webhook recovery. Evidence artifacts/workers/{before,after,postgres,docker}.json. Standalone synthetic QA scripts verify_workers_postgres.py and verify_workers_docker.py clean up only their unique containers/data; image required studio-worker-qa:local.

Provider-enabled cloud development API restored on8100 with in-process dispatch disabled; dedicated host worker is running with the same provider-dev.sh local SQLite/data config, web3100/demo3200 remain. Cloud-only PUBLIC_NETWORK_MODE=proxy override stays in helper; private.env remains portable direct. Do not confuse this local provider-enabled development DB with Supabase or the user's separate laptop Docker. Preserve the normal update-handoff/commit/fast-forward-push preference.

## Renderer closed-target race — 24 October 2026

User Docker logs showed intermittent Route.fulfill TargetClosedError / Error occurred in event listener while crawling Tecosys blog pages. Cause: rendered_html captured its snapshot or timed out/stopped, then closed Chromium while HTTP route callbacks still awaited safe_fetch or pacing/lock. Their eventual fulfill/abort targeted a closed page. Fixed renderer lifecycle in website_extraction.py: track owned HTTP/WebSocket handler tasks, mark shutdown, detach HTTP routes with context.unroute_all(behavior='ignoreErrors'), cancel/drain handlers before closing context/browser. Guards prevent new fetch/fulfill after shutdown; expected closed-target callbacks terminate as cancellation so Playwright's route-handled future is not left hanging. Unexpected live route errors still propagate, and main render timeout/cancellation/snapshot errors remain errors. Existing dead proxy, pinned safe_fetch, origin/robots/GET restrictions, budget60, default30s render bound and1500ms settling remain unchanged. Render timeout/settle constants extracted for deterministic tests only; no API/env/schema change.

Validation:24focused tests passed (test_renderer_lifecycle.py + test_website_assistants.py), including real system Chromium success with pending/queued background fetches, timeout, explicit cancellation/Stop-style interruption, externally closed page and genuine snapshot failure. Pending fetches end before return, browsers disconnect and no event-listener stderr or asyncio errors. Existing guarded-JS/external/POST rejection and crawl Stop/static-fallback/knowledge-preservation cases pass. Ran the new background-fetch regression against the pre-fix renderer in an isolated test subprocess: expected failure because the fetch remained active after return (artifacts/renderer-lifecycle/before-result.json). No actual Tecosys/customer crawl or paid provider request was made. Private.env/schema/frontend unchanged; latest schema revision2026-10-24-agent-deletion/64tables/OpenAPI147paths remains. Existing production migration requirement from agent deletion still applies if not previously deployed. Update docs/CRAWLING_PERFORMANCE.md and docs/VERIFICATION.md evidence; normal handoff/commit/push preference remains. Restarted provider-enabled local cloud API after applying the code.


## Agent deletion with owned-data cleanup — 24 October 2026

User requested proper delete-agent/all-data option. Added owner/admin-only Delete agent controls on list cards and editor, impact preview with affected counts + expand-all, exact saved-name confirmation, cancel and Archive instead. Delete immediately archives/disables agent/widgets, closes conversations, stops scheduled recrawls, unassigns numbers and cancels queued related work; active calls/running work block acceptance. Cleanup is a durable agent_delete job; Operations panel polls status and allows owner/admin retry on failure. Repeated confirmation returns same job, confirmed purge cannot be canceled. No actual user/customer agent deleted by implementation/QA.

agent_deletion.py collects agent-scoped versions/installations/websites/chats/messages/context/tickets, attributable leads/local bookings/availability/appointments, calls/transcripts/recordings, campaigns/attempts/jobs/tool executions and exclusive knowledge/products. Shared KB references from other drafts/published versions are retained. Shared content-addressed storage keys protected across source/logo/recording/product/job references. Qdrant deletion filters workspace+snapshot IDs with wait=true; Redis deletes derived source-chunk vector cache keys. Storage/vector/cache failure leaves disabled agent and durable cleanup manifest for retry; DB deletion commits after external cleanup. Pending knowledge marked deleting, config writes/publishing lock snapshots and reject new attachments, recrawl/upload blocked. Retry manifests exclude now-retained snapshots/blobs. Voice tool attribution accounts for up to24seeded chat history entries. Phone resources, immutable ledger/audit and shared workspace tools/credentials/contacts stay; financially referenced calls are scrubbed to minimal non-conversation records. External meetings/provider-side histories/exported files are not canceled/retracted. UI/docs disclose boundaries.

Schema revision NOW2026-10-24-agent-deletion,64tables; actual OpenAPI147paths. New GET /agents/{id}/deletion-preview and POST /agents/{id}/delete with confirmation. Important: production must run scripts/migrate_database.py using migration-capable connection before restarting new API. Migration keeps published versions UPDATE protected and permits DELETE only during matching running agent_delete job on archived agent; ledger/audit/http-tool-version guards unchanged. PostgreSQL old combined immutable_record UPDATE/DELETE trigger replaced for agent_versions with UPDATE-only guard plus conditional DELETE guard. Restricted runtime no CREATE is supported. Development initialization upgrades automatically. Private.env and remote Supabase untouched.

Final verification: full isolated backend378passed2intentional skips; production build/typecheck passed. Eight focused deletion tests (including final empty-draft/no-storage refinement) cover full graph, confirmation/idempotency/key invalidation, shared KB/blob preservation, financial scrubbing, storage failure/retry, vector scope/cache keys, active-work/tenant/role/immutability guards and deletion-time attachment/recrawl denial. Disposable PostgreSQL17 migration/reinitialization/no-CREATE runtime/ordinary delete protection/confirmed purge passed; only temporary container/data removed. Actual production browser on isolated local API/objects passed list+editor controls, wrong-name disabling, cancel, desktop/mobile dialog, worker+Operations completion, shared data/other agent preserved and archive alternative, zero page errors. Qdrant/Redis boundary tests synthetic, object store actual local; no paid/customer data deletion. Screenshots/results artifacts/agent-deletion/, reproduction scripts/verify_agent_deletion_browser.py and verify_agent_deletion_postgres.py. See docs/AGENT_DELETION.md. Provider-enabled cloud API restored after tests. Normal commit/push/handoff preference remains.


## Same-origin polling and portable keyed embeds — 24 October 2026

User Docker logs showed repeated GET /v1/public/conversation403 while dashboard requests succeeded. Reproduced: same-origin browser GET normally lacks Origin, so strict signed-origin validation rejected polling. Added POST on same path and changed React WidgetChat + standalone widget polling to POST (browser supplies Origin). Strict token-origin/key checks retained; legacy GET still requires matching origin. Both clients stop retrying on401/403/404 and expose reconnect, rather than silently looping. Actual browser regression reproduces old GET403 and passes POST/operator delivery/terminal-stop for same-origin clients.

User additionally explicitly requested widget ID/publishable key work on any website or normal HTML file without allowed-origin errors. Implemented installation_allows_origin: valid keyed widgets default to unrestricted HTTP/HTTPS/opaque null placement, covering arbitrary preview hosts and file://. Keys are still verified and sessions/resume bound to the originating origin; no-origin requests denied. Optional boolean theme.restrict_origins=true restores allowlist, exposed in customizer Website tab (unchecked by default). Legacy no-key installs retain allowlist. Updated config/session/resume/chat/dictation/voice/media checks consistently. Indexed navigation remains constrained to configured site origins and corpus; public CORS remains credential-free and advertises GET/POST. No API keys/dashboard auth scope exposed or relaxed. Historical tests/notes assuming keyed embeds always deny unlisted origins are superseded; explicit-restriction tests remain.

Validation:76focused widget/branding/website/platform tests passed, including null/unlisted origins with valid key, bad keys, optional restriction and cross-origin session replay denial. Additional57scheduling tests passed2intentional skips. Production build/typecheck passes. scripts/verify_widget_polling_browser.py uses actual Next rewrite + isolated local API and script-loaded HTML on same app and independent local HTTP; managed Chromium forbids file:// with ERR_BLOCKED_BY_ADMINISTRATOR, so actual sandboxed opaque-origin srcdoc verifies Origin:null without bypassing policy, plus operator replies and no polling after disable. No paid providers or external customer actions. Evidence artifacts/widget-polling/. OpenAPI retains145paths (new POST method on existing path), no migration/env changes. User laptop needs pull/rebuild API and web and reload widget page; current cloud cannot alter their running containers. Provider-enabled cloud API restored after isolated QA. See docs/WIDGET_LIVE_INBOX.md. Update handoff and commit/push after work as usual.


## Portable crawler network configuration — 24 October 2026

User screenshot from their own localhost showed0pages/failed with “Proxy network mode requires a configured HTTP/HTTPS proxy”. Cause: prior cloud-specific PUBLIC_NETWORK_MODE=proxy was committed in private.env and copied to ordinary local development without cloud proxy variables. Fixed tracked.env to direct (only that setting changed; all credentials preserved), matching .env.example/settings default. Restricted cloud still requires explicit PUBLIC_NETWORK_MODE=proxy at launch; /workspace/.cloud-setup/nutaan-Rea/provider-dev.sh now exports it, and local-dev.sh exports direct. Do not save cloud-only networking mode into portable.env again. Historical cloud-mode notes below are superseded.

Added shared configured_public_proxy validation before proxy DNS cache/HTTP and transport creation. Missing/invalid explicit proxy returns actionable ValueError: use direct on ordinary hosts and restart API/worker, or configure PUBLIC_HTTP_PROXY. No silent route fallback or secrets in error messages. Existing IP pinning/private-address denial/Host/SNI/TLS/robots checks remain. Tests cover missing proxy no-network failure, credential non-disclosure and actual direct HTTP transport with public-IP pinning/no CONNECT. Proxy/website suite29passed before final direct case; final focused proxy suite11passed. Real cloud safe_fetch for https://aurelyjewellers.in/ succeeded over configured proxy,155948HTML bytes; no new crawl/provider storage mutations. User's own laptop cannot be operated here: pull/settings reload and Recrawl there remain necessary. Compose env_file reload requires container recreation, not simple restart; docs/CRAWLING_PERFORMANCE.md explains. No UI/schema changes; update handoff/commit/push as usual.


## Apple-design skill audit and UI fixes — 24 October 2026

User explicitly requested installing `npx skills add https://github.com/emilkowalski/skills --skill apple-design`, auditing our website and fixing UI bugs. Installed noninteractively with npm_config_cache=/workspace/.cache/npm (default home cache read-only); committed .agents/skills/apple-design/SKILL.md and skills-lock.json for reuse. Read the full skill and applied feedback/hierarchy/accessibility guidance, retaining brand fonts and existing widget designs. See docs/APPLE_DESIGN_AUDIT.md for findings, verification and reproduction.

Fixes: undefined inbox --soft backgrounds now actual surface token, selected edge/aria-pressed; live thread uses its own scroll container and preserves older-message reading position instead of scrolling the document; notification responses are version/workspace guarded, stale callbacks ignored and old state cleared on workspace switch. New app/interaction.css supplies immediate press feedback, visible light/dark keyboard rings,44px icon/modal/coarse-pointer targets, near-solid blurred toolbar/depth, heading leading/tracking/optical sizing, reduced-motion and reduced-transparency/contrast fallbacks. Shared widget stylesheet gets keyboard rings and solid glass fallback for accessibility preferences. Production audit caught CSS optimizer retaining only prefixed backdrop-filter when declared last; prefixed-first/standard-last ordering now preserves Chromium blur in compiled dashboard preview and toolbar. No new gestures/spring dependency, API/schema/provider configuration changes.

Verification: production build/typecheck passed. Before and after dashboard audit passed96layouts each (24routes desktop/mobile light/dark) plus dialog focus/scroll, rail persistence, landscape nav, reduced-motion, notification loading/error/retry; zero page overflow/errors. Focused actual-API browser audit passes selected state, reading/document stability on incoming messages, focus ring, reversed notification ordering,44px mobile targets/no overflow, contrast toolbar, reduced-motion modal and glass contrast fallback. Synthetic local accounts/messages only; no paid provider, customer email, real booking or browser trust change. Screenshots/reports in artifacts/apple-design/ and artifacts/dashboard/. Private.env preserved. Provider-enabled runtime API is restored after isolated tests. Normal handoff/commit/push preference remains.


## Email-first widget, Deepgram input and live inbox — 24 October 2026

Latest request: microphone input using existing Deepgram, email-before-chat lead capture, navigation/booking checks, live dashboard conversations with human takeover/direct replies and notifications. Implemented on the actual public embed and React chat tester. Email-first is default unless theme.collect_email=false; a separate unchecked promotional opt-in is recorded with exact text/time/origin/conversation/installation in Lead.evidence and reserved context._widget_lead. Continuing chat does not grant marketing consent. Email remains unverified, shown with consent in Inbox/Leads; no email is sent automatically. Existing conversations resume without another lead. Dashboard Website tab controls email gate and voice_input_enabled independently from full voice_enabled.

Public microphone uses MediaRecorder (30s, permission/HTTPS), server-side Deepgram nova-3, editable transcript before send. Key remains server-side. Endpoint checks signed capability/origin/current key/installation/agent/state, audio type,5MiB and10/min/session bounds. Closing/leaving stops recording; failures/silence retain typed-chat fallback. Actual configured Deepgram passed browser synthetic-microphone speech transcription (not a physical microphone). Qdrant/LLM still returns actual₹699Aurely evidence.

Inbox now polls conversations/history every2s, including partial AI; notification bell5s. Take over assigns operator and pauses AI; monitor checks every250ms and cancels generation even during await. Partial assistant is persisted as interrupted, voice session also stops, future tool work is canceled (completed external operations cannot be undone). Shared DB state works across API workers. Assistant row is reserved before streaming to prevent concurrent retry duplication; interrupted replay retains one row/text and altered-message identity returns409. Operator replies are assigned-user-only and idempotent; visitor sees Support team label. Return to AI releases assignment and includes operator context for future replies. Resolve disables visitor sends; can reopen. Read/write/workspace/assignment guards and audit trails are retained. Owners/admins can release another operator; ordinary operators cannot steal/reply/release assigned conversations. Notifications deep-link to exact chat, including when already on Inbox; tickets retain state management/live list. Conversation list batches latest messages/context. Live mobile resize keeps latest message in view.

New widget_live.py provides GET /v1/public/conversation, POST /v1/public/voice/transcribe, PATCH /v1/workspaces/{workspace_id}/conversations/{conversation_id}/mode, POST existing /messages path for operators. PublicSession adds visitor_email/marketing_opt_in. No schema migration: existing64tables/revision retained; exported actual OpenAPI145paths. Confirmed/pending/local meeting events now create accurately labelled notifications; unchanged provider reconciliation avoids duplicate notifications. Existing guarded navigation/scheduling tools unchanged.

Validation: full isolated backend361passed2intentional skips before final ownership/retry refinements; final109focused live-widget/branding/platform/scheduling tests passed2intentional skips. Production build/typecheck passed. Actual production frontend plus independent Aurely HTML browser verification passed email/unchecked opt-in/lead, real Deepgram synthetic microphone transcription, actual LLM/Qdrant₹699answer, takeover/human reply/visitor replies/live updates, resume/mobile, return AI/resolve and notifications, zero page errors. Existing isolated website/navigation/history/current-page/mobile/crawl Stop browser acceptance passed, zero errors. Scheduling OAuth/availability/read-back/yes/history browser acceptance passed both adapters with synthetic external provider boundaries, zero errors/no real meeting. Final actual Aurely demo test passed source URL dispatch, six citations, resume/mobile and403key/origin guards; remote destination/thumbnails still hit earlier browser CA trust limit. No trust exception/change made.

Aurely QA Google Calendar is disconnected; Cal.com/Calendly absent. No live calendar booking was made; connect an account and select a meeting before real acceptance. No promotional email, phone call or customer action was performed. Screenshots/results: artifacts/widget-live/{01-email-welcome,02-voice-input,03-live-inbox-takeover,04-visitor-human-reply,05-mobile-human-reply,06-notifications,07-lead-consent}.png and results.json. Reproduce via provider-dev.sh .venv/bin/python scripts/verify_widget_live_browser.py (explicit localSQLite only, synthetic local editor, real small provider requests; requires prior synthetic artifacts/provider-smoke.wav). Existing demo/customizer/design/browser scripts now handle email gate. See docs/WIDGET_LIVE_INBOX.md for implementation/API/reproduction. API/web/demo remain running on8100/3100/3200, API using explicit localQA provider helper. Private.env and declined browser trust unchanged. Normal commit/push and handoff updates remain required.


## Ten dashboard-selectable widget designs — 24 October 2026

Latest request: premium/minimal widget appearance, each design selectable from the client dashboard, tested individually with screenshots. Interpreted “cleomerphism” as Claymorphism. Chat widget → Customize widget → Style → Widget style now offers Minimalism, Glassmorphism, Claymorphism, Skeuomorphism, Neobrutalism, Bento grid, Neumorphism, Aurora, Editorial and Monochrome. Each applies a recommended palette/font/shape/size/placement; branding/logo/messages/tone/origins/published agent/key are retained, and clients can fine-tune all existing controls afterward. Four legacy layouts remain. The independent Aurely demo is now left on Minimalism (right24px,370×560,20px radius, charcoal/white/system font), retaining its uploaded A logo, “Aurely concierge”, labels and concise tone. Earlier green/classic appearance below is historical.

Shared material stylesheet apps/web/public/widget-designs.css is imported by the dashboard preview and loaded by actual widget Shadow DOM; deploy it with widget.js. apps/web/src/lib/widget-designs.ts defines recommended palettes. Scoped predefined CSS provides real blur/translucence, clay shadows, paper/stitch/tactile details, neo outlines/offset shadows, modular bento sections/two-column product cards, raised/inset neumorphism, aurora gradients, editorial typography/rules and monochrome surfaces. Launcher aligns with chosen left/right placement. No arbitrary CSS injection, new endpoint, schema migration or provider setting is introduced. Backend validates all style IDs and retains existing legacy values.

Validation on final implementation: production build/typecheck passed;21focused branding tests passed, including every style saved through actual installation handler and returned by public configuration. scripts/verify_widget_designs_browser.py passed all10styles against production frontend, real dashboard/API/storage and independent Aurely HTML demo: dashboard select/save, shared material marker, retained key/name/tone, distinct computed material properties, actual configured LLM/Qdrant₹699answer for each,390pxmobile/dark bounds/no overflow/no visitor cookies, zero page errors. Existing isolated website/widget/navigation/history/crawl Stop regression also passed with zero page errors (its provider boundaries are synthetic). Screenshot captures are actual browsers, not generated images or mocked API responses. Runtime helper: /workspace/.cloud-setup/nutaan-Rea/provider-dev.sh .venv/bin/python scripts/verify_widget_designs_browser.py. It explicitly rejects non-SQLite databases, adds only a synthetic editor membership in the retained QA workspace, and makes ten real provider chat requests. Do not unnecessarily repeat paid checks.

Evidence: ignored artifacts/widget-designs/{preset}-dashboard.png, -desktop.png, -widget.png and -mobile.png, results.json, index.html and all-designs.png; scripts/verify_widget_designs_browser.py generates the gallery over temporary local HTTP (file:// blocked in Chromium). docs/WIDGET_CUSTOMIZATION.md documents each design. API remains provider-enabled localSQLite data/cloud-providers (remote Supabase limitations persist), web runs production on3100 and standalone demo on3200. Private.env and browser trust unchanged; prior declined persistent CA modification remains out of scope. Update this handoff and commit/push after subsequent work as requested.


## Complete dashboard widget customizer — 24 October 2026

Latest user requested complete client control over widget colours, button, logo, style, tone and welcome message to match a website. Chat widget now has Customize widget for website-bound and independent installations. A responsive4-section editor (Brand,Style,Messages & tone,Website) has colour pickers/hex inputs, presets, launcher shapes/icons including logo, fonts, dimensions, corner radius, placement/spacing, logo upload/URL/removal, welcome/placeholder/send/footer text, closed response-tone choices and existing origin/voice/navigation controls. Live preview supports desktop/mobile. Cancel does not save staged changes; styling reset preserves brand/conversation fields.

Public widget branding loads before first click. Saved changes appear after reload without replacing embed ID/key; original published agent/evidence and other installations remain unchanged. System colour-mode changes are observed. Responsive panel bounds keep custom dimensions inside mobile screens; uploaded logos are served through a public-key-protected endpoint. Public SVG icons/styles are predefined, theme inputs validated. Tone is installation-scoped predefined guidance applied to actual chat and widget voice configuration, preserving factual/tool/confirmation rules.

Backend adds widget_branding.py and verified PNG/JPEG/WebP uploads (Pillow12.3.0;2MB/4096px bounds) to workspace logos storage. Public configuration hides object keys/content metadata and ignores client attempts to set managed fields. Combined settings_json+file save is one DB transaction: invalid file/storage failure rolls settings back. Existing create/update routes remain; new logo upload/delete/public-read routes make actual OpenAPI142paths. No DB migration;64tables and schema revision unchanged. Export packages/contracts/implemented-openapi.json was refreshed; proposed API contract stays separate.

Validation: full isolated backend346passed2intentional skips before the last transactional-upload refinement; final11branding tests pass, including rollback/invalid files/tenant guards/key preservation/real-handler tone. Production build/typecheck and actual dashboard-to-demo browser verification passed; existing whole website/widget/Stop browser regression passed. Real dashboard test edits the Aurely demo widget, uploads the actual monogram to configured storage, saves/reopens, checks Cancel/mobile, then verifies public launcher styling before open, uploaded logo, dimensions/radius, text, and actual LLM/Qdrant₹699answer. Zero page errors. It adds a synthetic local QA editor membership in the retained QA workspace only; no customer DB is touched. Reproduce via provider-dev.sh .venv/bin/python scripts/verify_widget_customizer_browser.py. Evidence: artifacts/widget-customizer/ and docs/WIDGET_CUSTOMIZATION.md.

Aurely demo currently uses green#214d3b/ivory#fffaf0, uploaded A monogram, serif font, classic header, rounded logo launcher, bottom-left24px,380×580panel,22px corners, “Aurely concierge”, concise tone and new welcome text. Existing widget ID/key remain. Private.env/browser trust unchanged; the earlier user refusal of persistent browser CA changes remains in force. Follow normal commit/push preference and update this handoff after later work.


## Aurely widget on a demo HTML page — 24 October 2026

Latest request: create a widget, embed in demo HTML, test it there, and provide final working screenshots. Created a separate enabled installation "Aurely demo HTML widget" from the existing published Aurely agent/knowledge; original source-site installation/origins are unchanged. Local public installation3P1ap4o2rTwOsSIcCe19gsx0 allows only http://127.0.0.1:3200 and http://localhost:3200. Theme: Aurely guide / Ask Aurely, neutral gold appearance; no new crawl. examples/aurely-widget-demo/index.html is a standalone storefront with real-source images saved locally, actual product prices, and actual widget.js loaded from the app on3100. widget-config.json contains only public embed metadata/publishable key, no dashboard/session/provider credentials.

Run /workspace/.cloud-setup/nutaan-Rea/provider-dev.sh .venv/bin/python scripts/setup_aurely_widget_demo.py to recreate/reuse its installation in the explicit local DB. It uses the existing app installation handler and preserves existing demo settings; repeated runs leave one embed and the same public ID/key. Serve with `.venv/bin/python -m http.server 3200 --bind 127.0.0.1 --directory examples/aurely-widget-demo`. Demo server remains running in its own command session. API/web/Redis/Qdrant remain as documented below. Use HTTP, not file://, so origin binding works.

Actual independent visitor-browser verification passed: widget load/open on a different origin, real configured LLM/Qdrant response₹699/imitation jewellery with6source citations, product URL/new-tab dispatch, same-tab reload resume without another session, close/reopen,390px light/dark with no horizontal overflow, no app/demo cookies, disallowed origin403 and invalid publishable key403. Zero page JavaScript errors. scripts/verify_aurely_widget_demo.py reproduces the check without network mocks and records limitations honestly. Screenshots/results: artifacts/aurely-widget-demo/01-demo-page.png,02-desktop-answer.png,03-mobile-answer.png,04-mobile-dark.png,results.json. User specifically requested final screenshots.

Cloud Chromium rejects the proxy-issued certificate for remote Aurely images/product-page navigation (net::ERR_CERT_AUTHORITY_INVALID), although backend HTTPS via configured trust succeeds. A persistent user NSS trust-store CA addition was rejected by automatic review for broadening TLS trust and the user explicitly replied "No". DO NOT retry that trust change or disable verification. The widget now removes failed remote images gracefully, preserving working product text/links; demo storefront images are local copies. Source URL/new-tab request was verified, but successful remote destination rendering is NOT claimed. No browser trust changes were made. See examples/aurely-widget-demo/README.md. Private.env remains unchanged in this task.


## Actual Aurely crawl in our app — 24 October 2026

Latest user explicitly requested scraping/crawling https://aurelyjewellers.in/ with OUR APP and seeing results. This now passes in the real website-assistant UI:48pages,83chunks,18products in about190seconds. Sitemap46URLs/18products are covered after canonical query normalization; two extra discovered pages were indexed. Four notices are robots exclusions for /orders,/login,/account,/admin. No website writes, purchases or private-page access occurred. Qdrant hybrid retrieval returned supporting passages; the actual connected Azure gpt-6-luna widget answered the Premium Silver-Tone Designer Bangle price correctly at₹699 and identified imitation jewellery, with source/product evidence.36thin pages used guarded Chromium. Zero browser page errors.

The previous local-DNS blocker is resolved for public crawling by explicit PUBLIC_NETWORK_MODE=proxy (enabled privately in tracked.env). Normal hosts default direct. In proxy mode, public A/AAAA records are resolved over verified HTTPS via Cloudflare DNS using the configured/inherited proxy, every address is checked, and HTTP CONNECT targets the validated public IP. httpcore retains the original origin/Host/TLS SNI and certificate validation. Proxy denial fails closed without alternate routes; private, metadata, loopback and multicast targets are rejected. DNS results have a boundedTTL/cache. No verification/robots protections were disabled. PUBLIC_HTTP_PROXY is optional; leave it blank to inherit session proxy settings rather than saving a session-specific address. Tests clear proxy mode and credentials; proxy pinning/SNI/separate-origin/denial/mixed-private/literal regressions pass.

User changed direction from Firecrawl to our app. Firecrawl home scrape succeeded after egress changed, but NO Firecrawl output was imported into this crawl/knowledge. No managed Firecrawl crawl was started. App results use actual native safe_fetch/guarded renderer, real Azure blobs/embeddings/Qdrant and configuredLLM. Supabase raw DNS/TCP remains a separate unverified limitation; current app database remains explicit local data/cloud-providers SQLite, with actual providers. Public crawl proxy mode does not proxy PostgreSQL.

Retained workspace: "Aurely Jewellers crawl test", workspace632f4e20-9134-4efa-8842-5e60144f2e8e; website d47b8d54-e2fa-48d0-a476-256da2c7c183; completed job5ba30507-c0a8-4ff2-8233-c21a401e0e33. Evidence: artifacts/aurely-app/results.json and01-crawling.png,02-crawl-result.png,03-indexed-pages.png,04-grounded-answer.png. Screenshots were shown to the user. Reproduce with scripts/verify_aurely_browser.py; it creates a separate named QA account/workspace and retains real site knowledge, so avoid repeated full crawls without need. No credential values are printed/saved in that evidence. Source script uses the actual local API/web and does not mock networking. See docs/AURELY_CRAWL_TEST.md. Older blocked-native/Firecrawl403 statements below are historical and superseded for this target.


## Crawl performance, Stop, Redis and database — 24 October 2026

The user requested faster crawling/loading, a real Stop button, Redis, less Azure snapshot churn, the supplied replacement Supabase project, and commits/pushes after completed work. `.env` remains tracked/private/mode0600; both database URLs now select the latest supplied main database with TLS. Never print its URL or credentials. Read-only Supabase connectivity still fails from this cloud; no remote migration/data move is claimed.

Crawls now share a DNS-pinned HTTP connection pool with up to4 downloads, one robots-aware request-start gate including redirects, and bounded429/503 backoff. Already-readable SSR pages skip Chromium; thin pages retain the guarded renderer. Stop is exposed in Website assistant and cancels in-flight fetch/render/index work, leaving old published knowledge connected. Job-row locking serializes Stop/publication; queued cancellation updates knowledge status. Durable checkpoints retain in-flight URLs for retry. Unchanged extracted sources skip blob writes; unchanged source sets reuse the published snapshot and agent version. Azure content-addressed objects use conditional create instead of overwriting identical blobs; no old history is deleted.

Redis7.4 caches only derived embedding vectors, with opaque provider/credential/model/text keys, TTL, validation, bounded timeouts and failure fallback. Source text, authorization state, balances and job state are not cached there. `scripts/setup_redis.py` preserves existing private settings. Compose provides an authenticated, loopback-only, memory-bounded disposable Redis cache and existing authenticated Qdrant. `docker compose up -d redis qdrant` starts them. Website listing batches its related records/usage/latest-job queries instead of repeating queries per assistant; PostgreSQL pool and connection waits are bounded. Browser chat startup avoids Strict Mode duplicate sessions.

Validation and external limitations are recorded in docs/CRAWLING_PERFORMANCE.md and docs/VERIFICATION.md. Current API uses /workspace/.cloud-setup/nutaan-Rea/provider-dev.sh: local data/cloud-providers SQLite with real configured providers, disabled phone/payment/email actions and synthetic-only unverified signup. The older local-dev.sh retains cleared-provider QA. Built web runs on3100, Redis6379 and Qdrant6333. Normal default startup still selects the supplied remote database. Actual Redis/Qdrant contracts pass. After access changed, all configured live providers passed: Azure Blob, embeddings, Qdrant semantic/isolation, Azure gpt-6-luna streaming/tool round trip, Fish drama-3 and Deepgram nova-3. A synthetic website passed real Azure/Qdrant/LLM widget ingestion and unchanged-recrawl reuse; the actual synthetic-input spoken LLM/recording path passed too. Full isolated backend325passed2intentional skips, production build/typecheck and website Stop/widget/browser flow passed. Three additional transport/render/retry regressions were added. Isolated PostgreSQL17 with TLS passed64-table checks; five website assistants list in10queries including auth. Controlled5page600ms benchmark:3.316s serial vs1.872s concurrent (1.77×); not public-site latency. Read-only Azure listing:61raw crawl files (~10.2MiB), zero native snapshots/versioned entries. All-domain access is authorized and saved as ["*"] in the environment draft. Firecrawl skill/CLI are installed/authenticated, but api.firecrawl.dev returns proxy403; native DNS resolution and Supabase remain unavailable. Do not claim live public-site or remote DB success. User explicitly requests updating this AGENT.md after each completed task, then committing and pushing verified work without asking again. Preserve the private tracked .env. Current work is intended for a normal fast-forward push to origin/main; no public deployment or PR is requested.


Updated **24 October 2026**. Continue in `/home/hara/nutaan-platform`; preserve the implementation and private configuration. This is a tested development platform, with live-provider acceptance still pending. The user later supplied Azure Blob, Azure OpenAI/embedding, Fish and Deepgram credentials. These have been saved privately and live-tested; see docs/PROVIDER_ACCEPTANCE.md. The user deployed the exact Azure gpt-6-luna target; live streaming and a real function-call round trip now pass. Do not substitute another model or ask for the supplied keys again.

## Progressive workspace loading — 24 October 2026

Latest user reported extreme/repeated loading and explicitly requested fewer repeated tests. The performance update keeps Studio in a shared `/app/layout.tsx`, shows the real navigation after identity resolves, and loads only the current page's data. `useWorkspaceData` retains authenticated current-workspace memory for45seconds, deduplicates reads, keeps previously loaded pages visible during refresh, invalidates freshness after mutations, revalidates on focus/online, aborts obsolete requests on workspace change and ignores late responses. No private data is persisted to browser storage. Only visible active-job/call pages poll, with no overlapping requests. Auth/page reads have15-second timeout/retry recovery. First-load actions requiring resources remain behind page readiness; no empty-array fake readiness. Overview can show actual summary counts while activity remains a labelled skeleton; independent profile/settings screens do not wait for statistics.

Backend `/bootstrap?view=summary|overview|agents|...` is a closed optional page selection, reusing existing handlers, tenant permissions and redaction. No-query bootstrap remains backward compatible. Summary totals and14-day activity now aggregate in SQL instead of hydrating all calls. Page components are dynamically loaded; overview moved into overview.tsx so its first render does not download the monolithic editors, voice/tool/model screens. Shared route validator and a catch-all not-found boundary preserve missing-page behavior under the persistent client layout. Schema64/revision unchanged; OpenAPI140 paths gains only the optional query parameter. Private.env unchanged.

Completed verification: production build/typechecking passed; isolated full backend315passed2intentional skips; focused loading browser passed real API request ordering, shell/summary before activity, hot-page reuse, one identity request for Overview→Agents→Overview, zero full bootstrap requests, retry after503/timeout, independent profile and late-response isolation on workspace switch. Local compressed JS sample196907→161298bytes (~18% less), shell visible846ms with deliberately held page requests; these are local observations, not public latency guarantees. Beta regression, OAuth/WS booking and separate-origin website flows passed with zero page errors. Isolated PG17 summary aggregation, migration/restricted runtime and existing concurrency checks passed; no remote database/provider changes. Artifacts/dashboard/loading-before.json and loading-results.json.

An intermediate missing-route check found client loading hid server validation; children now render during identity loading and unknown routes use the scoped boundary/shared validator. Latest theme attempt passed missing-page display then hit the local synthetic-signup quota (429). The user then requested stopping broad repeats; remaining dashboard audit was stopped after desktop light/dark and mobile light, with no further broad runs. Do not claim a final completed full theme/96-route run for this loading update. Prior full dashboard results remain documented. Keep production signup limits intact. User preference: check focused behavior, avoid repeatedly rerunning every browser suite once relevant checks pass. Existing untracked .agents/ and skills-lock.json remain excluded.

## Dashboard readability and interaction polish — 24 October 2026

User requested larger text, smoother UI and dashboard bug fixes. New `apps/web/src/components/dashboard.css`, imported by Studio and scoped to `.studio`, owns readable workspace geometry/type: body/input16px, nav/table14px, secondary13–15px, headings30–40px, controls42–44px. Semantic light/charcoal colors remain in theme.css; local fonts/Lucide preserved. Sidebar256px/tablet224px, explicit76px collapsed rail, mobile288px; sticky header and responsive wrapped actions/cards. Dialog headers stay visible while their bodies scroll, notifications are bounded, short landscape sidebar remains reachable. Reduced motion disables transitions/scroll animation. Do not introduce tiny8–10px dashboard text again.

Fixed mobile close icon contrast, inherited toast dismissal timers, notifications retaining old workspace state (keyed by workspace base), misleading empty notification state while loading/failed (pending/error/retry now explicit), and close-button focus restoration. Mobile Test an agent action keeps its accessible label when visible text is hidden. An intermediate beta test caught a collapsed-rail CSS override; explicit scoped collapsed widths corrected it.

Final production build/typechecking passed. New scripts/verify_dashboard_browser.py covers24 pages ×2viewports ×2themes (96 route/layout checks), zero horizontal overflow/page errors, navigation persistence, short landscape, dialog scrolling/focus, reduced motion and deliberate notification outage/retry. Full beta browser passes all account/agent/contacts/notification/session/mobile flows. Theme browser also passed earlier in this pass. Artifacts/dashboard/results.json and screenshots; visual desktop/mobile review completed. Backend/schema/private.env unchanged, no provider calls/deployment; unrelated untracked .agents/ and skills-lock.json preserved. Local isolated API8100 and production web3100 remain running. See DESIGN_SYSTEM and VERIFICATION.

## Scheduling OAuth and preview answer correction — 23 October 2026

Latest user showed a real local Nature Nuskha preview answering “what all products give me one link” with an unrelated pregnancy FAQ. The cause was the one-page keyword extractor, not a failed crawl. New `preview_answers.py` separates catalog intent from evidence answers: real discovered same-origin catalog links, explicit partial products/missing information, sentence-level source fallback and the configured environment model for other follow-ups. The model receives bounded untrusted page evidence and up to8 validated user/assistant history entries; no tools, extra fetching or business side effects are exposed before signup. URLs use validated discovered link IDs, not guessed paths. Inference absence/failure is explicitly labelled. Initial overview still reads one page, saving still queues the broader website crawl. Frontend renders actual links/notices. Visual review additionally found the Send arrow inherited the button background color; a theme override and browser contrast assertion fix both themes.

Cal.com/Calendly now support dashboard owner/admin OAuth consent, exact fixed `/backend/v1/auth/scheduling/{provider}/callback` URLs, encrypted single-use ten-minute state, browser and exact auth-session binding, encrypted tokens, profile verification and durable one-shot rotating refresh. Cal confidential mode uses its secret; Cal public and Calendly use S256 PKCE. No API-key OAuth initiation. OAuth account binding survives access refresh but not replacement/event selection. Ambiguous refresh requires reconnect, never token/booking POST replay. Manual connection/disconnection serialize with refresh; tokens never reach browser payloads. Customer still selects the meeting type, enables the booking bundle and publishes. This is integration authorization for a signed-in workspace, not new Cal.com/Calendly application login. Google Calendar remains independent.

New private placeholders: `CALCOM_CLIENT_ID`, `CALCOM_CLIENT_SECRET`, `CALCOM_OAUTH_MODE=confidential`, `CALENDLY_CLIENT_ID`, `CALENDLY_CLIENT_SECRET`. `.env` retains every prior byte/value and mode0600. Register actual provider apps, fill credentials, restart API; Cal.com approval and Calendly Standard+/Scheduling API entitlement remain required. Exact production redirects/scopes/modes and honest source provenance are in `docs/SCHEDULING_OAUTH.md`. No live registration, consent, remote revocation, meeting, email, carrier action or deployment occurred. Local disconnect deletes encrypted credentials; external grant revocation remains at provider settings.

No new table/migration: **64 tables**, revision **2026-10-23-website-assistants**, exported OpenAPI **140 paths**. Final isolated suite **288 passed,2 intentionally skipped in86.37s**; targeted preview checks43passed and OAuth checks51passed. Production web build passed. Preview browser (actual app with synthetic website/model boundaries), OAuth browser (synthetic provider consent/token/profile/model with actual routes/WS booking), and full beta regression pass with zero page errors; preview and OAuth cover desktop/mobile/light/dark. Artifacts `artifacts/preview/browser-results.json`, `artifacts/scheduling-oauth/browser-results.json`, `artifacts/beta/results.json`. Isolated PG17 repeatable59→64 upgrade/restricted no-DDL startup and number/booking races pass; two concurrent OAuth refresh requests perform one simulated token exchange. No remote Supabase changes. Updated `/workspace/.cloud-setup/nutaan-Rea/local-dev.sh` API restored on8100 and built web on3100; QA providers remain deliberately cleared. Existing unrelated untracked `.agents/` and `skills-lock.json` remain excluded.

The uploaded log `sediment://file_00000000b7c481f5a8f601a0c27060ac` shows a separate Chromium apt build killed with exit137. It does not cause the keyword FAQ answer. No completed new API Docker image/resource diagnosis is claimed. Actual reference-site/provider acceptance still cannot be established from this cloud's blocked egress; synthetic checks must not be presented as a live Nature Nuskha or Aurely crawl.

## Website assistants and interactive widgets — 23 October 2026

The user supplied a full uploaded spec for automatic website ingestion and interactive widgets, with Fish/Nutaan screenshots. This checkpoint supersedes earlier static-only/manual-widget descriptions and counts. New `website_routes.py`, `website_crawler.py`, `website_extraction.py`, `website_actions.py` implement one-step URL → durable crawl → existing storage/chunks/embeddings/Qdrant → published bound agent → widget. Agent creation optionally accepts website_url; claiming the first-minute preview preserves its usable page and queues the broader crawl. Existing published configurations refresh after successful indexing while unpublished human draft edits remain unpublished; old conversations retain their pinned sources. Product facts/cards come from source revisions, not a mutable later crawl.

Crawl: same-origin links and bounded sitemap indexes; robots checked before requests/redirects, minimum250ms/robots crawl-delay/request-rate, permission errors fail closed; default100 indexed pages, operator range1–1000, remaining/failure/duplicate/rendered counts. Guarded Playwright/system Chromium renders thin/application-shell pages. All permitted HTTP is fulfilled via DNS-pinned public GETs, with a dead browser proxy as fallback, QUIC/background networking disabled, RTC/WebTransport/Workers disabled, service workers/websockets/downloads/POSTs/third-party resources blocked;30s/60-resource limits. API image installs system Chromium; Playwright moved to runtime dependencies. Complex third-party-dependent/login/anti-bot/OCR sites remain unsupported. JSON-LD products/offers/variants/specifications are embedded with page evidence and update the existing catalog. Absent/invalid prices are never invented; existing two-decimal catalog convention remains.

One new tenant binding table `website_assistants` stores relationships, bounded crawl settings/exclusions and next refresh. Daily refresh by existing worker, interval0 pause, install-disable/agent-archive pause. Crawl failures retain old active snapshots. Website dashboard provides actual progress/notices, page exclusion/include on next crawl, update schedule, neutral responsive appearance/settings, HTML/GTM/WordPress/Shopify snippets, API-backed chat testing, persisted usage counters and links to Inbox/Leads/Appointments. Existing installations remain under an expandable panel; none removed. Lucide/local-font/theme conventions preserved. Source/HTTP/product/model text stays untrusted data.

New widgets have unique public IDs and publishable keys; no private key is embedded. Keys stored in installation theme; updates preserve them; rotation revokes chat/resume/voice. Older installations without a key retain their existing snippets. Origin-bound30min access and seven-day same-tab sessionStorage resume preserve actual saved conversation history across navigation. Current origin/path only is sent, queries/fragments stripped. Model website_search/open_page/scroll tools validate indexed source URLs/sections; host independently restricts same-origin action shapes. No eval/arbitrary JS/selector/cart/checkout mutation. Navigation dispatch follows persistence; stored action IDs prevent repeated navigation. Dashboard shows links instead of navigating itself. Agent's existing configured ticket/lead/custom HTTP/calendar/booking tools remain shared. Text and voice share conversation evidence/history; scheduling context prioritizes widget conversation identity so a booking can be prepared in text and confirmed in voice. Voice website events follow final transcript persistence. Active/new voice checks key rotation.

Schema **2026-10-23-website-assistants**, **64 tables**, OpenAPI **138 paths**. Production startup still no-DDL; actual remote migration/grants/live activation pending. No new private .env fields; private .env byte-for-byte unchanged. New spec/doc: docs/WEBSITE_ASSISTANTS.md. Final full suite **217 passed,2 intentionally skipped**; guarded native Chromium, actual tool runtime and both provider scheduling paths/voice continuation covered. Production web build passed. New independent-origin website browser, beta regression and existing embed regression passed with zero errors; visual review corrected clipped mobile controls and current-product evidence ranking. Artifacts website/browser-results.json and screenshots. Isolated PG17 59→64 repeatable upgrade/restricted startup/concurrency passed; no Supabase changes/provider calls. API Docker dependency step passed with existing cloud CA secret but Chromium apt step hit host disk limit; updated full image build remains unaccepted here. Do not claim reference-site/provider/public/microphone acceptance. Reference-site robots fetch is blocked by cloud egress. Latest user specifically requested testing https://aurelyjewellers.in/: actual isolated app URL submission returns422 before crawl because DNS fails; www alias/example.com/github.com also fail and ordinary proxy diagnostics fail. Zero real pages/products extracted; no claim of proper Aurely coverage. Reproduce with scripts/verify_live_website.py; artifact artifacts/website/aurely-live-results.json. No paid action, email, real meeting or deployment occurred. Preserve unrelated untracked .agents/ and skills-lock.json.

## Neutral themes and motion — 23 October 2026

The user's latest Fish Audio/ElevenLabs screenshots override the older green/off-white-only direction below. Use warm neutral light surfaces and charcoal dark surfaces, subtle borders and restrained teal for status/highlights. Do not bring back a large green sidebar or green panels. `theme.css` owns semantic tokens and overrides; legacy geometry is in the base CSS layer. Preserve Lucide and locally bundled licensed WOFF2 fonts; never add third-party font/CDN calls.

`ThemeProvider` bootstraps the device/manual preference before paint, persists it locally and synchronizes tabs. Header controls offer Light/Dark/Use device setting across home/login/workspace/docs/404. Custom loading files and the initial workspace loader show an actual pending state without fabricated progress. Unknown workspace sections invoke notFound instead of rendering the dashboard; Next streamed notFound can retain HTTP200 with noindex.

A lazy Remotion4.0.538 Player provides a 16-second illustrated tour on home/overview with play/pause, chapter shortcuts and a text transcript. It stays paused initially, pauses when hidden and respects reduced motion. Route/hover/loading graphics use CSS; auth canvas uses theme tokens, visibility suspension and reduced-motion rendering. Do not load the Remotion player on every page or use it as the small loader. No audio/provider call or video export is necessary for this UI.

Run `scripts/verify_theme_browser.py` with the prepared system Chromium wrapper and isolated development API. It checks fonts, themes/persistence/tabs/device setting, loading, missing routes, tour controls, desktop/mobile pages and reduced motion. Existing beta/embed checks protect the app flows. Preserve private .env and its placeholders/values. Current changes do not activate any live provider.

## Cal.com/Calendly call-agent booking — 23 October 2026

The user requested direct booking during calls. `studio/scheduling.py` and `scheduling_providers.py` implement real provider availability, selected meeting types, caller-provided details and required questions, exact read-back, a later unambiguous confirmation and one-shot booking submission. `providers.answer_stream` routes four scheduling tools and emits the stored read-back/result verbatim into the actual conversation transcript. Confirm requires that exact prior non-interrupted assistant text, a later turn, unchanged connection/event data and a newly available exact slot. Qualified agreement such as “yes, but at11” cannot authorize the previous time. Duplicate/concurrent confirmations, interruptions and lost responses do not trigger another booking POST; stable Cal.com metadata/Calendly tracking allows read-only reconciliation. Pending host approval is not confirmed. Local cancellation cannot masquerade as remote cancellation.

Connect providers in Integrations, select an event under Set up call booking, enable the booking bundle in Agent → Actions, choose Booking platform and publish. The platform is bound per agent so callers do not choose one. Appointments shows recorded requests, provider status/refresh and management links; times use the stored caller timezone and mobile booking rows show status/actions without sideways scrolling. Keys remain encrypted per workspace; **no new .env fields**, and private .env is unchanged. Calendly direct booking requires Standard or above plus event_types:read, availability:read, scheduled_events:read and scheduled_events:write. Cal.com needs hosted API event/booking access. See docs/AGENT_SCHEDULING.md for supported forms, versions, limitations and source provenance.

Latest schema: **2026-10-23-agent-scheduling**, **63 tables** (adds scheduling_availability/scheduling_bookings to the prior61); contract **132 paths**. Production startup remains no-DDL. Agent tool config supports an optional scheduling_provider, narrowed in the tool schema and checked server-side. Do not claim a provider link or local appointment as a remote booking. Current constraints: one selected event per provider/workspace, a seven-day search window/100 slots, no required payments/Cal.com recurring events/unsupported required forms/Calendly invitee-selected locations, no provider webhooks or direct API reschedule/cancel. Manage changes at the provider and refresh status.

Verification: full isolated suite **203 passed,2 skipped in53.61s**; the two skips are intentionally provider-specific cases. Actual VoiceSession and WebSocket text simulation cover both adapters with fake model/provider responses. Production build passed; the scheduling browser checks connection and event-selection UI, per-agent platform selection/publication, read-back→yes→one simulated booking for each provider, history, themes and mobile. Full beta regression also passed with zero page errors. PostgreSQL17 isolated59→63 migration/repeatability, restricted-role production startup, phone admission/allocation and concurrent booking tests passed; two confirmations produced exactly one mocked booking POST. Artifacts: scheduling/browser-results.json and automatic-numbers/postgres-results.json. Temporary PostgreSQL/browser APIs were removed; local preview runs isolated SQLite63 and disabled paid providers. No real booking, provider notification, microphone or PSTN call occurred.

Research used official Cal.com source. Calendly developer/Stoplight domains were proxy-blocked, so the inspected contract was a dated third-party snapshot of Calendly’s published OpenAPI with generator provenance, explicitly recorded in docs/AGENT_SCHEDULING.md. Real account plan/scope/booking/notification/cancellation acceptance is still required; no actual carrier or calendar entitlement is implied by offline tests. This section supersedes earlier statements that Cal.com/Calendly direct booking is absent and earlier table/path counts below.

## Automatic seven-day number assignment and provider research — 23 October 2026

User preference: **always answer in English**. Users must not choose/buy their trial source number. They click Start free phone trial; the server assigns a dedicated number for seven days. This checkpoint supersedes the older operator-only/no-purchase statements below.

`studio/number_provisioning.py` adds durable one-person/one-workspace enrollment, approved owned-stock allocation and optional Twilio US local-number rental. A global PostgreSQL transaction advisory lock (SQLite BEGIN IMMEDIATE in tests) serializes rental reservations across pools. Quote/currency/per-number/total-budget/balance/stock/pool expiry checks precede the only carrier POST. Commit purchase intent first; timeouts/408/429/5xx/ambiguous outcomes are reconciled by exact carrier marker, never re-purchased. Unknown reservations remain charged against our internal rental budget; operator alerts use existing durable SMTP retry. No automatic parent-account creation, fresh credit, DID release or budget reset exists. Trial access does not cancel monthly rental.

The signed-in owner/admin endpoint accepts `{}` only: GET/POST `/v1/workspaces/{workspace_id}/phone-trial`; API keys cannot enroll people. Default grant expiry is at most seven days, bounded by pool expiry. Automatically assigned numbers start with no approved recipients; the operator approves provider-verified, consenting test destinations through CLI. The UI explains this and disables calling until recipients are configured. It refreshes actual queued jobs and contains no trial number picker.

CLI adds stock (read-only ownership proof), destinations and read-only reconcile. Existing configure/grant/replace/pause/revoke/status remain. `.env` and example gained six settings: optional blank TWILIO_API_KEY/SECRET, blank PHONE_TRIAL_AUTO_ASSIGN_POOL_ID, PHONE_NUMBER_PURCHASES_ENABLED=false, PHONE_NUMBER_MAX_MONTHLY_PRICE_MINOR=150 and PHONE_NUMBER_TOTAL_BUDGET_MINOR=1500 (USD cents). All existing private values and mode0600 were verified unchanged. Pool captures optional API key pair; account Auth Token remains required for callback signatures.

Schema revision is now **2026-10-23-auto-phone-numbers**, **61 tables**, adding phone_number_orders and phone_number_inventory to the prior59. Production startup still has no DDL. Contract has **128 paths**. Apply reviewed migrations and runtime grants on the actual database before rollout; no remote schema was changed here.

Latest verification: **150 isolated backend tests passed**; final production build passed. Mobile one-click enrollment, owned-stock allocation, automatic refresh and existing allowance/expiry/desktop/mobile/light/dark browser checks passed with zero page errors. Full beta browser regression also passed, including JWT/tab refresh and profile/contacts/agent/mobile flows. A temporary PostgreSQL17 upgrade59→61, restricted-role production startup and parallel admission passed. Two concurrent automatic orders under a one-rental budget made exactly one mocked purchase (assigned/unavailable); no real carrier request. Evidence: artifacts/phone-trials/results.json and artifacts/automatic-numbers/postgres-results.json. Reproduce with scripts/verify_number_allocation_postgres.py and the prepared system Chromium wrapper for verify_phone_trial_browser.py. All temporary PostgreSQL containers/volumes were removed.

At the user's request, official twilio/ai was cloned to /workspace/ai and its57 leaf skills installed under /home/agent/.agents/skills (also preserving the requested nested copy). Applied account setup, IAM authentication, number selection and reliability guides. Research sources and exact revisions are in docs/FREE_NUMBER_RESEARCH.md: Twilio, Telnyx freemium and SignalWire have one-number trial limits in inspected official sources. Current Vapi base offers one free US inbound-only number; higher counts depend on paid packages. Telnyx Professional identity evaluation is a conditional lead, not a confirmed free multi-number entitlement or guaranteed credit retention. Do not repeat the unverified $15/$1=ten Twilio trial numbers claim or identify Nutaan's private carrier bill as fact. Several documentation domains were proxy-blocked; official public GitHub documentation was inspected instead. No accounts, identity submissions, upgrades, rentals, calls or emails were made. Actual carrier/SMTP/public acceptance and other release gates remain.

## Expanded private beta — current cloud checkpoint

Phone trial update, 23 October 2026: user authorized bootstrapping an invited beta from available provider credits until initial revenue. `studio/phone_trials.py` and `scripts/manage_phone_trials.py` implement operator-funded Twilio pools, explicit assignments/replacements, a maximum 20-day window, default 10 lifetime workspace assignments and 3 calls of at most 60 seconds each. Calls reserve a non-refundable allowance before queuing, allow only approved test destinations, recheck eligibility at dispatch/answer/media, pin encrypted carrier bindings and apply provider time limits. The operator can pause/revoke or replace a valid account/owned number without resetting workspace usage/expiry. No account creation, credit renewal, number purchase, rental cancellation, shared caller ID or live provider acceptance is implemented. Platform Twilio credentials do not fall back to unassigned workspaces while trials are enabled.

Balance checks are read-only and fail closed on unknown/stale/low/wrong-currency balances. Operator expiry/balance/exhaustion emails use the existing SMTP path with persisted retry; workspace notifications and the Phone numbers allowance/test-call UI are implemented. The two new private settings are `PHONE_TRIALS_ENABLED=false` and blank `BETA_OPERATOR_EMAIL`; all earlier values are preserved. Real SMTP/Twilio access, public acceptance, the original stable APP_SECRET and other release gates remain pending. See `docs/PHONE_TRIALS.md`. `SCHEMA_REVISION` is now `2026-10-23-phone-trials`: 59 tables. Runtime remains no-DDL; apply reviewed migrations/grants on the actual main database before release.

Database configuration update, 23 October 2026: user selected the main Supabase project for both app and schema maintenance after supplying a second project URL. `.env` now uses its IPv4 transaction pooler (port 6543, TLS) in `DATABASE_URL` and `MIGRATION_DATABASE_URL`. The second project is not configured. Removed obsolete split `SUPABASE_DB_*`, duplicate `RUNTIME_DATABASE_URL`/`OPENAI_CHAT_MODEL` and redundant legacy Razorpay fallback keys; provider values and Google/SMTP placeholders are preserved. The beta overlay reads `DATABASE_URL` directly. Psycopg automatic prepared statements are disabled for transaction pooling. The supplied owner login is still used for runtime; restricted-role setup remains a release gate. Do not claim remote migration or connectivity success: read-only pooler probes failed due to cloud name/address resolution. Legacy split-field support remains in code for older deployments only; it must not override the new URL.

This checkpoint overrides older absent-feature and Docker statements below. Work is now in `/workspace/nutaan-Rea`. User requested the complete app/docs together at `docs.cynerza.in`; Google/SMTP configuration should be prepared and they will supply access. Preserve tracked `.env` and its original stable encryption secret. No PR, public deployment, carrier call or provider purchase occurred.

Implemented: Google OIDC state/nonce/PKCE and explicit linking; SMTP verification/reset; short-lived JWT access and rotating CSRF-bound refresh with replay revocation; session/device controls; profile/preferences and notifications; structured variables bound across widget/campaign flows; recent widget context; optional origin-bound public voice with durable turn/concurrency admission; tenant Twilio/Plivo credentials; Google Calendar OAuth/agent availability/sync; Cal.com/Calendly verified hosted links; consented contacts CSV/JSON preview/import/export/campaign drafts; collapsible desktop and accessible mobile navigation using Lucide and the existing palette. Cal.com/Calendly direct booking is covered by the newer scheduling checkpoint above. Importing hosted ElevenLabs/Fish agents remains unimplemented.

Production now checks `SCHEMA_REVISION` without DDL. `scripts/migrate_database.py` applies reviewed additive schema separately. `deploy/compose.beta.yaml` and Caddy route app/docs/API/SSE/WSS on one host and require runtime/migration connections to the same database. See `docs/BETA_DEPLOYMENT.md` for configuration, grants, backup and activation gates. Actual OpenAPI has 127 paths; trial status extends the authenticated summary. Tests remain isolated temporary SQLite and clear external keys.

Current cloud cannot resolve/connect to the supplied Supabase/Azure endpoints. Do not alter credentials, weaken DNS/SSRF/TLS or run destructive fixtures remotely. Explicit local helpers under `/workspace/.cloud-setup/nutaan-Rea` use `data/cloud-local`, local objects, cleared providers and verification disabled only for synthetic QA. Production requires verified email. Native SMTP and local signing need real secret values securely in environment/private .env, not network-proxy placeholder secrets.

Latest tests: full isolated suite 125 passed, including 21 phone-trial cases. Actual operator CLI and isolated SDK/SMTP contracts pass; the phone browser covers real API admission, allowance, expiry and light/dark desktop/mobile. PostgreSQL upgraded 56→59 tables, restricted production startup passed and parallel admission reserved one call. The final production build, full beta browser and theme browser pass with zero page errors. Studio now waits for the selected workspace bootstrap before exposing controls, fixing early agent dialogs with empty knowledge options. See VERIFICATION for evidence. Public Google/SMTP delivery, remote migrations/least privilege/restore, physical microphone, public carrier callbacks/calls, real calendar connections, load/recovery and paid pricing remain release gates. Earlier provider acceptances below are from another host and must not be reported as current cloud checks.

## User decisions and latest scope

- Public hero: **one promise, one primary button, useful result before signup in under 60 seconds**. Implemented `/`: “Your website. Answering customers.” → Try my website → cited answer → follow-up → Keep my assistant. Palsona returned its first answer in **6.91 seconds** in the latest timed browser check. Preview reads one page and explicitly labels source-excerpt text; it is not a simulated audible call.
- Current requested runtime LLM: Azure `gpt-6-luna` (env; live streaming/tool round trip passed). Code fallback default remains `gpt-5.6-luna`; supports **configurable OpenAI-compatible endpoints/models**. The later user instruction overrides the old fixed-model restriction. `OPENAI_BASE_URL`, protocol, token parameter and reasoning effort are configurable. Workspace model profiles require documentation retrieval and a streaming/tool-schema probe; keys are encrypted and write-only. Before adding any new preset, research official model/API docs, including reasoning-mode constraints. Do not assume all newer models reject temperature or all compatible endpoints accept the same cap. See `docs/MODEL_COMPATIBILITY.md`.
- Current runtime Fish Audio `drama-3`, supplied authorized voice ID; Deepgram `nova-3` recognition. Both passed real streaming tests with synthetic speech. App live PCM/ticket/announced stereo Azure recording path also passed (first audio3034ms); The full Deepgram→Azure gpt-6-luna→Fish→Azure recording path now also passes with synthetic input and lexical fixture knowledge; physical microphone remains unverified.
- Azure Blob Storage for object data; Supabase PostgreSQL for transactions; self-hosted Qdrant v1.19.2 with `text-embedding-3-small` (1536 dimensions). Rootless Podman/systemd on127.0.0.1:6333; authenticated persistent storage. Compose also includes Qdrant. See docs/QDRANT.md.
- Both Plivo and Twilio signed callbacks/media adapters. Public HTTPS/WSS origin and provider-owned numbers required. No live phone call has been placed by this implementation.
- Custom tools: cURL import, JSON Schema arguments, typed JSON/URL/header templates, immutable revisions, content/access/test UI, encrypted headers, mock/real test, blocking/background/fire-and-forget execution and audit history.
- Developer guide: frontend `/docs`, `docs/DEVELOPER.md`, actual API `/docs` and `packages/contracts/implemented-openapi.json` (127 paths).

Earlier authority covered inspecting the user's Nutaan account and controlled test phone, microphone, QA key and existing Nutaan credits. It does not authorize arbitrary recipients or unlimited new provider purchases. No new chats/subagents, PR or public deployment were created in this implementation pass. The checkout now has an existing origin and two commits, including pre-existing remote-tracking history. Preserve user Git work; do not rewrite or force-push history.

## Private configuration and safety of test data

Supabase, Azure Blob, Azure OpenAI/embeddings, Fish and Deepgram credentials are supplied. Azure container is private and real storage/embedding/speech tests passed; Azure gpt-6-luna deployment is available and live-tested. Qdrant is now self-hosted; its generated key is privately saved in `.env` and the user service environment. Telephony/SMTP/connector setup is still absent. Razorpay test/live key pairs are supplied; RAZORPAY_MODE=test selects the test pair throughout requests, checkout and signature verification. Checkout remains disabled because its existing activation flag is false and the webhook secret is absent. The user explicitly chose to keep `.env` tracked in the private repository; preserve that decision. Local file mode0600 is retained. Shareable source exports exclude `.env` and Git history. **Never print its contents, settings objects, DSN, keys or signing secrets.** Preserve `data/.session-secret` / stable `APP_SECRET`, which encrypt stored secrets. Do not copy private/runtime data into the source archive.

The default API selects the supplied Supabase `voice_studio` schema through `DATABASE_URL`. The legacy `SUPABASE_DB_PASSWORD` override remains supported for older deployments but is removed from the current `.env` and cleared in production Compose. Pytest must retain `tests/conftest.py` isolation: temporary SQLite, local objects, provider keys cleared, live calls/payments disabled. **Never run fixture drop/create against Supabase.** The separate PostgreSQL/browser checks retain clearly named synthetic QA rows without dropping/truncating remote tables or modifying unrelated schemas.

## Run and verify

Inspect listeners before starting duplicate processes. API/web were running on 8100/3100 at checkpoint; tool session IDs are transient. Environment changes need an API restart. Avoid reloading during a voice check.

```sh
uv sync --frozen
npm ci
uv run uvicorn studio.main:app --app-dir services/control --host 127.0.0.1 --port 8100
```

Second terminal: `npm run dev`. Home `http://127.0.0.1:3100`; workspace `/app`; guide `/docs`; API `http://127.0.0.1:8100/docs`, health `/healthz`.

```sh
uv run pytest -q
npm run build
uv run python scripts/check_database.py
uv run python scripts/verify_postgres.py
uv run python scripts/verify_first_minute.py
uv run python scripts/verify_agent_platform.py
uv run python scripts/verify_browser.py
uv run python scripts/verify_embed.py
uv run python scripts/verify_qdrant.py
docker compose config --quiet
```

Browser checks require Chromium (`uv run playwright install chromium`) and running servers. Results/screenshots are in ignored `artifacts/`. Follow the latest counts/results in `docs/VERIFICATION.md` and `PROGRESS.md`.

## Implementation map

Backend `services/control/studio`:

| Modules                                           | Responsibility                                                                                                                                                                                               |
| ------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `models`, `db`, `main`                            | 45 SQLAlchemy tables, dedicated PostgreSQL schema, composite tenant FKs, UTC, additive initialization, immutable ledger/audit/agent/tool-version triggers                                                    |
| `security`, `auth_routes`, `account_routes`       | Argon2, opaque revocable sessions, CSRF/origin/roles/scoped keys, single-use password reset, SMTP or private development email outbox, identity-bound invitations/access/revocation                          |
| `preview_routes`                                  | Owned expiring no-account website preview, citations, follow-up, atomic claim into KB/published agent/widget                                                                                                 |
| `core_routes`, `operations_routes`, `domain`      | Batched dashboard bootstrap, CRUD, immutable publication, runtime variables, wallet admission/settlement, transactional events                                                                               |
| `knowledge`, `storage`, `retrieval`, `network`    | Static crawl/robots/redirect/canonicalization, documents/chunks/snapshots, Azure/local objects, Qdrant/embedding contracts, DNS-pinned public egress                                                         |
| `llm`, `model_routes`, `providers`                | Responses + Chat streaming, API-specific caps, no default temperature, prestream parameter negotiation only, fragmented tool calls, documented encrypted profiles, Fish MessagePack stream                   |
| `agent_tools`, `http_tools`                       | Scoped persisted business actions; declarative HTTP tools, revision pinning, schema validation, no shell/local-file execution, bounded/redacted responses, stable identities and uncertain outcome handling  |
| `media`, `recording`                              | NTV1 PCM16 browser protocol (16k input/24k output, 32-byte header), recognition, epoch cancellation/clear, silence/idle limits, transcripts, announced opt-in stereo WAV recording/retention                 |
| `carrier`, `twilio_routes`                        | Separate Plivo/Twilio signature and protocol adapters, canonical leg binding, mu-law8k/stateful soxr, owned numbers, callback replay/settlement                                                              |
| `workers`                                         | Single dispatcher with durable jobs, checkpoints/leases, campaigns up to8 concurrent/5 attempts, busy/no-answer retry, calling windows, aggregate budget; signed webhook retry, retention/orphan maintenance |
| `resource_routes`, `connectors`, `payment_routes` | Transcript/CSV/audio downloads, expiry/deletion/audit; encrypted verified HubSpot/Google Calendar/Plivo SMS adapters; Razorpay orders/capture verification/once-only credit                                  |

Frontend `apps/web`: Next16.4.2/React19.3.1. Read `apps/web/AGENTS.md` and installed Next docs before framework changes. `studio.tsx` owns workspace/nav/refresh; `workspace-pages.tsx` core resource/editor views; `tool-studio.tsx`, `model-studio.tsx`, `business-tools.tsx`, `campaign-manager.tsx` expanded screens; `first-minute.tsx` public value flow; `voice-lab.tsx`, `widget-chat.tsx`, `public/widget.js` browser experiences. Fonts are self-hosted with OFL licenses.

## Current evidence and practical limits

Offline suite covers both LLM protocols/tool round trips, rejection fallback and no replay after partial text, cURL/schema/private-address guards, immutable HTTP versions, actual mock-transport execution/redaction/deduplication, Twilio/Plivo signatures/replay, account recovery/invites, captured payment deduplication, calendar busy checks/stable remote identity, stereo WAV/expiry, campaign concurrency/retry/budget and prior tenant/accounting/media tests.

Supabase TLS/45-table schema/isolation/append-only/concurrent settlement checks passed. Browser checks cover actual Palsona first value and saved assistant, tool setup/mock/access, models, team, workspace navigation/docs, prior text simulation/ticket/catalog and external widget. Do not present text simulation or offline provider contracts as live speech/phone acceptance.

Remaining gates:

1. Azure gpt-6-luna deployment404 is resolved; live streaming/tool round trip, Azure Blob/migration, embeddings, Fish drama-3 and Deepgram passed. Self-hosted Qdrant indexing/filter/outage/restart recovery and actual application hybrid retrieval now pass; production backup/restore and capacity acceptance remain. Full LLM voice using synthetic input/lexical fixture knowledge passed (reply audio7015ms after final transcript). Tune latency and complete physical microphone/interruption/disconnect acceptance. See docs/PROVIDER_ACCEPTANCE.md and the real provider scripts.
2. Public TLS/WSS staging, exact signature URLs, actual owned number inbound/outbound acceptance for each carrier; provider outage/unknown dispatch reconciliation. Current live tariff is explicitly **unpriced testing**.
3. Verify real connector scopes/actions and Razorpay capture flows. Calendar bookings are local until explicit remote sync succeeds; SMS acceptance is not delivery. Refunds, WhatsApp, MCP, human call transfer remains absent. Google OAuth/email verification are implemented in the expanded beta checkpoint above.
4. Production migrations/restricted runtime DB role/RLS/backups, pagination/aggregation, distributed rate limits/socket ownership/job recovery and load testing. Run one API/dispatcher process. Some async control paths still use synchronous DB access; per-frame media DB polling was removed, and idle dispatcher/retention DB work runs in dedicated threads.
5. JS-rendered crawling/OCR and broader site coverage; configurable model-graded post-call criteria/test suites and advanced guardrails remain future work. Current postcall summary is evidence-based local analysis, not a full model evaluator.
6. API/web Docker images/runtime remain unverified because daemon access is denied. The actual Qdrant image/runtime is accepted through rootless Podman. No public deployment performed.

Current docs override the older `/home/hara/nutaan-rebuild-kit` blueprint (pgvector/S3, fixed model, deferred features there are stale). Preserve `/home/hara/nutaan-investigation/REPORT.md` as observations, not recovered private backend code. Update this handoff/status/contracts/archive after material changes. Never advertise a config field alone as a working runtime feature.

Razorpay follow-up: both mode-specific pairs are privately saved. New mode selection prefers an entire matching pair, never mixes a missing secret with legacy credentials, and does not fall back from test mode to a recognizable legacy live key. No payment was created or charged.

Extended voice demo: scripts/generate_voice_demo.py generated a5m13s/192kbps MP3 using the configured Fish drama-3 voice, with English/Hindi/Hinglish and fictional business scenarios. MP3/transcript/manifest are in artifacts/voice-demo/ and private Azure copies are verified. Command uses paid Fish TTS; completed sections are cached unless --refresh. Full MP3 decode validation passed.

Historical visual direction (superseded by the neutral theme checkpoint above): the user wanted the site's green and off-white palette, including login. `auth-particles.tsx` draws an organic green point cloud on the light login/signup panel, with pointer response, a 30fps cap, reduced-motion still rendering and suspension when hidden/offscreen/mobile. The later neutral-theme instruction above takes precedence. The public hero art in `first-minute.tsx`/`first-minute.css` now has orbiting dots, expanding signal ripples, breathing center, animated voice bars and gently drifting notes; CSS motion stops for reduced-motion preferences and pauses offscreen/when the document is hidden. Existing one-promise/one-button copy, website preview and authentication behavior are preserved. Browser checks and production build passed; visual evidence is in ignored `artifacts/brand-motion/`.

Preview follow-up: the public preview still uses lexical/extractive page answers, not the configured LLM. Previously bare “hi” was incorrectly treated as absent website evidence, and every assistant reply got a source label/link. `preview_routes.source_answer` now handles greetings/thanks as `mode: conversation`, returns missing evidence as `mode: not-found`, and gives both an empty citations list. Only actual source excerpts have citations. `first-minute.tsx` uses the mode to label replies, safely handles empty citations and scrolls its message pane to the latest reply. Full isolated suite85 passed; build and actual Palsona browser flow passed (first result2.94s, greeting/thanks/unknown/source cases, mobile, keep handoff, zero page errors). API refreshed on8100. See docs/VERIFICATION.md and scripts/verify_first_minute.py.

Qdrant follow-up: `scripts/setup_qdrant.py` installs `deploy/qdrant.container` as the systemd user `voice-studio-qdrant.service`, saving its key privately and binding only127.0.0.1:6333. This host has lingering enabled for startup after reboot/continued operation after logout. Named Podman storage/snapshot volumes persist separately from Docker Compose volumes. API host setting is loopback; Compose overrides it to http://qdrant:6333 and gates startup on readiness. All14 published snapshots were backfilled with scripts/reindex_knowledge.py --apply;29 vectors persist. Live Azure1536 semantic ranking, tenant/snapshot filters, idempotent reindex, outage reporting, restart durability and application qdrant-hybrid retrieval passed. Full isolated suite85 passed in24.07s. scripts/verify_providers.py now performs the Qdrant check when configured. API/web host listeners were not running during this task; their next normal startup loads the new env. Do not ask for Qdrant credentials again or delete its volumes. docs/QDRANT.md records management/rebuild commands and remaining production backup/restore work.

Telephony research22 October2026: docs/INDIA_NUMBERS_RESEARCH.md records official current prices/KYC and captured Nutaan evidence. The trial line is US/Telnyx; the captured client explicitly routes India number search/purchase to Plivo. Its country dropdown leaves old rows visible while flags follow selected country, explaining India flags on +1 results. Earlier actual India searches returned +9180 Bengaluru fixed numbers. Plivo's reseller flow requires customer-specific compliance/subaccounts; GST, incorporation or Udyam are accepted alternatives. This research does not purchase numbers, submit KYC, identify Nutaan's last-mile operator or implement automated number rental. Existing call adapters/owned-number registration are separate from a complete provisioning/KYC product.

The user supplied a later screenshot showing Cynerza Systems Private Limited's Plivo India Local-number KYC Approved. Preserve that fact; don't ask for the same company KYC again. Customer-reseller compliance is still customer-specific. Per-call workspace number selection exists in workers.outbound_job, but settings.capabilities()['telephony'] still requires a global environment caller ID; this is a remaining gate to fix before treating PLIVO_CALLER_ID as purely optional. Research proposed a carrier-funded, verified-destination, capped seven-day outbound demo followed by a customer-owned dedicated number. No carrier purchase/provisioning or further spending was authorized or performed by this research.

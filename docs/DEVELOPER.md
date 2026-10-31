# Voice Studio developer guide

## Backend test modes

`uv run pytest -q --strict-markers` runs the fast local suite without Docker.
Tests marked `sandbox` are explicitly skipped. Use
`uv run pytest -q --run-sandbox --strict-markers` for full acceptance: Docker,
Chromium and `poppler-utils` must be installed. Pytest owns a temporary isolated
content container; an unavailable runtime fails this mode. CI requires the flag
and `.github/workflows/backend-tests.yml` installs the prerequisites, starts Redis,
builds the runtime and runs every backend/sandbox test. Production isolation stays
mandatory in both test modes. See [file safety](FILE_SAFETY.md) for runtime limits.

The browsable guide is `/docs` on the web app. Swagger is `/docs` on the API; implemented contract is `packages/contracts/implemented-openapi.json` (140 paths). `packages/contracts/openapi.json` is an old preparation blueprint.

## Authentication and versions

Server integrations send `X-API-Key` with a workspace-scoped key created under Developers. Examples below need calls:write, agents:write/read, knowledge:write/read or developer:write as appropriate. API keys never belong in browser bundles. Browser dashboard requests use short-lived HttpOnly JWT access cookies, rotating opaque refresh cookies and CSRF/Origin protection. Resource IDs are tenant-owned; foreign IDs return404.

Agents have mutable drafts and immutable published versions. New sessions pin the published agent, knowledge snapshot and custom tool revisions. Save agent drafts with expected_revision and publish with expected_draft_revision; stale edits return409. Disabling a tool/model immediately revokes further use.

## Knowledge and sessions

The public first-minute preview uses `POST /v1/public/preview` and `POST /v1/public/preview/question`, with an owned, expiring HTTP-only preview cookie. The first response reads one page and shows a sourced overview. Follow-up questions use the configured environment model with bounded website evidence and up to eight validated user/assistant history entries. Catalog requests return real same-origin links discovered on that page without an extra model call. Replies have `text`, `mode`, `citations` and optional `links`/`notice`: `answer` is a model answer, `website-link` provides discovered navigation, and `source-excerpt` is matching source text; model unavailability is explicitly labelled. `conversation` (greetings/thanks) and `not-found` return empty citations. No model tools, additional crawl, bookings or other side effects run in this public preview. Render a source label/link only for actual evidence; do not assume `citations[0]` exists.

```sh
curl -X POST "$API/v1/workspaces/$WORKSPACE/knowledge" \
  -H "X-API-Key: $STUDIO_KEY" -H 'Content-Type: application/json' \
  -d '{"name":"Business","website_url":"https://example.com","max_pages":20}'
```

Poll `/jobs/{id}`. Inspect source coverage before attaching the ready snapshot. Static HTML, TXT/PDF/DOCX are supported; JS-only pages/image-only PDFs require further rendering/OCR. Failed indexing keeps the prior snapshot active.

```sh
curl -X POST "$API/v1/workspaces/$WORKSPACE/voice/sessions" \
  -H "X-API-Key: $STUDIO_KEY" -H 'Content-Type: application/json' \
  -d '{"agent_id":"AGENT_ID","mode":"simulation","variables":{"customer_name":"Alex"}}'
```

Return only the short-lived session capability/media_url to the frontend. Connect WS, send client.start with session_token, wait for server.ready, then send client.text in simulation or NTV1 framed PCM16 in live mode. Input16k mono/output24k mono, 32-byte header; input frames at most200ms. server.clear advances the playback epoch: stop/discard old audio. client.stop ends the session. See `media.py`, `voice-lab.tsx`, `public/pcm-capture.js` for the complete protocol.

## Custom HTTP tools

Tools → Add HTTP tool → Import cURL parses method/URL/headers/JSON only. No shell, local-file upload or command execution. Supply name, description, object JSON Schema and fixed public destination host. Whole-value placeholders preserve JSON types; URL values are percent-encoded. Argument values override custom session variables; system.call_id/caller_number/workspace_id come from runtime context.

API endpoints: POST `/tools/import-curl`, GET/POST `/tools`, PUT/DELETE `/tools/{id}`, PUT `/tools/{id}/access` with agent_ids, POST `/tools/{id}/test` with arguments/mock, GET `/tool-executions`.

Headers are encrypted/write-only; leave headers omitted to preserve them, or submit{} to clear. Put credentials in headers rather than public URL/body configuration. Edits create immutable revisions; reattach/publish agents to activate. Public DNS is validated at actual TCP connection; redirects are not followed. Response limit64KiB; known header credentials are redacted from results.

Real tests/actions require a stable Idempotency-Key. Definitions specify wait_for_result, background (recorded result on a later user turn) or fire_and_forget (audit only). Queued acceptance never confirms completion. The remote endpoint receives its stable execution identity as Idempotency-Key/X-Voice-Studio-Execution; implement remote deduplication as well. Network failure may mean unknown; reconcile before trying a new identity. Mock tests explicitly return external_request:false.

## Models and phone

See [model compatibility](MODEL_COMPATIBILITY.md) for BASE_URL, API/cap/temperature research and test requirements. Streaming + function calling support are necessary for agentic endpoints; not every service calling itself compatible supports all required behavior.

Plivo/Twilio answer/status URLs and activation steps are in [deployment](DEPLOYMENT.md). Provider signature verification and media protocol compatibility are separate requirements. Do not wire arbitrary carriers into an adapter with a different protocol.

## Event webhooks

POST `/webhooks` with url/events/enabled returns a signing_secret once. Deliveries use:

- X-Studio-Timestamp: Unix seconds.
- X-Studio-Signature: `v1=` + hex HMAC-SHA256(secret, timestamp + `.` + exact raw body).
- X-Studio-Event: stable event ID.

Constant-time compare, reject stale timestamps (recommended five-minute tolerance), deduplicate event ID, then parse JSON. Delivery records retry with exponential backoff up to six attempts; inspect/replay under Developers. These report committed events; HTTP tools execute conversational actions; carrier webhooks admit/update calls.

401/403 indicate credentials/origin/scope/signature;404 scoped unavailable resource;409 state/idempotency conflict;410 expired capability;422 invalid configuration;429 rate limit;502 provider rejection/uncertain outcome. Never replay side effects with a new identity merely because a response was lost.

## Beta identity, contacts and distribution

Production signup sends an SMTP verification link; unverified users can manage verification/account details but cannot open workspace resources. Google OIDC uses state, nonce and PKCE; password accounts link explicitly from Profile. GET `/v1/auth/providers` reports activation flags. POST `/v1/auth/verify-email` consumes a one-use token; POST `/v1/auth/verification-email` resends. PATCH `/v1/auth/profile`, GET `/v1/auth/sessions`, DELETE `/v1/auth/sessions/{id}` and POST `/v1/auth/sessions/revoke-others` manage the account. POST `/v1/auth/refresh` rotates the HttpOnly refresh cookie and readable CSRF cookie; provide the current X-CSRF-Token. Refresh replay revokes the session family. API keys remain independent workspace-scoped server credentials.

Widget configuration is GET/POST `/v1/public/installations/{public_id}` with an allowed Origin and the generated `public_key` for new widgets. POST `/v1/public/sessions` accepts installation_public_id, public_key and declared variables; its greeting is bound to defaults/context. Use the returned capability for chat and optional voice, never dashboard cookies. POST `/v1/public/voice/sessions` accepts installation_public_id plus the widget Bearer capability and returns the short-lived media capability. POST `/v1/public/voice/sessions/{call_id}/stop` uses that same widget capability. Installation edit/disable and agent archive revoke public use. Durable daily workspace allowance cannot be reset by opening another widget conversation.

Contacts: GET `/contacts` with search/offset/limit, POST `/contacts/import` with contacts/dry_run, POST `/contacts/import.csv?dry_run=true` multipart file, GET `/contacts/export.csv`, PUT/DELETE `/contacts/{id}`. Review before importing; only explicitly permitted active contacts can be added with POST `/campaigns/{id}/contacts/from-addressbook`. CSV extras become variables. Permission is checked again at dispatch.

Cal.com and Calendly support dashboard-only OAuth authorization with encrypted rotating tokens; see [operator registration, exact callbacks and scopes](SCHEDULING_OAUTH.md). POST `/connections/{provider}/oauth/start` returns the consent URL; GET `/v1/auth/scheduling/{provider}/callback` verifies the same session, browser and one-use state. A successful connection still needs event selection and agent publication.

Integrations PUT `/connections/{provider}` stores verified encrypted credentials. Providers include google_calendar, hubspot, sms, twilio, plivo, calcom and calendly. Google connection can use `/v1/auth/google/start?purpose=calendar&workspace_id=...`. Cal.com/Calendly expose `/connections/{provider}/scheduling-link`, with booking_confirmed:false for links. Direct booking is available through the call-agent scheduling flow. Agent actions include get_scheduling_link, check_calendar_availability and explicit sync_calendar_appointment. Calendar sync uses an existing local appointment and stable Google event identity. Provider credentials never appear in list responses.

Webhooks support PUT/DELETE `/webhooks/{id}` and POST `/webhooks/{id}/rotate-secret`. Rotation returns a new secret once. Disabled endpoints stop queued deliveries and cannot be replayed. GET `/notifications` and POST `/notifications/read` maintain workspace notifications with personal read state. See [activation/deployment](BETA_DEPLOYMENT.md) for required live checks.


Cal.com/Calendly call booking: list `/connections/{provider}/event-types`, PUT `/connections/{provider}/booking-settings` with an event_type_id, then enable the scheduling bundle and select the provider on the agent. The tools are check_scheduling_availability → prepare_scheduling_booking → a later confirm_scheduling_booking; get_scheduling_booking reconciles the same request. GET `/scheduling-bookings` lists requests and POST `/scheduling-bookings/{booking_id}/refresh` performs read-only provider checks. The server requires the exact non-interrupted read-back and clear caller agreement, rechecks slots and persists one-shot submission intent. No repeated POST follows an ambiguous outcome. See [provider setup, versions, scopes and limitations](AGENT_SCHEDULING.md). Current schema is64 tables (`2026-10-23-website-assistants`); contract140 paths.


Website assistants: [URL onboarding, crawl/update limits, widget actions and resume protocol](WEBSITE_ASSISTANTS.md). `POST /agents` may include website_url to prepare a bound website assistant. The Chat widget URL flow creates and connects knowledge, an agent and a publishable installation together; successful crawls update the published binding while preserving unpublished human edits and pinned conversations.

## Progressive workspace loading

The shared `/app` layout retains the authenticated Studio shell across navigation. Identity resolves before showing tenant navigation. Bootstrap accepts a closed optional `view` (`summary`, `overview`, `agents`, `knowledge`, etc.); omitted `view` retains the original full response. Page selections call the same authorized/redacted resource handlers. Summary reads aggregate call totals and14-day activity in SQL. It does not load all call entities.

The client fetches summary and current-page resources independently, uses a45-second current-workspace in-memory freshness window, and loads screen code on demand. Cached content stays visible during refresh; mutations invalidate freshness, focus/online revalidate, and hidden tabs do not poll. Workspace changes abort old requests and discard old data. Page actions mount only after their required resources are available. No provider key or workspace response is cached in localStorage/sessionStorage. Failed or15-second stalled reads show retry without removing navigation. Server/client route validation and a catch-all not-found boundary preserve real missing-page handling.

Reproduce focused ordering/cache/failure/isolation checks with `scripts/verify_loading_browser.py` through the Chromium wrapper, against the isolated development API and built frontend. Its held requests verify rendering order; recorded local timings are not production latency guarantees.


## Phirmy public contact page

`MainPage/` serves `/contact`. Its same-origin `POST /api/contact` must proxy to
`POST /v1/public/contact`. The browser supplies `Origin` and an `Idempotency-Key`
UUID v4, reusing the same key for an unchanged retry. The JSON body is `name`,
`email`, optional `company`, `interest` (`voice`, `chat`, `both`, `exploring`),
`message`, `contact_permission: true`, and optional empty `fax_number` honeypot.
Response202 is `{status:"received",reference:"<uuid>"}`: durable receipt, not
SMTP confirmation. Reusing a reference with different content returns409.

Only the fixed user-confirmed support@phirmy.com receives mail. Existing SMTP
From is preserved; visitor email becomes Reply-To. Data is stored in the encrypted
EmailOutbox; normal workers handle retries. Quotas are5/IP/hour,3/email/day,100
new enquiries/hour, with20 endpoint attempts/IP/hour. Origin defaults to HTTPS
phirmy.com/www.phirmy.com; CONTACT_SITE_ORIGIN supports an exact additional site.
No new database migration is required. See MainPage/README.md for isolated local
SMTP preview and the production nginx template; the API needs the normal worker
for asynchronous mail delivery.

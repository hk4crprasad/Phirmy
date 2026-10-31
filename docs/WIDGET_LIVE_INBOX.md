# Widget leads, voice input and live support

The public website widget now asks for an email before creating a new conversation. The email creates a lead and follows the conversation into **Inbox** and **Leads**. Returning visitors resume their existing session/history. In **Chat widget → Customize widget → Website**, clients can disable the email requirement or microphone input independently of full voice conversations.

Promotional email consent is a separate, initially unchecked box. Continuing chat does not opt the visitor into marketing. The lead records the chosen consent, exact checkbox wording, origin, installation, conversation and timestamp; email ownership remains unverified. Leads and the live inbox show the promotional-email choice. No promotion or follow-up email is sent automatically by this feature.

## Voice input

The composer microphone records up to30seconds. Click again to stop; Deepgram nova-3 transcribes it on the server and inserts editable text. Review the message, then send. This uses Deepgram independently of Fish/TTS/full voice readiness. Provider credentials never enter the embed. Closing chat or leaving the page stops the microphone. HTTPS (or loopback development), a supported MediaRecorder browser and visitor microphone permission are required. Permission errors, provider failure, silence and unsupported browsers have text-chat fallback.

The transcription endpoint requires the visitor's signed widget capability, matching origin, current installation/key/agent and an active conversation. It accepts bounded audio types, caps uploads at5MiB and rate-limits10requests/minute per conversation. Audio is forwarded for transcription and is not saved to object storage by this endpoint.

## Live inbox

**Inbox → Conversations** shows visitors and current messages, including partial AI output. Both the visitor widget and dashboard refresh conversation data every2seconds; the existing notification bell refreshes every5seconds. The conversation list batches messages and visitor context rather than querying per row. Inbox data comes from the shared database and works across API workers.

- **Take over** assigns the conversation to the signed-in operator and pauses AI. In-flight text generation is checked every250ms, canceled and marked interrupted; partial text remains visible as interrupted in the inbox. Widget voice sessions also stop when AI is paused. An already completed external tool request cannot be undone by takeover.
- **Send reply** delivers an operator message to the visitor, visibly labelled Support team. Incoming visitor messages continue to reach the inbox while AI is paused. Stable client IDs prevent duplicate operator replies on retry.
- **Return to AI** releases assignment and resumes AI for the next visitor turn, with previous operator replies included in history.
- **Resolve** closes the conversation and disables further visitor sends. Return to AI can reopen it.

Only members with `inbox:write` can take over/reply. Another operator cannot steal an assigned chat or reply on that operator's behalf. Owners/admins can release or resolve it. Read operations require `inbox:read` and workspace membership. Notifications link to the exact conversation, and links also work while Inbox is already open. Existing notification preferences/read controls remain in place. Support tickets retain their own state controls and link to the conversation.

## Navigation and meeting booking

The existing indexed-site navigation/scroll tools remain origin/corpus-bound. Booking continues through the existing availability → read-back → explicit confirmation flow, retaining provider, tenant and idempotency protections. Meeting confirmation/pending-approval and local appointment creation now produce appropriately labelled dashboard notifications. Reconciliation does not create another notification for an unchanged booking state. A local appointment is not described as a remote confirmed meeting.

The retained Aurely QA workspace has no connected booking calendar (Google Calendar is disconnected and Cal.com/Calendly are absent), so an actual remote meeting was not created. Browser acceptance exercises both scheduling providers using synthetic external services; it does not send calendar invitations. Actual Aurely product navigation verifies dispatch to the correct source URL; this environment's previously documented remote-browser certificate restriction remains in force.

## API and data

New routes:

- `GET /v1/public/conversation`: scoped history/state for the visitor.
- `POST /v1/public/voice/transcribe`: bounded microphone audio → editable transcript.
- `PATCH /v1/workspaces/{workspace_id}/conversations/{conversation_id}/mode`: human/open/resolved.
- `POST /v1/workspaces/{workspace_id}/conversations/{conversation_id}/messages`: assigned operator reply.

Public session creation accepts `visitor_email` and `marketing_opt_in`; missing email is rejected unless `theme.collect_email` is explicitly false. Session responses report state, captured-lead status and voice-input readiness. Theme validation accepts boolean `collect_email` and `voice_input_enabled`. `Conversation.state`, `assigned_user_id`, existing Message metadata, Lead evidence and reserved `ConversationContext.variables._widget_lead` store the feature without a migration. Runtime variable binding filters declared variables; visitors cannot inject the reserved lead context. OpenAPI export:145paths;64tables/schema revision unchanged. Private.env and browser trust unchanged.

## Verification — 24 October 2026

Full isolated backend suite:361passed,2intentional skips. After the final assignment/notification/stream-retry refinements,109focused live-widget/branding/platform/scheduling tests passed with2intentional skips. Tests cover email validation/gate, separate consent/evidence, resume without another lead, scoped visitor reads, in-flight interruption, human-mode AI suppression, reply idempotency, ownership/role/workspace guards, resolved state and transcription auth/type/size/provider handling. Production build/typecheck passes.

The actual production-dashboard/independent-Aurely-HTML browser run passed real Deepgram transcription of synthetic microphone audio through Chromium MediaRecorder, actual configured Qdrant/LLM₹699answer, email-first capture with unchecked marketing box, operator takeover/direct reply, incoming human-mode visitor messages, live updates, mobile, reload resume, return to AI, resolve, notifications and zero page errors. No browser API mocks or generated screenshots were used. Reproduce with the explicit local QA helper (refuses non-SQLite):

```sh
/workspace/.cloud-setup/nutaan-Rea/provider-dev.sh .venv/bin/python scripts/verify_widget_live_browser.py
```

It uses the retained QA workspace, adds a synthetic local editor and makes real provider requests. Requires the running API/web/demo and synthetic `artifacts/provider-smoke.wav` from prior provider acceptance. Evidence: ignored `artifacts/widget-live/results.json` and actual screenshots `01-email-welcome.png`, `02-voice-input.png`, `03-live-inbox-takeover.png`, `04-visitor-human-reply.png`, `05-mobile-human-reply.png`, `06-notifications.png`, `07-lead-consent.png`. No customer email, real meeting, phone call or marketing send is performed.

Existing `verify_website_browser.py` passed onboarding, appearance, actual same-origin navigation/history/current-page evidence, mobile/dark and crawl Stop with zero page errors. `QA_SCHEDULING_OAUTH=1 verify_scheduling_browser.py` passed both provider adapters/confirmation/history/OAuth UI with synthetic provider boundaries, zero page errors and no real meeting. Final `verify_aurely_widget_demo.py` passed actual configured chat, six citations, source-URL dispatch, resume, mobile/dark and key/origin rejection; remote destination loading remains limited by browser certificate trust.


## Portable embeds and polling — 24 October 2026

Widgets with a publishable key now accept that valid widget ID/key from any HTTP/HTTPS origin and from a local HTML file (`Origin: null`). Copy the dashboard snippet into the page; there is no need to list every preview/test host. `Customize widget → Website → Restrict this widget to the origins listed below` optionally restores an explicit embed allowlist. The default is unrestricted placement for keyed widgets; legacy widgets without a key still require their original allowed origin. Invalid/missing keys, disabled installations and rotated keys remain rejected. Sessions/resume tokens remain bound to the origin on which each session started; a token from one origin cannot be replayed on another. Navigation targets remain limited to indexed pages on the configured website origins. Public requests never use dashboard cookies.

Both embedded widget and React chat tester poll with `POST /v1/public/conversation`. Same-origin browser GET normally omits Origin, which previously caused the strict session-origin check to return403 every2seconds. POST supplies the browser Origin naturally; the API retains its origin checks. GET remains available for existing clients that supply the proper origin. On401/403/404, clients stop polling the rejected session and show a reconnect action; transient failures still retry.

The production browser regression `scripts/verify_widget_polling_browser.py` reproduces the old same-origin GET403, checks successful same-origin POST polling, operator reply delivery and no repeat polling after disabling the installation. It also uses the actual script snippet on an independent local HTTP server. The managed browser blocks file:// navigation with ERR_BLOCKED_BY_ADMINISTRATOR, so the test uses a real sandboxed srcdoc HTML preview to verify the same opaque Origin:null; direct disk-file navigation is recorded as blocked, not claimed passed. No dashboard credentials, provider calls, calendar bookings or secret keys are exposed by these tests. Browser results/screenshots: `artifacts/widget-polling/`. Refresh/rebuild both API and web when adopting the change, then reload the page so it fetches the updated installer.

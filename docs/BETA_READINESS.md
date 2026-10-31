# Phirmy beta configuration review — 29 October 2026

Production update: core application is now live at https://app.phirmy.com with
API and voice WebSocket ingress at https://api.phirmy.com. GitHub deployment
40829506872 passed focused beta checks and live HTTPS/readiness acceptance;
desktop/mobile Chromium and WSS upgrade/origin checks passed. Restricted runtime
DB role, additive migration, verified backup/isolated restore, private Azure upload
and daily backup timer are configured. The previous mail MX issue is resolved in
DNS, though inbox delivery remains unverified. See PRODUCTION_DEPLOYMENT.md.
The historical audit below is retained for context; its hosting/configuration/
database-role blockers are resolved. Product legal/business review, real OAuth/
inbox/physical-mic acceptance and optional phone/payment setup remain outstanding.

Update: production environment preparation is complete. The private environment now
uses production mode and HTTPS origins at app.phirmy.com, secure cookies, disabled
development seeds and required email verification. The existing stable application
secret was preserved and configured explicitly. Local settings validation passed;
no deployment, service restart or external credential verification was performed.
The configuration gaps described below reflect the earlier audit; deployment,
database-role, email, policy and optional phone/payment work remains outstanding.

Static local configuration/source review only, at user request. No provider, OAuth,
SMTP, database or DNS requests; no tests, deployment or private.env edits. User
explicitly requested no OAuth credential tests. User chose app.phirmy.com for the
application and exact callback URLs; phirmy.com remains MainPage/contact only.

Present in private.env: GPT endpoint/model/key, Sarvam key, embeddings, Azure Blob
connection string/container, Qdrant endpoint/key, Redis URL/password, PostgreSQL
runtime/migration URLs, SMTP host/user/password/from SSL465, Google client pair,
Cal.com confidential client pair, Calendly client pair. Presence does not validate
credentials, approvals, entitlement, networking, balances or deployed services.
CALENDLY_WEBHOOK_SIGN is stored but unused by the current connector.

Blocking deployment settings: APP_ENV development, APP_ORIGIN localhost3100,
PUBLIC_API_ORIGIN localhost8100, PUBLIC_HOST docs.cynerza.in, SESSION_SECURE false,
DEV_SEED_ENABLED true. Beta overlay overrides modes/origins, but PUBLIC_HOST must
be app.phirmy.com. APP_SECRET is blank; data/.session-secret exists. Securely carry
forward that SAME stable encryption/signing secret into deployment; don't generate
a replacement. Runtime/migration URL hosts and paths match, both TLS require, both
owner-style logins. Use a restricted runtime role, additive reviewed migrations,
backups/restore and preserved object/vector data before deployment. No DB connected.

Deploy Next/API/worker/content-sandbox/Redis/Qdrant with persistent volumes, Azure
access, trusted proxy config and public HTTPS/WSS. Existing Nginx already serves
MainPage on80/443: adapt ingress for app subdomain or use a separate host; do not
blindly start the example Caddy on occupied ports. Old beta docs mention obsolete
brand/domain/provider info; current runtime/compose/SARVAM_VOICE take precedence.
After app deployment set MainPage VITE_APP_URL to https://app.phirmy.com and rebuild.

Readiness still needs live acceptance of auth/email/widget/voice/retrieval/worker
and backups/monitoring. Previous SMTP acceptance succeeded but MX/inbox issue was
not resolved at last checkpoint; current credentials alone don't prove delivery.
Google sign-in and Calendar currently share a client; isolate agent Calendar OAuth
before enabling both (Google's agent-client guidance checked earlier in thread).
App config/legal.json remains DRAFT placeholders/Voice Studio identity, separate
from implemented marketing-site policy pages. Resolve application terms/privacy/
retention/business identity before customer beta, not merely flip APPROVED.

Phone: Plivo ID/token present, global caller ID absent; Twilio pair/caller ID absent.
MEDIA_PUBLIC_ORIGIN unset, live calls/trials/purchases off, beta operator and trial
pool unset. Workspace-stored credentials/numbers weren't queried. Need chosen
carrier verified owned number, routing/callbacks, budgets/consent and real acceptance
for phone beta. Browser voice does not depend on these phone settings.
Paid: Razorpay test/live pairs present, webhook secret absent, mode test, payments
and paid activation disabled. Catalog/business config DRAFT. Leave paid collection
off for free beta; paid launch needs reviewed pricing/entity/invoices and webhook.
Turnstile keys absent, widget challenge off: optional hardening for broad public
widget access. REQUIRE_EMAIL_VERIFICATION=true, daily100/concurrency2 already set.
Existing voice provider defaults to Sarvam even without explicit VOICE_PROVIDER.

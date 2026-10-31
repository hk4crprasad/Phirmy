# Voice Studio

A business agent platform with an immediate website preview, knowledge ingestion, chat/voice sessions, custom HTTP tools and phone-provider adapters. The implementation is independent; the earlier Nutaan investigation is reference evidence.

**Try a website before signup.** The one-promise/one-button home produced Palsona's first cited answer in 6.91 seconds. Save the same knowledge into a published agent afterwards.

## Beta update

Google sign-in, verified SMTP signup/reset, JWT refresh/device sessions, profiles/notifications, structured agent variables, public voice widgets, tenant carrier connections, contacts CSV import/export, Calendar OAuth and Cal.com/Calendly scheduling links are implemented. The responsive workspace supports warm neutral light and charcoal dark themes, with Lucide icons and bundled local fonts. A lazy Remotion walkthrough, custom loading states and a custom 404 share the same palette. [Deployment and activation at docs.cynerza.in](docs/BETA_DEPLOYMENT.md) lists exact settings and remaining live checks. Google/SMTP access is pending; no public deployment has occurred.

## Run

The first phone beta has operator-assigned owned Twilio numbers, a maximum 20-day window, bounded calls, balance/expiry pauses and email alerts. It is disabled until credentials and live acceptance are complete. See [setup, limits and remaining launch needs](docs/PHONE_TRIALS.md).

Node24/Python3.12+/npm/uv required. The user keeps `.env` tracked in this private repository. The existing local `.env` contains the supplied Supabase credential; preserve it. Fresh machines use `.env.example` with credentials entered privately.

```sh
uv sync --frozen
npm ci
uv run uvicorn studio.main:app --app-dir services/control --host 127.0.0.1 --port 8100 --no-proxy-headers
```

Second terminal: `npm run dev`.

Docker Compose now runs background jobs in a separate `worker` service with four
concurrent job slots and bounded page/render/index pipelines. Apply the worker
schema migration before upgrading production. See [worker setup, tuning and
verification](docs/WORKERS.md).

Optional authenticated Redis caches derived embedding vectors for seven days;
unchanged crawl content reuses existing sources and knowledge revisions. Prepare
private local settings with `uv run python scripts/setup_redis.py`, then run
`docker compose up -d redis qdrant`. Cache failures fall back to the embedding
provider. See [crawl speed, Stop, storage and cache behavior](docs/CRAWLING_PERFORMANCE.md).

Self-hosted Qdrant is configured locally with rootless Podman. It starts through `voice-studio-qdrant.service`; new machines can run `uv run python scripts/setup_qdrant.py`. See [Qdrant setup, indexing and verification](docs/QDRANT.md). Docker Compose also includes the pinned Qdrant service.

[Home](http://127.0.0.1:3100) · [Workspace](http://127.0.0.1:3100/app) · [Developer guide](http://127.0.0.1:3100/docs) · [API reference](http://127.0.0.1:8100/docs)

Current local activation: Azure private container and embeddings, Fish drama-3 and Deepgram have passed live checks, including the app audio/ticket/recording path and a grounded LLM-generated spoken reply using synthetic input. Azure gpt-6-luna passes live Responses streaming and function-call round-trip checks. Self-hosted Qdrant authentication, indexing, semantic retrieval, isolation and restart persistence also pass; existing published knowledge was backfilled. See [provider acceptance](docs/PROVIDER_ACCEPTANCE.md).

## Stack and configuration

Next16/React19; FastAPI/WebSocket/durable jobs; Supabase PostgreSQL; Azure private blobs; Qdrant + text-embedding-3-small; configurable OpenAI-compatible LLM (default gpt-5.6-luna); Fish s2.1-pro; Deepgram nova-3; Plivo/Twilio. Local objects/lexical retrieval and synthetic fixtures are explicit development modes.

```dotenv
OPENAI_API_KEY=
OPENAI_MODEL=gpt-5.6-luna
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_API_STYLE=auto
OPENAI_TOKEN_PARAMETER=auto
OPENAI_REASONING_EFFORT=auto
```

Restart the API after env changes. Workspace Models supports encrypted write-only keys and documented streaming-tested profiles. See [model research](docs/MODEL_COMPATIBILITY.md). Never place secrets in browser code or NEXT_PUBLIC settings. Keep APP_SECRET stable. `DATABASE_URL` is the main app connection; the beta maintenance service uses `MIGRATION_DATABASE_URL` for that same database. Supabase's IPv4 transaction pooler is supported with automatic prepared statements disabled. The old split `SUPABASE_DB_*` settings are no longer needed in `.env`; clear any inherited legacy password override when deliberately selecting another URL or SQLite.

## Use

- Home → your website → real source-backed preview → Keep my assistant.
- Workspace → Knowledge → public website crawl or TXT/PDF/DOCX upload → ready snapshot → publish agent.
- Tools → import cURL → review schema/templates → save → agent access → mock or real request → publish updated agent.
- Models → documented endpoint/profile → streaming check → agent Voice & behavior → publish.
- Voice lab → text simulation now; live voice after providers are configured. Product widget, tickets, leads, local bookings and exports persist actual state.
- Campaigns support scheduling, concurrency up to8, busy/no-answer retries, calling windows and aggregate budget caps. Phone numbers support owned Plivo/Twilio registration and signed callback URL setup.
- Team/invitations/recovery, recording retention, HubSpot/Google Calendar/Plivo SMS connectors and Razorpay capture adapters are implemented. Provider-dependent actions require real configuration and acceptance.

## Verify and continue

```sh
uv run pytest -q
npm run build
uv run python scripts/check_database.py
uv run python scripts/verify_postgres.py
uv run python scripts/verify_first_minute.py
uv run python scripts/verify_agent_platform.py
uv run python scripts/verify_browser.py
uv run python scripts/verify_theme_browser.py
uv run python scripts/verify_embed.py
uv run python scripts/verify_qdrant.py
```

Pytest isolates temporary SQLite and clears provider credentials. Never point destructive fixtures at Supabase. Integration/browser scripts use configured services and retain clearly named QA rows. Provider/indexing checks may consume provider credits; they never place phone calls. Screenshots/results are ignored in artifacts/.

[AGENT.md](AGENT.md) is the continuation handoff. [Implementation status](docs/IMPLEMENTATION_STATUS.md), [verification](docs/VERIFICATION.md), [developer documentation](docs/DEVELOPER.md) and [deployment](docs/DEPLOYMENT.md) describe actual behavior and limits. Physical microphone, carrier, payment/connector acceptance and public deployment remain pending. Qdrant local integration is accepted; production backup/restore and capacity checks remain. Human transfer, WhatsApp/MCP, refunds, advanced model-graded evaluations and JS-rendered crawling remain future work.

Managed cloud crawling supports explicit `PUBLIC_NETWORK_MODE=proxy` while preserving verified public-IP pinning and TLS. [Actual Aurely crawl acceptance](docs/AURELY_CRAWL_TEST.md) records48pages,83passages and18products indexed through the app.

[Complete dashboard widget controls](docs/WIDGET_CUSTOMIZATION.md) provide a live branding preview, colours, logo uploads, button/style/layout settings and per-widget response tone without replacing the embed.

Owners/admins can [delete an agent and its owned data](docs/AGENT_DELETION.md), with impact preview, confirmation and retryable storage cleanup. This update requires schema migration before production startup.

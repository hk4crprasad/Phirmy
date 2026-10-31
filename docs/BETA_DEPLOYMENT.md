# Cynerza private beta at docs.cynerza.in

The complete app and documentation share one HTTPS host: `/` preview, `/app` workspace, `/docs` guide, `/backend/docs` API reference. This release is implemented locally and **has not been publicly deployed**.

## Configuration

Preserve the private `.env` and existing provider values. Add missing values privately or through the hosting secret manager. Keep the original stable `APP_SECRET`, which also decrypts stored credentials. If the old host generated `data/.session-secret`, recover that exact value securely; replacing it cannot decrypt the existing database's secrets.

| Setting                                                             | Purpose                                                                                     |
| ------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| `PUBLIC_HOST`                                                       | `docs.cynerza.in`                                                                           |
| `APP_SECRET`                                                        | Existing stable secret, at least 32 characters                                              |
| `DATABASE_URL`                                                      | Main application PostgreSQL TLS connection                                                  |
| `MIGRATION_DATABASE_URL`                                            | Schema maintenance connection to the same database; may use a separate owner role            |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`                          | Google web OAuth client                                                                     |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | Verified mail sender and authenticated SMTP settings                                        |
| `SMTP_SECURITY`                                                     | `starttls` for provider port 587 or `ssl` for port 465                                      |
| Existing Azure, LLM, Fish, Deepgram, Qdrant values                  | Preserve supplied settings and verify network access                                        |
| `WORKSPACE_DAILY_TURN_LIMIT`, `WORKSPACE_VOICE_CONCURRENCY`         | Production defaults: 100 admitted turns per UTC day and 2 browser voice calls per workspace |
| `PHONE_TRIALS_ENABLED`, `BETA_OPERATOR_EMAIL`                     | Disabled-by-default operator-funded phone beta and alert recipient; see [phone trials](PHONE_TRIALS.md) |

The overlay enforces production mode, secure cookies, verified email, disabled fixtures and Azure storage. It clears the legacy `SUPABASE_DB_PASSWORD` override so `DATABASE_URL` is selected. The split `SUPABASE_DB_*` fields and duplicate `RUNTIME_DATABASE_URL` are no longer needed in `.env`. Google/SMTP values are missing. Current cloud access to Supabase/Azure is blocked; isolated local QA uses separate SQLite/local objects and disabled provider keys.

Both database URLs now select the same main Supabase project, as requested. They use its IPv4 transaction pooler on port 6543 with `sslmode=require`; Psycopg automatic prepared statements are disabled for pooler compatibility. Different Supabase project references identify different databases: running schema migrations on a second project does not update or copy data into the main project. These schema migrations are separate from any future data transfer.

The supplied connection currently uses the project owner for both purposes. A restricted application login remains a production release gate; create it in the same database and update only `DATABASE_URL` after applying and checking the grants below. For DDL maintenance and external tools that require session state, use that project's session pooler (port 5432) or direct connection from Supabase Connect. Never substitute another project's URL to obtain IPv4.

For Google, create a **web application** OAuth client with origin `https://docs.cynerza.in` and exact redirect URI:

```
https://docs.cynerza.in/backend/v1/auth/google/callback
```

Configure the consent screen/test users and any Google review required for the selected audience/scopes. Sign-in requests `openid email profile`. Calendar connection adds event/read scopes and offline consent; enable Calendar API. Password users explicitly connect Google from Profile. Matching emails never silently link password accounts. A Calendar account can differ from the sign-in account.

Verify the SMTP sender domain using the provider's SPF/DKIM instructions. Test delivery/spam, resend, expiry, password reset and outage handling. Only development can use the private `DATA_DIR/mail-outbox`; production never returns tokens or falls back to that outbox.

## Hosting and migration

Use a Linux host with current Docker Compose supporting `!reset`, domain DNS pointing to the host, native PostgreSQL TLS connectivity and public TCP 80/443. Caddy obtains certificates; optional UDP 443 enables HTTP/3. Only Caddy exposes public ports. Internal API/web/Qdrant hostnames are excluded from inherited HTTP proxies so container traffic stays on the private network. Use one API/dispatcher process.

1. Back up PostgreSQL, private Azure objects, Qdrant snapshots and the stable encryption secret. Prove a restore to an isolated database. Preserve volumes.
2. Review `scripts/migrate_database.py` and `studio/main.py`. Apply additive schema changes through the migration role. Production API startup only checks the schema revision and performs no DDL.
3. Grant the runtime role schema usage and table DML; preserve append-only triggers and remove schema creation permission. Reapply reviewed grants after migrations. Tenant membership/scopes are enforced by the application; database per-tenant RLS is not implemented. Example grants for a role created by the administrator:

```sql
GRANT USAGE ON SCHEMA voice_studio TO cynerza_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA voice_studio TO cynerza_runtime;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA voice_studio TO cynerza_runtime;
REVOKE CREATE ON SCHEMA voice_studio FROM cynerza_runtime;
```

4. Supply private configuration, then run from the repository root:

```sh
docker compose -f compose.yaml -f deploy/compose.beta.yaml config --quiet
docker compose -f compose.yaml -f deploy/compose.beta.yaml build api web migrate
docker compose -f compose.yaml -f deploy/compose.beta.yaml --profile maintenance run --rm migrate
docker compose -f compose.yaml -f deploy/compose.beta.yaml --profile maintenance run --rm migrate python scripts/migrate_database.py --check
docker compose -f compose.yaml -f deploy/compose.beta.yaml up -d qdrant api web gateway
```

Expanded Compose output contains private values; use `config --quiet`. The migration owner's connection is cleared from API runtime environment. `--check` is read-only; application is repeatable and does not drop application tables. Roll back using a reviewed image/database restore, not by blindly deleting new tables.

On this cloud machine, `/workspace/.cloud-setup/nutaan-Rea/prepare-container-build.py` prepares the optional `compose-build-trust.json` override for the injected trusted CA. Add it when building. TLS verification remains enabled.

## Agent distribution and integrations

Publish an agent, copy its stable ID and test it in Voice lab. Variables have separate names, descriptions, defaults and required flags; widget and campaign sessions bind these values. Credentials belong in encrypted tool/connector settings, not public variables.

Chat widget → enter website URL → choose a new or existing agent → wait for knowledge indexing → Appearance to confirm exact allowed website origins → copy the generated widget ID/publishable-key script. The generated agent and knowledge binding publish automatically; existing manual installations remain accessible. `data-variables` accepts JSON such as `{"customer_name":"Alex"}`. Missing required values are collected before the conversation. Optional voice needs HTTPS, microphone permission and configured model/speech providers. Public sessions do not use dashboard cookies. Disabling an installation or archiving the agent revokes public use; active voice checks revocation too.

Google Calendar checks remote availability and syncs explicitly requested local appointments using stable remote event IDs. Cal.com/Calendly support selected-event availability and direct call-agent booking after an exact read-back and a later confirmation. Calendly needs Standard or above and the required API permissions. See [agent scheduling](AGENT_SCHEDULING.md). Custom HTTP tools connect other services with schemas, encrypted headers and idempotency keys.

Contacts supports reviewed JSON/CSV imports, export, editing and permission records. Additional CSV columns become contact variables. Only contacts with recorded permission can be selected into campaigns. Selection creates a simulation draft for review; revoked/archived address-book records are checked again before dispatch.

Connect Twilio/Plivo credentials per workspace, register an owned number, wait for verification and configure the exact signed answer/status URLs shown in Phone numbers. Event webhooks under Developers send signed committed events to an HTTPS receiver, with edit/disable/retry/secret rotation. They are separate from inbound carrier webhooks. No number purchase, KYC submission or live call occurred in this pass.

For the first invited phone users, [operator-funded phone trials](PHONE_TRIALS.md) support a maximum 20-day pool, assigned owned Twilio numbers, per-workspace call limits, provider balance/expiry pauses and operational emails. Operators configure the pool/inventory/budgets; customers can request server-selected seven-day assignments with one click. Optional carrier purchases default off and require a funded, entitled account. See [free-number research](FREE_NUMBER_RESEARCH.md). Trial numbers are outbound only; campaigns require a separate funded carrier binding. The new schema revision is `2026-10-23-website-assistants` with 64 tables; run migrations and runtime grants before updating the production API. Keep both live/trial flags off until public carrier acceptance passes.

## Public release gates

- Real Google sign-in/linking and Calendar consent on the public host, including denied/revoked access.
- Actual SMTP verification/reset delivery and unverified-account restrictions.
- Supabase migration, restricted runtime role and backup/restore drill.
- Independent HTTPS website widget and physical microphone, interruption, stop/reconnect and recording consent.
- Real Google Calendar actions and Cal.com/Calendly selected-event availability, booking, approval/cancellation status and notification checks.
- Controlled inbound/outbound acceptance for every advertised carrier, signed callbacks and once-only settlement.
- Monitoring, retention, capped load and outage/recovery checks. Daily turn/concurrency limits are not a provider-cost guarantee. Keep public paid phone usage closed until tariffs/reconciliation pass acceptance.

Local contracts do not establish these live outcomes. Full Fish/Nutaan parity, an ElevenLabs hosted-agent importer, human transfer, WhatsApp/MCP and refunds are not implemented. The app includes a lazy, illustrated Remotion walkthrough; video export is optional.

## Local verification

Run `uv sync --frozen`, `uv run pytest -q`, `npm ci` and `npm run build`. For synthetic cloud browser QA, start the local API/frontend helpers under `/workspace/.cloud-setup/nutaan-Rea`, then:

```sh
uv run python /workspace/.cloud-setup/nutaan-Rea/run-browser.py scripts/verify_beta_browser.py
uv run python /workspace/.cloud-setup/nutaan-Rea/run-browser.py scripts/verify_browser.py
uv run python /workspace/.cloud-setup/nutaan-Rea/run-browser.py scripts/verify_embed.py
```

The isolated QA API explicitly disables mail verification/providers only in its process. Production verification remains mandatory. These checks retain synthetic rows in `data/cloud-local`, never reset Supabase and never place calls. Results/screenshots are ignored under `artifacts/beta/` and `artifacts/`.

Website crawling now includes sitemap discovery and guarded JavaScript rendering. The API image installs Chromium and runs under its existing non-root user. Build the updated image before enabling rendering; retain the existing egress boundaries. See [website assistant configuration and coverage limitations](WEBSITE_ASSISTANTS.md). No new .env credentials are required for this feature.

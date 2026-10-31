# Workers and concurrent ingestion

The current release also includes API-key policy migration
`2026-10-24-key-security`; see [the security checkpoint](SECURITY_CHECKPOINT.md).
Apply that additive migration before starting the current production API and
worker. The older worker-pool revision below records the ingestion upgrade.

Compose now runs a dedicated `worker` service with four concurrent job slots.
The API accepts requests and reports progress with `WORKER_ENABLED=false`.
Webhooks and maintenance run independently of long jobs. PostgreSQL remains the
durable queue; Redis remains an optional derived-vector cache.

## Apply this release

Preserve the existing private `.env`. This release adds nullable
`jobs.lease_token` and schema revision `2026-10-24-worker-pool`; production needs
a migration-capable connection to the same database before restarting:

```sh
git pull
docker compose build api worker
docker compose stop api worker
docker compose run --rm --no-deps api python scripts/migrate_database.py
docker compose up -d api worker
docker compose ps api worker
```

For the beta overlay, use its `migrate` maintenance service and configured
migration-role connection; pass both Compose files to build/up. API and worker
must share the database, data volume, object-store settings, signing secret and
network configuration. Recreate both after env changes; restart does not reload
env files. Workers verify the schema without startup DDL.

Without Docker, initialize through the API first, then use two terminals:

```sh
WORKER_ENABLED=false uv run uvicorn studio.main:app --app-dir services/control --host 127.0.0.1 --port 8100 --no-proxy-headers
PYTHONPATH=services/control uv run python -m studio.worker_main
```

The original local API command retains its in-process dispatcher by default.
Disable it when using the separate worker.

## Concurrency controls

| Variable | Default | Meaning |
| --- | --- | --- |
| `WORKER_CONCURRENCY` | 4 | Concurrent top-level jobs, range1–16 |
| `WORKER_POLL_SECONDS` | 0.25 | Queue polling interval, range0.05–5s |
| `CRAWL_CONCURRENCY` | 4 | In-flight page pipelines per crawl, range1–8 |
| `RENDER_CONCURRENCY` | 2 | Chromium renders shared across a worker's jobs, range1–4 |
| `INDEX_CONCURRENCY` | 2 | Embedding/upsert batches shared across its jobs, range1–8 |

Defaults allow sixteen page pipelines across four crawls, with at most two using
Chromium and two indexing at once. Start with one dedicated worker; raising
limits increases memory, DB connections and provider load. SQLite serializes
writes; use PostgreSQL in production. Campaign child dispatch retains its
existing campaign-specific cap. Keep one API process for browser-call ownership;
this change does not distribute media sockets or rate limits across API replicas.

Sitemaps seed the queue before processing. Each slot fetches, optionally renders,
extracts and uploads changed evidence. Ready pages save and discover links
without waiting for an earlier slow request. HTTP uses async pooled transport;
parsing, checkpoint/source transactions and synchronous object-store SDK calls
run in threads, overlapping other pages' work. Some legacy API DB calls remain
synchronous.

Chunks embed in batches of32 with concurrent upserts and a pooled Qdrant client.
All batches must succeed before promotion; failure cancels siblings and retains
previous published knowledge. Concurrent Qdrant collection creation requires a
compatible read-back schema. Unchanged recrawls still skip uploads, indexing and
new knowledge/agent revisions.

## Recovery and Stop

PostgreSQL uses `FOR UPDATE SKIP LOCKED`, locking one claim candidate at a time.
Resource locks serialize jobs for the same KB, catalogue store or campaign. Unique lease
tokens renew every20seconds for three-minute leases. Checkpoint/publication
transactions check and lock the token; an expired owner cannot overwrite a new
owner. Expired jobs recover saved pending URLs and sources. Webhook claims also
have a three-minute retry window; event IDs and at-least-once semantics remain.

**Stop crawl** cancels pipeline/render/index tasks. An object-store SDK call
already running in a thread can finish, but cannot publish a stopped crawl.
Shutdown drains async children; unfinished work recovers after lease expiry.
Cancellation cannot undo completed external side effects.

Worker health uses a five-second event-loop heartbeat with a30second staleness
threshold. DB/provider errors remain visible in logs and jobs. Browser-session
orphan cleanup stays in the API, where live ownership is known. Begin with one
worker service: distributed maintenance and general external-side-effect
reconciliation need further replica/load acceptance before unattended scaling.

## Verification

These checks use disposable data without supplied Supabase or paid providers:

```sh
uv run pytest -q tests/test_worker_pool.py tests/test_website_assistants.py
uv run python scripts/benchmark_workers.py
uv run python scripts/verify_workers_postgres.py
# First build Dockerfile.api as studio-worker-qa:local:
uv run python scripts/verify_workers_docker.py
```

Controlled before/after comparison against commit `93ae9d4` uses the actual
crawler, dispatcher, SQLite, extraction and local objects with boundary latency:

| Workload | Before | After |
| --- | ---: | ---: |
| Five pages: fetch, render, upload, index | 5.051s | 2.978s |
| Eight queued jobs, 250ms handler each | 9.067s | 0.822s |

Both crawls produce five pages and20chunks. Peak renders/uploads rise from one
each to two each; peak top-level jobs rises from one to four. Queue improvement
includes shorter polling. An unchanged recrawl adds zero raw uploads. Public
site timing varies with network, content and robots pacing; the real250ms gate,
robots rules, SSRF/TLS checks and retry/backoff remain enabled.

Evidence: `artifacts/workers/{before,after,postgres,docker}.json`. Tests cover ready
pages progressing behind a blocked request, shared renderer/index limits, vector
alignment, failed-batch cancellation, heartbeat/Stop, webhook claims, KB/store queue
fairness and stale-owner fencing. PostgreSQL17 verifies upgrade/repeated migration,
no-CREATE runtime role, eight simultaneous distinct claims and one owner per KB.
Actual Docker acceptance verifies API dispatch disabled, queued document handled
by a separate worker, shared objects/DB, knowledge promotion, heartbeat and clean
SIGTERM. Only disposable test containers/data are removed.

# Crawling, knowledge readiness and loading

Jobs now run in a dedicated Compose worker with four concurrent slots. Fetch,
render, extraction and changed-page uploads overlap, while ready pages no longer
wait behind an earlier slow request. Indexing uses bounded parallel batches.
See [worker setup, migration and measured results](WORKERS.md).

The crawler downloads up to four pages concurrently by default (`CRAWL_CONCURRENCY`, range1–8), using one pooled DNS-pinned HTTP transport per job. A shared request-start gate preserves the minimum250ms interval and robots.txt delay/request-rate, including redirects and renderer fetches. Read-only429/503 responses use bounded backoff and Retry-After; a requested delay above60seconds is not retried early. Site permission, same-origin, response-size and private-address protections remain enabled.

Already-readable server-rendered pages do not start Chromium solely because they contain Next/React markers. Thin pages retain the guarded browser renderer. This improves permitted public sites; login walls, anti-bot challenges and third-party-dependent applications still require supported access and cannot be guaranteed to work.

Website assistant now shows **Stop crawl** while queued or running and **Stopping…** after the request. Stop is checked during downloads, rendering and embedding/indexing, and is serialized with final publication. Pending work is canceled and the previous published knowledge remains connected. A synchronous upload already accepted by Azure may finish; its result cannot publish a stopped crawl. The existing job retry resumes durable checkpoints, including in-flight URLs.

Knowledge becomes active only after extraction, chunk creation and configured Qdrant indexing succeed. Product evidence, agent binding and widget publication continue to use immutable source/snapshot revisions. Failed or canceled updates never replace the previous live knowledge.

## Why Azure has a snapshots folder

`snapshots` is the application's category for raw page evidence: generally one file per changed page. It is distinct from Azure's native blob snapshots and the database's knowledge-revision records. The prior crawler uploaded before checking whether extracted content already existed, and created another knowledge/agent revision after every successful recrawl. Daily automatic refresh could therefore create unnecessary storage writes and revision churn.

The new behavior is:

- Unchanged extracted text/facts reuse the existing source and raw object, even if irrelevant HTML nonces changed.
- An unchanged source set reuses the active knowledge snapshot and agent version; embedding/indexing are skipped.
- Content-addressed Azure objects use conditional creation, never overwriting identical blobs. This also avoids redundant versions on accounts with versioning enabled.
- Existing history remains intact. Deletion needs a reference-aware audit of published agents, pinned conversations, uploads and pending/retry jobs; arbitrary age-based deletion could break their evidence.

Read-only inspection on24 October2026 found61 raw crawl objects totaling10,723,811bytes (about10.2MiB), no native blob snapshots and no versioned entries in the listing. No old files were deleted. Account versioning enablement was not established by the returned service properties. Evidence: `artifacts/azure-storage-inventory.json`.

## Redis and database loading

Run `uv run python scripts/setup_redis.py` to prepare private settings without replacing existing values, then `docker compose up -d redis qdrant`. Both services bind to loopback and require authentication. Redis uses a pinned image digest, a256MiB cache limit, LRU eviction and no persistent cache disk. Production must keep these services private.

Redis caches only derived embedding vectors, default TTL seven days. Keys are opaque and include the embedding endpoint/model/dimensions/credential namespace. Source text is not stored in cache keys. Cache hits are shape/number-validated; bounded timeouts and a short failure circuit fall back to the configured embedding provider. Redis does not cache authorization, live job state or balances, and never replaces Qdrant.

Website listing now batches knowledge, installations, latest crawl jobs and usage. It no longer repeats those queries for each assistant or silently omits a job after200 unrelated newer jobs. PostgreSQL pool size/overflow are configurable with bounded connection/pool waits. The browser serializes its visible-tab refreshes and avoids duplicate development chat-session creation.

Both private database URLs select the latest user-supplied Supabase project with TLS. Existing credentials remain in tracked `.env`, mode0600. The cloud machine still cannot resolve the pooler, so no remote migration or data transfer occurred. The running development API explicitly uses `data/cloud-providers` SQLite while retaining real configured Azure/LLM/speech/Qdrant/Redis integrations; the separate cleared-provider `local-dev.sh` remains available for synthetic-only QA. Never confuse either local database with remote customer data.

## Managed cloud proxy mode

On hosts without external local DNS/direct routing, explicitly set `PUBLIC_NETWORK_MODE=proxy`. The tracked private `.env` stays `direct` so it works on ordinary local machines. This managed cloud explicitly overrides the mode in its launch environment (`PUBLIC_NETWORK_MODE=proxy`), using the inherited runtime proxy. Leave `PUBLIC_HTTP_PROXY` blank to use the inherited HTTPS/HTTP proxy, or configure a trusted operator proxy. Public addresses are resolved over TLS through Cloudflare DNS, cached for at most60seconds, and every returned address is validated. The backend sends CONNECT to the validated IP while httpcore retains the original hostname for HTTP Host, TLS SNI and certificate verification. Connections stay separated by origin even when addresses match. Policy denial never retries by another route. Private, metadata, loopback and multicast targets are rejected; normal hosts retain direct DNS-pinned mode by default.

This resolved the actual Aurely crawl:48pages,83passages,18products with real Azure/Qdrant/LLM services. See [the native app acceptance](AURELY_CRAWL_TEST.md). This HTTP transport does not provide PostgreSQL TCP access.

## Evidence

- Production Next.js build and TypeScript check passed.
- Full isolated backend suite:325 passed,2 intentional provider-specific skips. Three additional focused regressions cover pooled redirect pacing, readable SSR browser avoidance and bounded429 retry.
- Website browser verification passed actual URL-to-widget UI flow, product evidence, appearance, indexed pages, separate-origin widget/navigation/history, mobile/dark layouts and Stop preserving the published snapshot; zero page errors.
- PostgreSQL17 with TLS passed64-table integration, tenant isolation, concurrent settlement, append-only records and booking idempotency/conflicts. A five-assistant listing used10queries including authorization. This was an isolated QA container, not Supabase.
- Actual Redis warm reuse/TTL and Qdrant authenticated insert/search/tenant/revision isolation passed with synthetic vectors (`scripts/verify_local_index.py`).
- Live configured Azure Blob round trip, text-embedding-3-small1536 vectors, Qdrant semantic ranking/isolation/cleanup, Azure gpt-6-luna streaming/function round trip, Fish drama-3 speech and Deepgram nova-3 recognition all passed (`scripts/verify_providers.py`).
- A synthetic website passed the actual crawl→Azure blobs→embeddings→Qdrant→grounded LLM widget answer path, then reused its snapshot on recrawl (`scripts/verify_crawl_pipeline.py`). Its test blobs/points were removed.
- Actual spoken-agent flow passed synthetic PCM→Deepgram→grounded Azure LLM→Fish→stereo Azure recording/download (`scripts/verify_live_voice.py --llm`, matching the local API Origin). No physical microphone or phone call was exercised.
- Controlled benchmark: five synthetic600ms pages with the real250ms request gate took3.316s with one download and1.872s with four, a1.77× speedup. This measures this local workload, not public-site latency. Reproduce with `scripts/benchmark_crawl.py`.

User authorized all domains; `network.allowed_domains=["*"]` is saved in the environment draft. Saving alone is not evidence of publication. Later actual requests succeeded for Aurely and Firecrawl. Native public crawling now uses explicit validated-IP proxy mode and passed real-site acceptance; the earlier422/zero-page result was superseded. Supabase still needs working DNS/TCP support. No TLS/SSRF protections were disabled.

Evidence is in ignored `artifacts/`: `provider-results.json`, `qdrant-results.json`, `local-index-results.json`, `crawl-pipeline-results.json`, `crawl-benchmark.json`, `live-llm-session-results.json`, `website/browser-results.json`, `website/current-live-results.json`. They contain synthetic test data and are not source exports.

## Research and design choices

Reviewed official [Scrapy AutoThrottle](https://docs.scrapy.org/en/latest/topics/autothrottle.html) and [Crawl4AI multi-URL dispatchers](https://docs.crawl4ai.com/advanced/multi-url-crawling/): both emphasize bounded concurrency and pacing/backoff. The changes apply those principles to the existing crawler, preserving its actual tenant/revision and transport boundaries. Source copies were read from the projects' official GitHub repositories. Azure conditional-write behavior follows the [official Python Blob upload API](https://learn.microsoft.com/en-us/python/api/azure-storage-blob/azure.storage.blob.containerclient?view=azure-python#azure-storage-blob-containerclient-upload-blob).

Firecrawl search was attempted through the installed skill; proxy403 prevented obtaining results. No successful Firecrawl search or integration is claimed. A future optional managed scraping backend would need app-level credentials and a separate integration decision; the installed CLI's stored login is not copied into product configuration.


### Local error: proxy mode without a proxy

If a local crawl reports a missing HTTP/HTTPS proxy, set `PUBLIC_NETWORK_MODE=direct` in the local `.env`, restart the API and worker so they reload settings, and select **Recrawl**. The failed job retains its historical error until a fresh crawl runs. For Compose, recreate both containers (`docker compose up -d --force-recreate api worker`); restarting an existing container does not reload its `env_file` values. Plain local development can still use the in-process dispatcher.

If a proxy is intentional, configure `PUBLIC_HTTP_PROXY` or inherit a valid HTTP/HTTPS proxy instead. Explicit proxy mode now validates this before DNS/HTTP activity and gives actionable recovery text. It never silently falls back to direct routing. No credential values are included in errors.


### Renderer cleanup on success, timeout and Stop

The guarded renderer now owns its HTTP/WebSocket route callback tasks. After capturing HTML, or when rendering ends through timeout/cancellation/page close, it first marks shutdown and detaches HTTP routes with `unroute_all(behavior='ignoreErrors')`, then cancels and drains pending route work before closing the context and browser. This prevents a slow background `safe_fetch` from later calling `Route.fulfill`/`Route.abort` on a closed target and producing repeated event-listener tracebacks. Queued requests do not start more fetches during shutdown.

Expected closed-target callback errors end that callback as canceled; real snapshot errors and rendering timeouts still surface to the crawler, which retains static content under its existing fallback policy. The30-second render limit,1500ms settle period,60request budget, robots checks, same-origin GET-only interception, CSP and dead-proxy network boundary remain. No TLS/proxy safety check is disabled.

Verification:24focused renderer/website tests passed, including real Chromium with slow/queued requests, render timeout, caller cancellation, unexpected page closure, genuine snapshot failure, guarded scripts/network restrictions and existing crawl Stop behavior. Tests assert fetch cleanup/browser disconnection and no event-listener stderr/asyncio errors. The new background-fetch regression fails against the pre-fix source because a fetch is still active after return, and passes against the fix. These are controlled local browser tests with synthetic content, not a claim of recrawling the user’s Tecosys site.

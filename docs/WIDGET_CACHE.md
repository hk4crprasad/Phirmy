# Widget delivery cache

The four public assets (`widget.js`, `bot-challenge.js`, `pcm-capture.js`,
`widget-designs.css`) use `public, max-age=60, must-revalidate`. Next supplies ETag
and conditional304 responses. HTML, authenticated pages and API responses retain
no-store. Hashed Next assets retain Next's existing immutable caching.

Widget framing policy is public metadata cached for at most five seconds in
shared Redis, shortened to the earliest included ownership proof expiry. Proxy
reads it directly, so a warm page does not call the policy API. A cold page calls
the authoritative API, which claims its cache load before reading the database.
Only that still-current claim may publish. Strict nonce CSP remains per page.

Configure the same private `REDIS_URL` and `WIDGET_FRAME_CACHE_NAMESPACE` on API,
worker and web replicas; the default namespace is `studio:widget-frame:v1`.
Use different namespaces/Redis databases for different environments. This is a
standalone Redis deployment; Redis Cluster is not claimed supported. Redis must
use `maxmemory-policy noeviction`; both runtimes check it and otherwise disable
policy caching. The Compose configuration sets noeviction. Credentials/URLs stay
server-only. Its ACL needs the hash, expiry, EVAL and CONFIG GET commands used by
the adapter. Monitor Redis memory: noeviction refuses writes when full, rather
than evicting transaction guards. Existing embedding caching remains optional.

Before installation, origin-proof, agent or workspace mutations, transaction
hooks lock the workspace and replace affected entries with persistent guards.
Bulk ORM updates/deletes are covered. Guards survive nested savepoints, expire
only on the outer commit/rollback, and prevent an earlier read from restoring a
revoked policy. They also prevent loads during a long transaction. Direct SQL
changes outside the application are maintenance operations: invalidate policy
entries under the same workspace lock. Normal API edits perform this automatically.

If Redis is unavailable, reads fall back to the current database/API, without a
process-local stale cache. A configured but unavailable invalidation service
causes policy mutations to fail503 before their SQL executes. An unavailable
policy API permits self framing only. A writer crash can leave a guard and reduce
cache availability; it cannot turn that guard into a framing grant. Inspect and
recover under a database workspace lock, after the failed transaction resolves:

```sh
uv run python scripts/widget_frame_cache.py --workspace-id WORKSPACE_ID
uv run python scripts/widget_frame_cache.py --workspace-id WORKSPACE_ID --apply
```

These are CSP hints for page delivery. Every widget configuration, session,
dictation, chat, resume and voice request still checks installation enablement,
origin ownership and key/capability state against current server data. A page
already delivered, or a read racing a commit, cannot bypass those checks. A Redis
restart removes the cache; the final invalidation also clears loads that raced
recovery. Never use this cache as an authorization decision.

Reproduce native built-server checks with a disposable Redis URL and isolated
environment helper:

```sh
STUDIO_TEST_REDIS_URL=redis://127.0.0.1:6399/0 uv run python scripts/verify_widget_cache_browser.py
```

The script uses temporary SQLite/objects, synthetic ownership evidence, ephemeral
API/Next ports and real Chromium. It does not replace primary preview services.

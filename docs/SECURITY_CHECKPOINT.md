# Shared limits and API-key policy

24 October 2026, first Phase 1 checkpoint. See LAUNCH_CHECKLIST.md for the full
remaining launch scope; this is not a Phase 1 completion or public launch signoff.

## Limits

Redis uses an atomic Lua sliding window with Redis server time, unique members,
bounded expiry and HMAC-obscured identity keys. Two API processes share the same
counter when their Redis URL and stable APP_SECRET agree. Redis errors cause a
five-second reconnect delay and a bounded, locked per-process fallback; warnings
are limited to one per minute and contain no identity or connection URL.
Fallback has reduced aggregate protection during an outage and is not a global
quota or spend ledger. Redis recovery does not merge local outage counts.

Sign-in allows 30 attempts per IP per five minutes and 10 attempts per normalized
email per fifteen minutes. Email counts include all attempts regardless of
existence or password validity; Retry-After reports the remaining window. Cost
admission limits independently count IP and workspace/actor, so rotating one
identity cannot reset the other. Rejected downstream operations can consume
admission quota. Existing generation/widget/preview throttles use the same shared
backend. Installation quotas, spend caps and durable usage remain separate work.

## Forwarded addresses

Use `--no-proxy-headers` on every Uvicorn invocation: otherwise Uvicorn may rewrite
the client before application trust checks. Only explicit TRUSTED_PROXY_IPS
addresses/networks are accepted; default empty trusts none. Wildcards and /0
networks fail initialization. The beta overlay pins Caddy on an edge network to
GATEWAY_IPV4 (default 172.30.0.2) and trusts only that /32 on the API. Override
GATEWAY_SUBNET and GATEWAY_IPV4 together if the default subnet conflicts. The
gateway, API and web share edge; workers/cache remain on the default network.
Caddy's default incoming forwarded-header sanitization remains enabled. A CDN
in front of Caddy requires its own narrowly reviewed trust configuration; do not
trust arbitrary Internet forwarded headers.

## Keys and migration

All developer/team/billing mutation scopes require browser identity; even legacy
API keys stored with these scopes are denied. New keys cannot request those
mutation scopes. This deliberately also requires dashboard sessions for developer
webhook/model mutations. Read scopes still work, and allowed application scopes
retain their existing role/scope checks. Browser role checks and CSRF remain.

Each key optionally expires at a timezone-aware instant and has a 1–600 requests/
minute limit (default 60). Only successful request transactions persist last use;
expiry/revocation is checked before admission. Lists/UI expose policy and last
use but never the stored hash or secret. The creation secret is still shown once.

Revision `2026-10-24-key-security` adds nullable `expires_at`, `last_used_at` and
non-null `requests_per_minute DEFAULT 60` to api_keys. Use the repository's
existing migration maintenance command against the intended database before
starting production. Existing hashes/scopes are preserved. Runtime schema checks
reject missing policy columns or the release revision. The supplied Supabase
database was not changed. Alembic adoption/rollback belongs to Phase 5 and remains
unfinished; take the reviewed backup before any real migration.

## Reproduce

```sh
uv run pytest -q
npm run typecheck
npm run build
# For actual shared Redis coverage, use only a disposable local Redis:
STUDIO_TEST_REDIS_URL=redis://127.0.0.1:6399/0 uv run pytest -q tests/test_launch_security.py
# Creates and removes only its own isolated PostgreSQL container:
uv run python scripts/verify_workers_postgres.py
```

Tests cover concurrent Redis/fallback admission, expiry and recovery, opaque
keys/log redaction, fallback capacity, email throttling across trusted-proxy IP
rotation, spoofed forwarding, privilege escalation, API expiry/last-use/rate
limits, policy validation and preservation of existing credentials during
repeated SQLite/PostgreSQL migrations. The Redis test explicitly skips without
STUDIO_TEST_REDIS_URL; do not count that as a shared-backend acceptance.

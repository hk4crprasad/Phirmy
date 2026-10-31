# Deployment notes

For the current single-host beta, follow [docs.cynerza.in deployment and activation](BETA_DEPLOYMENT.md).

Next runs on3100 and FastAPI control/media on8100. `/backend/*` proxies HTTP/SSE. WebSocket clients use the separately configured public API/media origin.

## Configuration

Use `.env.example`/a deployment secret manager. Production validates PostgreSQL, Azure, durable APP_SECRET, secure sessions and disabled development seeding. Keep the Azure container private; provision its access externally. Qdrant is now self-hosted locally; [Qdrant deployment notes](QDRANT.md) cover the rootless service, Compose networking, persistent volumes, private key and existing-knowledge backfill. Preserve APP_SECRET across restarts for encrypted credentials.

Use one API/dispatcher process. Production startup checks the schema revision without DDL. Apply the reviewed migration command separately and provision a restricted runtime role/backups; per-tenant database RLS remains future work. Horizontal scaling needs shared rate limits, socket/job ownership, lease recovery and reconciliation. Some async control paths still use synchronous database operations. Lists need pagination/aggregation at scale.

Publish exact HTTPS APP_ORIGIN, PUBLIC_API_ORIGIN and MEDIA_PUBLIC_ORIGIN with WSS upgrades, long streaming timeouts and unbuffered SSE. Add logs/metrics with secret redaction, egress rules and restore drills. No public deployment has been performed.

## Controlled activation

1. Configure selected model (environment or documented profile), Fish key/authorized voice ID and Deepgram. Publish the agent. Test microphone STT→LLM/tools→TTS, latency, buffered interruption/clear, idle/duration, disconnect and recording/expiry first.
2. Supply the selected Plivo or Twilio credentials, an account-owned number and controlled test destination allowlist. Set LIVE_CALLS_ENABLED only in the controlled environment. Register/verify the number and attach a published agent. Registration does not buy a number or change its carrier dashboard configuration.
3. Configure provider POST URLs exactly:

| Provider | Answer                                | End/status                            |
| -------- | ------------------------------------- | ------------------------------------- |
| Plivo    | `/v1/provider-webhooks/plivo/answer`  | `/v1/provider-webhooks/plivo/hangup`  |
| Twilio   | `/v1/provider-webhooks/twilio/answer` | `/v1/provider-webhooks/twilio/status` |

Prefix with MEDIA_PUBLIC_ORIGIN. Outbound jobs append internal call_id themselves. Signatures use the exact configured public URL, query and form. Twilio uses Connect/Stream; Plivo has its own bidirectional Stream adapter. Both convert mu-law8k/stateful resampling and require provider-specific acceptance.

4. Test actual inbound/outbound, callback replay, leg binding, stop, one settlement and uncertain dispatch recovery. Live tariffs are **unpriced testing**. Implement priced admission/provider reconciliation before public paid usage.
5. Enable Razorpay only after configuring keys/webhook secret and validating order→capture→once-only credit in staging. Refunds are absent. Verify external connector scopes and actual actions; Google appointments remain local until sync succeeds, and SMS acceptance is not confirmed delivery.

## Containers

`docker compose config --quiet` validates without printing expanded secrets. Stop host listeners and any Podman Qdrant instance before `docker compose up --build -d`. Images exclude env/data/artifacts; API uid10001 uses its data volume; web bakes API_ORIGIN into rewrites and needs rebuild for changes. Compose includes authenticated Qdrant with readiness gating and persistent volumes; API uses its internal service hostname. Cloud Docker builds and isolated local runtime checks are recorded in VERIFICATION.md; public staging remains pending. Sites Worker hosting cannot run this Python media backend.

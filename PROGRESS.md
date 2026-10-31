# Current checkpoint

22 October 2026. Working source: `/home/hara/nutaan-platform`.

- Public one-promise/one-button website preview: real Palsona cited answer in 6.91s before signup. Save flow retains its sources as a published agent.
- Compatible model BASE_URL/profiles, API-specific caps, omitted default temperature, documentation/probe gate, tool-calling runtime.
- Custom cURL HTTP tools with content/access/test, immutable revisions, encrypted headers, three execution modes and durable results.
- Team/recovery, campaigns, recordings/exports, business connectors/payments adapters, Twilio + Plivo callbacks/media and developer guide implemented.
- 74 offline tests passed; production build, real Supabase (45 tables), first-minute/platform/dashboard/widget browser checks passed with zero page errors. See `docs/VERIFICATION.md`.
- Live Azure/Qdrant/embedding/LLM/Fish/Deepgram/carrier/connector/payment acceptance awaits keys. The user explicitly said to continue with keys later.

Read `AGENT.md` before continuing. Never print the private env or signing secret. Do not run destructive fixtures against Supabase. Production status and missing features are explicit in `docs/IMPLEMENTATION_STATUS.md`.

Latest provider activation: private Azure voice-agent container created, 3 local objects migrated/verified, Azure embeddings1536 and Fish drama-3→Deepgram real streaming passed. Azure gpt-6-luna deployment is now available; Responses streaming/function-call round trip passed. Qdrant remains unconfigured. See docs/PROVIDER_ACCEPTANCE.md.

Razorpay: both key pairs are saved privately; test mode routes provider requests/checkout verification through test credentials. Payments remain disabled pending explicit activation and webhook secret. No payment calls made.

Azure deployment resolution: actual gpt-6-luna streaming + tool round trip passed, then full synthetic speech→Deepgram→lexical knowledge→gpt-6-luna→Fish spoken answer→stereo Azure recording passed with zero media errors. Final-transcript-to-reply-audio7015ms in this run; latency tuning and physical microphone/PSTN/Qdrant acceptance remain.

User voice preview delivered: artifacts/voice-demo/voice-demo-drama-3.mp3, duration312.79s, approximately7.51MB,10 sections. Configured Fish voice, English/Hindi/Hinglish; full decode passed and Azure copies verified.

Visual follow-up: login/signup now has an animated organic green particle cloud on an off-white panel matching the site. Public hero artwork has moving orbit dots, signal ripples, a breathing center, voice bars and drifting notes. Reduced motion, offscreen suspension, mobile layout, form interactions and zero browser errors verified; production build passed. Evidence: artifacts/brand-motion/. AGENT.md records the user's palette correction.

Preview conversation fix: bare greetings/thanks no longer trigger missing-evidence refusals. Conversation and not-found replies have no fabricated source citations; labels match response modes and the latest reply scrolls into view. This public flow remains an extractive one-page preview without LLM generation. Full isolated suite85 passed in25.74s, production build passed, real Palsona first-minute browser check passed in2.94s with greeting/thanks/unknown evidence, mobile and keep handoff; zero page errors. Local API refreshed.

Self-hosted Qdrant: v1.19.2 runs under rootless Podman/systemd on loopback6333, with API-key auth, persistent named volumes, readiness health check, resource limits and startup after reboot/logout. Private vector settings are saved in .env; Compose now includes Qdrant and its internal API hostname. Backfilled all14 published snapshots/29 points. Actual Azure embedding semantic search, tenant/revision isolation, duplicate-free retry, service outage reporting, restart persistence and application qdrant-hybrid retrieval passed. Full isolated suite85 passed in24.07s; Compose validation passed. See docs/QDRANT.md and ignored artifacts/qdrant-*-results.json.

# Live provider acceptance — 22 October 2026

The user supplied Azure Blob, Azure OpenAI/embeddings, Fish and Deepgram credentials. Values are stored only in the local `.env` (tracked in the user's private repository by explicit choice), mode0600. They are never reproduced here or included in the shareable source archive.

| Service          | Executed result                                                                                                                                                                                                                                                                                                                            |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Azure Blob       | Created `voice-agent` in the supplied account, private access. Actual upload/read/delete and tenant-key guard passed. Blank AZURE_STORAGE_PREFIX is supported.                                                                                                                                                                             |
| Existing objects | Copied all3 existing local objects (31,248 bytes) into Azure with the same logical content-addressed keys; downloaded and compared each; local backups preserved.                                                                                                                                                                          |
| Azure embeddings | text-embedding-3-small returned2 valid finite vectors at1536 dimensions.                                                                                                                                                                                                                                                                   |
| Azure LLM        | After the user deployed gpt-6-luna, actual Responses streaming and function-call/result round trip passed with max_output_tokens, reasoning none and no temperature. Follow-up first token1847ms in this smoke run. Initial DeploymentNotFound is resolved; no alternate model was substituted.                                            |
| Fish             | Supplied voice is accessible. Actual drama-3 WebSocket synthesis returned3.90s of usable mono PCM16/24k audio; first audio2639ms in this smoke test.                                                                                                                                                                                       |
| Deepgram         | Actual nova-3 WebSocket transcribed Fish test audio as “hello your business voice assistant is ready to help”. Synthetic input; no physical microphone test.                                                                                                                                                                               |
| App live media   | Real greeting→synthetic PCM→Deepgram→persisted ticket confirmation→announced two-channel Azure recording/download passed, zero media errors. First server audio3034ms. This local ticket action bypasses LLM reasoning, so no LLM-turn success is claimed.                                                                                 |
| App LLM voice    | Actual synthetic question “What is the engraving character limit?” → Deepgram → lexical synthetic fixture → gpt-6-luna → spoken “The engraving limit is 20 characters.” → stereo Azure recording/download passed. Zero media errors. Greeting first audio3837ms; reply audio7015ms after final transcript. Physical microphone not tested. |
| Qdrant           | Self-hosted v1.19.2 runs in rootless Podman on loopback with API-key auth and durable volumes. Real Azure embeddings1536 → indexing/query, tenant/revision isolation, outage reporting and restart persistence passed. All14 published snapshots backfilled,29 points; application returns qdrant-hybrid. See QDRANT.md.                   |
| Razorpay         | Test/live key pairs saved; test mode selected and application credential routing verified locally. No payment/order request made. Existing activation flag remains false and webhook signing secret is not supplied.                                                                                                                       |
| Phone            | Plivo/Twilio credentials and public call routing remain pending; no telephone call was placed.                                                                                                                                                                                                                                             |

## Configuration details

OPENAI_MODEL is the canonical setting; OPENAI_CHAT_MODEL is now accepted as an alias when canonical is absent. Both are set consistently in the current env. Azure v1 uses the ordinary OpenAI client with the supplied base URL; explicit Responses/max_output_tokens/reasoning none is selected and temperature omitted. The requested target is preserved and its earlier deployment404 is resolved.

New agents take FISH_TTS_MODEL from configuration. Published agent configurations pin a supported Fish model and the runtime now sends that selected model rather than ignoring it. The editor includes drama-3 alongside existing supported models. Existing published agents remain immutable: select the current model/voice in a draft and republish intentionally.

## Reproduce

```sh
uv run python scripts/verify_providers.py
uv run python scripts/verify_live_voice.py
uv run python scripts/verify_live_voice.py --llm
uv run python scripts/verify_qdrant.py
```

These scripts make small **real provider requests**, may consume provider credit, and never place PSTN calls. They redact error output and write synthetic audio/results to ignored artifacts/. The live-session check exercises real WebSocket PCM, recognition, persisted support-ticket action and Azure recording; its explicit local ticket path does not by itself prove an LLM-generated reply; the separate model probe verifies streaming/tool round trips. The --llm variant verifies a real grounded model answer using synthetic fixture knowledge and lexical retrieval. Evidence: artifacts/live-session-results.json, artifacts/live-llm-session-results.json and matching recordings.

Unit tests continue to use temporary SQLite/local objects and clear all real provider keys. Never execute destructive fixtures against Supabase. Reloading the API is required after env changes. Configured capability flags indicate supplied settings, not successful deployment health.

## Primary references

- [Microsoft Azure OpenAI v1 API](https://learn.microsoft.com/en-us/azure/foundry/openai/api-version-lifecycle): ordinary OpenAI client, deployment model identity and v1 base URL.
- [Microsoft reasoning models](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/reasoning): Responses/Chat caps and model-specific support.
- [Fish TTS API](https://docs.fish.audio/api-reference/endpoint/openapi-v1/text-to-speech): drama-3 is a documented model header; unknown names can fall back, so the exact supported header matters.
- [Fish WebSocket TTS](https://docs.fish.audio/api-reference/endpoint/websocket/tts-live): MessagePack start/text/stop/audio/finish.
- [Deepgram streaming](https://developers.deepgram.com/reference/speech-to-text/listen-streaming): authenticated nova-3 streaming audio contract.

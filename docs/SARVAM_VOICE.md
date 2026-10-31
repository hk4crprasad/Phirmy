# Sarvam browser and telephone voice

Updated 30 October 2026. Browser voice, public-widget voice, Plivo and Twilio use
the same voice engine. Text chat retains its configured GPT/OpenAI-compatible
profile. No customer data migration or carrier deployment is included.

| Stage | Selected model | API |
| --- | --- | --- |
| Recognition | `saaras:v4` | `wss://api.sarvam.ai/speech-to-text-realtime/ws` |
| Voice replies and tools | `sarvam-105b-conversations` | `https://api.sarvam.ai/v1/chat/completions` (SSE) |
| Speech generation | `bulbul:v4-flash` | `wss://api.sarvam.ai/text-to-speech/ws` |

These are the current documented Sarvam models for this pipeline. The newer V2
chat endpoint does **not** list the conversations model; use V1 for that model.
There is no invented combined speech/tool WebSocket. Speech uses the documented
WebSockets; model text and tool arguments stream over SSE.

## Configuration and compatibility

The existing server `.env` supplies `SARVAM_API_KEY`. Keep it server-side; never
put it in a browser variable, URL, log or screenshot. `VOICE_PROVIDER=sarvam` is
the default. The existing text-chat `OPENAI_*` configuration is unchanged.

Defaults and supported settings are in `.env.example`: Saaras v4, Bulbul v4
Flash, Sarvam-105B Conversations, `simran_enhi_customer`, automatic input-language
detection, and 250 ms VAD endpointing. The agent editor offers recognition and
synthesis language controls and a Bulbul persona ID. Use a documented v4 persona,
not an old v3 short name or a Fish reference ID. Automatic recognition and the
configured synthesis language are independent controls. **Auto · follow the
speaker** selects a supported synthesis language from the recognition result,
with native-script detection for typed voice turns and English as the fallback.
The selected concrete language also guides the voice reply model; the literal
`auto` is never sent to TTS. A change of language reconnects synthesis, while
unchanged languages reuse the socket. Greetings use their configured text's
script. Romanised text without an ASR language falls back to English; the selected
persona must support the chosen language. Existing explicitly selected languages
are preserved: choose Auto, save and publish to change an existing agent.

Voice replies request concise, natural plain sentences. Before synthesis, a
bounded streaming buffer removes presentation Markdown, links and HTML markup,
retaining product names, numbers, currency and native scripts. Markup-only chunks
are skipped; sentence boundaries and bounded text chunks preserve streaming.
The original transcript remains available, and speech accounting uses the text
actually submitted to synthesis. Text-chat formatting is unchanged.

Existing agent speech configurations are normalized in memory to Sarvam at call
startup; immutable published versions and GPT text settings are not rewritten.
New drafts use Sarvam defaults. Saving an old draft in the editor adopts the new
speech configuration. Historical tariff records remain immutable; an admitted
call whose tariff predates Sarvam must be restarted rather than silently repriced.
`VOICE_PROVIDER=legacy` is an explicit operator rollback for older Fish/Deepgram
configurations and the older regression fixtures, not an automatic fallback.

Restart the API/worker after updating dependencies or environment. Do not run
pytest or destructive fixtures against the supplied Supabase database. No new
DB tables or schema migration are required for this change.

## Streaming and lifecycle

- Output pacing is anchored to actual audio availability. First-byte latency,
  pauses between synthesis chunks and late event-loop wake-ups do not accumulate
  a catch-up debt. A 160 ms send-ahead window bounds normal queued audio; complete
  20 ms frames and the final partial frame are paced before transmission. Browser
  playout overflow guards remain active. This prevents a delayed synthesis reply
  from arriving as a burst large enough to terminate Voice Lab/widget playback.
- Saaras uses `stream_type=fast`, linear16 mono 16 kHz, partial transcripts and
  VAD events. The application deduplicates utterance finals and retains its
  incremental transcript, interim-retrieval and interruption handling.
- Bulbul receives model deltas immediately and flushes at sentence/tool/turn
  boundaries. Empty duplicate flushes are suppressed. A completed socket is
  reused within the call. An interruption clears client playback, cancels the
  producer, closes the old synthesis socket, and opens a fresh one for the next
  reply. All pending tasks belong to the call and are closed on disconnect.
- Speech completion requires `send_completion_event=true` and the matching
  `event_type=final` events. Silence timeouts are failures, never proof that a
  spoken confirmation finished. Audio uses verified raw PCM16 at 24 kHz; WAV
  headers are not sent into the playback protocol. Live v4 Flash verification
  confirmed `linear16`, despite the model guide's narrower codec table.
- Browser NTV1 framing remains 16 kHz input / 24 kHz output. Existing carrier
  adapters retain their signed leg checks and stateful 8 kHz mu-law conversion.
- Sarvam model calls use `reasoning_effort=null`, bounded output, terminal usage,
  call-scoped HTTP keepalive and no transport retries. Streamed tool arguments
  are bounded; incomplete streams cannot authorize tools. Existing allowlists,
  tenant scope, later-turn confirmations, budgets and idempotency remain active.
- Widget microphone dictation uses the same latest recognition endpoint with
  manual turn boundaries after the existing isolated audio-normalization step.

## Usage and pricing

New immutable provider snapshots record separate `sarvam-stt`, `sarvam-tts` and
`sarvam-llm` costs. Speech input is billed in seconds at the documented pay-as-you-go
49 paise/minute, synthesis in Unicode characters at 100 paise/1,000 characters,
and model tokens at 1,500/500/6,000 paise per million input/cached/output tokens.
Provider prices exclude GST. The retail plan catalog remains **DRAFT**; paid
activation is unchanged. Legacy tariffs are retained.

Streaming synthesis reserves character credit before forwarding text and settles
actual submitted characters. Fish's UTF-8 byte tariff is not reused. STT cleanup
collects the server session-end duration; sent PCM provides a conservative fallback.
The economics report uses the Sarvam voice model independently of the selected
text model and treats its existing UTF-8 workload assumption as a conservative
upper bound on spoken characters.

## Verification

- Live end-to-end check: synthesized “Please check my booking status.” → nine
  partials and the matching final transcript → real streamed model call → one
  local read-only `lookup_demo_booking` fixture → real model continuation →
  “Your booking status is confirmed.” spoken by Bulbul v4 Flash.
- First reply audio arrived **1,385.7 ms after the final transcript**, including
  the tool round trip. This is one synthetic-input provider measurement, not a
  percentile, physical microphone result, or carrier round-trip guarantee.
- Live longer incremental synthesis passed with two explicit flush completions;
  manual-mode dictation of the generated reply also passed.
- Offline actual application WebSockets cover browser, Plivo and Twilio with
  synthetic provider boundaries, PCM/mu-law audio, cleanup and Sarvam cost lines.
  Tests also cover socket reuse, interruption, duplicate finals, malformed PCM,
  streamed tool arguments, incomplete tools and later-turn write confirmation.
- Actual Chromium verified desktop/mobile voice controls, saved speech settings,
  unchanged GPT configuration, voice-lab labeling and zero page errors. Evidence:
  `artifacts/sarvam/voice-editor-{desktop,mobile}.png` and `browser.json`.
- Live artifacts: `artifacts/sarvam/result.json` and `reply.wav`. These contain only
  synthetic fixture content. No real booking, phone call or customer action occurred.

Reproduce the bounded, billed provider check only when needed:

```sh
.venv/bin/python scripts/verify_sarvam_voice.py --live
.venv/bin/pytest -q tests/test_sarvam_voice.py
```

Physical microphone/echo/barge-in acceptance and real owned-number inbound/outbound
calls remain deployment acceptance work. Carrier credentials, owned numbers and
public TLS/WSS callbacks are required; no phone provider was called by these tests.

The credential-free `scripts/verify_voice_playout.py` regression uses disposable
SQLite, the production-built Voice Lab, real Chromium Web Audio, synthetic PCM and
the application's actual `AudioPacer`. Its legacy timing scenario reproduces the
old overflow; corrected desktop/mobile viewport scenarios exercise initial and
mid-response synthesis pauses without dropping audio. It does not establish
physical-device microphone/echo acceptance. Start its isolated `--serve` API and
loopback web server as described in the script; never aim it at production.
Voice Lab creates/resumes its audio context from the Start click before waiting
for microphone permission, following [Web Audio autoplay guidance](https://developer.mozilla.org/en-US/docs/Web/API/Web_Audio_API/Best_practices#autoplay_policy).

## Official sources read

- [Welcome](https://docs.sarvam.ai/api/getting-started/welcome)
- [Realtime recognition guide](https://docs.sarvam.ai/api/api-guides-tutorials/speech-to-text/realtime-streaming)
- [Realtime recognition protocol](https://docs.sarvam.ai/api-reference/speech-to-text/transcribe/realtime/ws)
- [Bulbul v4 Flash guide](https://docs.sarvam.ai/api/api-guides-tutorials/text-to-speech/best-practices)
- [Speech WebSocket lifecycle and interruption](https://docs.sarvam.ai/api/api-guides-tutorials/text-to-speech/streaming-api/web-socket)
- [Chat models, streaming and tools](https://docs.sarvam.ai/api/api-guides-tutorials/chat-completion/overview)
- [Provider pricing](https://docs.sarvam.ai/api/getting-started/pricing)

## Website microphone access

The embed script installs the voice iframe with `allow="microphone"`. Opening a
widget or switching to its voice panel does not capture audio. The visitor must
click **Start voice conversation** (or the dictation microphone) to call
`getUserMedia`. The browser displays its own permission prompt when permission
has not already been decided. An existing browser grant can start immediately;
a previous denial requires changing the browser's site settings.

Use HTTPS (loopback is allowed for local testing), add and verify the website's
origin in the installation, and install the generated script. Keep domain
verification enabled. A website's `Permissions-Policy: microphone=()` blocks
capture; the widget cannot override it. If the host sends a restrictive policy,
its owner must permit the widget origin, for example:

```http
Permissions-Policy: microphone=(self "https://YOUR_WIDGET_HOST")
```

Nested host iframes must delegate microphone access too. Browser/OS device
permissions still apply. No provider key belongs in this header or the embed.

Permission requests are guarded against repeated clicks. Closing while a prompt
is pending stops a subsequently granted stream without creating a voice session.
Denial, missing devices, device contention and blocked host policy have actionable
messages. Closing, ending or navigating away releases microphone tracks. Dictation
results arriving after cancellation cannot overwrite a new conversation. The
voice transcript scrolls within its own panel; compact iframe controls stay visible.

`node scripts/verify_voice_connection.mjs` covers permission/lifecycle races.
`scripts/verify_widget_microphone.py` exercises the actual widget on a different
origin with Chromium's synthetic microphone, real MediaRecorder/AudioWorklet PCM,
and explicitly synthetic backend media/transcription boundaries. It checks no
capture on load, denied permission/retry, missing device, late grant cleanup,
dictation, iframe delegation, ended tracks and a blocking host policy. Use
`scripts/run_sarvam_browser_qa.py` for its disposable SQLite API with a loopback-only
ownership proof stub; it clears all real provider keys and disables the worker.
This is browser integration evidence, not physical-device or real-phone acceptance.

Browser requirements: [getUserMedia](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia)
and [microphone Permissions Policy](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Permissions-Policy/microphone).

# Voice latency work

Phase6 runs before the remaining compliance, product and reliability phases under
the revised user order. Paid phone activation remains closed until workspace
approval, compliance and final commercial gates are complete.

The target is1.5s p50/2.5s p95 from the server receiving a final transcript to
writing its first audio frame. This excludes upstream speech endpoint detection
and physical speaker playback. Call detail shows the latest50per-turn records,
separating live, synthetic and development sources. Missing audio stays null;
greetings and failed/interrupted turns do not become successful latency samples.
Failure/interruption counts remain visible beside completed-turn percentiles.

## Measured synthetic results

| Implementation | Samples | p50 | p95 | Target |
| --- | ---: | ---: | ---: | --- |
| Instrumented original text batching | 12 | 2331.229ms | 2391.771ms | p50 missed |
| Immediate deltas and bounded speech credit | 12 | 423.657ms | 468.694ms | Passed in this fixture |
| Explicit voice/cache/completion contract | 12 | 426.834ms | 693.015ms | Passed in this fixture |
| Call-scoped model clients and bounded terminal drain | 12 | 430.061ms | 480.276ms | Passed in this fixture |
| Negotiated transcript patches | 12 | 444.298ms | 502.299ms | Passed in this fixture |
| Prefetch code, ordinary final-only path | 12 | 425.384ms | 454.522ms | Passed in this fixture |
| Fish setup overlapping retrieval | 12 | 368.356ms | 429.452ms | Passed in this fixture |
| Core media lifecycle offload | 12 | 371.302ms | 418.463ms | Passed in this fixture |
| Transfer feature present, activation off | 12 | 373.147ms | 409.488ms | Passed in this fixture |

These runs used the same configured fake delays:40ms retrieval,180ms first model
token,50ms subsequent tokens,40ms Fish connection and120ms first audio, with
38word chunks and a final sentence ending. Actual admission, SQL, prompt credential
filtering, metering, MessagePack event processing and audio framing ran locally.
These are measured synthetic results, **not measured Fish/OpenAI performance**.
Artifacts are under artifacts/voice-latency. Reproduce the current target check:

```sh
uv run python scripts/benchmark_voice_latency.py --iterations 12 --assert-target
```

The script owns temporary SQLite/objects and fake provider boundaries. It neither
needs Docker nor uses customer/provider credentials. The backend CI workflow runs
this assertion after its mandatory real sandbox suite. Hosted execution is not
claimed merely because the workflow was updated.

## Implemented streaming behavior

Each safe model text delta is forwarded immediately, preserving the credential
filter. The old80-character/punctuation batching rule is removed. Documented
FlushEvent control messages force generation at sentence/turn boundaries and
before tool work; they never enter transcripts or character/UTF-8 billing totals.
Live output stays balanced-mode PCM24kHz. Fish handles its own text context buffer.

Speech budget is acquired in configurable512-byte windows before text leaves the
server. Small deltas consume local credit instead of making a SQL transaction
each time. The whole window is reserved against existing workspace, shared Free
and installation caps; unused credit is released at settlement of submitted text.
Reservation bounds can reject work that a shorter eventual answer might have fit.
Unknown provider-usage holds remain protected by the existing accounting rules.
A canceled budget task observes its in-flight transaction before settlement;
playback is cleared before waiting for this cleanup.

The media consumer explicitly closes its audio generator on playback failure or
interruption. Fish sender failure is observed while receive is waiting, and all
owned sender/receiver tasks are drained. Premature finish is an error. Retrieval
SQL/ranking, model-profile reads and confirmation settlement now run off the
audio loop. Broader HTTP/socket setup DB offload remains part of reliability work.

Official gpt-5.6 voice uses Responses with explicit none/low effort. Stable trusted
policy and eligible static user guidance use explicit30-minute cache breakpoints;
visitor data and the dynamic date follow them. User guidance keeps user priority.
Personalized guidance is not cached. Tenant keys are keyed hashes, `store=false`,
and `VOICE_PROMPT_CACHE_ENABLED=false` removes breakpoints. Cache writes have
separate DRAFT rates and conservative admission; legacy snapshots disable writes.
No cache hits or live quality comparison were measured. Tool deltas are bounded
progress only; completed output authorizes tools. Incomplete output retains usage,
marks history interrupted, records a failed sample and never automatically replays.

LLM clients now persist for each call, bounded to two profiles and fenced to its
workspace. Profile authorization is still resolved for each turn. A bounded
terminal SSE drain preserves actual HTTP keepalive; a local real-SDK TCP test
proved two requests use one connection, while a stalled tail closes/reopens it
without replay. Final synthetic fixture used one model client for12requests and
12Fish sockets. All clients/streams closed. This does not measure internet
connection setup or attribute a latency improvement to pooling.

Dashboard/public voice now negotiate delta-v1. Stable turn IDs, Unicode prefix
patches and bounded client reconstruction handle assistant text and revised STT
hypotheses; one full final transcript remains authoritative. Old browser clients
continue receiving full partial frames. Sequence/epoch fences prevent stale or
duplicate text. A100-fragment wire-size test uses less than one-third of legacy
serialized transcript bytes. This is a bandwidth check, not a live latency claim.

Stable interim retrieval now debounces250ms and starts at most two read-only
queries per utterance, with at most two active across utterances. Exact final
query/snapshot matching, five-second lifetime and a current knowledge-access/
content recheck govern reuse. Flags and limits are configurable DRAFT tuning.
Canceled embedding requests retain or settle their actual financial obligations.
The final-only benchmark above does not measure prefetch savings.

Fish setup now overlaps SpeechStarted or safety/retrieval. One call-owned adapter
leases its empty-started socket to the response; all model/tool rounds share it.
Stop/finish remains the authoritative completion signal and closes that socket.
The next turn opens early again. This follows the explicit protocol; it does not
claim one physical socket across separately completed user turns. No quiet-time
completion inference. See DECISIONS for the documented contract discrepancy.
Completed static greetings now cache per workspace/version/exact text and speech
configuration. Dynamic variables and non-greeting utterances bypass it. DRAFT
bounds64clips/4MB/512KB each/one-hour TTL limit transient memory. Cache hits replay
normal transcript/audio/recording without new Fish synthesis or TTS cost. Exact
recording/AI announcement text is part of the key. No cache-hit latency measured.
Unexpected recognition termination now wakes all browser/carrier receives and
   fails the call through owned cleanup. Twilio shares the PCM admission/metering
   path. Core socket admission/context/settlement is offloaded with durable cleanup,
   verified by SQL execution hooks and canceled-initialization tests. Tool-specific
   async SQL and live acceptance remain active. Live transfer now has confirmed
   approved destinations, signed one-shot adapters and separate bounded parent/
   staff accounting behind a disabled activation flag; see HUMAN_TRANSFER.
   Full Docker suite788passed2skipped, PostgreSQL concurrency and browser checks pass. Confirmed manual
   callback requests now create an inbox record and owner outbox email after a
   later readback confirmation; they never automatically dial or promise a time.

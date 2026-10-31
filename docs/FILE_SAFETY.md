# Content isolation

Widget dictation also uses this boundary. FFmpeg runs with pipe-only input,
one decoder thread and a10s timeout. Only canonical mono16kHz WAV of at most30s
is forwarded to transcription; compressed upload size alone never establishes
duration. Malformed/long input is rejected before provider work. Original media
and its metadata/embedded references are never sent to the speech provider.

PDF, DOCX and TXT parsing and JavaScript rendering require the separate
`content-sandbox` service. Failure to connect rejects the job; there is no
in-process fallback. The API/worker never mounts Docker's socket. The service
has no application files, object/database volumes, provider credentials, ports
or network interface. Its only mount is a Unix socket directory. Compose mounts
that directory read-only into the API and worker. The image uses the frozen
Python lockfile and contains only dependencies and the two sandbox runtime files.

The small broker has only SETUID, SETGID, CHOWN and KILL capabilities. Each job runs
under a distinct nonzero UID/GID with no capabilities or supplementary groups,
no-new-privileges, a sanitized environment and a private temporary directory.
Children cannot traverse the broker socket directory. UIDs are not reused during
the broker's lifetime; recycle before 40,000 jobs. Only one job executes at once;
scale with additional isolated service instances. Completed/canceled jobs have
their process group and any remaining processes under their unique UID killed,
then temporary files removed. The root filesystem is
read-only; temporary storage is a 256 MB noexec/nosuid/nodev tmpfs. Container
cgroups cap total memory/swap at1GB, CPU at1.5 and processes at192. Parsing also
has a512MB address-space cap; jobs have20 CPU seconds,64MB file and256 descriptor
limits. Browser render time is30s; broker work is40s with a60s total queue budget.
The application has a bounded45s protocol deadline. Tune limits through reviewed
deployment changes rather than bypassing isolation.

Uploads and sandbox inputs are capped at20MB. Extracted text is capped at1M
characters. PDFs reject encryption and more than200 pages. Pypdf's decoding,
operator, object graph and expansion limits apply before extraction; decoded
streams are additionally counted against a40MB total and5MB per-page budget.
DOCX rejects more than1,000 ZIP members, duplicate/absolute/traversal/symlink or
encrypted entries, members above8MB, total expansion above40MB and excessive
compression ratios. Every member is read through a bounded stream with CRC
validation, including entries not used as text. XML DTDs/entities are prohibited,
external resolution is disabled, and XML node count is bounded. OOXML has no
authoritative pagination: the200-page budget covers reported pages, explicit
page breaks and an independent conservative400-word/page content estimate. It
does not claim to reproduce Word's physical layout. Scanned PDFs without text
are rejected with an OCR message.

The browser has no direct network. Each intercepted request is sent through the
Unix protocol; the parent accepts only GETs to the original origin allowed by
robots, and performs existing public-IP-pinned/TLS-verified `safe_fetch` with
redirect checks. Requests have a60-resource/40MB aggregate budget,5MB per
resource/output, crawl delays and no third-party image/media/font downloads.
WebSockets, service workers, workers, WebRTC, downloads and form actions are
disabled. A dead proxy is defense in depth. Pending parent fetches are canceled
and awaited when rendering completes, times out or is interrupted.

Local development:

```sh
python scripts/content_sandbox.py start
export CONTENT_SANDBOX_SOCKET=/tmp/studio-content-local/content.sock
uv run pytest -q
# Full integration acceptance (required in CI):
uv run pytest -q --run-sandbox --strict-markers
```

The default local run skips tests marked `sandbox` and never starts Docker. It
does not verify the isolation boundary. With `--run-sandbox`, pytest starts and
removes its own isolated container, using the runtime/Dockerfile/lockfile
fingerprint to rebuild stale images. Missing Docker then fails the run. CI rejects
omitting the flag and the backend workflow runs all real sandbox integrations.
This test selection never enables an in-process production fallback. Header and
dependency aggregation unit tests explicitly fake only the health response;
readiness against the real broker remains in the full integration run.
`STUDIO_TEST_SANDBOX_SOCKET` can select an already-running isolated test service.
`DOCKER_CONFIG` can select a writable cloud build cache and
`STUDIO_SANDBOX_BUILD_NETWORK=host` can repair a build-only bridge DNS limitation.
Build proxy names are resolved/pinned only for the build; destination TLS and
lockfile hashes remain checked. Optional `cloud_ca` build secrets provide the
configured trust bundle. No runtime network access is granted by these options.

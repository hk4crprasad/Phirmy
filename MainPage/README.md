# Phirmy MainPage

A standalone React homepage for **Phirmy — Build. Scale. Together.** It lives separately from the existing Next.js dashboard and the paused launch audit.

## Run

Use Node 22.12+ (verified with Node 24).

```sh
cd MainPage
npm ci
npm run dev
```

Open **http://localhost:3200**. Development links to the existing app on the same hostname, port 3100. No backend credentials are read, and the walkthrough never creates a lead, makes a call, or books an appointment.

```sh
npm run build       # TypeScript check and production bundle → dist/
npm run preview     # Serve the production bundle on port 3200
npm run studio      # Edit the four Remotion compositions on port 3201
npm test            # Build and run browser/accessibility checks against port 3202
```

Tests use an installed Chromium at `/usr/bin/chromium`. Set `CHROMIUM_PATH` if it lives elsewhere. They verify desktop and mobile navigation, all four walkthroughs, seeking/play/pause/restart, keyboard tabs, reduced motion, responsive overflow, and axe WCAG checks. They do not need Docker or backend/provider access.

## Connecting the homepage

Set `VITE_APP_URL` to your dashboard origin **at build time** when hosting this page separately. For example:

```sh
VITE_APP_URL=https://app.example.com npm run build
```

Without this variable, production buttons use the homepage's origin, suitable for hosting alongside the existing app routes. `VITE_` values are public; never put credentials in them. Use `.env.local` for local overrides. The current app's real routes are `/signin`, `/docs`, and `/legal/{privacy,terms,acceptable-use}`.

`dist/` is a static deployment artifact. Publish its contents at the domain root. HTTP hosting is configured as described in the deployment section below. Before publishing, set the real app origin and connect the contact API as described below. The Open Graph image uses the requested `https://phirmy.com` domain. Pricing is intentionally explained in the FAQ without invented plan numbers; paid activation remains governed by the existing product.

## What is included

- Warm-white, charcoal, and silver theme using the three user-supplied brand images.
- React Bits **BlurText** hero reveal and **SpotlightCard** pointer effects.
- A layered brand illustration with floating conversation cards, waveform, and orbit graphics.
- Product capabilities, knowledge-to-publication setup, a workspace illustration, integrations, FAQs, and app links.
- Four **18-second, 30fps Remotion** walkthroughs: website support, voice conversations, lead qualification, and appointment booking. Each has distinct content and an outcome. The voice scenario has its own animated voice interface.
- A lazy-loaded Player with scenario tabs, keyboard navigation, timeline scrubbing, restart, playback state, and a readable transcript. Playback pauses offscreen and when the document is hidden. Playback includes prerecorded Fish narration after a deliberate user action. There is no autoplay on page load or live customer call.
- Ambient motion pause, OS reduced-motion support (including changes while the page is open), skip link, visible focus, mobile navigation with Escape dismissal, and native FAQ disclosures.
- Local fonts and brand assets, metadata, favicon, and no tracking scripts.

Illustrated examples use the fictional business **Form & Field**. Provider setup, booking confirmation, staff handoff, and paid availability are described with their real prerequisites. No fabricated testimonials, customer logos, latency numbers, or business outcomes are used.

## Files

- `src/App.tsx` — page content and layout.
- `src/styles.css` — responsive theme and ambient animation.
- `src/components/react-bits/` — upstream React Bits components; BlurText's root is adapted to a span for valid heading markup.
- `src/components/ProductDemo.tsx` — accessible Player controls and lifecycle.
- `src/motion/ConversationFilm.tsx` — deterministic frame-driven motion graphics.
- `src/motion/scenarios.ts` — walkthrough copy and text alternatives.
- `src/motion/Root.tsx` — four individually registered Studio compositions.
- `public/brand/` — supplied original brand images, unchanged.
- `tests/homepage.spec.ts` — browser verification.

## Sources and licenses

The official [Remotion skill](https://github.com/remotion-dev/skills/blob/main/skills/remotion-best-practices/SKILL.md) was read and applied on 27 October 2026, including its Player, markup, creation, composition, and timeline references. Remotion is pinned to **4.0.538** across the Player, runtime, and CLI. The composition uses frame-based interpolation and sequences; CSS ambient animations are confined to the webpage. The walkthrough runs as a Remotion Player composition; no standalone video export is included.

React Bits sources were retrieved on 27 October 2026 from [DavidHDev/react-bits](https://github.com/DavidHDev/react-bits):

- `src/ts-default/TextAnimations/BlurText/BlurText.tsx`
- `src/ts-default/Components/SpotlightCard/SpotlightCard.tsx`
- `src/ts-default/Components/SpotlightCard/SpotlightCard.css`

Their **MIT + Commons Clause** license is preserved in `licenses/REACT-BITS.md`. These components are used within this website. Font licenses are preserved in `licenses/`. Brand images were supplied by the user. Remotion's applicable license remains available in its installed packages.

## Verification — 27 October 2026

Production build and strict TypeScript compilation passed. **11 Chromium browser tests passed in 24.1 seconds**, including axe WCAG 2 A/AA and 2.1 AA checks on desktop and mobile. The four scenarios were exercised through playback, pause, seek, restart, and their final outcomes. Widths of 360, 390, 768, 1024, and 1440 pixels passed overflow checks. Remotion Studio was opened in Chromium with no page errors.

Screenshots are kept in the repository's ignored `artifacts/mainpage/` directory. These checks concern the standalone homepage; they do not re-verify the paused backend audit or claim live provider performance.

## Contact page and SMTP forwarding

“Build your agent,” “Get started,” and the closing build CTA now open **`/contact`**. The page includes name, email, optional company, an interest selector, message, permission to reply, an email alternative, useful error states, and a personalized receipt screen. The explicitly confirmed destination is **support@phirmy.com**.

The browser sends `POST /api/contact`. Vite's development and preview proxies forward it to `/v1/public/contact` at `CONTACT_API_ORIGIN` (default `http://127.0.0.1:8102`). No SMTP secret is bundled into the frontend. The control API validates the origin and fields, applies per-IP/email/global quotas and a honeypot, and stores an encrypted email in the existing durable outbox. A UUID v4 idempotency key prevents a repeated browser submission from queueing a second enquiry; changed content with the same key is rejected. SMTP itself retains the outbox's at-least-once retry semantics.

The worker uses the existing root `.env` values `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, and `SMTP_SECURITY`, with certificate verification and STARTTLS or SSL. The authenticated sender stays in From; the visitor goes in Reply-To. Support receives a branded, escaped HTML email and a plain-text alternative. No automatic email is sent to the unverified visitor, and submitting the form does not subscribe them to marketing.

For the isolated local preview, run this from the repository root in another terminal:

```sh
uv run python scripts/run_mainpage_contact.py
```

This serves port 8102 and runs only its contact email outbox. It creates `data/mainpage-contact/enquiries.db` and a private encryption key in the same directory. It uses the real SMTP settings, but does not connect to Supabase or start the other product workers. Preserve the directory/key to retain queued enquiries. The existing production control API also registers this route; use its normal worker for production delivery.

For `phirmy.com`, configure the reverse proxy using `MainPage/nginx.conf` as a template: serve `dist/`, route `/contact` to the SPA, and proxy `/api/contact` to the private control API. Enable TLS at the edge. Set `VITE_APP_URL` to the actual dashboard origin so the existing documentation and legal pages remain reachable. The allowlist defaults to `https://phirmy.com` and `https://www.phirmy.com`; `CONTACT_SITE_ORIGIN` can add an exact preview origin. Configure Uvicorn to trust only the reverse proxy's address for forwarded client IPs. Keep the normal outbox worker running and monitor failed mail rows.

### Contact verification — 27 October 2026

- Production build and **18 browser tests passed in 35.4s**, covering the contact and success pages on desktop/mobile, accessibility, required consent, retry keys, errors, all homepage controls, and four walkthroughs. A visibility race in the Watch CTA was fixed during regression checks.
- **72 backend tests passed in 49.85s with the real sandbox enabled**, including the new contact route, concurrent idempotency, SSL/STARTTLS fake SMTP delivery, failure/retry, account mail, identity, key rotation, callbacks, invoices, and widget protection.
- One clearly labeled verification enquiry traversed the real browser → Vite proxy → contact API → encrypted local outbox path (HTTP 202, zero page errors). **Live SMTP delivery is not verified**: DNS resolution failed with `EAI_AGAIN` for both the configured SMTP host and a general public hostname, including an approved probe outside the sandbox. The single verification message remains queued for bounded retry; no inbox receipt is claimed.

## HTTPS deployment — 28 October 2026

`MainPage/deploy/nginx.conf` is the active HTTPS host template for
`phirmy.com` and `www.phirmy.com` on `20.40.52.17`. It is installed as
`/etc/nginx/sites-available/phirmy`. Certbot now manages TLS for both names, with HTTP redirects and automatic renewal.

`.github/workflows/mainpage-deploy.yml` builds only this frontend on main
pushes changing MainPage or its workflow, or manual dispatch. The self-hosted
runner labels are `self-hosted, Linux, X64, cynerza`; systemd service
`phirmy-actions-runner` runs `/home/cynerza/github/1/actions-runner/run.sh`.
`deploy/publish.sh` atomically switches `/var/www/phirmy/current` to a new
release and checks homepage/contact HTTPS responses with certificate verification. Previous releases and
assets are retained. Roll back by atomically repointing current to a retained
release. Deployment does not overwrite Nginx, allowing later Certbot changes.

Only the static frontend is hosted. The contact API returns explicit JSON503
until the separate backend is deployed; email support@phirmy.com directly.
Sign-in, legal and documentation app routes also need the separate app. Set
repository variable `PHIRMY_APP_URL` to its actual origin and redeploy when ready.
No root .env or backend is copied by this workflow.

## Builder visual refresh and directed narration — 28 October 2026

Stronger headline weights, darker body copy, larger navigation and section text,
mint/forest accents, and responsive conversation scenes replace the miniature
silent demo. Mobile uses a 600×680 composition; desktop uses 1000×520.
Four tours contain three narrated beats each, with readable synchronized captions,
play/pause/restart/seek, mute, and a complete transcript. Playback is user initiated;
leaving the viewport or hiding the tab pauses it.

`src/motion/narration-directed.json` contains Drama 3 performance directions,
`[pause]`, and scoped `<emphasis>` tags. `narration.json` is the clean caption text.
The generator checks they match and reads Fish key/model/voice privately from the
root .env. The selected configured model is drama-3. No credentials enter the
browser bundle or CI. Only the finished audio and timing manifest are deployed.
Official direction syntax verified at https://fish.audio/drama-3/ on28October2026.

Regeneration is a paid, explicit local operation:
`../.venv/bin/python scripts/generate_narration.py` from MainPage.
Completed takes are cached under ignored artifacts; audio is normalized to -16LUFS
with a -1.5dB true-peak target and fully decoded for validation. Each scene lasts
at least6seconds and extends automatically if speech needs more room. Hashed
filenames and retained deployed audio protect sessions open during new releases.

## Remotion scene rebuild — 28 October 2026

Applied the installed Remotion create, markup, captions, rendering and Studio
guides. Each tour has three named Sequence groups, with audio and captions inside
the same scene boundary. Separate question/answer/outcome components use frame
interpolation, spring entrances and staggered titles. Voice visualization reads
actual audio samples via media-utils. Audio uses @remotion/media; local font loads
are gated by @remotion/fonts. All Remotion dependencies remain pinned4.0.538.

Locally transcribed all12 source clips with Remotion Whisper WebGPU small.en.
`captions.json` retains source-relative word timings; `SceneCaptions.tsx` contains
inline editable Caption arrays. The official BasicCaptions element is copied
unchanged from https://www.remotion.dev/elements/captions/basic-captions.md.
Regenerate via `node scripts/transcribe_narration.mjs` then
`python scripts/build_caption_scenes.py` in MainPage; requires local WebGPU.
Captions are inside the composition; the outside transcript remains accessible.
Desktop is1000×640, mobile600×900. Existing Drama3 directed recordings retained.

Studio was opened at localhost3201/VoiceConversations with zero page errors;
CLI frame renders and desktop/mobile screenshots inspected. Browser suite19pass
including real Web Audio decode/start evidence. No standalone MP4 export requested;
the live interactive Player is the deliverable. The lazy demo bundle is about266KB
gzip after adding media decoding/caption editing support.

## React Bits motion pass — 28 October 2026

Used the explicitly requested React Bits skill and fetched live TS-CSS source
with its rb-add.mjs script from https://reactbits.dev/r/ (parsed JSON, not SPA HTML).
New registry components in src/components/react-bits/new: Threads, ShinyText,
RotatingText, Magnet. Existing motion dependency satisfies the fetched requirement;
no additional runtime dependency was required. License retained in licenses/REACT-BITS.md.

Threads adds an airy green line field behind hero artwork, lazy loaded only on
visible desktop fine-pointer surfaces. It unmounts offscreen, hidden, paused or
under reduced motion; mobile has a static fallback. ShinyText performs a single
view-triggered sweep with readable dark greens. RotatingText cycles three
conversation phrases with a fixed, complete screen-reader description. Magnet
adds bounded7–8px attraction to primary CTAs. Existing BlurText/SpotlightCard remain.
The pause control and live reduced-motion preference disable new effects.

Screenshots: artifacts/mainpage/reactbits-{desktop,mobile}.png. Build/typecheck
passed; existing19browser tests passed19.7s. Added focused tests for phrase cycling,
pause/resume, dynamic reduced motion, mobile WebGL exclusion and CTA navigation.

## Live Hostinger contact delivery — 28 October 2026

Contact delivery is now hosted. POST /api/contact proxies to the isolated service
on127.0.0.1:8102, running as phirmy-contact.service. It reuses the validated public
contact route and encrypted EmailOutbox, with its own persistent SQLite database
and key in /var/lib/phirmy-contact. Only that table is created; no platform worker,
Supabase connection, agent, payment or call service runs. APP_ENV=contact selects
this isolated mode; an additional hosted-origin guard accepts only the two HTTPS
Phirmy origins. Nginx replaces forwarded IP headers; Uvicorn trusts loopback only.
Single-process rate limits apply and reset on service restart.

Hostinger smtp.hostinger.com:465 uses certificate-verified implicit TLS, with
support@phirmy.com as authenticated sender and destination, visitor as Reply-To.
Secrets live in /etc/phirmy/smtp.json (root:phirmy-contact0640), outside web roots
and deployment artifacts. Local private tracked.env is updated per repo policy.
No automatic visitor response is sent. Never print either configuration file.

CI checks out only MainPage, the contact runner and eight shared Python modules;
MainPage/deploy/contact.sh installs the pinned mail-only requirements and restarts
only phirmy-contact.service. Initial provisioning needs the phirmy-contact system
user and private config/data directories; the unit uses read-only system paths,
private tmp, a0077umask and a writable private data directory. Back up both the
SQLite database and its .encryption-secret together; preserve them on deployments.

Checks: Hostinger TLS/authentication passed;18isolated API tests passed; live
browser form received202 and the encrypted outbox reached sent on its first attempt.
A verification enquiry was explicitly requested by the owner. An invalid origin
received403. No customer data was used for verification.

## Editorial homepage and privacy (29 October 2026)

Phirmy uses a warm editorial hero, native smooth scrolling, accessible product
navigation, light product walkthroughs, and a responsive footer. Existing React
Bits motion, reduced-motion/ambient pause, Remotion scenarios, narration and the
contact flow remain. Only implemented voice/chat/knowledge/tool features appear;
public rollout and paid activation are described separately. Unconfigured
workspace links go to contact rather than an unavailable dashboard.

`/legal/cookies`, `/legal/privacy`, and `/legal/terms` are actual local routes.
The public site installs no analytics/ad trackers. The notice therefore provides
Manage/Got it, not fictional analytics consent toggles. The native dialog lists
actual use and can save/reset the local-only `phirmy:privacy-choice:v1` record
(180-day validity). No future tracking permission is inferred. Storage failures
leave the site usable. Review these notices if the deployment's data practices
change. Cookie wording was checked against the ICO's guidance on
[managing storage consent](https://ico.org.uk/for-organisations/direct-marketing-and-privacy-and-electronic-communications/guidance-on-the-use-of-storage-and-access-technologies/how-do-we-manage-consent-in-practice/).

Run `npm run build`, then `CHROMIUM_PATH=/path/to/chrome npm exec playwright test`.
The existing default `/usr/bin/chromium` may need an override on another machine.
Privacy/menu regressions include keyboard/focus, direct policy URLs, expiry,
blocked storage, no cookies before choice, saved choice and reset, plus axe.

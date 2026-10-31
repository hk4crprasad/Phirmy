# Interface themes, fonts and motion

The 23 October 2026 Fish Audio/ElevenLabs references define the current direction: warm neutral light surfaces, charcoal dark surfaces, understated borders and small teal status accents. This supersedes the earlier green sidebar/panel direction. Keep Lucide as the icon pack.

## Theme ownership

`apps/web/src/app/theme.css` owns semantic colors, shared component treatments, custom loading/404 styles and motion accessibility. Existing layout geometry lives in the `base` CSS layer. Use tokens such as `--paper`, `--white`, `--ink`, `--muted`, `--line`, `--surface-soft`, `--primary` and `--on-primary` when adding components. Use `--success`, `--warning` and `--danger` for meaning; avoid filling whole sections with status colors. Profile swatches retain their individual colors deliberately.

| Token        | Light     | Dark      |
| ------------ | --------- | --------- |
| Page         | `#faf9f7` | `#242321` |
| Card         | `#ffffff` | `#2c2a27` |
| Sidebar      | `#f7f5f2` | `#282622` |
| Text         | `#242321` | `#eeeae5` |
| Border       | `#eae6e1` | `#44403b` |
| Small accent | `#00a88e` | `#42c9ad` |

The header theme control offers Light, Dark and Use device setting. Preference stays in local storage and synchronizes between tabs. A small inline bootstrap applies it before paint; changing themes makes no network request. Device-mode changes follow the OS. ThemeProvider also works for the current page when browser storage is unavailable.

## Dashboard readability — 24 October 2026

`apps/web/src/components/dashboard.css` owns workspace-specific typography, responsive geometry and transitions, scoped under `.studio`. Colors continue to come from `theme.css`; public/auth/widget pages retain their own layouts. Dashboard body/input text is16px, navigation14px, table cells14px, secondary copy13–15px and headings30–40px. Main controls are42–44px tall. Keep these readable sizes when adding features rather than bringing back8–10px table labels.

The expanded sidebar is256px (224px on tablets), with an explicit76px collapsed rail. Mobile navigation uses a288px drawer; narrow/short screens retain reachable controls. The topbar stays visible while scrolling. Page actions wrap, table scrolling stays inside its container, and dialogs keep their header outside the scrolling body. State transitions are short, and reduced-motion preferences disable them. Mobile toolbar actions retain accessible labels when their visible text is hidden.

Notification loading and failure are separate from the empty-inbox state, with retry and focus restoration. Workspace changes reset notification state. Toast replacement clears the preceding dismissal timer so an older notification cannot erase a newer one early.

## Font privacy

DM Sans and Manrope WOFF2 files and SIL licenses are bundled under `apps/web/src/app/fonts`. The root layout uses `next/font/local`; browser font requests stay on the app's own origin. No Google Fonts, font CDN or font analytics call is needed. The public installation script uses system fonts in its shadow root. See the font directory README for provenance and licenses.

## Loading and missing pages

The root loader and initial identity request use the small voice mark and skeleton. The shared workspace layout then retains navigation while individual pages show bounded skeletons; loaded pages remain visible during refresh. Overview shows real summary counts before recent activity finishes. There is no fabricated percentage or minimum delay. Request failures provide retry/sign-in actions. The custom 404 has home/workspace/docs links and shares the active palette. Unknown workspace section URLs invoke Next's notFound rather than silently rendering Overview. Next may retain HTTP200 after streaming begins and injects noindex; unmatched root routes return404.

## Motion

Use small CSS transitions/graphics for loading, route entry, hover and the 404 orbit. The authentication canvas reads theme colors, suspends while hidden/offscreen, caps frame rate and renders a still scene for reduced motion. Hero movement also stops for reduced-motion users.

The optional **Take a 16-second tour** button loads Remotion4.0.538 and its Player only when opened. Its illustrated timeline explains knowledge → agent → test → channels, has explicit play/pause, chapter shortcuts and a text transcript, starts paused and pauses when the document is hidden. It uses locally loaded fonts and makes no provider/media request. It does not show live account data, place a call or claim a provider was activated. Keep Remotion out of small loading indicators and normal page bundles. Video export is not part of the app walkthrough.

## Verification

Use the isolated development API, then run `scripts/verify_theme_browser.py` through the prepared system Chromium wrapper in this cloud environment. It covers theme persistence/tabs/device mode, actual pending account loading and recovery, missing routes, all tour chapters/play/pause/focus, same-origin successful font requests, ten desktop screens, eight mobile routes in both themes and reduced motion. It also runs against the built web image. Existing beta and separate-origin widget verifiers protect normal workflows. Screenshots/results are ignored under `artifacts/theme/`.

Dashboard-specific acceptance: run `scripts/verify_dashboard_browser.py` through the Chromium wrapper against the isolated development API and built web frontend. It checks24 routes on desktop/mobile in both themes, typography, overflow, collapsed navigation/persistence, short landscape navigation, small dialog scrolling/focus, reduced motion and a deliberately delayed/failed notification request with retry. Evidence: `artifacts/dashboard/results.json` and screenshots.

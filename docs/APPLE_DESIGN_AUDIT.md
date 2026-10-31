# Apple-design audit — 24 October 2026

Installed the requested `apple-design` skill from `emilkowalski/skills` using the skills CLI with a workspace-writable npm cache. Its source is checked in at [.agents/skills/apple-design/SKILL.md](../.agents/skills/apple-design/SKILL.md); `skills-lock.json` records the source/hash. The review applies its feedback, agency, hierarchy, typography and accessibility guidance to the existing site. Existing bundled brand fonts are retained deliberately; this is an interaction/accessibility refinement, not an Apple identity copy.

## Findings and changes

| Finding | Effect | Fix |
| --- | --- | --- |
| Inbox uses undefined `--soft` token | Selected conversation and visitor bubbles lose their background | Use the actual shared surface token; add a green selected edge and `aria-pressed` state |
| Inbox scrolls a child into view on new messages | Reading older messages can jump, and the document can move | Scroll only the message container when already following the latest reply; preserve reading position otherwise |
| Notification requests can finish out of order/across workspace changes | Older data can replace newer notifications | Version requests, guard workspace scope, clear old items on switch and ignore stale callbacks |
| Pale keyboard focus outlines | Focus is difficult to locate | Distinct light/dark green focus rings across keyboard-operable controls; widget focus follows its text colour |
| Compact icon/small action controls on touch screens | Harder to activate reliably | 44px icon/modal controls and coarse-pointer small actions; retain desktop density |
| No press feedback on several controls | Touch interaction feels delayed | Immediate pointer-down brightness feedback without delaying click actions or adding gesture motion |
| Toolbar has little separation from scrolling content | Floating chrome reads as a flat content row | Near-solid blurred toolbar with a restrained shadow, respecting both themes |
| Production CSS retained only the prefixed blur property | Glass preview loses blur in Chromium | Put prefixed property first and standard property last; verify the compiled production preview |
| Missing reduced-transparency/high-contrast materials | Glass effects can impair legibility | Solid toolbar/widget glass fallbacks; contrasting panel boundaries and text |
| Modal motion can conflict with reduced-motion preference | Unnecessary moving surfaces | Explicitly disable modal/panel/rail motion in reduced-motion mode |
| Heading tracking/leading lacks consistent hierarchy | Large headings feel less coherent | Size-appropriate heading tracking and leading, optical font sizing and comfortable supporting-copy leading |

## Verification

Before changes, the existing dashboard verifier passed96layout checks. Its before captures are retained in `artifacts/apple-design/before/`. After changes, it again passed24routes ×2viewports ×2themes, plus small-screen dialogs/focus restoration, rail persistence, landscape navigation, reduced motion and notification loading/error/retry. No page overflow or browser errors.

`scripts/verify_apple_design_browser.py` uses actual local API/database data with synthetic accounts, leads and operator messages. It verifies selected-row visibility/accessibility, reading position/document stability after an incoming message, keyboard focus colour, reversed notification-response ordering, mobile toolbar target sizes/no overflow, contrast fallback, reduced-motion modal and glass-widget contrast fallback. Only notification ordering uses deliberately held responses; ordinary application data is real local API data. No provider calls, marketing emails or calendar bookings are made. Production build/typecheck passes.

Reproduce against the explicit isolated local API and production frontend:

```sh
/workspace/.cloud-setup/nutaan-Rea/local-dev.sh
npm --workspace apps/web run start
UV_CACHE_DIR=/workspace/.cache/uv uv run python /workspace/.cloud-setup/nutaan-Rea/browser.py scripts/verify_dashboard_browser.py
UV_CACHE_DIR=/workspace/.cache/uv uv run python scripts/verify_apple_design_browser.py
```

The runtime API is restored to provider-enabled development after acceptance. Private `.env`, database schemas and browser trust are unchanged. The audit is browser/source based; no real-user usability study or native-device gesture acceptance is claimed. No new gestures or spring dependency was needed for the interactions changed here.

Screenshots/results are ignored artifacts under `artifacts/apple-design/`: landing, desktop inbox, mobile light/dark inbox, small-screen dialog, glass contrast fallback and `results.json`. The dashboard sweep writes `artifacts/dashboard/results.json` and matching screenshots.

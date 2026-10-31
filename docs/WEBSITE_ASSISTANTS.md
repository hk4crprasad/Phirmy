# Website assistants

In Chat widget, enter a website URL and choose a new or existing agent. The API creates a tenant-owned knowledge base, agent binding and widget installation in one transaction, then queues a durable crawl. Agent creation also accepts `website_url`. Saving the public first-minute preview keeps its immediately usable page and starts this broader crawl automatically.

The widget becomes testable after successful knowledge indexing. Configure its name, welcome message, logo, colors, position, allowed origins and optional voice under Appearance. Install the generated script before `</body>` on each page. HTML, Google Tag Manager, WordPress footer/Custom HTML and Shopify theme instructions use the same installer:

```html
<script defer src="https://docs.cynerza.in/widget.js"
  data-widget-id="cyne-YOUR_WIDGET_ID"
  data-public-key="cyne_pk_YOUR_PUBLISHABLE_KEY"></script>
```

These identifiers are public configuration credentials. They are never workspace API keys or provider secrets. Existing installation snippets continue to work for older installations without publishable keys; new installations require the generated publishable key. Other agent installations remain visible under the dashboard’s expandable list. Rotation invalidates old chat/resume/voice capabilities; replace the snippet after rotating.

## Public preview before signup

The first-minute page reads one public HTML page, gives a source-labelled overview and retains discovered same-origin navigation. Catalog questions such as “what all products give me one link” return an actual discovered catalog URL as a clickable link, rather than an unrelated FAQ that happens to contain “products.” Category/product links are explicitly partial if no complete catalog link was found. Missing links are never constructed by guessing a URL.

Other follow-up questions use the configured environment model, bounded page evidence and the last eight user/assistant messages to resolve references. Website text and history are untrusted data; no tools or side effects are exposed. The response validates link IDs against discovered navigation and distinguishes fetched evidence from links that have not been crawled. Unavailable inference is labelled, with matching source sentences or an explicit missing-evidence result. This remains a one-page preview: saving the assistant starts the broader crawl below. It does not prove whole-site coverage.

## Crawling and knowledge

The crawler follows same-origin internal links, robots.txt Sitemap directives and `/sitemap.xml`, including bounded sitemap indexes. Robots rules are checked before every fetch and redirect. Missing robots files allow crawling; permission/server/network errors fail the crawl rather than assuming permission. Requests have at least a 250 ms interval and respect longer robots crawl-delay/request-rate directives. Sites requiring more than 60 seconds between requests are reported as unsupported. Sitemap discovery is limited to 30 files. Redirects cannot leave the submitted origin. Use the website’s final canonical hostname if it redirects to another hostname.

Default coverage is 100 indexed pages per crawl; Updates allows 1–1,000 pages. Discovery is additionally bounded to 10× that limit, visits to 4× that limit, and each fetched/ rendered document to 3 MB. Reports show failures, duplicate pages, rendered pages and remaining discovered URLs. “Discovered pages complete” means the permitted discovered queue was exhausted; it does not guarantee that every page of an arbitrary website exists in the index. Login-only pages, blocked pages, media, anti-bot challenges and undocumented private APIs are not bypassed.

JavaScript rendering runs when static text is insufficient or a known application-shell marker is found. Chromium has no direct network path in the renderer: intercepted same-origin GETs go through the existing DNS-pinned public transport and robots checks. Third-party scripts/resources, POSTs, websockets, service workers, downloads and private destinations are blocked. Each rendered page has a 30-second deadline and a 60-resource budget. Complex applications requiring third-party APIs may remain incomplete; a crawl notice reports failures while retaining available static content. No OCR or authenticated browser crawling is provided.

The API image includes system Chromium; local development needs system Chromium or a Playwright-installed Chromium (`uv run playwright install chromium`). The Python Playwright package is a runtime dependency. The browser runs under the non-root API user in the container.

HTML text, headings/sections and JSON-LD products/ProductGroups/variants are extracted. Product evidence includes source URLs, descriptions, HTTPS images, offered prices/currencies, SKU, known availability, variants and additional specifications. Invalid or absent prices are not invented as zero; their remaining business content is still searchable. Generic page text remains available for services, policies, FAQs and product pages without structured metadata. Automatic catalog records require structured offers; arbitrary unstructured prices/variants are not inferred. Currency minor-unit handling follows the existing catalog’s two-decimal convention.

Extraction uses the existing object storage, source/chunk/snapshot tables, embeddings and Qdrant index. Production requires configured embeddings/Qdrant and fails indexing when they are unavailable. The labelled development mode uses lexical retrieval/source excerpts and does not simulate an LLM or audible call. Exact URL/content revisions are reused; identical text across aliases is excluded from the published snapshot. Unchanged content retains its revision across recrawls.

A successful crawl publishes its snapshot and refreshes the bound live agent. Unpublished human draft edits remain unpublished. Existing calls and widget conversations keep their pinned agent/knowledge versions. Product cards and tool results use immutable source evidence, preventing a partial or failed crawl from changing their prices. The mutable catalog also receives structured product records for operator review; manual catalog overrides do not rewrite website source revisions.

Updates default to every 24 hours. Set the interval to zero to pause automatic updates, or request Recrawl. The existing worker schedules durable jobs and checkpoints crawl progress. Disable the installation or archive the agent to stop automatic refreshes. Indexed pages can be excluded/included in the next snapshot; settings cannot be changed during an active crawl. Old pinned conversations retain their old evidence. An all-excluded/failed crawl does not erase the last working snapshot.

## Visitor context and actions

The installer sends only the current origin/path as page context, excluding query strings and fragments. Backend validation restricts this to installation origins. Questions about “this product” prioritize evidence from that exact indexed page; product search and comparison use the scoped snapshot corpus. Crawled text is explicitly supplied as untrusted evidence, never as instructions.

The model has a closed action vocabulary:

- `website_search`: retrieve indexed product facts, source text and available section IDs.
- `website_open_page`: request navigation to an exact indexed page/product URL after the visitor asks.
- `website_scroll`: request scrolling to an indexed section ID on the current page.

No generated JavaScript, selectors, arbitrary URLs, cart mutations or checkout submissions run in the host website. The backend validates actions and the installer independently requires the same website origin and supported action shape. Navigation occurs after a response is persisted. Action IDs suppress repeated execution across navigation/retries. Dashboard tests show action links instead of navigating the dashboard.

The configured agent’s existing tool registry remains available alongside website retrieval: support tickets, consented contact capture, custom endpoints, Google Calendar and direct Cal.com/Calendly booking. A booking uses actual provider availability, caller-provided details, read-back and a later clear confirmation; pending/unknown outcomes are not claimed as confirmed. These integrations must be connected, enabled on the agent and published. No separate booking system was added. Cart/checkout assistance can explain source facts; direct commerce mutations need a configured supported tool and are not built-in generic website actions.

Optional voice uses the existing speech pipeline and the same pinned knowledge/tool runtime. Text and voice share persisted conversation context; widget bookings retain their conversation scope across modalities. Website action events are delivered to the installer after the voice transcript is persisted. Microphone/provider acceptance still requires a real browser, configured speech services and a secure public deployment.

Conversation history survives same-tab page navigation through a seven-day, origin-bound resume capability in sessionStorage. Access capabilities last 30 minutes and can be renewed through resume. No dashboard cookie is sent by widget requests. History resumes only for that installation, tenant and allowed origin; key rotation, disabling the widget or archiving the agent revokes access. Session storage does not provide cross-device history and can be unavailable in restricted browsers; chat still starts without it. Do not put sensitive visitor data in installation variables.

## Dashboard and API

Chat widget provides URL setup, actual crawl/job counts and notices, indexed pages/exclusions, update settings, installation instructions, live API-backed text testing and appearance. Conversation counts and visitor turns come from saved records. Existing Inbox, Leads, Appointments and Overview screens provide history, captured contacts, bookings and broader usage. Existing installations remain accessible; no legacy installation is removed.

New workspace endpoints under `/v1/workspaces/{workspace_id}/website-assistants`:

- `GET /`, `POST /`: list or create (website_url, name, optional agent_id/goal, max_pages/render_js/refresh_hours).
- `PUT /{id}/options`: update bounded crawl settings and excluded_urls.
- `POST /{id}/recrawl`: enqueue one active crawl for that binding.
- `POST /{id}/rotate-key`: rotate the publishable key.
- `GET /{id}/pages`: current and prior indexed page metadata.

Public configuration accepts `public_key`; new public session input includes `public_key`. Chat input accepts `page_url`. SSE includes `chat.products`, `chat.citations`, `chat.actions` and the persisted `chat.completed` result. `POST /v1/public/sessions/resume` takes the resume bearer capability. Voice input can include current `page_url`; media events include `server.website` for validated actions/cards.

Schema revision: **2026-10-23-website-assistants**, **64 tables**. Apply the reviewed additive migration and runtime grants before production startup; startup itself performs no DDL. This release adds one tenant-scoped binding table and does not require new private environment variables. Existing `.env` values are preserved.

## Verification and limits

`tests/test_website_assistants.py` covers full ingestion, sitemap discovery, robot exclusions, products/variants, duplicate detection, safe actions, page context, tenant/corpus isolation, key rotation, persisted history/resume, automatic updates, failed-index isolation, actual guarded Chromium rendering and model-tool dispatch. Scheduling tests cover public chat read-back/resume/confirmation against both simulated provider contracts. Fixtures are QA-only, not production responses.

`uv run python /workspace/.cloud-setup/nutaan-Rea/run-browser.py scripts/verify_website_browser.py` runs the production-built frontend against a temporary SQLite API/worker and an actual local HTTP website. The QA fixture replaces network guards only for its exact loopback website. It checks URL setup, extraction, appearance, dashboard testing, page management, an independent-origin embed, automatic navigation/history/current-product evidence, mobile/dark themes and usage. No real provider requests occur. On hosts with installed Playwright Chromium, run the verification script directly.

Public website, real embedding/model/speech accounts, carrier callbacks and calendar acceptance depend on deployment access. The supplied reference website could not be fetched through this cloud’s public egress; its individual content and integrations have not been certified. Do not claim arbitrary websites, JavaScript applications or commerce systems have complete coverage.

Aurely live check, 23 October 2026: the real `POST /website-assistants` path returned422 before creating a crawl because this host could not resolve aurelyjewellers.in. The www alias, example.com and github.com also failed DNS resolution; ordinary proxy diagnostics failed as well. No page/product/coverage assertion is possible from that run. Evidence: artifacts/website/aurely-live-results.json. Re-run safely on a networked host with `uv run python scripts/verify_live_website.py https://aurelyjewellers.in/ --max-pages 30 --output artifacts/website/aurely-live-results.json`; the script uses an isolated temporary database and disables model/embedding/mail/carrier credentials.

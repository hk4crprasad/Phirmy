# Aurely Jewellers — actual app crawl

Tested https://aurelyjewellers.in/ on24October2026 through the real Voice Studio website-assistant screen.

| Check | Observed result |
| --- | --- |
| Native app crawl | Completed in about190seconds |
| Indexed pages | 48 |
| Searchable passages | 83 |
| Structured products | 18 |
| Guarded browser rendering | 36pages |
| Sitemap coverage | All46URLs represented after canonical normalization |
| Remaining discovered URLs | 0 |
| Notices | robots exclusions: `/orders`, `/login`, `/account`, `/admin` |
| Knowledge query | HTTP200; supporting passages; Qdrant hybrid retrieval |
| Connected assistant | Correct₹699 price and imitation-jewellery material for Premium Silver-Tone Designer Bangle |
| Browser page errors | 0 |

The app used live website GETs, robots.txt/sitemap discovery, the guarded renderer, real Azure object storage, configured embeddings/Qdrant, and the configured Azure LLM. No Firecrawl output or synthetic website responses were imported. The source site was not modified; no account, order, checkout or admin pages were accessed. This is coverage of discovered permitted pages at test time, not a guarantee about future site changes or hidden pages.

The test initially reproduced the cloud's local-DNS failure. Explicit `PUBLIC_NETWORK_MODE=proxy` now resolves public A/AAAA records through verified HTTPS DNS using the configured/inherited proxy, validates all addresses, and tunnels only the selected public IP. Original Host/TLS SNI/certificate verification and same-origin/robots guards remain intact. Policy denials fail closed. Other hosts default to direct DNS-pinned mode. This transport does not resolve Supabase/PostgreSQL TCP routing.

The app remains on its explicit local provider-enabled database (`data/cloud-providers`), with actual Azure/Qdrant/Redis integrations. It did not write to the unreachable Supabase database. The named QA workspace and completed website knowledge are retained for inspection.

Reproduce only when needed, with the API/web/Redis/Qdrant running:

```sh
uv run python scripts/verify_aurely_browser.py
```

The verifier creates a new synthetic QA account/workspace, submits the real URL through the app UI, waits for the actual worker, checks indexed pages and Qdrant retrieval, then asks the connected agent the bangle question. Credentials are never printed or written to its results. Provider use and storing site evidence can incur normal service charges.

Ignored evidence retained locally under `artifacts/aurely-app/`:

- `01-crawling.png`: actual queued/running crawl with Stop control.
- `02-crawl-result.png`: completed knowledge summary.
- `03-indexed-pages.png`: actual source list.
- `04-grounded-answer.png`: actual assistant answer and source/product evidence.
- `results.json`: job, extracted catalog/pages, coverage comparison, query and answer evidence.

Proxy-mode regression tests verify original Host/TLS SNI, separate-origin pools, public-IP CONNECT, denial without route fallback, mixed-public/private DNS rejection and private/metadata/loopback/multicast rejection. Direct transport and existing website tests remain in place.

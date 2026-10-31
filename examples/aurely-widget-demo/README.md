# Aurely HTML widget demo

A standalone sample storefront with the actual Voice Studio widget, connected to the published Aurely crawl:48pages,83passages and18products. It uses a separate demo installation; the original Aurely website installation is unchanged.

The HTML embed contains only a widget installation ID and an origin-bound publishable key. `widget-config.json` contains public setup metadata. No dashboard cookie, session token or provider credential is included.

## Run

From the repository root, with the provider-enabled local API on8100 and web app on3100:

```sh
/workspace/.cloud-setup/nutaan-Rea/provider-dev.sh .venv/bin/python scripts/setup_aurely_widget_demo.py
.venv/bin/python -m http.server 3200 --bind 127.0.0.1 --directory examples/aurely-widget-demo
```

The setup helper reuses the completed Aurely knowledge and the existing demo installation; repeated runs preserve its public ID/key and one embed. A fresh database needs the Aurely crawl first. Keep the static server in a separate long-running terminal.

Serve the file over HTTP on the configured3200origin. Opening it directly with `file://` has a different origin and is not an equivalent test. For another host/port or deployment, create an installation with that exact allowed origin and update the script source/public fields. No public deployment was performed here.

The sample storefront's three product images are local copies of public Aurely source images. Its prices and product links come from the actual crawled catalog. The widget still calls the real app, Qdrant and configured LLM; its response is not hard-coded into this HTML.

## Verify

```sh
.venv/bin/python scripts/verify_aurely_widget_demo.py
```

The independent browser has no dashboard login. Checks cover:

- Loading/opening chat and receiving the actual₹699/imitation-jewellery answer with source evidence.
- Correct product URL dispatched in a new tab.
- Reloading and resuming the same conversation without creating another session.
- Close/reopen and390px light/dark layouts without horizontal overflow.
- No app/demo cookies; invalid origins and publishable keys receive403.
- A graceful text/link fallback when remote product images fail.

The cloud browser reports `net::ERR_CERT_AUTHORITY_INVALID` for proxy-issued certificates on the external Aurely product page/images. Backend HTTPS with the configured CA works. The requested persistent browser trust change was rejected by automatic review and declined by the user; trust settings and TLS verification were preserved. Successful remote destination rendering is therefore not claimed. The verifier records this limitation separately from passed chat/embed checks.

Working screenshots and public test results are retained in ignored `artifacts/aurely-widget-demo/`:

- `01-demo-page.png`
- `02-desktop-answer.png`
- `03-mobile-answer.png`
- `04-mobile-dark.png`
- `results.json`

The local installation depends on this environment's retained provider-enabled SQLite DB. Restoring this repository without that DB requires running setup after completing an Aurely crawl.

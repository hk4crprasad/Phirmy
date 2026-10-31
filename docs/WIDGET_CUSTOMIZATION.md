# Dashboard widget controls

See also [email capture, microphone input and live support](WIDGET_LIVE_INBOX.md).

Open **Chat widget → Customize widget**. Website assistants have this button beside their selected website; independent installations have it under **Other agent installations**. Each installation keeps its own branding and conversation style.

The editor provides a live desktop/mobile preview and four sections:

- **Brand:** assistant name, launcher label, logo upload or HTTPS logo URL, and system/serif/rounded fonts.
- **Style:** light/dark/device colour mode; button, button text, panel, body text, visitor bubble/text and border colours; ten material designs and four legacy layouts; pill/rounded/circle launcher, chat/sparkle/logo/text icon choices; panel corner radius, width, height, side/bottom spacing and left/right placement.
- **Messages & tone:** welcome message, input placeholder, send-button label, footer text, and agent-default/professional/friendly/warm/concise response tone.
- **Website:** optional origin restriction, configured website origins for navigation, enabled state, voice availability and permitted indexed-page navigation/scrolling. Valid keyed embeds work on any origin/local HTML file by default.

**Save widget** applies the settings without changing the widget ID, publishable key, embed snippet, published agent or knowledge. Existing website pages receive the saved branding on reload, including the launcher before chat is opened. Existing conversations retain their history; changing the welcome message does not rewrite old conversation messages. Cancel discards the draft, including staged logo uploads. Reset styling resets presentation while keeping brand text/logo and conversation settings.

Response tone is applied to the selected widget's chat and widget voice configuration through predefined communication guidance. Connected evidence, permissions, tools and confirmation rules remain in place. It does not rewrite the underlying published agent or other installations.

## Design collection

Select **Style → Widget style** to start with one of these designs, then adjust the colours and layout to match the website:

| Design | Appearance |
| --- | --- |
| Minimalism | White surfaces, fine lines, charcoal controls and generous spacing |
| Glassmorphism | Translucent surfaces, background blur and luminous edges |
| Claymorphism | Rounded sculpted surfaces and soft inset/raised shadows |
| Skeuomorphism | Warm paper texture, stitched bubbles and tactile controls |
| Neobrutalism | Bold outlines, crisp corners, chartreuse accents and offset shadows |
| Bento grid | Modular header/composer and a two-column product card grid |
| Neumorphism | Soft raised bubbles and inset input controls |
| Aurora | Restrained gradients with a dark lilac palette |
| Editorial | Warm ivory, serif type, fine rules and understated controls |
| Monochrome | Black-and-white surfaces with subtle borders |

Choosing a design applies its recommended colours, font, shape, dimensions and placement. Assistant name, logo, labels, messages, tone, origins and published knowledge are retained. Later colour/layout edits remain editable. Compact, spacious, soft-bubble and classic-header layouts remain available for existing installations.

The dashboard preview and actual embedded Shadow DOM load the same `apps/web/public/widget-designs.css`; `apps/web/src/lib/widget-designs.ts` holds recommended palettes. Material styles use scoped classes and fixed CSS; no customer-supplied CSS is executed. The public embed fetches the stylesheet from the application origin. Reduced-motion preferences are respected. Deployment must include both `widget.js` and `widget-designs.css`.

## Logos

Uploads accept verified PNG, JPEG or WebP images up to2MB and4096pixels per side. Logo files remain in workspace-scoped object storage; browsers receive a widget-key-protected image path. Private object keys/content metadata are not included in public configuration and cannot be replaced through client-supplied theme fields. Uploading a logo and saving its accompanying settings uses one database transaction; a bad file or upload failure rolls back the settings. Logos can also be removed or replaced with a public HTTPS URL. Remote URL rendering still depends on browser/network certificate trust; no trust exception or disabled verification is used.

## API and compatibility

Existing installation create/update routes accept the expanded validated `theme` fields. Additional routes are:

- `POST /v1/workspaces/{workspace_id}/installations/{installation_id}/logo`: multipart `file`, with optional `settings_json` for a combined settings/logo save.
- `DELETE /v1/workspaces/{workspace_id}/installations/{installation_id}/logo`: remove the logo from the installation.
- `GET /v1/public/installations/{public_id}/logo?public_key=…`: read the current verified logo for an enabled installation.

The exported actual OpenAPI now has142paths. No database table or schema revision change is needed. New Pillow dependency verifies image files; `uv sync --frozen` installs it. Existing themes continue to work, and new style values are bounded/validated before saving. The public renderer uses fixed CSS variables and predefined SVG icons, with text assigned as text rather than executable HTML.

## Validation — 24 October 2026

The full isolated backend run passed346tests with2intentional provider-specific skips before the final transactional upload refinement. All11focused branding tests pass on the final upload implementation, including invalid files, rollback, tenant isolation, protected object metadata, key preservation and tone reaching the real chat handler.

`scripts/verify_widget_customizer_browser.py` passed actual dashboard edit/save/reopen/cancel and mobile editor checks, then opened the separate demo HTML as an anonymous visitor. It verified uploaded-logo loading through actual storage, saved launcher branding before opening, font/placement/dimensions/radius, welcome/placeholder/footer, preserved embed ID/key, and a real configured LLM/Qdrant answer of₹699. It recorded zero browser page errors. The existing website/widget/crawl-Stop browser regression also passed, including separate-origin chat, navigation and resumed history.

The live demonstration uses the retained Aurely QA workspace and provider-enabled local SQLite database, not the unavailable Supabase database. The test creates a synthetic local editor membership only in that QA workspace; credentials are not printed or stored in screenshots. Run it through the explicit local helper:

```sh
/workspace/.cloud-setup/nutaan-Rea/provider-dev.sh .venv/bin/python scripts/verify_widget_customizer_browser.py
```

Ignored screenshots/results are in `artifacts/widget-customizer/`: `01-dashboard-brand.png`, `02-dashboard-messages.png`, `03-dashboard-mobile.png`, `04-customized-demo.png`, `05-customized-demo-mobile.png`, and `results.json`. Private `.env` and browser trust remain unchanged. The existing declined browser CA modification remains out of scope.

The ten-design extension passes **21 focused branding tests**, including saving each design and reading it through the real public configuration handler. `scripts/verify_widget_designs_browser.py` selects and saves every design in the actual dashboard, checks both preview/embed material styles, preserves the embed key/name/tone, asks the real Aurely assistant a bangle-price question, and checks mobile bounds and dark media with zero page errors. All ten return the grounded ₹699 answer through configured LLM/Qdrant services. The test adds a synthetic editor membership only in the retained local QA workspace and requires the explicit provider-enabled local helper; it refuses a non-SQLite database.

```sh
/workspace/.cloud-setup/nutaan-Rea/provider-dev.sh .venv/bin/python scripts/verify_widget_designs_browser.py
```

Per-design dashboard, desktop, widget and mobile screenshots are under ignored `artifacts/widget-designs/`, alongside `results.json`, an `index.html` gallery and `all-designs.png`. The demo is left on Minimalism. Remote source-image browser trust limits still apply as described above; failed remote thumbnails are hidden gracefully and local storefront/uploaded-logo images work.

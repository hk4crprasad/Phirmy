# Bundled fonts

These WOFF2 assets are stored in the repository and loaded with `next/font/local` in the root layout. Next serves the optimized files from this app's own `/_next/static/media/` path. Neither the browser nor the build needs a font service request.

- `dm-sans.woff2`: DM Sans, used for the neutral interface. [Project](https://github.com/googlefonts/dm-fonts); license in `dm-sans-LICENSE.txt`.
- `manrope.woff2`: Manrope, retained for existing display typography. [Project](https://github.com/googlefonts/manrope); license in `manrope-LICENSE.txt`.

Both are distributed under SIL Open Font License 1.1. Preserve the license files when updating assets. Keep font URLs local; do not add Google Fonts stylesheets, CDN imports or font analytics. The public installation script uses system fonts inside its shadow root, requiring no font download.

`scripts/verify_theme_browser.py` checks that actual font requests stay on the app origin and finish successfully across the interface.

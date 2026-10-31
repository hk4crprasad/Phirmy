# Cynerza beta implementation

This is the implementation checklist for the expanded beta requested on 22 October 2026. Preserve the tracked private `.env`, existing credentials, neutral light/charcoal palette, and Lucide icon pack. Use the existing checkout. Tests use isolated SQLite and never reset Supabase.

- [x] Authentication: Google OIDC with state/nonce/PKCE, verified email signup over SMTP, short-lived JWT cookies, rotating refresh tokens, revocation and session management.
- [x] Account: editable profile/preferences, account linking, notification inbox and read state.
- [x] Agent correctness: widget variables, recent conversation history, campaign variables, structured variable editor and lifecycle controls.
- [x] Agent distribution: public voice testing/widget, explicit usage/concurrency limits, platform connection settings.
- [x] Integrations: Google Calendar, Cal.com/Calendly event selection and direct call-agent booking with confirmation/recovery, tenant carrier settings and contacts import/export. Real scheduling acceptance remains pending.
- [x] First phone beta: operator-funded trial pools, one-click seven-day dedicated number assignment, optional budget-capped rental with uncertain-outcome reconciliation, expiry/balance/usage controls, operational email retry, manual account/number replacement and customer allowance/test UI. Activation still needs real access; see [phone trials](PHONE_TRIALS.md).
- [x] UX: retractable desktop sidebar, accessible mobile drawer, clear headings, first useful result and next steps, consistent icons, reduced-motion support.
- [x] Deployment: configuration and reverse proxy for docs.cynerza.in, migrations/backups guidance, current contracts and setup instructions.
- [x] Validation: meaningful auth/integration regression tests, full isolated suite, build, desktop/mobile browser checks and accurate live-service limitations.

Google OAuth client and SMTP credentials are currently missing. Implement and test these flows with isolated fixtures while the user supplies secure configuration. Deployment/domain ownership and live carrier acceptance require external access; do not advertise local checks as public deployment.

Product animation/audio is an optional follow-up to the functional beta, using the supplied Fish configuration if needed. It must not delay the account and agent workflows.

Implementation boxes record code completion, not live activation. See BETA_DEPLOYMENT.md and IMPLEMENTATION_STATUS.md for external gates. The before-change audit found a substantial working agent/tool/voice foundation, with Google/verified signup/session controls/contacts and launch operations missing. Those implementation gaps are now addressed at the private-beta level; do not turn the checklist into a production-readiness percentage.

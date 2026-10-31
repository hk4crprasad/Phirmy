# Connect Cal.com and Calendly with OAuth

Workspace owners/admins can authorize a scheduling account in **Integrations**, select a meeting type under **Set up call booking**, then enable the scheduling bundle and publish their agent. This authorizes an integration for an existing signed-in workspace; application signup and Google login remain separate. Each workspace stores its own encrypted provider access/refresh tokens. Customers do not need to paste their tokens when OAuth is configured.

## Register the operator's apps

Use the following exact production values when `APP_ORIGIN=https://docs.cynerza.in`. The frontend and API must be served together through the existing `/backend` proxy. Register separate development apps if needed; their callback must use the actual development `APP_ORIGIN` with the same path. Redirect wildcards are not used.

| Field | Cal.com | Calendly |
| --- | --- | --- |
| App name | Voice Studio | Voice Studio |
| Website | `https://docs.cynerza.in` | `https://docs.cynerza.in` |
| Redirect URI | `https://docs.cynerza.in/backend/v1/auth/scheduling/calcom/callback` | `https://docs.cynerza.in/backend/v1/auth/scheduling/calendly/callback` |
| Client kind | Confidential, PKCE toggle off; or the supported public PKCE option below | Web, production with HTTPS (sandbox permits localhost HTTP) |
| Permissions | `PROFILE_READ`, `EVENT_TYPE_READ`, `BOOKING_READ` | `users:read`, `event_types:read`, `availability:read`, `scheduled_events:read`, `scheduled_events:write` |

Cal.com: create the client in [Settings → Developer → OAuth](https://app.cal.com/settings/developer/oauth). Enter a purpose such as “Let workspace owners authorize their AI assistant to check availability and book customer meetings after confirmation.” Request the listed scopes, not all organization/team permissions. Obtain Cal.com's approval for third-party/customer use. The supplied Cal.com documentation states public slots and booking creation do not require an additional OAuth write scope; profile, event and booking reads do require the scopes above.

Calendly: register a developer account and a Web OAuth application in the [developer console](https://developer.calendly.com/). Select sandbox for development or production for customer data. Copy the client ID and secret when displayed. The app uses PKCE S256 in addition to the web client secret. A webhook signing key can be saved privately in the provider console, but this feature does not subscribe to Calendly webhooks and does not need a pretend webhook setting.

Add the operator credentials to the existing private `.env` or deployment environment:

```dotenv
CALCOM_CLIENT_ID=
CALCOM_CLIENT_SECRET=
CALCOM_OAUTH_MODE=confidential
CALENDLY_CLIENT_ID=
CALENDLY_CLIENT_SECRET=
```

These placeholders have already been added without replacing existing values. Restart the API after supplying them. For a **public Cal.com client**, enable its PKCE option, set `CALCOM_OAUTH_MODE=public`, supply its ID, and leave its secret blank. Public mode sends S256 PKCE without a client secret. Confidential mode sends the secret and matches the confidential flow in the inspected Cal.com source. Client configuration changes require reconnection. Google Calendar remains an independent integration; the app never silently books into a different service when one fails.

## What the app does

- `POST /v1/workspaces/{workspace_id}/connections/{provider}/oauth/start` requires an owner/admin dashboard session and CSRF protection. It returns a fixed provider authorization URL and sets an HttpOnly browser-binding cookie. API keys cannot initiate OAuth.
- `GET /v1/auth/scheduling/{provider}/callback` requires the same dashboard session, browser binding, provider and single-use ten-minute state. A consumed attempt is committed before token exchange. The code never accepts a user-supplied redirect destination. It exchanges the code on the server and verifies the actual provider profile before connecting the workspace. Failed/denied callbacks do not create a connection.
- Cal.com uses `https://app.cal.com/auth/oauth2/authorize` and `https://api.cal.com/v2/auth/oauth2/token`. Calendly uses `https://auth.calendly.com/oauth/authorize` and `https://auth.calendly.com/oauth/token`, with HTTP Basic client authentication at the token endpoint.
- Access/refresh tokens, account identity, expiry and PKCE verifier are encrypted at rest. Tokens never appear in frontend responses, URLs or snippets. Refresh starts before expiry, using a durable database claim so parallel requests do not reuse a rotating refresh token. An ambiguous/lost refresh requires reconnecting; the app does not repeatedly submit the old token.
- Refreshing access preserves a prepared booking's account identity. Replacing the connected account or selecting another event invalidates that binding. A provider 401 marks the affected OAuth connection for reconnection; it never authorizes retrying a booking POST.
- OAuth alone does not enable a meeting type. Select it, enable agent actions and publish. Booking still requires actual availability, caller details, the exact read-back and a later unambiguous confirmation. API key/personal-token connections remain available separately.
- Disconnect removes the locally stored credentials and blocks further use. No undocumented remote revocation endpoint is called. To revoke the grant at the provider too, remove the app from that account's authorized integrations.

No database table or schema revision is added: the existing OAuth-attempt and encrypted connector-credential records are used. The current schema remains `2026-10-23-website-assistants` with64 tables; the API contract has140 paths.

## Activation and evidence limits

OAuth does not grant a paid plan or bypass provider approval. Calendly direct booking still requires **Standard or above**, appropriate Scheduling API entitlement and the listed scopes. Unsupported forms/payment/location choices still require the hosted scheduler. See [booking requirements](AGENT_SCHEDULING.md).

The Cal.com flow was checked against the documentation supplied by the user on23 October2026 and the [vendor's OAuth service source](https://github.com/calcom/cal.com/blob/0f19cc46ef6b6426ee398c670575b3c96be7af9e/apps/api/v2/src/lib/services/oauth.service.ts). The Calendly flow follows the user's pasted OAuth application guide (PKCE, web client and redirect requirements), the [developer documentation](https://developer.calendly.com/docs/authentication/creating-an-oauth-app), and the previously inspected contract provenance in [AGENT_SCHEDULING](AGENT_SCHEDULING.md). Direct documentation fetches remain proxy-blocked in this cloud.

Automated checks simulate only the external authorization/token/profile/model/booking boundaries; they exercise the actual application routes, cookies, database, refresh coordination and booking runtime. No provider application has been registered or approved here, no live consent has been granted, and no real meeting or email has been created. After registering the apps and supplying credentials, complete an actual consent flow and a controlled booking/status/cancellation check for each provider before inviting customers. That final acceptance must use the deployed HTTPS callbacks and the intended customer account plan.

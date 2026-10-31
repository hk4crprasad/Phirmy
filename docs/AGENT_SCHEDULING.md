# Book Cal.com and Calendly meetings during a call

The agent can check real availability, collect the caller's details, read back a proposed meeting and create it after a separate confirmation. Both phone calls and the browser voice runtime use this tool path. The text simulation exercises the conversation and persistence path without sending microphone audio to speech providers.

## Set up a workspace

1. Open **Integrations** and choose **Connect with Cal.com** or **Connect with Calendly** to authorize the account. API key/personal-token connections also remain available. Existing hosted scheduling links remain available.
2. Select **Set up call booking**. Choose an event from the connected account's meeting types. Selection and verification are performed on the server; agents cannot supply an arbitrary event URL or another customer's credentials.
3. Open an agent's **Actions** tab. Enable **Book meetings through Cal.com or Calendly**, choose its **Booking platform**, then publish. The selector fixes the service for that agent; the caller does not need to choose an integration.
4. Test in **Voice lab**. Ask for a meeting, give a date/time window and timezone, then provide a name, confirmation email and any required answers. After the agent reads the exact meeting back, say **Yes, please book it**.
5. Review **Appointments → Agent booking requests**. Its time is displayed in the caller's stored timezone. Confirmed bookings also have a workspace appointment. Use **Check status** to read the provider again; **Manage at provider** opens the provider's management page.

Credentials stay encrypted per workspace. OAuth requires the operator app registration and five client settings in [OAuth setup](SCHEDULING_OAUTH.md); customers authorize their own accounts. Manual token connections need no global OAuth client settings. Do not put customer calendar tokens in website variables, agent prompts or browser code.

## Provider requirements

| Service | Required access / supported scope |
| --- | --- |
| Cal.com | Approved hosted OAuth client/account authorization, or an `api.cal.com` API key with the required event/booking access. One selected event per workspace connection. |
| Calendly | **Standard or above**, with Scheduling API access. Required token permissions: `event_types:read`, `availability:read`, `scheduled_events:write`, and `scheduled_events:read` for verification/reconciliation. A free account can expose event information without allowing the booking POST. |

Use an active event without required payment. Cal.com recurring events and forms with unsupported required controls are excluded. Calendly events with a choice of multiple locations or an invitee-specified location require the hosted scheduler. Fixed meeting durations from 1–480 minutes are supported; the event's default duration is used. A search covers at most seven days and returns at most100 slots. The event selector lists the first100 returned event types.

The agent collects supported required form answers from caller evidence and includes them in the read-back. A Calendly outbound-call location also requires an explicitly provided/known caller phone number. The adapter does not invent a location or payment answer. Standard provider notifications and workflows can run after a real booking; an API acceptance does not prove email delivery.

## Call flow and status

The bundled tools are:

| Tool | Result |
| --- | --- |
| `check_scheduling_availability` | Reads the configured event and provider slots; stores a short-lived offer scoped to this workspace and call/conversation. |
| `prepare_scheduling_booking` | Validates an exact returned slot, timezone, caller-provided name/email/phone and required answers. Persists a proposal and its read-back; sends no booking POST. |
| `confirm_scheduling_booking` | Requires the exact non-interrupted read-back in the preceding assistant transcript, a later turn and an unambiguous affirmative reply. Rechecks event settings and current availability before committing one submission. |
| `get_scheduling_booking` | Reads/reconciles the existing request. It never creates a replacement booking. |

The runtime emits the server's read-back verbatim, so the subsequent confirmation applies to the actual stored proposal. A qualified reply such as “Yes, but at11AM” is a change request and does not authorize the previous time. Proposals/offers expire after ten minutes. Changed credentials, selected events, event settings, unavailable slots, expired proposals or another conversation cannot silently reuse an old confirmation. Only one submitted/pending/confirmed request per conversation/provider is allowed.

The agent says **confirmed** only after the provider response identifies the correct meeting type, exact start/end and invitee email and reports acceptance. Cal.com `pending` becomes **pending_approval**. An interrupted submission, timeout, failed response validation or ambiguous provider result becomes **unknown**; a clear provider rejection becomes **failed**. A later failed verification GET is uncertain even when the original booking POST succeeded.

The app persists submission intent before its single POST. Duplicate confirmations, concurrent workers and later turns reuse that request. It does not assume either provider supports an undocumented idempotency header. Cal.com metadata and Calendly UTM tracking carry a stable request marker. If the response was lost, reconciliation uses only GET requests and requires an exact marker plus matching booking details. A lookup that finds nothing does not authorize another POST. The caller should check the existing request before trying another time.

Known requests can be checked for later provider cancellation or host approval. If the provider is unreachable, the UI retains the last observed state and says the refresh failed; it does not fabricate a fresh verification. No provider webhooks or automatic rescheduling are implemented. Do not cancel a remote meeting by changing only its local appointment: the API blocks that misleading operation. Use the provider to change/cancel and then refresh the record.

## API and deployment

- `GET /v1/workspaces/{workspace_id}/connections/{provider}/event-types`
- `PUT /v1/workspaces/{workspace_id}/connections/{provider}/booking-settings` with `{"event_type_id":"…"}`
- `GET /v1/workspaces/{workspace_id}/scheduling-bookings`
- `POST /v1/workspaces/{workspace_id}/scheduling-bookings/{booking_id}/refresh` with `{}`

The configuration endpoints require workspace settings permissions; history/refresh require appointment permissions. Agent tool contexts bind the workspace and actual call/conversation on the server. Secrets are never included in these responses.

Schema revision **`2026-10-23-agent-scheduling`** adds `scheduling_availability` and `scheduling_bookings` to the prior61-table checkpoint, for **63 tables**. Apply reviewed additive migrations and runtime grants before updating the production API. Production startup still performs no DDL. The latest website/OAuth release retains64 tables with revision `2026-10-23-website-assistants` and contains140 paths; agent configuration adds an optional `scheduling_provider` on the availability tool.

## API sources and evidence limits

Checked23 October2026. Browser-facing Cal.com and Calendly developer sites were blocked by this cloud's proxy. The Cal.com adapter was checked against the vendor's public source at commit `0f19cc46ef6b6426ee398c670575b3c96be7af9e`:

- [Slots controller](https://github.com/calcom/cal.com/blob/0f19cc46ef6b6426ee398c670575b3c96be7af9e/apps/api/v2/src/modules/slots/slots-2024-09-04/controllers/slots.controller.ts): `GET /v2/slots`, `cal-api-version:2024-09-04`, UTC ranges and range output.
- [Bookings controller](https://github.com/calcom/cal.com/blob/0f19cc46ef6b6426ee398c670575b3c96be7af9e/apps/api/v2/src/platform/bookings/2024-08-13/controllers/bookings.controller.ts): `POST /v2/bookings`, `cal-api-version:2024-08-13`.
- [Booking input](https://github.com/calcom/cal.com/blob/0f19cc46ef6b6426ee398c670575b3c96be7af9e/packages/platform/types/bookings/2024-08-13/inputs/create-booking.input.ts): UTC start, attendee/timeZone/email/phone, field responses and metadata.
- [Booking output](https://github.com/calcom/cal.com/blob/0f19cc46ef6b6426ee398c670575b3c96be7af9e/packages/platform/types/bookings/2024-08-13/outputs/booking.output.ts): accepted/pending/rejected/cancelled states.
- [Event controller](https://github.com/calcom/cal.com/blob/0f19cc46ef6b6426ee398c670575b3c96be7af9e/apps/api/v2/src/platform/event-types/event-types_2024_06_14/controllers/event-types.controller.ts): authorized event reads, `cal-api-version:2024-06-14`.

For Calendly, the inspected contract is a **third-party snapshot of Calendly's published OpenAPI**, not a successful direct fetch from Calendly in this cloud:

- [Snapshot at22 October2026](https://github.com/soenneker/soenneker.calendly.openapiclient/blob/b338cd9eca0909ae31b1d52127ab65a79a66e9c0/openapi.json).
- [Generator provenance](https://github.com/soenneker/soenneker.calendly.runners.openapiclient/blob/1eb49ba3bd383a2bec0734be85853fc3ab03e35d/src/Soenneker.Calendly.Runners.OpenApiClient/Utils/FileOperationsUtil.cs): downloads and bundles Calendly's [published OpenAPI endpoint](https://stoplight.io/api/v1/projects/calendly/api-docs/nodes/reference/calendly-api/openapi.yaml).
- Contract sections: `POST /invitees` (paid plan, `scheduled_events:write`, invitee name/email/timezone, exact required question strings and tracking); `GET /event_type_available_times` (`availability:read`); event types and scheduled-event/invitee GETs. The snapshot supports a31-day availability range; the app deliberately limits its search to seven days.
- [Calendly developer documentation](https://developer.calendly.com/api-docs) and [Cal.com booking documentation](https://cal.com/docs/api-reference/v2/bookings/create-a-booking) are the live references to verify when activating real accounts.

No live account entitlement, real booking, notification delivery, microphone or PSTN acceptance is claimed by these source checks. Do a controlled real booking with the selected account, verify its dashboard/calendar entry and notification, then change/cancel it at the provider and check status in the app before inviting users.

Local verification uses simulated provider/model responses with the real agent runtime, database and WebSocket text simulation. Reproduce with `uv run pytest -q`, `npm run build`, the system Chromium wrapper for `scripts/verify_scheduling_browser.py`, and `scripts/verify_number_allocation_postgres.py` for isolated PostgreSQL migration/restricted-role/concurrent-number/concurrent-booking checks. See [verification](VERIFICATION.md) for actual results.

# Running the first phone beta

Customers can click **Start free phone trial** to receive a server-selected dedicated US voice number. The app assigns approved owned stock first, or optionally rents one through Twilio within configured rental caps. The default entitlement is **seven days from assignment** and **3 calls of up to 60 seconds**. An operator pool can remain open for up to 20 days with at most 10 lifetime workspace assignments by default. Automatic enrollment closes when fewer than seven full days remain, stock/budget runs out or provider balance is unavailable.

Number purchases default to **disabled**. The app never creates parent carrier accounts or renews promotional credit. Twilio's official account-setup skill lists one number for trial accounts; a $15 credit balance does not override that limit. Use actual approved inventory/entitlements. Each assigned number belongs to one workspace. The seven-day app deadline does not cancel monthly carrier rental. See [provider comparison and funding findings](FREE_NUMBER_RESEARCH.md).

## What is implemented

- Operator-only pool/inventory/budget configuration. A signed-in workspace owner/admin can request the configured trial with an empty POST body; users cannot select a source number, country, pool, price, other user or allowance. One durable automatic request per person and workspace prevents repeated claims. Scoped API keys cannot enroll people. Manual operator grants remain available.
- Ownership verification of the assigned Twilio number. Trial numbers are outbound only and can call only their operator-approved, consenting, provider-verified destinations.
- Durable, idempotent admission, one outstanding phone call per workspace, a lifetime call allowance and Twilio's per-call `time_limit`. Failed or uncertain dispatches retain their reserved allowance. The workspace wallet is not charged for these operator-funded calls.
- A provider balance check every five minutes while the dispatcher runs. Missing, failed, wrong-currency or older-than-ten-minute balance checks block new trial calls. The default floor is **USD 2.00**, configured in cents. Balance is a delayed provider observation, not an exact total-spend cap; number rental and other AI providers are billed separately.
- Admission and queued dispatch both recheck eligibility. Expired, paused, revoked or low-balance trials cannot start new calls. Active media checks access and the connected-time limit; the carrier time limit provides an additional bound. Live carrier behavior still requires acceptance testing.
- Phone numbers displays allowance, assigned number, expiry and a test-call form using published agents and approved destinations. Bulk campaigns and inbound routing are excluded from the trial allowance.
- Operator emails at 48 hours/24 hours before expiry, after expiry, for low/unavailable balance and final-call reservation. Workspace notifications report trial expiry and exhaustion. Notices are persisted once per condition; SMTP failures retry with backoff. Email delivery may repeat if a process dies after SMTP accepts a message but before its completion is recorded.
- Stored carrier bindings are encrypted with the existing stable `APP_SECRET`. Environment credential changes do not silently change already assigned trials. Operators can refresh a token for the same account or explicitly replace an account/number while preserving the workspace's original expiry and used allowance. Past callbacks retain the original account binding.

## Before enabling

Fill the existing private `.env` settings:

| Setting | What to supply |
| --- | --- |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` | Credentials for the account that actually owns the demo number |
| `BETA_OPERATOR_EMAIL` | Your email address for operational alerts |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_SECURITY` | Working, verified email delivery; use the same SMTP configuration as account verification |
| `MEDIA_PUBLIC_ORIGIN` | The public HTTPS origin, normally `https://docs.cynerza.in` |
| `LIVE_CALLS_ENABLED` | Keep false until the controlled public call test is ready |
| `PHONE_TRIALS_ENABLED` | Defaults false; enable only after the steps below |
| `APP_SECRET` | The original stable encryption/signing value; recover it from the original host if needed |

The existing LLM, Fish, Deepgram, database and object-store settings also need to work on the deployment host. There are no additional provider keys to invent. A global `TWILIO_CALLER_ID` is not required for assigned trials; the assigned, verified workspace number is used. For non-trial live calls, the existing controlled deployment allowlist still applies. Operator-approved trial destinations must separately be verified in Twilio as required by that account.

1. Apply the latest additive **2026-10-23-agent-scheduling** migration to the main database and reapply runtime grants. The order/inventory update raised59 tables to61; the subsequent agent-scheduling update adds two more, for **63 application tables**. Take and verify backups first; see [deployment](BETA_DEPLOYMENT.md).
2. Deploy the app/docs on `docs.cynerza.in` with HTTPS/WSS and public carrier callbacks. Keep the original stable encryption secret. Use one API/dispatcher process.
3. Check the real Twilio account's expiry, number allowance, credit eligibility, geography and verified destinations. Stock registration and pool configuration commands do not purchase numbers. Keep automatic purchases disabled for an owned-number-only rollout.
4. Set the private credentials, SMTP and operator email, then configure the pool. Use `--expires-at` with the actual provider expiry if earlier than 20 days:

```sh
uv run python scripts/manage_phone_trials.py configure --name "First beta" --days 20
uv run python scripts/manage_phone_trials.py status
```

For the production Compose environment, run these commands through the maintenance service so the production configuration and stable secret are loaded:

```sh
docker compose -f compose.yaml -f deploy/compose.beta.yaml --profile maintenance run --rm migrate python scripts/manage_phone_trials.py configure --name "First beta" --days 20
```

5. For manual assignment, invite a user and identify their workspace ID from the authenticated `/v1/auth/me` response. Assign the existing owned source number and their verified test destination. Replace every placeholder:

```sh
uv run python scripts/manage_phone_trials.py grant --pool-id POOL_ID --workspace-id WORKSPACE_ID --number OWNED_E164_NUMBER --destination VERIFIED_E164_DESTINATION
```

Repeat `--destination` for up to five approved test numbers. The dispatcher verifies number ownership before enabling calls. The configured workspace maximum is a limit, not a promise that Twilio supplies that many numbers.

6. Enable `PHONE_TRIALS_ENABLED`, restart the API and run a balance check. Enable live calls only for the controlled test:

```sh
uv run python scripts/manage_phone_trials.py check-balances
uv run python scripts/manage_phone_trials.py status
```

7. Verify a real incoming ring at the approved test destination, signed callbacks, speech, interruption, stop, duration enforcement and once-only settlement. Test expiry/low balance and actual email receipt. Invite more users only within the verified account allowance.

## Automatic assignment setup

These settings are now present in private `.env` and `.env.example`; earlier values are preserved:

| Setting | Default / purpose |
| --- | --- |
| `TWILIO_API_KEY`, `TWILIO_API_SECRET` | Blank optional pair; production SDK requests can use this pair with Account SID. Keep `TWILIO_AUTH_TOKEN` for signed callbacks. Both key fields must be provided together. |
| `PHONE_TRIAL_AUTO_ASSIGN_POOL_ID` | Blank; set it to the ID printed by `configure` to expose the offer. |
| `PHONE_NUMBER_PURCHASES_ENABLED` | `false`; leave off to assign only explicitly approved owned stock. |
| `PHONE_NUMBER_MAX_MONTHLY_PRICE_MINOR` | `150` USD cents; maximum accepted quoted US local monthly rental. |
| `PHONE_NUMBER_TOTAL_BUDGET_MINOR` | `1500` USD cents; cumulative reserved rental quotes across all automatic pools, including assigned and uncertain orders. |

For already owned US numbers, approve each specific unused voice number as inventory:

```sh
uv run python scripts/manage_phone_trials.py stock --pool-id POOL_ID --number OWNED_US_E164_NUMBER
```

This performs a read-only ownership/capability check. It does not sweep arbitrary numbers from your carrier account or change their routing. Numbers already registered to a workspace cannot be stocked. Owned stock is reserved when enrollment is accepted, so a second user cannot claim the same remaining number while the first request is queued. The pool's balance check must be fresh before enrollment. Set the pool ID, enable phone trials, restart the API and keep the dispatcher running. A customer then clicks **Start free phone trial**. The page polls actual job progress; there is no source-number picker or customer purchase form.

To allow new rental, explicitly enable `PHONE_NUMBER_PURCHASES_ENABLED` only on an account entitled and funded to acquire the required numbers. A public HTTPS `MEDIA_PUBLIC_ORIGIN` is required. The worker obtains the USD local-number quote, selects US voice inventory without an address requirement, rechecks the pool/budget under a database transaction lock, commits purchase intent, then sends the carrier POST. A valid operator stock number is preferred over a purchase. No new Twilio parent account or fresh promotional balance is created.

Carrier APIs checked against Twilio's official OpenAPI specification:

- Search: `GET /2010-04-01/Accounts/{AccountSid}/AvailablePhoneNumbers/US/Local.json`.
- Rental quote: `GET https://pricing.twilio.com/v1/PhoneNumbers/Countries/US` (SDK `pricing.v1.phone_numbers.countries('US').fetch()`).
- Rent: `POST /2010-04-01/Accounts/{AccountSid}/IncomingPhoneNumbers.json` with the selected number, stable order marker and public voice/status callbacks.
- Reconcile: read the account's incoming numbers using the exact order marker; validate exact number, account and voice capability.
- `POST /2010-04-01/Accounts.json` creates a **subaccount**, not a fresh parent trial account. Its billing is consolidated with the parent.

Quoted rental caps exclude taxes, call usage, setup charges if any, later renewals and price changes. They do not constitute a carrier spending limit. There is no automatic rental release or budget reset. Recent reserved rentals are also deducted conservatively from the last balance observation before another purchase. Do not assume seven-day prorating or a universally current $1 price.

A destination is not silently authorized during number assignment. Approve up to five provider-verified, consenting test destinations before the customer can call:

```sh
uv run python scripts/manage_phone_trials.py destinations --workspace-id WORKSPACE_ID --destination VERIFIED_E164_DESTINATION
```

The number is visible immediately after successful assignment; the call button explains if a verified test destination is still needed. This command does not initiate an OTP or assert that the provider has verified a number. Ordinary carrier trial restrictions still apply. The app's three-call allowance does not permit unrestricted dialing or campaigns.

A durable order and stable carrier marker protect against duplicate charges. HTTP408/429/5xx, connection failures and ambiguous purchase outcomes retain their rental reservation and trigger **read-only reconciliation**. An order in `unknown` is never sent as another purchase. The operator receives a persisted alert through the existing SMTP retry mechanism. Review the carrier console and run:

```sh
uv run python scripts/manage_phone_trials.py status
uv run python scripts/manage_phone_trials.py reconcile --order-id ORDER_ID
```

Reconciliation never purchases a replacement. If it cannot prove one exact number, the order remains pending operator review. Known carrier rejections release the quoted budget reservation but retain the person's/workspace's order; repeated clicks do not create a fresh order. An operator can resolve an unavailable request using an explicitly verified manual grant. Do not delete uncertain orders to force a retry.

The authenticated API is `POST /v1/workspaces/{workspace_id}/phone-trial` with `{}` and valid dashboard CSRF, plus `GET` for status. Existing trial details also appear in bootstrap/summary. Schema additions are `phone_number_orders` and `phone_number_inventory`. Live entitlement/purchase/callback tests still require actual credentials and public hosting.

## Operating and changing credentials

```sh
uv run python scripts/manage_phone_trials.py pause --pool-id POOL_ID
uv run python scripts/manage_phone_trials.py resume --pool-id POOL_ID
uv run python scripts/manage_phone_trials.py revoke --workspace-id WORKSPACE_ID
```

`PHONE_TRIALS_ENABLED=false` is a global pause for trial calls. It does not stop normal browser chat or renew any carrier entitlement. Revoking a workspace preserves its used allowance and prevents self-enrollment into another trial.

After changing a token for the **same** Twilio account in private `.env`, update its captured binding:

```sh
uv run python scripts/manage_phone_trials.py refresh-credentials --pool-id POOL_ID
```

For an explicitly authorized replacement account, configure a new pool with its valid credentials and actual expiry, then assign a newly owned number. Finish or reconcile outstanding calls first. Verify the approved destinations in the replacement account too:

```sh
uv run python scripts/manage_phone_trials.py replace --pool-id NEW_POOL_ID --workspace-id WORKSPACE_ID --number NEW_OWNED_E164_NUMBER
```

Replacement does **not** reset usage, extend the original workspace expiry, transfer the old phone number, create new free credit or automatically change callbacks. Number ownership is verified again. The old binding remains available for delayed callbacks; do not delete it or rotate the stable encryption secret blindly. Rentals continue at the provider until you explicitly release them there; expiry of app access does not cancel a carrier rental.

## What is still needed for launch

As of this cloud implementation, Google OAuth client credentials, SMTP access, the operator email and Twilio credentials/owned numbers are missing. The production `APP_SECRET` must be recovered from the original host. Supabase/Azure/model/speech settings are already supplied, but this cloud cannot reach the supplied database route; the deployment host needs real connectivity and a restricted runtime database login.

The release still needs public deployment/TLS, actual Google sign-in and email delivery, a microphone/widget check on an independent HTTPS site, controlled real carrier calls, connector acceptance, backups/restore and basic monitoring. For collecting payments later, provide the Razorpay webhook secret, validate the existing live keys and implement/accept actual tariffs and reconciliation before enabling checkout. Provider promotional credit does not establish customer pricing.

Local tests and mock provider calls do not establish those live outcomes. No real Twilio account, rental, call or SMTP delivery was created by this implementation.

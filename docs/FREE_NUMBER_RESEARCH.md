# Seven-day automatic phone-number trials

Checked **23 October 2026**. Requirement: a signed-in customer clicks **Start free trial**, the server assigns that customer a dedicated outbound-capable source number without a number picker, and access lasts seven days. The number must connect to Cynerza's own speech/agent runtime. Number rental, telephone minutes and AI processing are separate costs.

## Finding

The inspected official sources do **not** establish a generally available, zero-payment offer that provides ten dedicated outbound numbers to one new SaaS operator. There are useful one-number evaluation offers. A customer-facing seven-day trial can also be funded by an approved carrier balance, promotional agreement or a small paid inventory; the seven-day deadline is then enforced by the SaaS, rather than being the carrier's rental term.

**The most promising additional lead is Telnyx's documented Professional-tier evaluation.** Its official toolkit describes applying through GitHub or LinkedIn identity verification when the freemium one-number limit blocks an operation. Approval is conditional. That source does not establish credit retention after upgrade, eligibility for this resale/demo use, a current multi-number entitlement or a seven-day rental refund. Those points need confirmation in the actual account before presenting this as a free solution. Do not silently submit identity data or run an upgrade while researching.

## Verified comparison

| Provider | What the official source actually says | Fit for our requirement |
| --- | --- | --- |
| **Twilio trial** | One phone number, up to five verified recipients, one subaccount. Subaccounts share the parent's billing balance. The setup guide says trial credit does not carry over on upgrade. | Suitable for one controlled evaluation. The proposed "$15 / $1 = ten user numbers" calculation does not overcome the account's number limit. An upgraded/otherwise approved funded account can support automated rental, subject to its actual allowance and prices. |
| **Telnyx freemium** | Official toolkit describes a one-number limit and $10 credit ceiling; unverified destinations and managed accounts are restricted. | One-number evaluation. Its **conditional Professional upgrade** is worth checking for an early funded pool; not a confirmed ten-free-number offer. |
| **SignalWire trial** | One total phone number, ten verified caller IDs, no international calling/SMS; trial DIDs cannot be released for 30 days. Removing trial mode requires a payment method and at least $5 funding. | Does not supply ten dedicated numbers for free or a seven-day rental cycle. Verified caller IDs are existing numbers, not ten newly issued DIDs. |
| **Vapi current base offering** | One free US number without a saved payment method. It is **inbound only**. Current package table lists 1/5/10/custom numbers for Usage only/Core/Pro/Premier. Calls consume credits. Free numbers reside on Vapi's carrier accounts and cannot be ported out. | A hosted inbound demo, not our requested dedicated outbound pool. Extra numbers under paid packages are not a ten-number free signup offer. Does not provide us a Twilio Account SID/token or establish a direct hand-off to our existing carrier adapter. |
| **Plivo** | Current official integration guide describes rented source numbers and accepted India compliance, with one application per reseller customer. It also notes that a US trial organization may have voice disabled pending access approval. | Our existing company India KYC approval is useful, but is not proof of free customer numbers or unrestricted trial calls. No ten-number zero-payment entitlement was verified. |

The distinction between **free US numbers** and the telephone expression **toll-free numbers** matters: a toll-free number can still have rental and call charges. A free SIP address, a verified existing mobile caller ID and an SMS-receiving website are also not newly allocated programmable PSTN numbers.

## What can explain another platform's seven-day offer

Earlier authenticated Nutaan observations recorded a US trial number, an outbound-only label and application `trialExpires` metadata. The user subsequently reported that its owner described using Twilio. These observations can coexist with several carrier funding arrangements; they do not disclose Nutaan's actual account tier, invoice, credits or allocation implementation.

Plausible designs include a paid/promotion-funded dedicated number inventory, or a caller-ID pool managed by the platform. **Neither is proven to be Nutaan's implementation.** Its customer's account is an account in the SaaS; the platform does not need to open a fresh parent carrier account for every customer. A number-to-workspace mapping plus an entitlement expiry can implement the visible product behavior.

The exact English name/URL of the other platform mentioned by the user is still unconfirmed. Do not identify that service or claim its internal carrier arrangement from phonetics alone.

## Cost and allocation decision

For unique numbers, budget the full quoted rental period unless the carrier explicitly documents prorating. For example, **at a hypothetical $1 monthly rental, ten simultaneous numbers require $10 in number rental**, even if app access ends after seven days. Telephone minutes, AI usage, taxes and any setup fees are additional. This is an illustration, not a live price quote. Deleting the customer's trial entitlement does not cancel a carrier rental.

The practical options are:

1. **Zero-payment evaluation:** use an account's actual single trial number with verified destinations, and keep browser voice available to other users. This does not meet the promise of a dedicated telephone number for every user.
2. **Dedicated numbers for the first users:** obtain an approved account with enough inventory/credit, automatically allocate owned stock or rent within explicit price and total-budget caps, give each workspace seven days, and stop enrollment when stock or budget is exhausted. Users do not select the source number. This meets the requested product flow when funded.
3. **Investigate additional subsidy:** review Telnyx Professional eligibility and ask the carrier to confirm promotional credit retention, multiple-number access, allowed demo use, destinations and rental cancellation. Startup/partner programmes are applications, not guaranteed cash or an entitlement that should be promised in the UI.

Retain Twilio/Plivo for the existing runtime until another provider's call control, signatures and media transport are implemented and accepted. Vapi numbers are not a drop-in carrier credential for that runtime. A US source number also does not establish permission or routing for calls to Indian mobiles; confirm the account's actual geography before offering that test.

## Sources and verification limits

The browser-facing provider documentation domains were blocked by this cloud's network proxy. Official public GitHub documentation and vendor-authored skills were reachable and inspected directly. Consequently these findings are documentary evidence, **not** live account entitlement, available-inventory, checkout or telephone acceptance tests. No account was created, upgrade submitted, number purchased or call placed.

- **Twilio account setup skill**, installed at the user's request from `twilio/ai`: [source](https://github.com/twilio/ai/blob/803790a281f0ef11d2928ffb41bc8422237fb434/skills/twilio/twilio-account-setup/SKILL.md), especially Accounts/Subaccounts, Upgrade from Trial and Trial Restrictions. [Number selection skill](https://github.com/twilio/ai/blob/803790a281f0ef11d2928ffb41bc8422237fb434/skills/twilio/twilio-numbers-senders/SKILL.md).
- **Telnyx freemium/Professional evaluation**: [official toolkit source](https://github.com/team-telnyx/telnyx-toolkit/blob/0c752ffbcc141c0311175c79c169b9e31a19d4db/getting-started/telnyx-freemium-upgrade/SKILL.md), particularly Heuristic Triggers, Proactive Upgrade and outcomes. This is a July 2026 toolkit checkpoint, so account confirmation remains necessary. [Official number guide](https://github.com/team-telnyx/ai/blob/c53048dc1ed16d7ee9b1af1ef9a144b9b655989d/guides/phone-numbers.md).
- **SignalWire trial mode**: [published route](https://developer.signalwire.com/docs/platform/trial-mode), [official source](https://github.com/signalwire/docs/blob/c0c5b2c641027b04021f2db28ba7ddcd65ebc85a/fern/products/platform/pages/platform/setup/trial-mode.mdx). [Trial credit expiry source](https://github.com/signalwire/docs/blob/c0c5b2c641027b04021f2db28ba7ddcd65ebc85a/fern/products/platform/changelog/2025-04-18.mdx) describes expiration after 90 days for Spaces still in trial mode, not an unlimited renewable credit.
- **Vapi free numbers**: [published guide](https://docs.vapi.ai/free-telephony), [official source](https://github.com/VapiAI/docs/blob/4a76e45eba69dc702514c65baf4b729a7daae094/fern/phone-numbers/free-telephony.mdx). [Current package limits](https://docs.vapi.ai/billing/pricing-and-success-packages), [official source](https://github.com/VapiAI/docs/blob/4a76e45eba69dc702514c65baf4b729a7daae094/fern/billing/pricing-and-success-packages.mdx). Legacy customers can have different terms; do not promise those to a new account.
- **Plivo current carrier/runtime guidance**: [official source](https://github.com/plivo/plivo-cli/blob/ca8157cc91da571b7067b4e2f427e2ca7c1316e4/audio-streaming-skill/SKILL.md), India compliance and Outbound sections; [published India rental guide](https://www.plivo.com/docs/numbers/rent-india-numbers).
- [Earlier Nutaan/India investigation](INDIA_NUMBERS_RESEARCH.md) separates captured UI evidence, the later owner report and unverified private billing arrangements.

Additional official Bolna integration skills, Bland cookbook examples, Exotel examples and Twilio's startup resource repository were inspected. They did not establish a current qualifying multi-number zero-payment offer. Older example repositories are not current pricing evidence; their absence of a price does not mean numbers are free. No current exact credit award for a startup programme is claimed here.

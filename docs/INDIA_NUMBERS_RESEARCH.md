# Nutaan trials and Indian telephone numbers

Researched **22 October 2026** using the user's screenshots, the earlier authenticated Nutaan inspection and current official provider documentation. This is research; no number was purchased, call placed, provider account created or compliance application submitted.

## What the Nutaan evidence establishes

| Observation                                               | Evidence and boundary                                                                                                                                                                                                                                                                        |
| --------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| The displayed trial is a US line                          | +1 6202990133, outbound-only. Earlier account UI identified Telnyx. This is not a seven-day Indian-number offer.                                                                                                                                                                             |
| India searches target Plivo                               | Captured `Dashboard.js:32448` maps IN to plivo; other supported countries to telnyx. The search sends provider/country/type; purchase sends provider/number. This identifies the client integration, not a recovered private backend or last-mile carrier contract.                          |
| Actual Indian inventory was previously returned           | `india-number-requirement.txt` records +9180655… fixed-line Bengaluru results after an India search. The Mobile selector alone does not establish mobile inventory. Availability may change.                                                                                                 |
| The India flags beside US numbers are a display/state bug | Country selection changes the selected country/type without clearing existing rows or searching. The flag helper prioritizes selected country over the number prefix. Old US results therefore acquire India flags. Use India/Fixed, clear the US212 area-code filter and explicitly search. |
| Seven days is represented by application metadata         | The client requests `/api/voice/numbers/trial`, displays `trialExpires`, and labels trial access outbound-only/removed on top-up. The private allocation and billing logic was not recovered.                                                                                                |
| The displayed $11.76 is a wallet threshold                | The captured client formats a minimum balance of₹1,000. It is not the quoted monthly rental price of an Indian number.                                                                                                                                                                       |

Local evidence: `/home/hara/nutaan-investigation/formatted/Dashboard.js` at line 32448 (provider selection), 32458 (flag precedence), 32627 (country change), 32936 (trial request), 33240 (expiry); `/home/hara/nutaan-investigation/outbound-attempt.txt` at line 56; `/home/hara/nutaan-investigation/india-number-requirement.txt`.

## How a trial can work

Update, 23 October 2026: the user reports that Nutaan's owner described using Twilio for its outbound trial numbers. Treat this as newer owner-reported information; the earlier captured Telnyx client label does not establish Nutaan's current carrier or commercial terms. The suggested $15 credit/$1 rental arithmetic has not been verified against the user's Twilio account. Browser-facing Twilio documentation access is blocked from this cloud. On 23 October the official Twilio skills were installed and inspected: their account-setup guide lists one number for a trial account. Actual account eligibility remains unverified; see the newer [provider comparison](FREE_NUMBER_RESEARCH.md).

The platform can fund carrier rental and call usage, allocate access to a number for seven days, impose a usage budget and revoke access at expiry. A pre-provisioned number pool is another possible implementation. Neither exclusive ownership nor a shared pool is proven by these screenshots. Nutaan's exact carrier bill is unknown.

Telnyx's own account trial is distinct: its current documentation limits number ordering to one local number over the trial account's lifetime, restricts voice traffic to a verified destination/source, and describes number reclamation within 30 days unless upgraded. It does not establish an unlimited seven-day number supply for SaaS customers. [Telnyx trial documentation](https://developers.telnyx.com/docs/account-setup/levels-and-capabilities/trial).

## Published carrier economics

| Item                                  | Current published rate                                                      |
| ------------------------------------- | --------------------------------------------------------------------------- |
| Telnyx local number                   | From US$1/month; volume tiers available                                     |
| Plivo India domestic number           | ₹200/month                                                                  |
| Plivo India domestic inbound/outbound | ₹0.38/min each; 30-second billing pulse; audio streaming listed as included |

These are public base rates, not evidence of Nutaan's negotiated costs. AI inference, speech providers and applicable extras are separate. Sources: [Telnyx numbers](https://telnyx.com/pricing/numbers), [Plivo India pricing](https://www.plivo.com/voice/pricing/in/).

## Obtaining Indian numbers for our platform

Plivo requires an India-data-region organization and accepted compliance. Its accepted business-document alternatives are GST, incorporation or Udyam certification. The documented reseller flow creates a customer subaccount, submits that customer's compliance application, then rents numbers linked to that approved application. GST is not the only accepted document. [Plivo India KYC and reseller APIs](https://www.plivo.com/docs/numbers/rent-india-numbers).

Plivo's India route documentation also requires India-registered businesses and domestic media anchoring. Fixed service/transactional numbers, promotional140-series and BFSI160-series are separate products/use cases. Provider approval must match the intended traffic. [Plivo India calling](https://www.plivo.com/docs/voice/concepts/india-calling).

Exotel offers another documented path: its licensed virtual-network infrastructure connects a Voice AI platform's SIP trunk to Indian PSTN, with DID mapping and KYC. This is an alternative, not proof that Exotel issued the numbers in these screenshots. [Exotel vSIP integration](https://support.exotel.com/support/solutions/articles/3000133452-flow-and-api-configuration-guide-for-voice-ai-contact-centre-platforms-via-exotel-virtual-sip-trunk).

Recommended product approach: retain instant browser voice as the first experience; fund any telephone demo from an approved carrier account with verified test destinations and explicit expiry/budget; provision dedicated +91 numbers through a proper customer-specific reseller/KYC flow. Keep rental, call usage and AI usage separately accounted for. The existing platform has owned-number registration and call adapters; this research does not implement automated rental or customer KYC.

The exact underlying Indian network operator and Nutaan's commercial agreement remain unverified. Do not infer Airtel/Jio/BSNL ownership, SIM capability, exclusive trial ownership or regulatory approval from a flag or frontend provider label.

## Finding PLIVO_CALLER_ID

This is the rented source telephone number, not the Plivo Auth ID or Auth Token. The Home screen's credentials and trial credit do not identify it. Use the Phone Numbers sidebar or Buy Phone Number card, then copy the approved/rented number in E.164 format into PLIVO_CALLER_ID. For the shown India organization, Plivo's domestic caller-ID rule requires a Plivo-rented Indian number; an arbitrary personal mobile is not a substitute. If the number list is empty, complete KYC and rental first. [Plivo source-number requirements](https://www.plivo.com/docs/voice/concepts/india-calling).

The user subsequently supplied a Plivo console screenshot showing Cynerza Systems Private Limited's Local-number KYC as Approved in the India data region. Do not ask the user to repeat that company approval. Approval is separate from number rental and from individual reseller customers' applications.

For the multi-tenant product, store each purchased number against its workspace and select it for that call; do not rewrite a global environment variable per customer. An environment caller ID can be a platform demo/default number. The current worker reads workspace-owned `number_id` and uses its E.164 value/provider; the expanded beta removed the old mandatory global caller-ID readiness check. As of 23 October, [phone trial entitlement, expiry, budget limits and alerts](PHONE_TRIALS.md) are implemented through explicit operator assignment. The subsequent update adds one-click seven-day assignment and optional budget-capped Twilio rental, disabled by default; see [current setup](PHONE_TRIALS.md). Provider subaccount creation and customer-specific KYC remain outside this implementation.

Proposed trial design: use an approved paid carrier account to fund a small US outbound-demo number pool, verify each customer's test destination, grant seven-day access with a bounded minute/credit allowance, bind every call to its own workspace/agent, and revoke trial access at expiry. Whether a number may be shared is subject to the carrier's approved configuration; unique inbound numbers need dedicated allocation. A paid customer's purchased number replaces the demo source for that customer's calls. This is a proposed platform design, not a claim about Nutaan's private implementation.

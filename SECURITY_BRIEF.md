# SquadPay — Payments Security & Compliance Brief

**For:** Investors · Partners · Regulators · Insurance underwriters
**From:** NueveTech LLC, makers of SquadPay
**Last updated:** June 2025
**One-line summary:** *SquadPay never touches, transmits, or stores customer card data — Stripe does.*

---

## Why this matters

A single line of due-diligence usually decides whether a fintech-adjacent
app is fundable, partnerable, or insurable: **"Do you handle cardholder
data?"** For SquadPay the answer is a clear, defensible **no.** This brief
explains exactly why, in terms that compliance officers, technical
reviewers, and non-technical stakeholders can all verify in a single
read-through.

---

## 1. We are a software facilitator, not a money-services business

| Concern | SquadPay's posture |
|---|---|
| Do you take possession of customer funds? | **No.** Funds move within Stripe's regulated payment system (a licensed Money Transmitter / E-Money Institution depending on jurisdiction). |
| Do you store card numbers (PAN), CVV, or expiry? | **No.** Card data is captured by Stripe's PCI-DSS Level-1 certified UI components and tokenised before it reaches our servers. |
| Do you require a Money Transmitter License? | **No** — we never take custody of customer money. |
| What is your PCI-DSS scope? | **SAQ-A** (the lowest possible tier — "outsourced e-commerce"). |
| Could a breach of your servers expose card data? | **No.** Even with full backend compromise, an attacker would obtain zero card numbers — they never reach us. |

---

## 2. The Cardholder-Data Flow

```
   Customer's phone           Stripe (PSP)              SquadPay
   ──────────────────         ─────────────             ────────
   1. Opens app
   2. Taps "Pay $X"
   3. Stripe iframe   ───►    Captures raw
      renders (NOT             card #, CVV
      our code)                in PCI vault
                               │
                               ▼
                          Returns one-time
                          payment_method_id
   4. App passes the   ───────────────────────►   Backend receives
      TOKEN to backend                            only the TOKEN
                                                  (e.g. pm_1Q3xRk…)
                          ◄─────────────────────  5. Backend calls
                          Stripe charges card        Stripe with the
                                                     token to confirm
                                                     the payment
```

**Plain English:** the raw card number travels directly from the customer's
phone to Stripe's PCI vault, via an encrypted channel. SquadPay only ever
sees an opaque reference — like a check number, not the bank account
itself.

---

## 3. The Funds-Flow

```
Member's card → Stripe PaymentIntent → Stripe Platform Balance → Stripe Issuing Card → Merchant
                                       (held inside Stripe,
                                        not in any SquadPay account)
```

- **No SquadPay bank account holds customer money.** The "wallet" you see
  in our UI is a *display abstraction* over Stripe's ledger.
- **Settlement is automatic.** When the Lead pays the merchant with our
  virtual card, the same Stripe balance is debited — no manual transfer,
  no float, no commingling.
- **Refunds and chargebacks** are handled natively by Stripe with full
  consumer-protection rules; we mirror status via webhook.

---

## 4. What We Do Store

To run the product we keep the following business metadata in our database
(MongoDB):

- User name + phone number (verified via OTP)
- Bill metadata: items, taxes, tip, totals, splits, status
- Stripe object IDs as opaque references (e.g. `pi_3Q3xRk`, `ic_1Q3xRkABC`)
- Per-member contribution amounts (mirroring Stripe's ledger)
- Audit log of administrative actions

None of this is **cardholder data** under PCI definitions, **personal
financial information** under GLBA, or **payment account information**
under PSD2.

Sensitive third-party API keys we hold (Stripe secret key, OpenAI key,
Twilio token) are encrypted at rest with an envelope-encryption scheme
backed by a hardware-rooted KMS master key.

---

## 5. What Would Happen in a Worst-Case Breach

| Threat | Blast radius |
|---|---|
| Backend fully compromised | Attacker sees phone numbers + bill metadata. **No card data exposed.** Stripe object IDs are useless without our Stripe secret key. |
| Stripe secret key leaked | Attacker can issue API calls in our name. **Mitigated by:** envelope-encryption at rest, IP allowlist, immediate revocation via Stripe Dashboard, alerts on unusual volume. Stripe still refuses card-data-access scopes our integration doesn't have. |
| Customer phone stolen | Attacker faces phone-OTP + Stripe biometric reveal gate on the card. **Card number is never visible without Stripe's ephemeral-key flow.** |
| Insider threat | Audit log records every admin action. No employee has direct access to Stripe vault data. |

---

## 6. Regulatory & Standards Posture

| Framework | Status |
|---|---|
| PCI-DSS | **SAQ-A** (lowest tier — outsourced payments) |
| GDPR / CCPA | User PII (phone + name) honoured via export & delete endpoints |
| GLBA (US) | Out of scope — we are not a "financial institution" |
| PSD2 (EU) | Stripe handles SCA via 3DS2 on every PaymentIntent |
| BSA / AML | Stripe's KYB onboarding covers issuance; we add phone-OTP for ad-hoc use |
| SOC 2 | Roadmap (Q4 2025); foundational controls already in place |

---

## 7. Independent Verification

A reviewer can verify every claim in this brief without trusting our word
for it:

1. **Open the SquadPay app in iOS or Android.** Navigate to *"Contribute
   your share"*. Inspect the network — the only request hitting our
   backend is `POST /api/groups/{id}/contribute` with `{ "amount": X }`.
   The card data goes directly from the device to `api.stripe.com`.
2. **Decompile our app.** No Stripe-secret-key, no card-number-handling
   code, no plaintext PAN ever appears.
3. **Audit our backend.** `git log --all -p | grep -iE 'card_number|pan|cvv'`
   returns zero results.
4. **Stripe support letter.** Available on request — Stripe will confirm
   the type of API access SquadPay's account is provisioned for (charges
   + issuing, *not* raw card-data access).

---

## 8. The bottom line

> **SquadPay coordinates who owes what. Stripe moves the money.**
> *We are a software layer over a regulated payments rail.*
> *We never touch, transmit, or store a customer card.*

Contact for security disclosures or compliance questions:
**security@squadpay.us**  (PGP key on request)

---

*This brief is a plain-English summary of SquadPay's data and money flows.
For a deeper technical specification — including database schema, API
contracts, and end-to-end code paths — see the full application
documentation available to vetted technical reviewers under NDA.*

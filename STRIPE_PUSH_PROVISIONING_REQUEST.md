# Stripe Push Provisioning — Enablement Request

> **How to send:** Copy the body below into an email, fill in the four `[BRACKETED]` fields, and send to your Stripe Account Executive (preferred) or to `issuing-support@stripe.com`. If you don't have an AE assigned yet, open a ticket from the Stripe Dashboard → Support → Issuing → "Request Push Provisioning enablement".
>
> **What you'll need before sending:**
> 1. Your Stripe Account ID — find it at Dashboard → Settings → Account details (looks like `acct_1Q…`)
> 2. Your card-art design (PNG, 1536×969 px, ≥300 DPI) — Stripe needs this for the digital wallet card face
> 3. Your brand logo (PNG with transparent background, ≥1024×1024)
> 4. A short demo video or screenshots of the SquadPay "Add to Apple/Google Wallet" flow in-app
>
> Attach all of the above to the email.

---

**To:** issuing-support@stripe.com  *(cc your Stripe AE if you have one)*
**Subject:** Push Provisioning enablement request — SquadPay by NueveTech (Stripe Issuing — [YOUR_STRIPE_ACCOUNT_ID])

---

Hi Stripe Issuing team,

We'd like to request **Push Provisioning** enablement for our Stripe Issuing program so our users can add their virtual cards to Apple Wallet and Google Wallet directly from inside the SquadPay app.

### 1. Account details

| Field | Value |
|---|---|
| Legal entity | NueveTech LLC *(or your registered legal name)* |
| Stripe Account ID | `[YOUR_STRIPE_ACCOUNT_ID]` |
| Product name | SquadPay |
| Production domain | https://squadpay.us |
| App Store / Play Store bundle IDs | iOS: `com.squadpay.app` · Android: `com.squadpay.app` |
| Apple Team ID | 4JXHW2G4T7 |
| Android signing cert SHA-256 | `40:57:51:BC:31:36:3A:DB:13:CA:85:55:BA:26:59:C1:B9:94:0B:5A:CA:85:CA:38:EA:F7:DD:E4:1D:65:03:1F` |
| Primary contact | [YOUR_NAME], [YOUR_EMAIL], [YOUR_PHONE] |

### 2. Use case

SquadPay is a group-payment app for restaurants, group activities, and shared expenses. When a group of friends opens a tab:

1. A **Lead** starts the bill and invites members via SMS / QR / Universal Link.
2. Each member contributes their share via Stripe PaymentIntents — funds settle into the platform balance.
3. Once the bill is 100% funded, we **auto-issue a one-time virtual card** via Stripe Issuing, with a spending limit equal to the bill total.
4. **Push Provisioning** lets the Lead tap "Add to Apple/Google Wallet" and pay the merchant at the POS via NFC — no need to share PAN/CVV verbally with the server.

Push Provisioning is critical to our UX because typing a 16-digit number into a card reader is *not* an option in a busy restaurant — the Lead needs the card on their phone, ready to tap.

### 3. Volume & risk profile

| Metric | Estimate (first 12 months) |
|---|---|
| Active users | [E.G. 5,000] |
| Active bills / month | [E.G. 2,000] |
| Avg bill size | [E.G. $80] |
| Expected gross volume / month | [E.G. $160,000] |
| Cards issued / month | Equal to bills, so [E.G. 2,000] |
| Geographies | United States (USD only) |
| Card lifespan | Single-use — auto-disabled within 24 h of merchant settlement |
| Spend cap | Hard-limited to the bill total at issuance time |

### 4. Compliance posture

- **PCI-DSS scope:** SAQ-A — we never touch, transmit, or store cardholder data. All card-data UI is rendered by Stripe Elements / PaymentSheet inside our app.
- **KYC:** Every user must verify their phone via OTP before joining or creating a bill. Lead identity is verified at first card issuance via Stripe Identity (planned for production).
- **Fraud controls:** Hard per-card spend cap, single-merchant settlement window, automatic 24h disable, server-side `is_blocked` flag on suspicious accounts.

### 5. Assets attached

- `card_art.png` — Wallet card face design (1536×969 px)
- `brand_logo.png` — SquadPay logo (transparent, 1024×1024)
- `wallet_flow.mp4` — Screen recording of the "Add to Apple/Google Wallet" flow in-app (currently stubbed; we want to wire the live `stripe.issuing.Card.create_push_provisioning_data(...)` call once enablement is granted)
- `app_store_listings.pdf` — App Store + Play Store screenshots

### 6. Technical readiness on our side

We've already scaffolded the integration end-to-end:

- **Backend** endpoint `POST /api/cards/{group_id}/provision` (FastAPI) is live and currently returns `pending_psp_approval`. The day enablement lands, we swap the stub body for `stripe.issuing.Card.create_push_provisioning_data(…)` — no other code changes needed.
- **iOS** native shim is ready to feed the returned payload into `PKAddPaymentPassRequestConfiguration` / `PKAddPaymentPassRequest`.
- **Android** native shim is ready to feed it into `PushTokenizeRequest` via the Tap & Pay SDK.
- **App entitlements** — we have not yet requested `com.apple.developer.payment-pass-provisioning` (iOS) or the Google `PUSH_PROVISIONING_PRIVILEGED` permission, since we understand those come *after* Stripe + the card networks (Visa VDEP / Mastercard MDES) co-sign. Please let us know the next step once Stripe approves on its side.

### 7. Asks

1. Please enable Push Provisioning on Stripe Account `[YOUR_STRIPE_ACCOUNT_ID]` for both Apple Pay and Google Pay.
2. Please relay our program details to Visa (VDEP) and Mastercard (MDES) for card-network sign-off.
3. Please share the next steps for requesting the iOS / Android wallet entitlements from Apple and Google.
4. If you need anything else (additional docs, a call, a sandbox demo), please let us know.

Thanks very much — happy to jump on a call any time.

Best,
[YOUR_NAME]
[YOUR_TITLE], NueveTech
[YOUR_EMAIL]
[YOUR_PHONE]
https://squadpay.us

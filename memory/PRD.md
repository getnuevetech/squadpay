# GroupPay — Product Requirements (MVP)

## Problem
At group meals, one person pays upfront and others delay repayment; or
everyone tries to split at checkout and it slows things down. Lead ends
up chasing everyone. GroupPay solves this by letting the lead pay
instantly while the system automatically tracks who owes what and
collects repayments.

## MVP Scope (delivered)
1. **Identity**: Fast name-only join. Phone + mocked OTP (code `123456`)
   required before paying or being owed money.
2. **Group creation**: Lead enters a total (or scans a receipt via
   OpenAI GPT-4o OCR) and picks a split mode.
3. **Join flow**: 8-character code + shareable deep link +
   on-screen QR code.
4. **Split modes**: Fast (equal), Smart (itemized with auto-claim),
   Itemized (per-item self-claim with quantity selectors).
5. **Item assignment**: Real-time self-claim with live per-user totals.
6. **Summary**: Per-person breakdown (food / tax+tip / total).
7. **Funding modes (NEW)** — three scenarios from Stage 5 of the spec:
   - **Group-funded** — every member contributes their share via
     `POST /api/groups/{id}/contribute` before checkout; once total
     contributions meet the bill total the group auto-finalizes
     (`status='paid'`, `funding_mode='group'`, `lead_shortfall=$0`).
   - **Lead-funded** — no one contributes; lead taps Pay → covers full
     bill (`funding_mode='lead'`).
   - **Shortfall** — some members contribute, lead taps Pay → covers
     only the remaining shortfall (`funding_mode='shortfall'`,
     `lead_shortfall=remaining`). Members who already contributed don't
     owe the lead anything.
8. **Repayment**: Members repay their `outstanding` (= share − contributed
   − repaid). Group auto-closes when every non-lead member has
   `outstanding ≤ 0`.
9. **Lead dashboard**: Progress bar, member list with outstanding
   balances, instant/standard withdraw options (simulated).

## Architecture
- **Backend**: FastAPI + MongoDB (motor, async). All mutations are
  single-document updates on `groups`. No ObjectIDs returned.
- **Frontend**: Expo Router (SDK 54) + React Native, lucide-react-native
  icons, react-native-qrcode-svg for QR codes.
- **Integrations**:
  - OpenAI GPT-4o via EMERGENT_LLM_KEY + `emergentintegrations` for
    receipt OCR (`POST /api/receipt/scan`).

## API Surface
Auth: `/auth/register`, `/auth/send-otp`, `/auth/verify-otp`
Users: `/users/{id}`, `/users/{id}/groups`
Groups: `/groups` (POST), `/groups/{id}` (GET), `/groups/by-code/{code}`,
        `/groups/{id}/join`, `/groups/{id}/items` (PUT),
        `/groups/{id}/assign`, `/groups/{id}/contribute`,
        `/groups/{id}/pay`, `/groups/{id}/repay`
OCR: `/receipt/scan`

## Business Enhancement
**Instant Withdraw Fee (1.5%)** — the lead can cash out immediately
with a small percentage fee, or wait 1–2 business days for free.
This creates a natural revenue stream per bill without taxing the
core use case (splitting itself is free).

## Deferred / Not in MVP
- Real Stripe virtual card issuing (mocked)
- Real Twilio SMS OTP (mocked `123456`)
- Push notifications / automated reminders
- Merchant-side integration

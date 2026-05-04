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
7. **Payment (mocked)**: Lead-funded flow — lead pays the full bill
   upfront, system flips to "repaying" and tracks balances.
8. **Repayment**: Members repay via in-app button; repayments are
   tracked; group auto-closes when fully settled.
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
        `/groups/{id}/assign`, `/groups/{id}/pay`, `/groups/{id}/repay`
OCR: `/receipt/scan`

## Business Enhancement
**Instant Withdraw Fee (1.5%)** — the lead can cash out immediately
with a small percentage fee, or wait 1–2 business days for free.
This creates a natural revenue stream per bill without taxing the
core use case (splitting itself is free).

## Deferred / Not in MVP
- Real Stripe virtual card issuing (mocked)
- Real Twilio SMS OTP (mocked `123456`)
- Shortfall / group-funded modes (currently only lead-funded)
- Push notifications / automated reminders
- Merchant-side integration

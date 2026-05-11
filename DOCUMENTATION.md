# SquadPay by NueveTech — Application Documentation

> **Mission:** SquadPay turns the awkward end-of-meal moment of splitting a bill into a smooth, fair, fully-funded payment everyone can settle in seconds — even when half the table doesn't carry cash.

---

## ⚖️ Trust & Compliance Posture (READ FIRST)

**SquadPay is a software orchestration layer — not a money-services business or a card processor.**

- **No customer card data ever touches SquadPay servers.** Members enter their card details directly into Stripe's PCI-DSS Level-1 certified payment sheet (Stripe Elements / PaymentSheet SDK), and Stripe returns a one-time `payment_method_id`. The raw PAN (Primary Account Number), CVV, and expiry **never traverse our infrastructure, never appear in our logs, and never persist in our database.**
- **No customer funds are held by SquadPay.** Contributions move *within Stripe's regulated payment system* — from the contributing member's funding source into a Stripe-managed connected account. SquadPay only orchestrates the metadata (who contributed what, against which bill) — the actual money lives entirely inside our payment partner's regulated ledger.
- **No virtual-card PANs are stored.** The virtual cards issued at bill settlement are created by **Stripe Issuing** and live inside Stripe's vault. Card numbers are revealed to the Lead via Stripe's secure, ephemeral-key-protected reveal flow — they're rendered client-side inside an iframe (web) / native secure element (mobile) and **never round-trip through SquadPay's backend**.
- **PCI-DSS scope is minimised to SAQ-A.** Because we never touch, transmit, or store cardholder data, our PCI scope is the lowest possible (Self-Assessment Questionnaire A — outsourced e-commerce). All sensitive payment surfaces are rendered by Stripe-hosted UI components inside our app.
- **What SquadPay *does* store:** user phone numbers, bill metadata (items, splits, status), Stripe object IDs (e.g. `pi_…`, `ic_…`), and per-member contribution amounts. None of this is cardholder data under PCI definitions.

In one line: **SquadPay helps friends *coordinate* who owes what — Stripe *actually moves* the money. We never hold, see, or store a customer card.**

---

## Table of Contents

1. [Trust & Compliance Posture](#️-trust--compliance-posture-read-first)
2. [Overview](#overview)
3. [Tech Stack](#tech-stack)
4. [Repository Layout](#repository-layout)
5. [Core Concepts](#core-concepts)
6. [User Roles](#user-roles)
7. [Key Features](#key-features)
8. [End-to-End User Flows](#end-to-end-user-flows)
9. [Architecture](#architecture)
10. [Money Movement & Custody Model](#money-movement--custody-model)
11. [Backend API Reference](#backend-api-reference)
12. [Frontend Routes](#frontend-routes)
13. [Database Schema](#database-schema)
14. [Bill Math & Fees](#bill-math--fees)
15. [Admin Dashboard](#admin-dashboard)
16. [Integrations](#integrations)
17. [Deep Linking](#deep-linking)
18. [Non-Functional Requirements](#non-functional-requirements)
19. [Error Handling & Edge Cases](#error-handling--edge-cases)
20. [Environment Variables](#environment-variables)
21. [Deployment](#deployment)
22. [Testing](#testing)
23. [Security & Privacy](#security--privacy)
24. [Roadmap / Backlog](#roadmap--backlog)
25. [Glossary](#glossary)

---

## Overview

SquadPay is a **group payment system** for restaurants, group activities, and shared expenses. One person — the **Lead** — starts a bill (either by scanning a receipt or typing the total). They invite friends via QR or a short 8-character code. Each member contributes their share via Stripe; once the bill is fully funded, the Lead can pay the merchant with a one-time **Virtual Card** that's auto-issued via Stripe Issuing.

Built by **NueveTech** as a mobile-first cross-platform app (iOS, Android, Web).

### Why it's different
- **No IOUs** — money lands in a SquadPay-controlled wallet before the bill is paid.
- **Itemized splits** — receipt OCR extracts line items, members claim what they ordered, unclaimed items become a transparent "shortfall".
- **Auto-issued virtual card** — no Lead has to front the bill out-of-pocket.
- **Real-time math** — every contribution updates everyone's dashboard instantly.

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Mobile + Web frontend** | Expo SDK 51+ · React Native 0.74+ · Expo Router (file-based routing) · TypeScript |
| **Backend API** | FastAPI (Python 3.11) · Motor (async MongoDB driver) · Pydantic V1 |
| **Database** | MongoDB |
| **AI / OCR** | OpenAI GPT-4o vision (via Emergent LLM key) |
| **Payments** | Stripe (PaymentIntents, Issuing, Ephemeral Keys) |
| **SMS / OTP** | Twilio + SignalWire (multi-provider failover) |
| **Auth** | Custom OTP-based (no passwords for end users) + JWT for admin |
| **Web Hosting** | Vercel (Expo `dist/` static export) |
| **Mobile Builds** | EAS Build (Expo Application Services) |
| **Native UI** | react-native-gesture-handler · react-native-reanimated · lucide-react-native (icons) |

---

## Repository Layout

```
squadpay/
├── frontend/                        # Expo Router app (iOS / Android / Web)
│   ├── app/                         # File-based routes
│   │   ├── index.tsx                # Home screen (FeaturedBillCard)
│   │   ├── auth.tsx                 # OTP-based signup / signin
│   │   ├── create.tsx               # Create bill (scan or manual)
│   │   ├── join/[code].tsx          # Join via 8-char code or QR
│   │   ├── activity.tsx             # Past bills feed
│   │   ├── squad.tsx                # Friends / past collaborators
│   │   ├── settings.tsx             # User settings
│   │   ├── group/[id]/              # Per-bill screens
│   │   │   ├── index.tsx            # Lobby (QR, invite, members list)
│   │   │   ├── dashboard.tsx        # LEAD Dashboard
│   │   │   ├── summary.tsx          # USER Dashboard (non-leads)
│   │   │   ├── items.tsx            # Item list + claim/assign UI
│   │   │   ├── pay.tsx              # Pay flow (contribute / repay / lead-pay)
│   │   │   ├── card.tsx             # Virtual card display
│   │   │   └── success.tsx          # Post-payment confirmation
│   │   └── admin/                   # Web-only admin console
│   │       ├── _layout.tsx          # Sidebar nav
│   │       ├── dashboard.tsx        # Metrics tiles
│   │       ├── users.tsx
│   │       ├── groups.tsx
│   │       ├── admins.tsx
│   │       ├── platform-fees.tsx    # Admin-configurable extra fees
│   │       ├── integrations.tsx     # Twilio / Stripe / SignalWire creds
│   │       └── ...
│   ├── src/                         # Non-route code
│   │   ├── api.ts                   # End-user API client
│   │   ├── adminApi.ts              # Admin API client
│   │   ├── session.ts               # User session storage
│   │   ├── theme.ts                 # COLORS, FONT, SPACING, RADIUS tokens
│   │   ├── Button.tsx
│   │   ├── StatusBadge.tsx
│   │   ├── EditMetaModal.tsx
│   │   ├── RevealCardModal.tsx
│   │   ├── components/
│   │   │   ├── redesign/
│   │   │   │   ├── FeaturedBillCard.tsx
│   │   │   │   └── BottomTabBar.tsx
│   │   │   ├── NewBillSheet.tsx
│   │   │   ├── EmptyState.tsx
│   │   │   ├── Skeleton.tsx
│   │   │   ├── Toast.tsx
│   │   │   └── AvatarRing.tsx
│   │   └── ...
│   ├── public/.well-known/
│   │   ├── apple-app-site-association
│   │   └── assetlinks.json
│   ├── app.json                     # Expo config (scheme, intentFilters, associatedDomains, permissions)
│   ├── vercel.json                  # Vercel rewrites + headers
│   ├── package.json
│   ├── yarn.lock
│   └── eas.json                     # EAS build profiles
├── backend/
│   ├── server.py                    # FastAPI entry point
│   ├── core.py                      # Bill math + recompute logic
│   ├── admin_routes.py
│   ├── admin_integrations.py
│   ├── issuing.py                   # Stripe Issuing wrapper
│   ├── crypto_kms.py                # KMS for sensitive field encryption
│   ├── reminders.py                 # Background SMS reminder loop
│   ├── sms_providers.py             # Twilio + SignalWire abstraction
│   ├── routes/
│   │   ├── auth_routes.py
│   │   ├── groups_routes.py
│   │   ├── pay_routes.py
│   │   ├── contribute_routes.py
│   │   ├── misc_routes.py           # OCR + referrals + credits
│   │   ├── legal_routes.py
│   │   ├── admin_platform_fees.py   # Admin-configurable extra fees
│   │   └── ...
│   ├── .env                         # MONGO_URL, DB_NAME, secrets
│   └── requirements.txt
├── DOCUMENTATION.md                 # ← this file
└── README.md
```

---

## Core Concepts

### Bill / Group
A single restaurant tab or shared expense. Has one Lead, ≥1 member, items, tax/tip, fees, and a status (`open` → `paid` → `closed`).

### Lead
The user who created the bill. Holds the burden of paying the merchant. Cannot remove themselves; can remove non-contributing members; can edit tax/tip.

### Member
Any non-lead user in the group. Joins via 8-char code or QR. Contributes their share to the SquadPay wallet, after which their dashboard shows "Contributed".

### Wallet
Per-bill virtual escrow. Members contribute → wallet balance grows → Lead settles merchant from wallet.

### Virtual Card
Auto-issued Stripe Issuing card once the wallet is fully funded. Lead reveals card details to charge at the restaurant.

### Shortfall
The gap when items + tax + tip > what members have actually claimed. Lead decides who absorbs it.

---

## User Roles

| Role | Capabilities |
|---|---|
| **Anonymous** | Browse landing page, sign up |
| **Member** | Join bill, claim items, contribute, repay lead, view User Dashboard |
| **Lead** | All Member capabilities + create bill, scan receipt, edit tax/tip, assign items, remove non-contributing members, reveal virtual card, settle merchant |
| **Admin** | Read access to users / groups / metrics / audit log |
| **Super Admin** | All Admin + reassign group leads, configure platform fees, manage admins, block users/groups |

---

## Key Features

### 1. Bill Creation
- **Receipt scanning** — OpenAI GPT-4o vision OCR extracts items, tax, tip, total. Smart reconciliation: if items+tax+tip ≠ total, the difference is absorbed into tax (handles multi-tax receipts like Sales Tax + Alcohol Tax).
- **Manual entry** — type the total directly.
- **Editable** — Lead can adjust tax/tip after creation.

### 2. Invite & Join
- **8-char code** (e.g. `ABC12345`) shareable via SMS/WhatsApp
- **QR code** with the same code embedded as a deep link `https://squadpay.us/join/<code>`
- **Custom URL scheme** `squadpay://join/<code>` as fallback

### 3. Splitting Modes
- **Fast split** — equal split across all members (no items)
- **Itemized** — members claim individual items from the receipt; the Lead can assign unclaimed items to specific members via a picker modal

### 4. Contributions
- Each member sees their personal share on the **User Dashboard** (matching the Lead Dashboard layout for consistency)
- Stripe PaymentIntent → wallet credit
- Real-time progress bar: "$X of $Y collected · NN%"

### 5. Lead Dashboard (LEAD_DASHBOARD label)
- Hero card with bill title, status badge, "Your Share" on the right
- **Edit Tax & Tips** button (placed right after the hero)
- Quick actions: **Items / Invite / Card**
- Bill / Fund Breakdown collapsible card with every fee line
- Member list with swipe-left-to-remove for non-contributing members
- Bottom CTA: dynamic — "Contribute your share" → "Pay $X (cover shortfall)" → "Settle bill — fully funded"

### 6. User Dashboard (USER_DASHBOARD label)
- Identical layout to Lead Dashboard minus the Lead-specific buttons
- Shows the member's personal share + group progress
- Contribute button leads through Stripe checkout

### 7. Virtual Card
- Auto-issued via Stripe Issuing when wallet hits 100% funded
- Dedicated `/group/[id]/card` page
- Reveal flow requires OTP for security (`squadpay://card-reveal`)
- One-time use, scoped to the bill amount

### 8. Admin-Configurable Platform Fees
- Up to 2 extra fees on every bill (in addition to the built-in 3% transaction fee and $0.03 platform fee)
- Each fee: name + type (percent of merchant subtotal OR flat per bill) + value + enable toggle
- Stored in `platform_config` MongoDB doc, cached in-memory on backend
- Applied to every NEW bill on creation, split equally across members
- Editable via `/admin/platform-fees` page

### 9. Min 2 Members Rule
- Bills cannot be paid/contributed until ≥2 members are in the group
- Frontend shows a yellow banner + "Invite a member to start" CTA when only the Lead is present

### 10. Auth Flow
- Phone-based OTP (Twilio + SignalWire failover, mock mode for dev)
- "Skip phone" path allows browse but blocks payment
- Sign-in merges duplicate accounts by phone with confirmation prompt

### 11. Intent-Aware Routing
- Tapping "Split a Bill" → after auth, lands on `/create`
- Tapping "Join a Bill" → after auth, lands on `/join/code` (code entry form)

### 12. Activity & Squad
- **Activity** — historical bills with status, total, your share
- **Squad** — past collaborators for quick re-invite

---

## End-to-End User Flows

### Flow A — Brand new user creates a bill
```
Landing → "Split a Bill" → Auth (signup) → /create → Scan receipt or type total
       → Bill created → Lobby (QR/invite) → Wait for members → Items page (assign)
       → Bottom CTA "Contribute your share $X" → Stripe checkout → Lead Dashboard
       → As members contribute, progress rises → "Settle bill" CTA when full
       → Virtual Card auto-issued → /group/[id]/card → Reveal → Pay merchant
       → /success → Bill marked paid
```

### Flow B — Existing user joins someone's bill
```
SMS link "https://squadpay.us/join/ABC12345" → App opens (native) or web
       → If unauthenticated: /auth → "Sign in" → after auth, /join/ABC12345
       → "Join bill" confirmation → /group/[id]/items (claim what you ordered)
       → User Dashboard → "Contribute $X" → Stripe → Contributed badge ✓
```

### Flow C — Lead removes a non-contributing member
```
Lead Dashboard → swipe member row left → red "Remove" panel appears
       → Confirmation Alert "Remove member?" → API call POST /groups/{id}/remove-member
       → Member dropped, item claims released, all members get a notification
```

---

## Architecture

```
┌──────────────┐        ┌──────────────────┐        ┌──────────────┐
│  Expo Web    │───────►│  Vercel Static   │        │   GitHub     │
│  (browser)   │◄───────│  /dist + .well-  │        │   main       │
└──────────────┘        │  known/AASA      │◄───────┤   (source)   │
                        └──────────────────┘        └──────────────┘
                                                            │
┌──────────────┐                                            ▼
│  Expo Native │                                    ┌──────────────┐
│  (iOS/And.)  │                                    │   EAS Build  │
└──────┬───────┘                                    │   Pipeline   │
       │                                            └──────────────┘
       ▼
┌──────────────────────────────────────────────────────────────────┐
│  EXPO_PUBLIC_BACKEND_URL = https://joint-pay-1.emergent.host     │
└──────────────────────────────────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────────────────────────────┐
│                    FastAPI Backend (Emergent)                     │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐  │
│  │ /api/auth  │  │ /api/groups│  │ /api/pay   │  │ /api/admin │  │
│  └─────┬──────┘  └─────┬──────┘  └─────┬──────┘  └─────┬──────┘  │
│        └──────────────┬┴────────────────┴─────────────┬┘         │
│                       ▼                               ▼          │
│              ┌────────────────┐            ┌──────────────────┐  │
│              │   MongoDB      │            │ Stripe / OpenAI  │  │
│              │  test_database │            │ Twilio / Sig.Wire│  │
│              └────────────────┘            └──────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

---

## Money Movement & Custody Model

> **TL;DR — SquadPay coordinates; Stripe custodies and settles.**

### 1. Cardholder Data Flow (what we *don't* touch)

```
┌─────────────────────┐  raw PAN/CVV   ┌──────────────────────────┐
│  Member's device    │ ─────────────► │   Stripe.js / SDK iframe │
│  (Stripe PaymentSheet)│  (TLS, direct)│   (PCI-DSS Level 1 vault) │
└─────────────────────┘                └──────────────┬───────────┘
                                                      │ tokenises
                                                      ▼
                                              payment_method_id
                                                      │
                ┌─────────────────────────────────────┘
                ▼
       ┌─────────────────────┐         ┌──────────────────────────┐
       │ SquadPay Backend    │ ──────► │  Stripe API              │
       │ (sees TOKEN only,   │ confirm │  (creates PaymentIntent, │
       │  never the PAN)     │ intent  │   moves money in Stripe) │
       └─────────────────────┘         └──────────────────────────┘
```

**Notes on this diagram:**
- The dashed flow is the *only* path that a card number ever takes. It goes browser → Stripe directly via TLS, *bypassing* SquadPay's servers entirely.
- What we receive from the client is an opaque token like `pm_1Q3xRkABCDXyz` — a reference to a card object that lives inside Stripe's vault.
- Even if our entire backend were compromised, an attacker would obtain zero card numbers.

### 2. Funds Movement (what we orchestrate)

```
                      Contribute  ┌──────────────────────────┐
   Member's card  ─── via Stripe ►│   Stripe PaymentIntent   │
                                  │   (member → platform)    │
                                  └────────────┬─────────────┘
                                               │  funds settle into
                                               ▼
                                  ┌──────────────────────────┐
                                  │   Stripe Platform Balance│
                                  │   (held inside Stripe)   │
                                  └────────────┬─────────────┘
                                               │  spent via
                                               ▼
                                  ┌──────────────────────────┐
                                  │   Stripe Issuing Card    │
                                  │   (Lead pays merchant)   │
                                  └────────────┬─────────────┘
                                               │  authorisation
                                               ▼
                                          Merchant POS
```

**Key points:**
- Member funds *never* sit in a SquadPay-controlled bank account. They settle into a **Stripe Platform Balance** which is regulated, ring-fenced, and entirely under Stripe's banking partner controls.
- When the Lead settles the merchant, the **Stripe Issuing virtual card** draws against that same Stripe-held balance. SquadPay just authorises the issuance — Stripe approves/denies the merchant authorisation in real time.
- The "wallet" you see in our UI is a *display abstraction* over Stripe's ledger; the source of truth for any cent of money is the Stripe API.

### 3. What SquadPay's Database Actually Contains

| We **DO** store | We **DO NOT** store |
|---|---|
| User phone, name, role | Card PAN, CVV, expiry, ZIP |
| Bill items, tax, tip, totals | Cardholder name, billing address |
| Stripe object IDs (`pi_…`, `ic_…`, `cus_…`) | Bank account / routing numbers |
| Per-member contribution amounts (as recorded by Stripe) | Raw Stripe API secret keys (encrypted only, in KMS) |
| Receipt OCR JSON & image (transient, hashed) | Plaintext virtual card numbers |

### 4. Why This Matters

| Concern | SquadPay's posture |
|---|---|
| **PCI-DSS scope** | SAQ-A (lowest tier) — no cardholder data ever transits or is stored on our systems |
| **Money Transmitter License** | Not required — we never take possession of customer funds; Stripe is the regulated money mover |
| **Data breach blast radius** | Zero cardholder data exposure even in worst-case backend compromise |
| **Refunds / chargebacks** | Handled natively by Stripe; we mirror status via webhook |
| **Regulatory burden** | Minimised — we operate as a software facilitator, not an MSB |

> If a compliance reviewer asks "where do you store card numbers?", the answer is literally: **we don't, and we cannot — they never reach us.**

---

## Backend API Reference

### Auth (`/api/auth/*`)
| Method | Path | Purpose |
|---|---|---|
| `POST` | `/auth/start-otp` | Send OTP to phone |
| `POST` | `/auth/verify-otp` | Confirm OTP, create/login user |
| `POST` | `/auth/check-session` | Validate user session |
| `POST` | `/auth/accept-terms` | Mark T&C accepted |
| `POST` | `/auth/admin-login` | Admin email+password login (JWT) |

### Groups (`/api/groups/*`)
| Method | Path | Purpose |
|---|---|---|
| `POST` | `/groups` | Create a new bill |
| `GET` | `/groups/{id}` | Enriched group (members, per_user, funding) |
| `POST` | `/groups/{id}/join` | Join with user_id |
| `POST` | `/groups/{id}/remove-member` | Lead removes a non-contributing member |
| `POST` | `/groups/{id}/items` | Replace items (lead) |
| `POST` | `/groups/{id}/items/append` | Add new items mid-bill (lead) |
| `POST` | `/groups/{id}/assign` | Claim an item |
| `POST` | `/groups/{id}/edit-tax-tip` | Lead edits tax/tip |
| `POST` | `/groups/{id}/issue-card` | Auto-issue virtual card when fully funded |
| `POST` | `/groups/{id}/refund-overpayment` | Refund a member |

### Contributions (`/api/groups/{id}/contribute`)
- `POST /contribute` — Stripe PaymentIntent for a member's share. Guards: min 2 members, valid amount, not already paid.

### Pay (`/api/groups/{id}/pay`)
- `POST /pay` — Lead settles merchant (after wallet funded). Guards: lead only, status open, min 2 members.

### Misc
| Path | Purpose |
|---|---|
| `POST /api/receipt/scan` | OCR a base64-encoded receipt image |
| `GET/POST /api/referrals/*` | Referral code generation + tracking |
| `GET /api/legal/*` | Terms / Privacy MDX |

### Admin (`/api/admin/*` — JWT required)
- `GET /metrics` — top-line dashboard metrics
- `GET/PUT /users/*` — user management
- `GET/PUT /groups/*` — group management + force reassign lead
- `GET/PUT /admins/*` — admin user management
- `GET/PUT /platform-fees` — admin-configurable extra fees
- `GET/PUT /integrations/*` — Stripe / Twilio / SignalWire credential management

---

## Frontend Routes

| Route | Component | Auth | Description |
|---|---|---|---|
| `/` | `app/index.tsx` | optional | Landing or home with FeaturedBillCard |
| `/auth` | `app/auth.tsx` | — | OTP flow (signup/signin/skip-phone) |
| `/create` | `app/create.tsx` | required | New bill flow (scan or manual) |
| `/join/[code]` | `app/join/[code].tsx` | required | Join via code/QR |
| `/group/[id]` | `app/group/[id]/index.tsx` | required | Lobby (QR + member list) |
| `/group/[id]/dashboard` | `app/group/[id]/dashboard.tsx` | required (lead-only, redirects others) | Lead Dashboard |
| `/group/[id]/summary` | `app/group/[id]/summary.tsx` | required (member-only, redirects lead) | User Dashboard |
| `/group/[id]/items` | `app/group/[id]/items.tsx` | required | Item list + claim/assign |
| `/group/[id]/pay` | `app/group/[id]/pay.tsx` | required | Pay (kind=contribute|repay|lead) |
| `/group/[id]/card` | `app/group/[id]/card.tsx` | required | Virtual Card display |
| `/group/[id]/success` | `app/group/[id]/success.tsx` | required | Post-payment confirmation |
| `/activity` | `app/activity.tsx` | required | Past bills feed |
| `/squad` | `app/squad.tsx` | required | Friends list |
| `/settings` | `app/settings.tsx` | required | Profile + signout |
| `/admin/*` | `app/admin/*` | admin JWT | Web-only admin console |

---

## Database Schema

### `users`
```json
{
  "id": "u_abc123",
  "name": "Adams G",
  "phone": "+18325933512",
  "phone_verified": true,
  "tcs_accepted_at": "2026-05-11T10:59:22Z",
  "is_admin": false,
  "role": "super_admin | admin | user",
  "created_at": "...",
  "stripe_customer_id": "cus_..."
}
```

### `groups`
```json
{
  "id": "g_bc983231c8",
  "code": "ABC12345",
  "title": "Slick Willie's Friday",
  "lead_id": "u_abc123",
  "members": [{ "user_id": "u_...", "role": "lead|member", "joined_at": "..." }],
  "items": [{ "id": "i_...", "name": "Maker's Mark", "price": 8.75, "quantity": 2 }],
  "assignments": [{ "item_id": "i_...", "user_id": "u_...", "quantity": 1 }],
  "tax": 6.43,
  "tip": 0,
  "total": 84.33,
  "status": "open | paid | closed",
  "split_mode": "fast | items",
  "contributions": [{ "user_id": "u_...", "amount": 28.10, "stripe_pi": "pi_...", "ts": "..." }],
  "repayments": [...],
  "per_user": [
    {
      "user_id": "u_...",
      "merchant_share": 28.10,
      "transaction_fee": 0.84,
      "platform_fee": 0.03,
      "extra_fees": [{ "id": "extra_1", "name": "Service Fee", "amount": 0.42 }],
      "extra_fees_total": 0.42,
      "total": 29.39,
      "contributed": 29.39,
      "repaid": 0,
      "outstanding": 0
    }
  ],
  "funding": { "total_contributed": 84.33, "total_repaid": 0, "remaining_to_collect": 0 },
  "virtual_card": { "stripe_card_id": "ic_...", "last4": "4242", "nickname": "..." },
  "notifications": [{ "id": "...", "user_id": "u_...", "message": "...", "kind": "...", "created_at": "..." }],
  "is_blocked": false,
  "lead_reassigned_at": null
}
```

### `platform_config`
```json
{
  "_id": "platform_fees_config",
  "fees": [
    { "id": "extra_1", "name": "Service Fee", "type": "percent", "value": 1.5, "enabled": true },
    { "id": "extra_2", "name": "Insurance",   "type": "flat",    "value": 0.25, "enabled": false }
  ]
}
```

### Other collections
- `admins` — admin credentials (bcrypt hashed)
- `audit_log` — admin actions
- `referrals` — referral codes + claims
- `credits` — wallet credits ledger
- `legal_pages` — versioned T&C / Privacy MDX
- `integrations` — encrypted third-party credentials (KMS)

---

## Bill Math & Fees

### Per-member share
```
share = merchant_share + transaction_fee + platform_fee + sum(extra_fees)
```
- `merchant_share` = items they claimed + their portion of tax/tip
- `transaction_fee` = 3% of merchant_share
- `platform_fee` = $0.03 flat
- `extra_fees` = sum of admin-configurable enabled fees

### Grand Total (displayed)
```
grandTotal = items + tax + tip + transaction_fees + platform_fees + extra_fees
```
Computed client-side from rendered breakdown rows so the math is always self-consistent on screen.

### Remaining & Outstanding (unified)
```
remaining = outstanding = max(0, grandTotal − total_contributed)
```

### "Paid count" on home card
A member is counted as "paid" if `contributed > 0` or `repaid > 0`. So a brand-new bill correctly shows "0 of N paid".

---

## Admin Dashboard

Accessible at `/admin/dashboard` (web only, requires admin JWT).

### Sidebar nav
- Dashboard (metrics tiles)
- Bills
- Users
- Admins
- Integrations
- **Platform Fees** (super_admin only)
- Referrals
- Legal
- Audit Log
- KMS / Keys
- ...

### Default admin credentials (dev)
```
Email:    admin@squadpay.us
Password: Letmein@2007#ForReal
```

---

## Integrations

### OpenAI (via Emergent LLM key)
- Used in `routes/misc_routes.py` for receipt OCR
- Model: `gpt-4o`
- Prompt instructs the model to sum all tax lines, return unit prices, skip $0 modifier lines

### Stripe
- **PaymentIntents** for member contributions
- **Issuing** for auto-generated virtual cards (1-time use, scoped to bill total)
- **Ephemeral Keys** for the reveal-card flow

### Twilio + SignalWire
- Dual-provider SMS for OTP delivery
- Mock mode in dev (logs OTP "123456" to console)
- Configured via Admin → Integrations page

---

## Deep Linking

### iOS Universal Links
- `app.json` → `ios.associatedDomains: ["applinks:squadpay.us", "applinks:www.squadpay.us"]`
- File: `frontend/public/.well-known/apple-app-site-association`
- Team ID: `4JXHW2G4T7`
- Bundle: `com.squadpay.app`
- Paths: `/join/*`, `/group/*`

### Android App Links
- `app.json` → `android.intentFilters` with `autoVerify: true`
- File: `frontend/public/.well-known/assetlinks.json`
- Package: `com.squadpay.app`
- SHA256: `40:57:51:BC:31:36:3A:DB:13:CA:85:55:BA:26:59:C1:B9:94:0B:5A:CA:85:CA:38:EA:F7:DD:E4:1D:65:03:1F`

### Custom Scheme (fallback)
- `squadpay://join/<code>`
- `squadpay://group/<id>`

---

## Non-Functional Requirements

### Performance
| Metric | Target |
|---|---|
| Cold-start API response (warm DB) | < 300 ms p95 |
| Group dashboard fetch (`GET /groups/{id}`) | < 400 ms p95 |
| Receipt OCR end-to-end | < 8 s p95 (dominated by OpenAI vision call) |
| Stripe contribute end-to-end | < 3 s p95 |
| Web first-contentful-paint (Vercel CDN) | < 1.5 s on 4G |

### Scalability
- **Backend** is stateless FastAPI → horizontal scaling behind any load balancer.
- **Hot caches** in `core.py` (platform fees config) are refreshed on startup and on admin edit — eventually consistent within seconds across replicas.
- **MongoDB** indexes: `groups.code` (unique), `groups.lead_id`, `groups.members.user_id`, `users.phone` (unique).
- **Rate limits** on `/auth/start-otp` (5 req / phone / hour) to mitigate SMS abuse.

### Observability
- Backend logs are emitted as structured key=value pairs to stdout (collected by host platform).
- Stripe webhook deliveries are idempotency-key protected.
- Admin **Audit Log** persists every privileged action with actor, target, timestamp.

### Availability
- Web: dependent on Vercel SLA (≥ 99.99%).
- API: dependent on Emergent platform host SLA.
- SMS: dual-provider failover (Twilio primary, SignalWire fallback) — if one carrier is down, OTPs still deliver.

---

## Error Handling & Edge Cases

| Scenario | Behaviour |
|---|---|
| Member tries to contribute, only 1 member in group | API returns `409 NEED_MORE_MEMBERS`; UI shows yellow "Invite a member to start" banner |
| Stripe PaymentIntent fails (declined card) | Frontend surfaces the Stripe decline reason verbatim; no DB write |
| OCR receipt items + tax + tip ≠ scanned total | `routes/misc_routes.py` reconciles the delta into the tax field so the math always closes |
| Lead attempts to remove themselves | API rejects with `403 LEAD_CANNOT_REMOVE_SELF` |
| Lead removes a member who has already contributed | API rejects with `409 MEMBER_HAS_CONTRIBUTED` (refund flow must be used first) |
| Member's claimed items > bill total | UI clamps + warns; backend allows but flags |
| Bill is fully funded but Lead never settles | Background reminder job nudges Lead every 24 h |
| Duplicate user on signup (same phone) | OTP flow merges accounts; ownership of groups / credits / referrals transferred and logged |
| Universal Link not opening the app | Falls back to the web app at `https://squadpay.us/join/<code>` (graceful degradation) |
| Receipt OCR returns empty / nonsense | UI shows "Couldn't read receipt — type the total manually" with a retake button |
| Stripe Issuing returns 4xx (card creation refused) | Lead is told "Card issuance temporarily unavailable — please try again in a minute" and bill stays open |

---

## Roadmap / Backlog

### Near-term (next milestones)
- Apple Pay / Google Pay **push provisioning** of the SquadPay virtual card into the Lead's native wallet — pending approvals from our **PSP** (Payment Service Provider — Stripe) and the **PNO** (Payment Network Operator — Visa via VDEP / Mastercard via MDES).
  - ✅ Backend stub endpoint `POST /api/cards/{group_id}/provision` is live and returns `pending_psp_approval` until approvals land.
  - ✅ Frontend "Add to Apple/Google Pay" button gracefully surfaces the "coming soon — pending bank approval" status.
  - Email draft to Stripe support: see `/app/STRIPE_PUSH_PROVISIONING_REQUEST.md`.
  - When approvals land: replace the stub in `routes/wallet_routes.py` with the real Stripe Issuing push-provisioning call (`stripe.issuing.Card.create_push_provisioning_data(...)`), then request the Apple `payment-pass-provisioning` and Google `PUSH_PROVISIONING_PRIVILEGED` entitlements. No frontend changes needed.
- ✅ **Refactor** complete: `HeroCard`, `BillBreakdown`, and `useBillMath` extracted into `/src/components/redesign/` and `/src/hooks/` so Lead and User dashboards share a single source of truth.
- **Multi-receipt** scanning: stitch two receipts into a single bill (split-tab dinners).

### Future
- Recurring bills (monthly roommate utilities).
- Per-bill split rules persisted to user profile (e.g. "this group always splits evenly").
- International expansion (EUR, GBP, AUD).
- Native dark-mode support across all screens.
- Optional end-to-end encryption of bill notes / chat.

---

## Environment Variables

### Frontend (`frontend/.env`)
```
EXPO_PUBLIC_BACKEND_URL=https://joint-pay-1.emergent.host
EXPO_PUBLIC_STRIPE_PUBLISHABLE_KEY=pk_test_...
EXPO_PUBLIC_WEB_BASE_URL=https://squadpay.us
EXPO_PACKAGER_PROXY_URL=...     # DO NOT MODIFY
EXPO_PACKAGER_HOSTNAME=...      # DO NOT MODIFY
```

### Backend (`backend/.env`)
```
MONGO_URL=mongodb://localhost:27017      # DO NOT MODIFY
DB_NAME=test_database                    # DO NOT MODIFY
JWT_SECRET=...
EMERGENT_LLM_KEY=...                     # for OpenAI access
STRIPE_SECRET_KEY=...
STRIPE_WEBHOOK_SECRET=...
TWILIO_ACCOUNT_SID=...                   # optional, falls back to mock
TWILIO_AUTH_TOKEN=...
SIGNALWIRE_PROJECT_ID=...                # optional
KMS_MASTER_KEY=...                       # for encrypting sensitive admin creds
```

---

## Deployment

### Web → Vercel
1. Emergent UI → **Save to GitHub** → push to `main`
2. Vercel auto-deploys on push (linked to `getnuevetech/squadpay`)
3. Production URL: `https://squadpay.us`
4. Build command: `npx expo export --platform web`
5. Output: `dist/`

### Mobile → EAS
1. From local Mac:
   ```bash
   git pull --rebase origin main
   cd frontend && yarn install     # generates yarn.lock
   cd .. && git add frontend/yarn.lock && git commit -m "chore: lockfile" && git push origin main
   cd frontend
   eas build --platform all --profile production
   ```
2. Watch builds at `https://expo.dev/accounts/<account>/projects/squadpay/builds`
3. Submit:
   ```bash
   eas submit --platform android --latest
   eas submit --platform ios --latest
   ```

---

## Testing

### Backend
- Use the `deep_testing_backend_v2` agent (Emergent platform tool) which runs curl-based contract tests against the API.
- Test credentials are at `/app/memory/test_credentials.md`.
- All major endpoints have automated test coverage (Phase A through Phase N).

### Frontend
- Use `expo_frontend_testing_agent` (Emergent platform tool) which drives Playwright in mobile dimensions.
- Always test in iPhone 12 (390x844) and Galaxy S21 (360x800) viewports.

### Manual
- For deep linking, send an SMS with `https://squadpay.us/join/<code>` to a device with the app installed and tap.

---

## Security & Privacy

- **Phone numbers** stored plain (not PII-encrypted in MVP)
- **Admin credentials** bcrypt-hashed
- **3rd-party API keys** encrypted at rest with `crypto_kms.py` (master key in env)
- **Stripe secrets** never reach the frontend
- **JWT** for admin sessions, short-lived
- **OTP** valid for 5 minutes
- **CORS** locked to expected origins
- **Rate limiting** on `/auth/start-otp` (per phone, per IP)

---

## Glossary

| Term | Meaning |
|---|---|
| **Lead** | Bill creator, holds the merchant payment responsibility |
| **Member** | Non-lead participant in a bill |
| **Squad** | A user's history of past collaborators |
| **Contribute** | Pay your share into the SquadPay wallet (before merchant is paid) |
| **Repay** | Pay back the Lead AFTER they've fronted the merchant bill |
| **Settle** | Lead pays the merchant from the wallet |
| **Shortfall** | Gap between bill total and what members have claimed |
| **AASA** | Apple App Site Association (iOS Universal Links manifest) |
| **Asset Links** | Android equivalent of AASA |
| **EAS** | Expo Application Services — managed mobile build pipeline |
| **SAQ-A** | PCI Self-Assessment Questionnaire A (lowest scope, outsourced payments) |
| **PSP** | **Payment Service Provider** — the regulated company that actually processes card transactions and issues virtual cards on our behalf. *In SquadPay this is Stripe.* (Alternatives: Adyen, Marqeta, Lithic, Galileo.) |
| **PNO** | **Payment Network Operator** — the card-network rails the card runs on. They set the rules for digital-wallet provisioning and approve which programs may push cards into Apple/Google Wallet. *In SquadPay these are Visa (via VDEP — Visa Digital Enablement Program) and Mastercard (via MDES — Mastercard Digital Enablement Service).* |
| **Push Provisioning** | The flow that lets a user tap "Add to Apple/Google Wallet" inside the app and have the card appear on their phone instantly. Requires PSP + PNO + Apple/Google sign-off. |
| **Tokenisation** | Replacing the real card number with a one-time, device-bound reference (the "DPAN"). What actually sits in Apple Wallet — never the real PAN. |

---

## Maintainers

**NueveTech** — getnuevetech (GitHub org)

Built with **Emergent** (rapid full-stack mobile app development platform).

---

*Last updated: June 2025 — Phase N (Lead removes member) + Universal Links rolled out.*

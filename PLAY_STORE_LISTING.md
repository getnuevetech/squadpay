# SquadPay — Google Play Store Listing Draft

Copy/paste these into Google Play Console when uploading the AAB. Adjust as you see fit; everything is in plain English/US-style copy and respects Google's character limits.

---

## App name (max 30 chars)

```
SquadPay
```

> Already at 8/30 — short and brandable.

---

## Short description (max 80 chars)

```
Split bills with friends — pay together with one tap. No more chasing IOUs.
```
*(76 chars)*

Alternatives if Google says it's too promotional:
- `Split bills, scan receipts, pay together. Group payments made simple.` *(72)*
- `Group payments made easy. Split, scan, settle in one place.` *(60)*

---

## Full description (max 4000 chars)

```
Tired of being the friend who fronts the dinner bill and then chases everyone for their share? SquadPay is the easiest way for groups to split, scan, and settle bills together — no spreadsheets, no Venmo requests, no awkward reminders.

★ HOW IT WORKS

1. Create a group bill — name it (Saturday brunch, ski trip, group gift) and invite friends with a one-tap link or QR code.
2. Split the cost — divide it equally, line-by-line from a receipt photo, or assign specific items to specific people.
3. Each member pays their share securely with their card. When the bill is fully funded, you get a single virtual card to use at checkout.

★ WHY PEOPLE LOVE SQUADPAY

• EQUAL OR ITEMIZED SPLITS — Quick equal split for casual meals, or itemized when one person ordered the lobster.
• SMART RECEIPT SCANNING — Snap the receipt and SquadPay's AI extracts every line item automatically. No typing.
• ONE-TAP JOIN — Send a link or QR code. New members can join, contribute, and see who's paid in real time.
• REAL VIRTUAL CARD — When the group is fully funded, SquadPay issues a one-time virtual card you can use at any merchant that accepts Visa or Mastercard.
• GROUP CHAT BUILT-IN — Talk about the bill where the bill lives. No more switching between Messenger and your bank app.
• REMINDERS WITHOUT THE AWKWARDNESS — Friendly nudges to people who haven't paid yet, sent automatically.
• FULL TRANSPARENCY — Every member sees who has paid, who hasn't, and exactly where the money is going.
• SECURE BY DESIGN — Bank-grade encryption. Your card data never touches our servers; we use Stripe (the same platform powering Shopify, Lyft, and DoorDash) to handle every payment.

★ PERFECT FOR

✓ Roommates splitting groceries, utilities, or rent
✓ Friends splitting dinner, drinks, or trips
✓ Couples managing date-night spending
✓ Group gifts for birthdays, weddings, baby showers
✓ Office lunches, team off-sites, and shared subscriptions
✓ Sports clubs, gym memberships, and weekend escapes

★ NO MORE…

✗ "I'll Venmo you later" (which never happens)
✗ Chasing five people for their share over WhatsApp
✗ Trying to remember who paid for what
✗ Math errors when splitting an itemized bill
✗ The host getting stuck with the entire tab

★ SAFE & SIMPLE

SquadPay is built on Stripe's payment infrastructure — the same platform trusted by Amazon, Google, and millions of businesses. Your payment data is encrypted end-to-end and never stored on our servers.

★ GETTING STARTED

Download SquadPay, sign in with your phone number, and create your first bill in under 60 seconds. Splitting has never been this fast.

Questions? Reach us at help@squadpay.us — we read every message.

Privacy policy: https://www.squadpay.us/legal/privacy
Terms of service: https://www.squadpay.us/legal/terms
```

> ~3,150 chars — leaves headroom for tweaks. Keep the bullet markers (★ ✓ ✗) — Play Store renders them well.

---

## What's new in this version (max 500 chars per release)

### v1.0.1 (your first build with the backend URL fix)

```
First public release of SquadPay 🎉

• Create group bills and invite friends via link or QR code
• Equal or itemized splits with automatic receipt scanning
• Pay your share securely; group gets a virtual card when funded
• In-bill chat, automatic reminders, and live status

Got feedback? help@squadpay.us
```

*(412 chars — good headroom)*

---

## Categorization

- **App category**: Finance ★ recommended
- **Content rating questionnaire** answers (preview):
  - User-generated content? **Yes** — group chat
  - Simulated gambling? No
  - Violence? No
  - Strong language? No
  - Sexual content? No
  - Drugs/Alcohol? No
  - In-app purchases? No (you're not selling subscriptions yet)
  - Connected to social networks? No
  - Shares user location? No (only optional)
  - Collects user data? **Yes** — phone, email, payment-method details (via Stripe)

- **Target audience**: 18+ (financial product)
- **Tags** (Play Store auto-suggests these): Bill splitting, Group payments, Expense splitter, Receipt scanner, Roommate expenses, Trip costs

---

## Required visual assets for Play Console

| Asset | Size | Format | Status |
|---|---|---|---|
| App icon | 512 × 512 | PNG (32-bit, no alpha) | ⚠️ Need flatten — your current `icon.png` is 1024×1024 RGBA. Generate a 512×512 RGB version. |
| Feature graphic | 1024 × 500 | JPG/PNG | ❌ You'll need to design this — use the SquadPay violet (#7C3AED) gradient + tagline "Split bills with friends" |
| Phone screenshots (min 2, max 8) | 1080 × 1920 (or up to 1440 × 2560) | JPG/PNG | ❌ Capture from your test device |
| Tablet screenshots (optional but recommended for `supportsTablet`) | 1200 × 1920 min | JPG/PNG | ❌ |
| Promo video (optional) | YouTube link | — | ❌ skip for v1 |

> **Tip**: For phone screenshots, use a tool like https://app.previewed.app or https://shots.so to wrap actual screenshots in a phone frame with a colorful background. Looks 10× more professional than raw screenshots.

**Suggested screenshot lineup (4 screens):**
1. Welcome/home screen with hero illustration → caption: "Split bills with your squad"
2. Receipt scan + itemized split → caption: "Scan, split, settle"
3. Group lobby with avatars + payment status → caption: "See who's paid in real time"
4. Virtual card reveal → caption: "Pay together with one card"

---

## Privacy & data declarations (Data safety form)

| Data type | Collected? | Shared? | Optional? | Purpose |
|---|---|---|---|---|
| Name | Yes | No | No | Account management |
| Email | Optional | No | Yes | Account recovery |
| Phone number | Yes | No | No | Account / OTP / contact |
| Payment info | Yes (via Stripe) | Yes (Stripe — payment processor) | No | Process payments |
| Photos (receipts) | Optional | Yes (OpenAI for OCR) | Yes | Receipt scanning |
| Device IDs | Yes | No | No | Analytics, fraud prevention |
| Crash data | Yes | No | No | App stability |
| Diagnostics | Yes | No | No | Performance |

- **Encryption in transit**: Yes (HTTPS only)
- **Encryption at rest**: Yes (KMS-encrypted in MongoDB)
- **Account deletion**: User-initiated via app + email request to `help@squadpay.us`
- **Data deletion URL**: `https://www.squadpay.us/legal/privacy#data-deletion` *(make sure your privacy.tsx page documents this)*

---

## App Reviewer notes (paste into Google Play Console "Internal testing notes" or Apple App Store "Notes for reviewer")

```
SquadPay is a group-payment splitting app. We use Stripe Test Mode for v1 release — no real funds are processed.

Test account credentials:
- Email signup: any phone number, OTP code = "123456" in test mode
- For full demo: contact help@squadpay.us — we'll provide a test phone with prefilled groups

Key flows to test:
1. Sign up with phone (OTP mocked to "123456")
2. Create a group bill ("Saturday brunch", $80)
3. Invite a second test account via the share link
4. Both contribute their share via Stripe Test card 4242 4242 4242 4242 (any future expiry, any CVC)
5. Once funded, view the virtual card

We comply with all Google Play Finance/Payments policies. Stripe (PCI-DSS Level 1) handles every payment; we never see, store, or transmit raw card data.

Privacy policy: https://www.squadpay.us/legal/privacy
Terms: https://www.squadpay.us/legal/terms
Support: help@squadpay.us
```

---

## Store listing checklist before "Submit for review"

- [ ] App name correct
- [ ] Short description ≤ 80 chars
- [ ] Full description ≤ 4000 chars and proofread
- [ ] Category: Finance
- [ ] Tags filled in
- [ ] App icon 512×512 (no transparency)
- [ ] Feature graphic 1024×500 designed
- [ ] At least 2 phone screenshots uploaded
- [ ] Privacy policy URL set + page is publicly reachable
- [ ] Terms URL set + page is publicly reachable
- [ ] Content rating questionnaire completed
- [ ] Data safety form completed
- [ ] Pricing: Free
- [ ] Available in: United States (Stripe Issuing is US-only for now)
- [ ] AAB uploaded with `versionCode: 1`
- [ ] App Reviewer notes filled in (above)
- [ ] Internal testing track ready before promoting to Production

Once everything is green, click **Send for review**. Google's review usually takes **1-3 days** for a new finance app. Plan accordingly.

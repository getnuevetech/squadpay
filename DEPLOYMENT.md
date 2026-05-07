# SquadPay — Deployment Runbook (Hybrid)

> Backend on **Emergent** · Mobile on **Expo EAS** · Web on **Vercel**

---

## 0. Prerequisites (one-time setup on YOUR local machine)

You **cannot** run `eas build` from inside the Emergent container because EAS
needs to authenticate with your personal expo.dev account. Pull this repo to
your laptop, then:

```bash
# Node 20+ recommended
node --version

# Install the Expo & EAS CLIs globally
npm install -g eas-cli expo

# Log in to expo.dev (uses the getnuevetech account)
eas login
# → enter your getnuevetech password

# Confirm logged in
eas whoami
# → should print: getnuevetech
```

---

## 1. Project identity (already configured ✅)

| Field | Value |
|---|---|
| App name | **SquadPay** |
| Slug | `squadpay` |
| Owner | `getnuevetech` |
| iOS bundle ID | `com.squadpay.app` |
| Android package | `com.squadpay.app` |
| Brand color | `#7C3AED` (used for splash + Android adaptive icon background) |

These live in `frontend/app.json` and `frontend/eas.json`.

---

## 2. Link the project to expo.dev (run ONCE)

```bash
cd frontend
eas init
```

This will:
- Prompt: "Existing project found for `getnuevetech/squadpay`. Use it? [y/N]" → **y** (or it'll create one)
- Write the `projectId` into `app.json` → `expo.extra.eas.projectId`

After this, your project is visible at:
**https://expo.dev/accounts/getnuevetech/projects/squadpay**

> ⚠️ Commit the resulting `app.json` change so the team uses the same `projectId`.

---

## 3. Set production environment variables on EAS

Set these once on the EAS server so all production builds pick them up:

```bash
# Backend production URL (replace with the Emergent prod URL once deployed)
eas env:create --environment production \
  --name EXPO_PUBLIC_BACKEND_URL \
  --value https://api.squadpay.com

# Stripe LIVE publishable key (or _test_ for first launch)
eas env:create --environment production \
  --name EXPO_PUBLIC_STRIPE_PUBLISHABLE_KEY \
  --value pk_live_REPLACE_ME

# Repeat with --environment preview for staging URLs
```

> The placeholders in `eas.json` (`pk_live_REPLACE_ME`, `your-production-backend.example.com`) are fallbacks — the EAS env vars take precedence and are the recommended path.

---

## 4. First builds (preview / internal distribution)

Quick way to verify everything works without store submission:

```bash
# Android APK — installable on any device via the EAS link
eas build --profile preview --platform android

# iOS — needs a paid Apple Developer account; for sim only:
eas build --profile preview --platform ios
```

When the build finishes, EAS prints a URL like
`https://expo.dev/artifacts/eas/...apk`. Share that link with testers.

---

## 5. Production builds (store-ready)

### Android (Google Play)

```bash
# One-time: create a service account JSON for Play Console submission
# https://expo.fyi/creating-google-service-account
# Save it to frontend/pc-api-service-account.json (gitignored)

eas build --profile production --platform android
eas submit --profile production --platform android
# → uploads the AAB to Play Console "Internal Testing" track
```

### iOS (App Store)

```bash
# One-time: create an App Store Connect app (one-line wizard)
# https://appstoreconnect.apple.com/apps → "+" → "New App"
# Bundle ID: com.squadpay.app
# Note the App ID and Team ID, paste them into frontend/eas.json under
# "submit.production.ios.ascAppId" and "appleTeamId"

eas build --profile production --platform ios
eas submit --profile production --platform ios
# → uploads to TestFlight; promote to App Store after review
```

**Apple/Google Account Checklist:**
- [ ] Apple Developer Program ($99/yr) — https://developer.apple.com/programs
- [ ] Google Play Console ($25 one-time) — https://play.google.com/console
- [ ] Apple Team ID — Apple Developer → Membership tab
- [ ] App Store Connect App ID — created via "+" New App
- [ ] Google service account JSON — for `eas submit`

---

## 6. Web build (Vercel)

```bash
cd frontend
# Build the static web bundle
npx expo export -p web
# → outputs to ./dist
```

### Deploy to Vercel

Option A — CLI:
```bash
npm install -g vercel
cd frontend
vercel --prod
# Choose: Framework = Other, Build command = npx expo export -p web, Output = dist
```

Option B — Connect the GitHub repo at vercel.com → Import:
- **Root Directory**: `frontend`
- **Build Command**: `npx expo export -p web`
- **Output Directory**: `dist`
- **Environment Variable**: `EXPO_PUBLIC_BACKEND_URL=https://api.squadpay.com`
- **Environment Variable**: `EXPO_PUBLIC_STRIPE_PUBLISHABLE_KEY=pk_live_REPLACE_ME`

Vercel rebuilds automatically on every push to `main`.

---

## 7. Backend (Emergent)

Already running. Once Emergent gives you the public production URL, paste it into:
- EAS production env (`eas env:create --environment production --name EXPO_PUBLIC_BACKEND_URL --value ...`)
- Vercel env vars (Project Settings → Environment Variables)

Keep MONGO_URL, Stripe secret keys, Twilio/SignalWire creds, and OpenAI keys in
the Emergent backend `.env` only — they should never reach the mobile/web bundle.

---

## 8. Updates (over-the-air via EAS Update)

After your app is on the stores, you can ship JS-only fixes without a new
binary:

```bash
eas update --branch production --message "Fix: lobby header alignment"
```

OTA updates only work for code changes — adding native deps still needs a new
build + store submission.

---

## 9. Quick reference — common commands

| Need | Command |
|---|---|
| Login | `eas login` / `eas whoami` |
| Link project | `cd frontend && eas init` |
| Preview Android APK | `eas build --profile preview --platform android` |
| Production iOS | `eas build --profile production --platform ios` |
| Submit to stores | `eas submit --profile production --platform <ios\|android>` |
| Push OTA fix | `eas update --branch production --message "..."` |
| Web bundle | `npx expo export -p web` |
| List builds | `eas build:list` |
| Cancel build | `eas build:cancel` |

---

## 10. Rollback

| What broke | How to revert |
|---|---|
| Bad EAS production build | `eas build:view` → previous build → "Roll back" in dashboard |
| Bad OTA update | `eas update:rollback --branch production` |
| Vercel deploy | `vercel rollback` (or use the Deployments page) |
| Backend (Emergent) | Use Emergent's rollback UI |

---

## 11. Open items / TODO before first store submission

- [ ] Replace `pc-api-service-account.json` placeholder with the real key
- [ ] Replace `appleTeamId` and `ascAppId` in `eas.json`
- [ ] Replace `EXPO_PUBLIC_STRIPE_PUBLISHABLE_KEY` with `pk_live_...` (or stay test for soft launch)
- [ ] Run `eas init` to populate `expo.extra.eas.projectId` in `app.json`
- [ ] Apple Privacy Nutrition Label answers — fill in App Store Connect
- [ ] Privacy policy URL + Terms of Service URL — required for both stores
- [ ] App icon (`./assets/images/icon.png`) and splash (`./assets/images/splash-icon.png`) — currently placeholders, ideally upload SquadPay-branded artwork (1024×1024 icon, 1284×2778 splash)

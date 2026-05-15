# EAS Build Preflight — Run this on your Mac

This document captures everything needed to ship SquadPay to TestFlight / Play
Console after pulling the latest commits. The preview build is required for
**physical-device push-notification testing** (Expo Push tokens don't issue in
Expo Go).

## 0. One-time setup (skip if already done)

```bash
# Globally install EAS CLI
npm install -g eas-cli@latest

# Authenticate with the Expo account that owns the project
# Account: getnuevetech (per app.json `expo.owner`)
eas login
```

## 1. Bind the local repo to the Expo project

`app.json` currently has `expo.extra.eas.projectId = ""` (empty). EAS needs
this populated before any build can run.

```bash
cd /path/to/SquadPay/frontend

# This will detect the owner+slug from app.json and either link to the
# existing project on expo.dev OR offer to create one. Pick the existing
# "squadpay" project under the "getnuevetech" org.
eas init

# Verify it wrote the projectId into app.json:
grep projectId app.json
```

Commit the `projectId` change to git so subsequent CI builds inherit it.

## 2. Verify env vars are in `eas.json`

Already configured for all 3 channels (development / preview / production):

```
EXPO_PUBLIC_BACKEND_URL          = https://joint-pay-1.emergent.host
EXPO_PUBLIC_STRIPE_PUBLISHABLE_KEY = pk_test_...                ⚠️ TEST KEY
EXPO_PUBLIC_WEB_BASE_URL          = https://www.squadpay.us
```

**Action item before production submission**: swap the Stripe TEST publishable
key for the LIVE one in `eas.json` → `build.production.env`.

## 3. Run the build

```bash
# iOS + Android in parallel, preview channel (TestFlight / internal Play track)
eas build --platform all --profile preview

# OR per-platform
eas build --platform ios     --profile preview
eas build --platform android --profile preview
```

Builds run on EAS's cloud workers. First-time iOS build asks you to upload
your Apple cert / provisioning profile or auto-generate them (let EAS handle).
First-time Android build will auto-generate an Upload Keystore.

## 4. Push-notification verification (the real reason for this build)

On the installed preview build:

1. Open the app on a physical iOS or Android device.
2. Log in / register — the splash screen requests Push permission.
3. App should fetch an Expo Push token and POST it to
   `POST /api/users/me/push-token`. Check backend logs for the call.
4. From the admin Notification Center (`/admin/notification-config`), send a
   test broadcast to `audience: members` → `channels: push: true`.
5. Device should receive a foreground/background notification within ~5s.

If the token is never registered, check:
- iOS: `app.json` → `expo.ios.bundleIdentifier === com.squadpay.app` (✅)
- Android: `expo.android.package === com.squadpay.app` (✅)
- Backend `/api/users/me/push-token` route exists and accepts POSTs.

## 5. Production build + submit

```bash
# Production binaries (App Store / Play Store)
eas build --platform all --profile production

# Submit to stores (uses `submit` block in eas.json):
#   - iOS: Apple ID = aoolomola@outlook.com, app id 6768632339
#   - Android: ./pc-api-service-account.json must exist locally
eas submit --platform ios     --profile production
eas submit --platform android --profile production
```

## Common gotchas

| Symptom | Fix |
|---|---|
| `Error: projectId not configured` | Run `eas init` (step 1) |
| iOS build pending forever | Check Apple Developer Program billing status |
| Android `keystore.json` missing | Let EAS auto-generate, or `eas credentials` to upload yours |
| Build succeeds but app crashes on launch | Almost always a missing `EXPO_PUBLIC_*` env var — recheck `eas.json` |
| Push tokens not registering on iOS preview | iOS Simulator builds CAN'T receive push. Use a real device. |

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

---

## 🔄 Icon refresh — why old icons stick after install (May 2026)

If the SquadPay app icon on your phone STILL looks like the old SP-sparkle
mark after you've run `eas build` and reinstalled, walk through this list:

### 0. Are you looking at Expo Go's icon?
If you installed the app via **Expo Go** (i.e. you scanned the QR code from
`expo start`), the icon you see on the home screen is **Expo Go's own
icon**, not your project's. Custom icons only appear after a real native
build (`eas build`) installed via TestFlight / Play Internal Testing /
sideload (.apk / .ipa).

### 1. Confirm the build picked up the new files
Locally:
```bash
cd frontend
git pull                         # make sure your checkout has the new logos
git log -- assets/images/icon.png  # the last commit should be the logo refresh
md5sum assets/images/icon.png    # should match GitHub
```
Then in `app.json` confirm:
- `"icon": "./assets/images/icon.png"`           (top-level)
- `"ios.icon": "./assets/images/icon.png"`       (added May 2026 — some
  builds need this explicit override)
- `"android.icon": "./assets/images/icon.png"`   (added May 2026)
- `"android.adaptiveIcon.foregroundImage": "./assets/images/adaptive-icon.png"`

### 2. Bump the build versions (already done May 2026)
- `version: "1.0.1"`
- `ios.buildNumber: "2"`
- `android.versionCode: 2`
Bumping these forces EAS to produce a fresh artifact (it won't reuse a
cached build with the old icon baked in).

### 3. Run the build with a cleared cache
```bash
eas build --platform ios     --clear-cache
eas build --platform android --clear-cache
```
`--clear-cache` is the silver bullet for "icon didn't update".

### 4. Clean install — both OSes cache icons aggressively
**iOS (TestFlight, ad-hoc, dev profile):**
1. Long-press the SquadPay app icon → **Remove App** → **Delete App**
2. Reboot the iPhone (Springboard rebuilds its icon cache on boot)
3. Reinstall from TestFlight / Xcode

**Android:**
1. Settings → Apps → SquadPay → Uninstall
2. Settings → Apps → (your launcher, e.g. Pixel Launcher) → Storage → Clear cache
3. Reboot
4. Reinstall the new APK

### 5. Verify the icon is opaque (Apple requirement)
The `icon.png` is now saved as **RGB (no alpha channel)** so Apple
processing won't auto-flatten transparent pixels to black. Verify with:
```bash
python3 -c "from PIL import Image; im=Image.open('frontend/assets/images/icon.png'); print(im.mode, im.size)"
# expect: RGB (1024, 1024)
```

### 6. The Android adaptive foreground MUST stay transparent
`adaptive-icon.png` is **RGBA** with the logo inside the central safe zone
(~70% of the 1024² canvas). Android composites it on top of
`android.adaptiveIcon.backgroundColor` (`#FFFFFF`) and applies a circular
mask. If you replace it with an opaque PNG, the launcher will show a
white square instead of the rounded squircle. **Don't make it opaque.**

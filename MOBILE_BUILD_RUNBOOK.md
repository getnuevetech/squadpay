# SquadPay — Mobile Build & Submit Runbook

This runbook tells you exactly how to build and submit SquadPay to the App Store and Google Play. Run these commands from your local machine (not from this container — EAS auth requires interactive Apple/Google login).

---

## ✅ 0. Pre-flight checklist (already done)

These are baked into the repo and you don't need to redo them:

| Item | Status | Where |
|---|---|---|
| `eas.json` → Apple Team ID `4JXHW2G4T7` | ✅ | `frontend/eas.json` |
| `eas.json` → ASC App ID `6768632339` | ✅ | `frontend/eas.json` |
| `app.json` → Apple Pay entitlement `merchant.us.squadpay` | ✅ | `frontend/app.json` |
| `app.json` → iOS Privacy Manifest (`NSPrivacyAccessedAPITypes`, data types) | ✅ | `frontend/app.json` |
| `app.json` → iOS deployment target 15.1, Android compileSdk 35 | ✅ | `expo-build-properties` plugin |
| `app.json` → permission strings (camera/photos/contacts/face‑id) | ✅ | `ios.infoPlist` + `expo-image-picker` |
| `apple-app-site-association` (universal links) | ✅ | `frontend/public/.well-known/` |
| `assetlinks.json` (Android App Links) | ✅ | `frontend/public/.well-known/` |
| `DELETE /api/users/me/delete` (App Store 5.1.1(v)) | ✅ | `backend/routes/account_deletion_routes.py` |
| Delete-account button in Settings | ✅ | `frontend/app/settings.tsx` |
| `expo-camera`, `expo-document-picker`, `expo-build-properties` pinned to SDK 54 versions | ✅ | `frontend/package.json` |

---

## 🔑 1. One-time setup on your laptop

```bash
# Install the latest EAS CLI
npm install -g eas-cli

# Authenticate (Expo + later you'll be prompted for Apple/Google)
eas login

cd frontend
```

> **Tip:** The `owner` in `app.json` is `getnuevetech`. Make sure your `eas login` is on an account that belongs to that organisation, otherwise the build will fail with "owner not found".

---

## 🆔 2. Link the EAS project (run once)

```bash
eas init                    # creates the project on EAS and writes `extra.eas.projectId` into app.json
eas project:info            # sanity-check
```

This will populate the empty `"projectId": ""` in `app.json`. **Commit that change.**

---

## 🍏 3. iOS — Build & submit

### 3a. Confirm Apple Developer account artefacts

Before you can build, you need (in App Store Connect / Apple Developer):

1. **Apple Developer Team:** `4JXHW2G4T7` (already in `eas.json`).
2. **App ID record:** `com.squadpay.app` with these capabilities:
   - In‑App Purchases (off — we don't use them)
   - **Apple Pay** ← required. Create the **Merchant ID** `merchant.us.squadpay` and associate it with the App ID.
   - Associated Domains
3. **App Store Connect app**: `ascAppId 6768632339` (you provided this — confirm it shows under "My Apps").
4. **Bundle ID** in the ASC app == `com.squadpay.app`.
5. **Test users** for the demo flow (`admin@squadpay.us / Letmein@2007#ForReal` is fine, but the App Store review team usually needs a regular user too).

EAS will generate (or reuse) the certs / provisioning profiles automatically when you run `eas build`.

### 3b. Build iOS

```bash
# Production build (App Store distribution)
eas build --platform ios --profile production
```

When prompted:
- Apple ID → `aoolomola@outlook.com`
- App-specific password → generate at https://appleid.apple.com → Security → App-Specific Passwords
- Let EAS manage your credentials (recommended): `Yes`
- For Apple Pay, when EAS asks about merchant identifiers, select `merchant.us.squadpay`.

Watch the build at: https://expo.dev/accounts/getnuevetech/projects/squadpay/builds

### 3c. Submit to App Store Connect

```bash
eas submit --platform ios --latest
```

This uploads the artefact built above to App Store Connect using the credentials in `eas.json → submit.production.ios`.

### 3d. In App Store Connect — fill out the listing

Before TestFlight / submission for review:

1. **App Privacy** → check the boxes that match the manifest we declared in `app.json → ios.privacyManifests.NSPrivacyCollectedDataTypes`:
   - Name, Phone, Payment Info, Photos, User ID, Device ID — all **linked**, **not used for tracking**, purpose: **App Functionality** (Device ID also: Analytics).
2. **Data deletion** → "Provide a link to account deletion" → use `https://squadpay.us/legal/support` (the Support page tells them about the in-app Settings → Delete account button).
3. **Encryption** → "Does your app use non-exempt encryption?" → **No** (already declared via `ITSAppUsesNonExemptEncryption: false`).
4. **App Review information**:
   - Demo account: provide a test user phone + the mock OTP `123456` (your backend already supports mock-mode OTP).
   - Notes for Apple: mention that Stripe keys are TEST and no real money moves.

---

## 🤖 4. Android — Build & submit

### 4a. Pre-reqs

1. A **Google Play Developer** account at https://play.google.com/console.
2. Create an app entry for `com.squadpay.app`.
3. Generate a **service account JSON** for `eas submit`:
   - Play Console → Settings → API access → Create new service account
   - In Google Cloud, grant it the role "Service Account User"
   - Back in Play Console → Grant access → Permissions → all permissions needed for "Release manager" → invite
   - Download the JSON, place it at `frontend/pc-api-service-account.json` (already referenced by `eas.json`). **Do NOT commit this file.**

> If you don't have a Google service account JSON yet, you can still build with `eas build`. You'll just upload the `.aab` manually via the Play Console for the first release.

### 4b. Build Android

```bash
eas build --platform android --profile production
```

This produces an `app-release.aab` (App Bundle).

### 4c. Submit

```bash
# Automated — requires pc-api-service-account.json
eas submit --platform android --latest
```

Or manually: download the `.aab` from the EAS build page and upload it under **Play Console → Internal testing → Create new release**.

### 4d. In Play Console — fill out the listing

1. **Data safety** form → list: Name, Phone, Photos, Payment Info, User ID, Device ID — collected & encrypted in transit, not shared, optional, declaration matches the iOS manifest.
2. **Account deletion** → "User-initiated deletion URL" → `https://squadpay.us/legal/support` and confirm that the in-app Settings → Delete account works.
3. **Content rating** → fill IARC questionnaire (financial app, no violence/profanity, etc.).
4. **Target audience** → 18+ (because of financial txns).

---

## 🔁 5. Subsequent updates

When you ship a new version:

```bash
# 1. Update app.json
#    expo.version → bump (e.g. "1.0.1")
#    expo.ios.buildNumber → bump
#    expo.android.versionCode → bump

# 2. Build + submit (one command each platform)
eas build --platform ios --profile production --auto-submit
eas build --platform android --profile production --auto-submit
```

The `appVersionSource: "remote"` setting in `eas.json` means EAS will auto-increment the iOS `buildNumber` and Android `versionCode` for you if you set `autoIncrement: true` in the profile (already on for `production`).

---

## 🛟 6. Common pitfalls

| Symptom | Fix |
|---|---|
| Build fails with **"Invalid entitlement: in-app-payments"** | The Merchant ID `merchant.us.squadpay` doesn't exist or isn't linked to the App ID. Create it in Apple Developer → Identifiers → Merchant IDs. |
| **"Bundle identifier already exists"** during `eas init` | Someone in your Apple team already registered `com.squadpay.app`. Either reuse it or switch the bundle id (e.g. `com.squadpay.app2`) in `app.json`. |
| **Universal links don't open the app** after install | Re-deploy `frontend/public/.well-known/apple-app-site-association` (Apple fetches it from `https://squadpay.us/.well-known/apple-app-site-association`). It must have `Content-Type: application/json` and HTTP 200. |
| **Android App Links not verifying** | The SHA-256 in `assetlinks.json` must match the certificate Google Play signs your app with. Run `eas credentials` to print the upload key SHA-256 and update `frontend/public/.well-known/assetlinks.json`. |
| App Store rejects for missing "Delete Account" flow | Confirmed implemented — Settings → "Delete account" row → soft-delete with 30-day grace. Point reviewer to it. |

---

## 📨 7. Help / Support

If a build fails or App Store sends a rejection, paste the error here and we'll triage it together. For account deletion enquiries from users, the email `help@squadpay.us` is wired up via Gmail SMTP and reaches the Contact Us inbox.

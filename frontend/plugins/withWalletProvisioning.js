/**
 * SquadPay Push Provisioning — Expo Config Plugin.
 *
 * Wires up the iOS + Android entitlements, capabilities, and native modules
 * needed to call Apple Wallet (PKAddPaymentPassRequest) and Google Wallet
 * (PushTokenizeRequest) from inside the SquadPay app.
 *
 * STATUS: SCAFFOLDED, DISABLED BY DEFAULT.
 *
 * Once Stripe + Visa/Mastercard + Apple/Google approve our program:
 *   1. Apple grants the `com.apple.developer.payment-pass-provisioning`
 *      entitlement to our App ID (4JXHW2G4T7.com.squadpay.app).
 *   2. Google grants the `PUSH_PROVISIONING_PRIVILEGED` permission to our
 *      Play Console app.
 *   3. Stripe replaces the stub in /app/backend/routes/wallet_routes.py
 *      with the real `stripe.issuing.Card.create_push_provisioning_data(…)`
 *      call.
 *
 * Then to enable it in our build, set:
 *
 *     expo.extra.walletProvisioning.enabled = true
 *
 * in /app/frontend/app.json — and run `eas build`. No other code changes.
 *
 * The frontend already reads the bridge via /app/frontend/src/lib/walletProvisioning.ts
 * and gracefully degrades when the bridge is absent (Expo Go, web, etc.).
 */
const {
  withInfoPlist,
  withEntitlementsPlist,
  withAndroidManifest,
  withAppBuildGradle,
  AndroidConfig,
} = require('@expo/config-plugins');

const PLUGIN_NAME = 'withWalletProvisioning';

function withIosEntitlements(config) {
  return withEntitlementsPlist(config, (mod) => {
    // Apple Wallet push-provisioning entitlement.
    // Approved by Apple after Stripe + Visa/Mastercard co-sign.
    // Until then this is a no-op — Apple build-tooling won't reject it,
    // but the app won't be able to actually call PKAddPaymentPassRequest
    // without the matching provisioning profile.
    mod.modResults['com.apple.developer.payment-pass-provisioning'] = true;
    return mod;
  });
}

function withIosInfoPlist(config) {
  return withInfoPlist(config, (mod) => {
    // Required user-facing description in iOS Settings if we ever ask
    // for PassKit permissions (we don't, but Apple reviewers check anyway).
    mod.modResults.NSPaymentPassUsageDescription =
      mod.modResults.NSPaymentPassUsageDescription ||
      'SquadPay adds your virtual SquadPay card to Apple Wallet so you can pay merchants by tapping your phone.';
    return mod;
  });
}

function withAndroidPermissions(config) {
  return withAndroidManifest(config, async (mod) => {
    const manifest = mod.modResults;
    AndroidConfig.Permissions.addPermission(
      manifest,
      'com.google.android.gms.permission.PUSH_PROVISIONING_PRIVILEGED',
    );
    AndroidConfig.Permissions.addPermission(
      manifest,
      'com.google.android.gms.permission.AID_BASED_PROVISIONING_PRIVILEGED',
    );
    // Required for the Tap & Pay SDK to read the device's stable hardware ID.
    AndroidConfig.Permissions.addPermission(manifest, 'android.permission.NFC');
    return mod;
  });
}

function withAndroidGradle(config) {
  return withAppBuildGradle(config, (mod) => {
    if (mod.modResults.contents.includes('com.google.android.gms:play-services-tapandpay')) {
      return mod;
    }
    const dep = `    implementation 'com.google.android.gms:play-services-tapandpay:18.2.0'\n`;
    mod.modResults.contents = mod.modResults.contents.replace(
      /dependencies\s*\{\n/,
      (match) => match + dep,
    );
    return mod;
  });
}

module.exports = function withWalletProvisioning(config, props = {}) {
  // Master switch — keep this `false` until Stripe + PNO approvals land,
  // then flip to `true` and `eas build`.
  const enabled = props.enabled === true;
  if (!enabled) {
    console.log(
      `[${PLUGIN_NAME}] Push Provisioning is DISABLED. ` +
        'Flip expo.extra.walletProvisioning.enabled = true in app.json after Stripe approval.',
    );
    return config;
  }

  console.log(`[${PLUGIN_NAME}] Push Provisioning ENABLED — applying entitlements & permissions.`);
  config = withIosEntitlements(config);
  config = withIosInfoPlist(config);
  config = withAndroidPermissions(config);
  config = withAndroidGradle(config);
  return config;
};

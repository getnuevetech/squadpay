#!/usr/bin/env node
/**
 * Pre-build environment guard for SquadPay.
 *
 * Run automatically by EAS via the eas.build.[profile].prebuildCommand or
 * by the npm/yarn `prebuild` lifecycle hook (see package.json).
 *
 * Fails the build EARLY if any required public env var is empty, missing,
 * or still set to an obvious placeholder. Saves ~15 minutes vs. discovering
 * a broken APK after install.
 *
 * Required env vars (per profile):
 *   EXPO_PUBLIC_BACKEND_URL
 *   EXPO_PUBLIC_STRIPE_PUBLISHABLE_KEY  (only enforced for preview/production)
 */
/* eslint-disable no-console */
const REQUIRED = {
  EXPO_PUBLIC_BACKEND_URL: {
    profiles: ['development', 'preview', 'production'],
    placeholders: [
      'your-staging-backend.example.com',
      'your-production-backend.example.com',
      'REPLACE_ME',
      'CHANGE_ME',
      '',
    ],
    mustStartWith: 'https://',
  },
  EXPO_PUBLIC_STRIPE_PUBLISHABLE_KEY: {
    profiles: ['preview', 'production'],
    placeholders: ['pk_live_REPLACE_ME', 'pk_test_REPLACE_ME', 'REPLACE_ME', ''],
    mustStartWith: 'pk_',
  },
  EXPO_PUBLIC_WEB_BASE_URL: {
    profiles: ['preview', 'production'],
    placeholders: [
      'your-web-domain.example.com',
      'REPLACE_ME',
      // Backend host accidentally used as web base — historically what caused
      // join links to 404 (FastAPI does not serve the join screen).
      'emergent.host',
      '.emergentagent.com',
      '',
    ],
    mustStartWith: 'https://',
  },
};

const profile = process.env.EAS_BUILD_PROFILE || process.env.NODE_ENV || 'development';
const errors = [];
const warnings = [];

console.log(`\n[squadpay-prebuild] running env checks for profile=${profile}\n`);

for (const [varName, rule] of Object.entries(REQUIRED)) {
  if (!rule.profiles.includes(profile)) continue;
  const val = (process.env[varName] || '').trim();
  const masked = val
    ? (val.length <= 12 ? val : `${val.slice(0, 8)}\u2026${val.slice(-4)}`)
    : '<UNSET>';
  console.log(`  ${varName.padEnd(40)} ${masked}`);

  if (!val) {
    errors.push(`${varName} is unset for profile=${profile}.`);
    continue;
  }
  if (rule.placeholders.some((ph) => ph !== '' && val.includes(ph))) {
    errors.push(
      `${varName} still contains a placeholder value ("${val}"). Update eas.json or your dashboard env.`,
    );
    continue;
  }
  if (rule.mustStartWith && !val.startsWith(rule.mustStartWith)) {
    errors.push(
      `${varName} must start with "${rule.mustStartWith}" but starts with "${val.slice(0, 8)}\u2026".`,
    );
    continue;
  }
  // Soft warnings
  if (varName === 'EXPO_PUBLIC_STRIPE_PUBLISHABLE_KEY' && val.startsWith('pk_test_') && profile === 'production') {
    warnings.push(
      `${varName} is a TEST key but the profile is "production". This is fine for Stripe Test Mode launches, but switch to a live key (pk_live_...) before processing real funds.`,
    );
  }
  if (varName === 'EXPO_PUBLIC_BACKEND_URL' && (val.includes('preview.emergentagent.com') || val.includes('localhost'))) {
    warnings.push(
      `${varName} points at a development/preview URL (${val}) but profile is "${profile}". Preview hosts may sleep \u2014 use the production native deploy URL instead.`,
    );
  }
}

if (warnings.length) {
  console.log('\n[squadpay-prebuild] \u26a0  warnings:');
  for (const w of warnings) console.log(`    - ${w}`);
}
if (errors.length) {
  console.error('\n[squadpay-prebuild] \u274c  build aborted \u2014 fix these before retrying:');
  for (const e of errors) console.error(`    - ${e}`);
  console.error('');
  process.exit(1);
}

console.log('\n[squadpay-prebuild] \u2705 all required env vars look good. Proceeding with build.\n');

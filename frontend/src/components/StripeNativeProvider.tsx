/**
 * Native-only Stripe wrapper (Phase 7 — Apple Pay / Google Pay).
 *
 * `@stripe/stripe-react-native` is a native module — importing it on web
 * blows up the bundler. We dynamically require it only on iOS / Android.
 *
 * The publishable key + Apple merchant identifier come from
 * GET /api/stripe/publishable-key so admins can rotate keys without a rebuild.
 *
 * On web, this is a transparent passthrough — payments fall back to the
 * existing Stripe Checkout (WebView) flow, which on Safari/Chrome ALREADY
 * shows Apple Pay / Google Pay buttons automatically.
 */
import { Platform } from 'react-native';
import { ReactNode, useEffect, useState } from 'react';
import { api } from '../api';

export function StripeNativeProvider({ children }: { children: ReactNode }) {
  if (Platform.OS === 'web') return <>{children}</>;
  return <NativeImpl>{children}</NativeImpl>;
}

function NativeImpl({ children }: { children: ReactNode }) {
  const [publishableKey, setPublishableKey] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const r = await api.stripePublishableKey();
        if (r.configured && r.publishable_key) setPublishableKey(r.publishable_key);
      } catch (e) {
        // eslint-disable-next-line no-console
        console.warn('[stripe-native] publishable-key fetch failed:', e);
      }
    })();
  }, []);

  // Lazy-require the native module so web builds aren't affected
  let StripeProvider: any = null;
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    StripeProvider = require('@stripe/stripe-react-native').StripeProvider;
  } catch {
    // Module not installed in this build flavor — passthrough.
    return <>{children}</>;
  }

  // If the publishable key hasn't loaded yet, render children without the
  // provider — the contribute screen will simply hide the "Tap to Pay"
  // button until the provider is ready.
  if (!publishableKey) return <>{children}</>;

  return (
    <StripeProvider
      publishableKey={publishableKey}
      merchantIdentifier="merchant.us.squadpay"
      urlScheme="squadpay"
    >
      {children}
    </StripeProvider>
  );
}

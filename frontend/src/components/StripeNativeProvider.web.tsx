/**
 * Web variant of StripeNativeProvider — passthrough.
 *
 * Why this file exists
 * ────────────────────
 * `@stripe/stripe-react-native` is a native-only module (it uses
 * codegenNativeComponent which 500s the Metro web bundle). To keep the web
 * build from ever importing it, we ship a `.web.tsx` variant that Metro
 * picks automatically when `Platform.OS === 'web'`.
 *
 * On web, Apple Pay / Google Pay still works — but via the hosted Stripe
 * Checkout WebView/redirect (Stripe Checkout detects browser-supported
 * wallets automatically).
 */
import { ReactNode } from 'react';

export function StripeNativeProvider({ children }: { children: ReactNode }) {
  return <>{children}</>;
}

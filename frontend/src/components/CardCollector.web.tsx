/**
 * CardCollector — WEB variant.
 *
 * Uses `@stripe/react-stripe-js` + `@stripe/stripe-js` to render Stripe
 * Elements `<CardElement>` and tokenise the card client-side. The PAN
 * never touches our backend.
 *
 * Wraps itself in `<Elements>` provider (lazy-loaded publishable key).
 *
 * Imperative ref API:
 *   await ref.current?.tokenize()  →  { token: 'tok_xxx', last4: '4242' }
 *
 * Caller still owns the "Cardholder name" input (passed in as a prop) so
 * we can pass it into Stripe's billing_details and into the receipt copy.
 */
import { forwardRef, useCallback, useImperativeHandle, useMemo, useState, useEffect } from 'react';
import { ActivityIndicator, Platform, StyleSheet, Text, View } from 'react-native';
import { Elements, CardElement, useStripe, useElements } from '@stripe/react-stripe-js';
import { loadStripe, Stripe } from '@stripe/stripe-js';
import { COLORS, FONT, RADIUS, SPACING } from '../theme';

export type CardCollectorHandle = {
  tokenize: () => Promise<{ token: string; last4: string }>;
};

type Props = {
  cardholderName?: string;
  onReady?: (ready: boolean) => void;
};

const PUBLISHABLE_KEY = process.env.EXPO_PUBLIC_STRIPE_PUBLISHABLE_KEY || '';

// Singleton — Stripe.js must only be loaded once per page.
let _stripePromise: Promise<Stripe | null> | null = null;
function getStripePromise() {
  if (!_stripePromise) {
    if (!PUBLISHABLE_KEY) {
      // eslint-disable-next-line no-console
      console.warn('[CardCollector] EXPO_PUBLIC_STRIPE_PUBLISHABLE_KEY is not set.');
      return Promise.resolve(null);
    }
    _stripePromise = loadStripe(PUBLISHABLE_KEY);
  }
  return _stripePromise;
}

// ─────────────────────────────────────────────────────────────────────────────
// Inner — must be a child of <Elements> to use useStripe()/useElements().
// ─────────────────────────────────────────────────────────────────────────────
const InnerCollector = forwardRef<CardCollectorHandle, Props>(function InnerCollector(
  { cardholderName, onReady },
  ref,
) {
  const stripe = useStripe();
  const elements = useElements();
  const [elReady, setElReady] = useState(false);
  const [elError, setElError] = useState<string | null>(null);

  useEffect(() => {
    if (onReady) onReady(Boolean(stripe && elements && elReady));
  }, [stripe, elements, elReady, onReady]);

  useImperativeHandle(
    ref,
    () => ({
      tokenize: async () => {
        if (!stripe || !elements) throw new Error('Stripe Elements not ready');
        const card = elements.getElement(CardElement);
        if (!card) throw new Error('Card element not mounted');
        const res = await stripe.createToken(card, {
          name: (cardholderName || 'Squad Lead').slice(0, 64),
        });
        if (res.error) {
          throw new Error(res.error.message || 'Card validation failed');
        }
        const tok = res.token;
        return {
          token: tok.id,
          last4: (tok.card && tok.card.last4) || '****',
        };
      },
    }),
    [stripe, elements, cardholderName],
  );

  return (
    <View>
      <View
        style={[
          styles.elementBox,
          elError ? { borderColor: COLORS.danger } : null,
        ]}
      >
        {/* CardElement renders an iframe — we wrap with a styled View. */}
        {/* eslint-disable-next-line react/no-unknown-property */}
        <View nativeID="stripe-card-element-wrap" style={{ minHeight: 24 }}>
          {/* @ts-expect-error react-native View accepts DOM children on web */}
          <CardElement
            onReady={() => setElReady(true)}
            onChange={(ev: any) => setElError(ev?.error?.message || null)}
            options={{
              style: {
                base: {
                  fontSize: '16px',
                  color: '#0F172A',
                  '::placeholder': { color: '#94A3B8' },
                  fontFamily:
                    'system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
                },
                invalid: { color: '#DC2626' },
              },
              hidePostalCode: false,
            }}
          />
        </View>
      </View>
      {!stripe || !elements || !elReady ? (
        <View style={styles.loadingRow}>
          <ActivityIndicator size="small" color={COLORS.primary} />
          <Text style={styles.loadingText}>Loading secure card form…</Text>
        </View>
      ) : null}
      {elError ? <Text style={styles.errorText}>{elError}</Text> : null}
    </View>
  );
});

// ─────────────────────────────────────────────────────────────────────────────
// Outer — wraps Inner with <Elements> provider.
// ─────────────────────────────────────────────────────────────────────────────
export const CardCollector = forwardRef<CardCollectorHandle, Props>(function CardCollector(
  props,
  ref,
) {
  if (Platform.OS !== 'web') {
    // Defensive — this file is .web.tsx so should never run on native, but
    // if Metro mis-resolves we want a clear error rather than a crash.
    return (
      <View style={styles.fallback}>
        <Text style={styles.fallbackText}>
          Card collector unavailable on this platform.
        </Text>
      </View>
    );
  }
  const stripePromise = useMemo(() => getStripePromise(), []);
  return (
    <Elements stripe={stripePromise as any}>
      <InnerCollector {...props} ref={ref} />
    </Elements>
  );
});

CardCollector.displayName = 'CardCollector';
export default CardCollector;

const styles = StyleSheet.create({
  elementBox: {
    borderWidth: 1,
    borderColor: COLORS.border,
    borderRadius: RADIUS.md,
    paddingHorizontal: SPACING.md,
    paddingVertical: 14,
    backgroundColor: COLORS.surface,
  },
  loadingRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: SPACING.sm,
    marginTop: SPACING.sm,
  },
  loadingText: { fontSize: FONT.small, color: COLORS.subtext, marginLeft: 6 },
  errorText: { color: COLORS.danger, fontSize: FONT.small, marginTop: 6 },
  fallback: { padding: SPACING.md, alignItems: 'center' },
  fallbackText: { color: COLORS.subtext },
});

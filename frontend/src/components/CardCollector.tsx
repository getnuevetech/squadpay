/**
 * CardCollector — NATIVE variant (iOS / Android).
 *
 * Uses `@stripe/stripe-react-native`'s `CardField` + `useStripe()` to
 * tokenise the card via Stripe.js native SDK. PAN never touches our
 * backend; we only receive a `tok_xxx` token.
 *
 * The root layout already wraps the app in `<StripeProvider>` (see
 * StripeNativeProvider.tsx), so we can just consume the hook directly.
 *
 * Imperative ref API (parity with .web.tsx):
 *   await ref.current?.tokenize()  →  { token: 'tok_xxx', last4: '4242' }
 */
import { forwardRef, useImperativeHandle, useState, useEffect, useRef } from 'react';
import { Platform, StyleSheet, Text, View } from 'react-native';
import { COLORS, FONT, RADIUS, SPACING } from '../theme';

export type CardCollectorHandle = {
  tokenize: () => Promise<{ token: string; last4: string }>;
};

type Props = {
  cardholderName?: string;
  onReady?: (ready: boolean) => void;
};

// Lazy-require so the .web.tsx bundle never tries to evaluate native code.
let _stripeNativeMod: any = null;
function getStripeMod() {
  if (_stripeNativeMod) return _stripeNativeMod;
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    _stripeNativeMod = require('@stripe/stripe-react-native');
    return _stripeNativeMod;
  } catch {
    return null;
  }
}

export const CardCollector = forwardRef<CardCollectorHandle, Props>(function CardCollector(
  { cardholderName, onReady },
  ref,
) {
  const mod = getStripeMod();
  const CardField = mod?.CardField as any;
  const useStripe = mod?.useStripe as any;

  // useStripe may be undefined if the native module didn't load — guard.
  const stripe = typeof useStripe === 'function' ? useStripe() : null;
  const [complete, setComplete] = useState(false);
  const [errMsg, setErrMsg] = useState<string | null>(null);
  const detailsRef = useRef<any>(null);

  useEffect(() => {
    if (onReady) onReady(Boolean(stripe && CardField));
  }, [stripe, CardField, onReady]);

  useImperativeHandle(
    ref,
    () => ({
      tokenize: async () => {
        if (!stripe) throw new Error('Stripe SDK not ready');
        if (!detailsRef.current?.complete) {
          throw new Error('Please complete the card details');
        }
        const { token, error } = await stripe.createToken({
          type: 'Card',
          name: (cardholderName || 'Squad Lead').slice(0, 64),
        });
        if (error) {
          throw new Error(error.message || 'Card validation failed');
        }
        return {
          token: token.id,
          last4: (token.card && token.card.last4) || '****',
        };
      },
    }),
    [stripe, cardholderName],
  );

  if (!CardField) {
    return (
      <View style={[styles.fallbackBox]}>
        <Text style={styles.fallbackText}>
          Card payments aren&rsquo;t available in this build. Please use ACH instead.
        </Text>
      </View>
    );
  }

  return (
    <View>
      <View style={styles.fieldWrap}>
        <CardField
          postalCodeEnabled
          placeholders={{ number: '1234 5678 9012 3456' }}
          cardStyle={{
            backgroundColor: COLORS.surface,
            textColor: COLORS.text,
            placeholderColor: COLORS.disabledText,
            borderRadius: RADIUS.md,
            fontSize: 16,
          }}
          style={Platform.OS === 'ios' ? styles.fieldIos : styles.fieldAndroid}
          onCardChange={(details: any) => {
            detailsRef.current = details;
            setComplete(Boolean(details?.complete));
            setErrMsg(details?.validNumber === 'Invalid' ? 'Card number is invalid' : null);
          }}
        />
      </View>
      {errMsg ? <Text style={styles.errorText}>{errMsg}</Text> : null}
      {!complete && !errMsg ? (
        <Text style={styles.hintText}>Enter card details to continue.</Text>
      ) : null}
    </View>
  );
});

CardCollector.displayName = 'CardCollector';
export default CardCollector;

const styles = StyleSheet.create({
  fieldWrap: {
    borderWidth: 1,
    borderColor: COLORS.border,
    borderRadius: RADIUS.md,
    backgroundColor: COLORS.surface,
    overflow: 'hidden',
  },
  fieldIos: { width: '100%', height: 50 },
  fieldAndroid: { width: '100%', height: 56 },
  errorText: { color: COLORS.danger, fontSize: FONT.small, marginTop: 6 },
  hintText: { color: COLORS.subtext, fontSize: FONT.small, marginTop: 6 },
  fallbackBox: {
    borderWidth: 1,
    borderColor: COLORS.border,
    borderRadius: RADIUS.md,
    padding: SPACING.md,
    backgroundColor: COLORS.surface,
  },
  fallbackText: { color: COLORS.subtext, fontSize: FONT.small, textAlign: 'center' },
});

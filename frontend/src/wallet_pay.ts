/**
 * Native-only wallet-pay helper (Phase 7).
 *
 * Wraps `@stripe/stripe-react-native`'s PaymentSheet so the rest of the app
 * never imports the native module directly. A `.web.ts` sibling exists that
 * throws so any accidental web call surfaces immediately.
 *
 * Why a separate file?
 * Metro statically follows every `require('@stripe/stripe-react-native')`
 * call — even ones nested inside runtime guards — and tries to bundle the
 * native module on web (which fails). Splitting the import into a
 * platform-resolved file (`wallet_pay.ts` vs `wallet_pay.web.ts`) tells
 * Metro to skip the native module entirely on web.
 */
// eslint-disable-next-line @typescript-eslint/no-require-imports
const Stripe = require('@stripe/stripe-react-native');

export type WalletInitArgs = {
  merchantDisplayName: string;
  customerId: string;
  customerEphemeralKeySecret: string;
  paymentIntentClientSecret: string;
  returnURL?: string;
  applePayMerchantCountryCode?: string;
  googlePayMerchantCountryCode?: string;
};

export async function payWithNativeWallet(args: WalletInitArgs): Promise<{ status: 'ok' | 'cancel' | 'error'; message?: string }> {
  const init = await Stripe.initPaymentSheet({
    merchantDisplayName: args.merchantDisplayName,
    customerId: args.customerId,
    customerEphemeralKeySecret: args.customerEphemeralKeySecret,
    paymentIntentClientSecret: args.paymentIntentClientSecret,
    applePay: { merchantCountryCode: args.applePayMerchantCountryCode || 'US' },
    googlePay: {
      merchantCountryCode: args.googlePayMerchantCountryCode || 'US',
      testEnv: true,
      currencyCode: 'USD',
    },
    allowsDelayedPaymentMethods: false,
    returnURL: args.returnURL || 'squadpay://stripe-redirect',
  });
  if (init?.error) return { status: 'error', message: init.error.message || 'Could not init payment sheet' };
  const res = await Stripe.presentPaymentSheet();
  if (res?.error) {
    if (res.error.code === 'Canceled') return { status: 'cancel' };
    return { status: 'error', message: res.error.message || 'Payment failed' };
  }
  return { status: 'ok' };
}

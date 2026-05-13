/**
 * Web stub for wallet_pay (Phase 7).
 * Native Apple Pay / Google Pay is only available on iOS/Android via
 * @stripe/stripe-react-native; on web we fall back to Stripe Checkout
 * (which itself surfaces Apple Pay / Google Pay buttons in the browser).
 */
export type WalletInitArgs = {
  merchantDisplayName: string;
  customerId: string;
  customerEphemeralKeySecret: string;
  paymentIntentClientSecret: string;
  returnURL?: string;
  applePayMerchantCountryCode?: string;
  googlePayMerchantCountryCode?: string;
};

export async function payWithNativeWallet(_args: WalletInitArgs): Promise<{ status: 'ok' | 'cancel' | 'error'; message?: string }> {
  return { status: 'error', message: 'Native wallet not available on web. Use Stripe Checkout fallback.' };
}

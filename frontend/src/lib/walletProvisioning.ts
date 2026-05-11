/**
 * Native Push Provisioning shims for SquadPay.
 *
 * Exposes a single async API:
 *
 *    import { addCardToWallet, isWalletProvisioningAvailable } from '@/src/lib/walletProvisioning';
 *
 *    if (await isWalletProvisioningAvailable()) {
 *      await addCardToWallet({ groupId, userId });
 *    }
 *
 * Internally this calls our backend `POST /api/cards/{groupId}/provision`,
 * inspects the returned `status`, and — only on `ready` — hands the encrypted
 * payload to the OS-native wallet activation request:
 *
 *   • iOS    → PKAddPaymentPassRequestConfiguration / PKAddPaymentPassRequest
 *              via the `react-native-passkit-wallet` bridge.
 *   • Android → PushTokenizeRequest via the Google Tap & Pay SDK bridge
 *               (`react-native-android-wallet`).
 *
 * Until Stripe + Visa/Mastercard + Apple/Google all approve, the backend
 * returns `pending_psp_approval` and this function surfaces a graceful
 * "coming soon" message — the same UX users see today.
 *
 * No frontend changes are needed when approvals land. The backend swap
 * (stub → real `stripe.issuing.Card.create_push_provisioning_data(...)`)
 * is the only code change required.
 */
import { Platform, Alert, NativeModules, Linking } from 'react-native';
import { toast } from '../components/Toast';

// ──────────────────────────────────────────────────────────────────────────
// Types
// ──────────────────────────────────────────────────────────────────────────

export type WalletPlatform = 'apple' | 'google';

export type ProvisionStatus =
  | 'ready'
  | 'pending_psp_approval'
  | 'card_not_issued'
  | 'not_lead'
  | 'unsupported_platform';

interface BackendProvisionResponse {
  ok: boolean;
  status: ProvisionStatus;
  payload: AppleProvisioningPayload | GoogleProvisioningPayload | null;
  message?: string;
}

/**
 * Apple Wallet payload — mirrors what `stripe.issuing.Card.create_push_provisioning_data`
 * returns for `platform=apple`. Fed into `PKAddPaymentPassRequest`.
 */
interface AppleProvisioningPayload {
  activation_data: string;          // base64
  encrypted_pass_data: string;      // base64
  ephemeral_public_key: string;     // base64
  // Cardholder display info — shown on the wallet card face
  cardholder_name: string;
  primary_account_suffix: string;   // last 4
  localized_description: string;    // e.g. "SquadPay · Slick Willie's"
  payment_network: 'visa' | 'mastercard';
}

/**
 * Google Wallet payload — mirrors the Google Tap & Pay `PushTokenizeRequest`
 * constructor arguments.
 */
interface GoogleProvisioningPayload {
  opaque_payment_card: string;      // base64
  user_address: {
    name: string;
    address1?: string;
    locality?: string;
    administrative_area?: string;
    country_code?: string;
    postal_code?: string;
    phone_number: string;
  };
  network: 'VISA' | 'MASTERCARD';
  token_service_provider: 'TOKEN_PROVIDER_VISA' | 'TOKEN_PROVIDER_MASTERCARD';
  display_name: string;             // e.g. "SquadPay · Slick Willie's"
  last_digits: string;
}

interface AddCardArgs {
  groupId: string;
  userId: string;
}

// ──────────────────────────────────────────────────────────────────────────
// Native bridges (declared optional — present only in EAS production builds)
// ──────────────────────────────────────────────────────────────────────────
//
// In Expo Go these modules are absent; we degrade to a graceful toast.
// In an EAS production build with the entitlements granted, these bridges
// are linked by the config-plugin in /app/frontend/plugins/withWalletProvisioning.js
// (see that file for the autolinking setup).

interface SquadPayWalletNativeAPI {
  isAvailable(): Promise<boolean>;
  /** iOS path: PKAddPaymentPassRequestConfiguration + PKAddPaymentPassRequest */
  addToAppleWallet(payload: AppleProvisioningPayload): Promise<{ added: boolean }>;
  /** Android path: PushTokenizeRequest via Google Tap & Pay SDK */
  addToGoogleWallet(payload: GoogleProvisioningPayload): Promise<{ added: boolean }>;
}

const NativeBridge: SquadPayWalletNativeAPI | undefined =
  (NativeModules as any)?.SquadPayWallet;

// ──────────────────────────────────────────────────────────────────────────
// Public API
// ──────────────────────────────────────────────────────────────────────────

export async function isWalletProvisioningAvailable(): Promise<boolean> {
  // Web → never available (Apple/Google Wallet are device-native only).
  if (Platform.OS === 'web') return false;

  // Expo Go → native bridge is absent. We still allow the UI to call our
  // backend so users see the "coming soon" toast instead of nothing.
  if (!NativeBridge) return false;

  try {
    return await NativeBridge.isAvailable();
  } catch {
    return false;
  }
}

export async function addCardToWallet({ groupId, userId }: AddCardArgs): Promise<void> {
  const platform: WalletPlatform = Platform.OS === 'ios' ? 'apple' : 'google';

  // 1. Ask our backend for the provisioning payload.
  const base = process.env.EXPO_PUBLIC_BACKEND_URL || '';
  let res: BackendProvisionResponse;
  try {
    const r = await fetch(`${base}/api/cards/${groupId}/provision`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: userId, platform }),
    });
    res = await r.json();
  } catch (e: any) {
    toast.error(e?.message || 'Could not reach SquadPay servers');
    return;
  }

  // 2. Branch on the backend status. Today this is always
  //    `pending_psp_approval` — the UX message is intentionally polished.
  switch (res.status) {
    case 'pending_psp_approval':
      toast.info(
        'Apple/Google Wallet support is launching soon — we\'re finalising approvals with our bank network.',
      );
      return;

    case 'card_not_issued':
      toast.error('Fully fund the bill first to issue the card.');
      return;

    case 'not_lead':
      toast.error('Only the bill lead can add the card to a wallet.');
      return;

    case 'unsupported_platform':
      toast.error(
        Platform.OS === 'web'
          ? 'Open SquadPay on your phone to add the card to your wallet.'
          : 'This platform doesn\'t support digital wallets yet.',
      );
      return;

    case 'ready':
      break; // continue below
  }

  // 3. We have a real payload. Hand it to the native bridge.
  if (!NativeBridge) {
    Alert.alert(
      'Update required',
      'Please update SquadPay to the latest version to add cards to your wallet.',
      [
        { text: 'Not now', style: 'cancel' },
        {
          text: 'Update',
          onPress: () => {
            const url = Platform.OS === 'ios'
              ? 'https://apps.apple.com/app/squadpay/id0000000000'
              : 'https://play.google.com/store/apps/details?id=com.squadpay.app';
            Linking.openURL(url).catch(() => undefined);
          },
        },
      ],
    );
    return;
  }

  try {
    if (Platform.OS === 'ios') {
      const result = await NativeBridge.addToAppleWallet(
        res.payload as AppleProvisioningPayload,
      );
      if (result.added) toast.success('Card added to Apple Wallet');
    } else {
      const result = await NativeBridge.addToGoogleWallet(
        res.payload as GoogleProvisioningPayload,
      );
      if (result.added) toast.success('Card added to Google Wallet');
    }
  } catch (e: any) {
    const msg = e?.message || 'Could not add card to wallet';
    if (/cancel/i.test(msg)) return; // user dismissed the OS sheet
    toast.error(msg);
  }
}

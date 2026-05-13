import { useLocalSearchParams, useRouter } from 'expo-router';
import { useEffect, useState } from 'react';
import {
  Alert,
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Apple, Check, CreditCard, Lock, Smartphone, Wallet, ShieldCheck, Sparkles, Receipt } from 'lucide-react-native';
import { Button } from '../../../src/Button';
import { GradientButton } from '../../../src/components/GradientButton';
import { api, Group } from '../../../src/api';
import { refreshUser, saveUser } from '../../../src/session';
import { COLORS, FONT, RADIUS, SHADOW, SPACING } from '../../../src/theme';
import { toast } from '../../../src/components/Toast';
import { friendlySmsError } from '../../../src/sms_errors';

type Kind = 'lead' | 'repay' | 'contribute';
type VerifyStep = 'idle' | 'phone' | 'otp';

// Phase H4 — single line of the breakdown card.
// `tone` controls color: default/success(green)/warning(amber)/primary(indigo).
function BreakRow({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: number;
  hint?: string;
  tone?: 'success' | 'warning' | 'primary';
}) {
  const isNeg = value < 0;
  const valueColor =
    tone === 'success' ? COLORS.success :
    tone === 'warning' ? COLORS.warning :
    tone === 'primary' ? COLORS.primary :
    COLORS.text;
  const sign = isNeg ? '−' : '';
  const abs = Math.abs(value).toFixed(2);
  return (
    <View style={breakRowStyles.row}>
      <View style={{ flex: 1 }}>
        <Text style={breakRowStyles.label}>{label}</Text>
        {hint ? <Text style={breakRowStyles.hint}>{hint}</Text> : null}
      </View>
      <Text style={[breakRowStyles.value, { color: valueColor }]}>
        {sign}${abs}
      </Text>
    </View>
  );
}

const breakRowStyles = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'space-between', gap: SPACING.sm, paddingVertical: 6 },
  label: { fontSize: FONT.sizes.sm, color: COLORS.text, fontWeight: FONT.weights.medium },
  hint: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: 2 },
  value: { fontSize: FONT.sizes.md, fontWeight: FONT.weights.semibold, fontVariant: ['tabular-nums'] as any },
});

export default function PayScreen() {
  const { id, kind, session_id: sessionIdFromUrl, contrib_session_id: contribSessionId, stripe_cancel } = useLocalSearchParams<{
    id: string;
    kind?: Kind;
    session_id?: string;
    contrib_session_id?: string;
    stripe_cancel?: string;
  }>();
  const router = useRouter();
  const [group, setGroup] = useState<Group | null>(null);
  const [userId, setUserId] = useState<string | null>(null);
  const [isVerified, setIsVerified] = useState(false);
  const [loading, setLoading] = useState(false);
  const [stripeBusy, setStripeBusy] = useState(false);
  const [stripeBanner, setStripeBanner] = useState<string | null>(null);

  // Inline verification state
  const [verifyStep, setVerifyStep] = useState<VerifyStep>('idle');
  const [phone, setPhone] = useState('');
  const [otp, setOtp] = useState('');
  const [verifyLoading, setVerifyLoading] = useState(false);

  // Receipt-update opt-in (contribute flow only)
  const [notifyOnSettled, setNotifyOnSettled] = useState(true);

  // Phase H4 — wallet credits balance for breakdown preview
  const [creditBalance, setCreditBalance] = useState(0);

  // Shortfall settlement (lead pay flow only)
  const [shortfallMode, setShortfallMode] = useState<'lead' | 'member' | 'split_equal'>('lead');
  const [isLoan, setIsLoan] = useState<boolean>(true);
  const [funderMemberId, setFunderMemberId] = useState<string | null>(null);
  // Phase H6.4 — track whether the OTP we just sent was mocked or live so the
  // hint UI can show "(Demo: 123456)" only in mock mode.
  // NOTE: kept up here (above the early-return guard) so hook order stays stable.
  const [otpMocked, setOtpMocked] = useState<boolean | null>(null);

  // Phase 7 — Native wallet pay (Apple Pay / Google Pay via Stripe PaymentSheet).
  // IMPORTANT: declared above the `if (!group || !userId) return null;` early-return
  // so React's Rules of Hooks (consistent order across renders) is preserved.
  const [nativePayBusy, setNativePayBusy] = useState(false);
  const [nativePayAvailable, setNativePayAvailable] = useState(false);
  // #13 — admin-controlled wallet flags. Default both ON so first-loads
  // don't suppress the button; refresh from server below.
  const [walletFlags, setWalletFlags] = useState({ apple: true, google: true });

  useEffect(() => {
    if (Platform.OS === 'web') return;
    if (kind !== 'contribute') return;
    (async () => {
      try {
        const r = await api.stripePublishableKey();
        setNativePayAvailable(!!r.configured);
        setWalletFlags({
          apple: r.apple_pay_enabled !== false,
          google: r.google_pay_enabled !== false,
        });
      } catch {}
    })();
  }, [kind]);

  useEffect(() => {
    (async () => {
      const u = await refreshUser();
      if (!u) {
        router.replace('/auth');
        return;
      }
      setUserId(u.id);
      setIsVerified(u.verified);
      if (u.phone) setPhone(u.phone);
      try {
        const g = await api.getGroup(id);
        setGroup(g);
      } catch (e: any) {
        Alert.alert('Error', e.message);
      }
      // Best-effort: fetch wallet credits to preview in breakdown
      try {
        const c = await api.getUserCredits(u.id);
        setCreditBalance(c.balance || 0);
      } catch (_e) {
        // non-fatal — credits feature may be off
      }
    })();
  }, [id, router]);

  // Phase E: handle return from Stripe Checkout
  useEffect(() => {
    if (!sessionIdFromUrl || !id) return;
    let cancelled = false;
    let attempts = 0;
    const maxAttempts = 8;
    const poll = async () => {
      try {
        const r = await api.getCheckoutStatus(sessionIdFromUrl);
        if (cancelled) return;
        if (r.payment_status === 'paid' || r.applied) {
          setStripeBanner('✅ Payment confirmed via Stripe.');
          // Refresh group to reflect paid status
          try { setGroup(await api.getGroup(id)); } catch {}
          // Also navigate to success
          setTimeout(() => router.replace(`/group/${id}/success?amount=${(r.amount_total/100).toFixed(2)}&kind=lead&via=stripe`), 1200);
          return;
        }
        if (r.status === 'expired') {
          setStripeBanner('⚠️ Stripe session expired. Please try again.');
          return;
        }
        attempts += 1;
        if (attempts < maxAttempts) {
          setStripeBanner(`Confirming with Stripe… (${attempts}/${maxAttempts})`);
          setTimeout(poll, 2000);
        } else {
          setStripeBanner('Status check timed out — refresh the page if your bill is not marked paid.');
        }
      } catch (e: any) {
        if (!cancelled) setStripeBanner(`Status error: ${e?.message || 'unknown'}`);
      }
    };
    setStripeBanner('Confirming with Stripe…');
    poll();
    return () => { cancelled = true; };
  }, [sessionIdFromUrl, id, router]);

  // Phase F1: handle return from Stripe Checkout for member contribution
  useEffect(() => {
    if (!contribSessionId || !id) return;
    let cancelled = false;
    let attempts = 0;
    const maxAttempts = 8;
    const poll = async () => {
      try {
        const r = await api.getContributeStatus(contribSessionId);
        if (cancelled) return;
        if (r.payment_status === 'paid' || r.applied) {
          setStripeBanner('✅ Contribution confirmed via Stripe.');
          try { setGroup(await api.getGroup(id)); } catch {}
          try {
            (globalThis as any).__SQUADPAY_AWARDED_CREDITS__ = (r as any).awarded_credits || [];
          } catch {}
          setTimeout(() => router.replace(`/group/${id}/success?amount=${((r.amount_total||0)/100).toFixed(2)}&kind=contribute&via=stripe`), 1200);
          return;
        }
        if (r.status === 'expired') {
          setStripeBanner('⚠️ Stripe session expired. Please try again.');
          return;
        }
        attempts += 1;
        if (attempts < maxAttempts) {
          setStripeBanner(`Confirming contribution… (${attempts}/${maxAttempts})`);
          setTimeout(poll, 2000);
        } else {
          setStripeBanner('Status check timed out — refresh if your contribution is not reflected.');
        }
      } catch (e: any) {
        if (!cancelled) setStripeBanner(`Status error: ${e?.message || 'unknown'}`);
      }
    };
    setStripeBanner('Confirming contribution with Stripe…');
    poll();
    return () => { cancelled = true; };
  }, [contribSessionId, id, router]);

  // Phase E: cancel banner
  useEffect(() => {
    if (stripe_cancel) setStripeBanner('Stripe payment was cancelled.');
  }, [stripe_cancel]);

  const onPayWithStripe = async () => {
    if (!group || !id) return;
    if (group.funding && (group.funding.remaining_to_collect || 0) <= 0.01) {
      Alert.alert('Already covered', 'There is no remaining balance to charge.');
      return;
    }
    setStripeBusy(true);
    try {
      const origin = Platform.OS === 'web' && typeof window !== 'undefined'
        ? window.location.origin
        : (process.env.EXPO_PUBLIC_BACKEND_URL || '').replace(/\/api$/, '');
      let appReturnUrl: string | undefined;
      if (Platform.OS !== 'web') {
        try {
          const Linking = require('expo-linking');
          appReturnUrl = Linking.createURL(`/group/${id}/pay`);
        } catch {}
      }
      const r = await api.createCheckoutSession(id, origin, appReturnUrl);
      if (Platform.OS === 'web' && typeof window !== 'undefined') {
        window.location.href = r.url;
      } else {
        try {
          const WebBrowser = require('expo-web-browser');
          const result = await WebBrowser.openAuthSessionAsync(r.url, appReturnUrl || origin);
          if (result?.type === 'success' && typeof result.url === 'string') {
            try {
              const Linking = require('expo-linking');
              const parsed = Linking.parse(result.url);
              const qp: any = parsed?.queryParams || {};
              if (qp.stripe_cancel) {
                setStripeBanner('Stripe payment was cancelled.');
              } else if (qp.session_id) {
                router.replace(`/group/${id}/pay?kind=lead&session_id=${encodeURIComponent(qp.session_id)}`);
              }
            } catch {
              try { setGroup(await api.getGroup(id)); } catch {}
            }
          } else if (result?.type === 'cancel' || result?.type === 'dismiss') {
            setStripeBanner('Stripe payment was cancelled or dismissed.');
            try { setGroup(await api.getGroup(id)); } catch {}
          }
        } catch {
          Alert.alert('Open in browser', r.url);
        }
      }
    } catch (e: any) {
      Alert.alert('Stripe error', e?.message || 'Could not start Stripe checkout.');
    } finally {
      setStripeBusy(false);
    }
  };

  if (!group || !userId) return null;

  const myPer = group.per_user.find((p) => p.user_id === userId);

  // Compute amount + label per kind
  let amount = 0;
  let title = 'Pay';
  let summary = '';
  let actorIcon = <Smartphone color={COLORS.primary} size={18} />;
  let actorTitle = 'In-app balance';
  let actorSub = '';

  if (kind === 'lead') {
    amount = group.funding.remaining_to_collect;
    title = 'Pay restaurant';
    summary =
      group.funding.total_contributed > 0
        ? `Group already covered $${group.funding.total_contributed.toFixed(2)}. You cover the rest.`
        : `Charge the bill to a real Stripe checkout, or fall back to the virtual card.`;
    actorIcon = <CreditCard color={COLORS.primary} size={18} />;
    actorTitle = 'Stripe Checkout (or Virtual Card)';
    actorSub = 'Real card payment via Stripe — virtual card fallback for shortfalls';
  } else if (kind === 'contribute') {
    // Both lead and members use this flow to fund the wallet upfront.
    // Lead's outstanding is force-zeroed in backend (they pay merchant), so we compute
    // contribute amount as: their share + any shortfall obligation - already contributed.
    const myShare = myPer?.total || 0;
    const myContrib = myPer?.contributed || 0;
    const myShortfallOwed = myPer?.shortfall_owed || 0;
    amount = Math.max(0, myShare + myShortfallOwed - myContrib);
    const hasShortfall = myShortfallOwed > 0.01;
    title = hasShortfall ? 'Pay your share + shortfall' : 'CONTRIBUTE YOUR SHARE';
    summary = hasShortfall
      ? `Includes your shortfall obligation of $${myShortfallOwed.toFixed(2)}. Pay so the bill can be settled.`
      : '';
    actorIcon = <Wallet color={COLORS.primary} size={18} />;
    // Replace the legacy "Group wallet · Funds held until the merchant is paid"
    // pill with the actual squad name so the user immediately recognizes
    // which bill they're contributing to.
    actorTitle = group.title || 'Your squad';
    actorSub = '';
  } else {
    amount = myPer?.outstanding || 0;
    title = 'Pay your share';
    summary = `Reimburse the lead for what they covered upfront.`;
  }

  const blockedNoAmount = amount <= 0;

  const sendOtp = async () => {
    const cleaned = phone.trim();
    if (cleaned.length < 7) {
      Alert.alert('Enter a valid phone number');
      return;
    }
    setVerifyLoading(true);
    try {
      const r = await api.sendOtp(userId, cleaned);
      setOtpMocked(!!r.mocked);
      setVerifyStep('otp');
      if (r.live) {
        toast.success('Code sent to your phone');
      }
    } catch (e: any) {
      const f = friendlySmsError(e?.message);
      Alert.alert(f.title, f.message);
    } finally {
      setVerifyLoading(false);
    }
  };

  const verifyCode = async () => {
    if (!userId) return;
    if (otp.length !== 6) {
      Alert.alert('Enter the 6-digit code');
      return;
    }
    setVerifyLoading(true);
    try {
      // Phase H2 (pay flow) — pre-flight: detect "phone already registered to another account"
      // BEFORE we hand over the OTP, so we can ask the user before merging — same UX as
      // the initial sign-in screen.
      let confirmExisting = false;
      try {
        const lookup = await api.lookupPhone(phone.trim(), userId);
        if (lookup?.exists && !lookup.blocked && lookup.name) {
          const proceed = await new Promise<boolean>((resolve) => {
            Alert.alert(
              'Phone already registered',
              `An account with this number is already registered as "${lookup.name}".\n\nDo you want to sign in to that account? Your current session will switch to "${lookup.name}", and any group you started will stay yours under the registered name.`,
              [
                { text: 'Cancel', style: 'cancel', onPress: () => resolve(false) },
                { text: `Use ${lookup.name}`, onPress: () => resolve(true) },
              ],
              { cancelable: false },
            );
          });
          if (!proceed) {
            setVerifyLoading(false);
            return;
          }
          confirmExisting = true;
        } else if (lookup?.blocked) {
          Alert.alert(
            'Account blocked',
            'This phone number is associated with a blocked account. Please contact support.',
          );
          setVerifyLoading(false);
          return;
        }
      } catch (_e) {
        // best-effort; fall back to server 409 below
      }

      const finishVerify = async (u: any) => {
        await saveUser(u);
        // If the account merged, our local userId changes to the merged account's id.
        if (u?.id && u.id !== userId) {
          setUserId(u.id);
          // Refresh group so per_user / membership reflects the merged identity.
          try {
            const g = await api.getGroup(id as string);
            setGroup(g);
          } catch (_e) {
            // non-fatal — group view will refresh on next focus
          }
        }
        setIsVerified(true);
        setVerifyStep('idle');
        setOtp('');
      };

      try {
        const u = await api.verifyOtp(userId, phone.trim(), otp, confirmExisting);
        await finishVerify(u);
      } catch (e: any) {
        const msg = String(e?.message || '');
        if (msg.includes('phone_already_registered') || msg.includes('already registered')) {
          // Server fallback (e.g. lookup couldn't run): surface the same prompt.
          const proceed = await new Promise<boolean>((resolve) => {
            Alert.alert(
              'Phone already registered',
              'An account with this number is already registered. Do you want to sign in to that account?',
              [
                { text: 'Cancel', style: 'cancel', onPress: () => resolve(false) },
                { text: 'Use existing', onPress: () => resolve(true) },
              ],
              { cancelable: false },
            );
          });
          if (proceed) {
            const u = await api.verifyOtp(userId, phone.trim(), otp, true);
            await finishVerify(u);
          }
        } else {
          throw e;
        }
      }
    } catch (e: any) {
      Alert.alert('Invalid code', e?.message || 'Verification failed');
    } finally {
      setVerifyLoading(false);
    }
  };

  // ──────────────────────────────────────────────────────────────────────
  // Phase 7 — Native wallet pay handler (state + effect hoisted to top of component)
  // ──────────────────────────────────────────────────────────────────────
  const onPayWithWallet = async () => {
    if (Platform.OS === 'web') return;
    if (!isVerified) { setVerifyStep('phone'); return; }
    if (blockedNoAmount || amount <= 0) {
      Alert.alert('Nothing to pay', 'Amount is zero.');
      return;
    }
    setNativePayBusy(true);
    try {
      const pi = await api.contributePaymentIntent(group.id, {
        user_id: userId,
        amount,
        notify_on_settled: notifyOnSettled,
      });
      // Platform-resolved helper — on web this is a stub that returns error.
      // On native it bridges to @stripe/stripe-react-native PaymentSheet.
      // eslint-disable-next-line @typescript-eslint/no-require-imports
      const { payWithNativeWallet } = require('../../../src/wallet_pay');
      const res = await payWithNativeWallet({
        merchantDisplayName: pi.merchant_display_name || 'SquadPay',
        customerId: pi.customer_id,
        customerEphemeralKeySecret: pi.ephemeral_key_secret,
        paymentIntentClientSecret: pi.client_secret,
        returnURL: 'squadpay://stripe-redirect',
      });
      if (res.status === 'cancel') return;
      if (res.status === 'error') throw new Error(res.message || 'Payment failed');
      // Finalize on backend
      const fin = await api.finalizeContributePaymentIntent(group.id, pi.payment_intent_id);
      if (fin.applied) {
        try { (globalThis as any).__SQUADPAY_AWARDED_CREDITS__ = fin.awarded_credits || []; } catch {}
        router.replace(`/group/${group.id}/success?amount=${amount.toFixed(2)}&kind=contribute&via=wallet`);
      } else {
        Alert.alert('Payment status', `Stripe reports: ${fin.payment_status}`);
      }
    } catch (e: any) {
      Alert.alert('Wallet payment failed', e?.message || 'Please try card payment instead.');
    } finally {
      setNativePayBusy(false);
    }
  };

  const doPay = async () => {
    if (!isVerified) {
      setVerifyStep('phone');
      return;
    }
    if (blockedNoAmount) {
      Alert.alert('Nothing to pay', 'Amount is zero.');
      return;
    }
    setLoading(true);
    try {
      if (kind === 'lead') {
        const opts: any = {};
        if ((group.funding?.remaining_to_collect || 0) > 0.01) {
          opts.shortfall_mode = shortfallMode;
          opts.is_loan = shortfallMode === 'split_equal' ? true : isLoan;
          if (shortfallMode === 'member') {
            if (!funderMemberId) {
              Alert.alert('Pick a member', 'Choose who will cover the shortfall.');
              setLoading(false);
              return;
            }
            opts.funder_member_id = funderMemberId;
          }
        }
        await api.payGroup(group.id, userId, opts);
        // For member / split_equal: merchant pay is DEFERRED — return to summary with a toast
        if (shortfallMode !== 'lead' && (group.funding?.remaining_to_collect || 0) > 0.01) {
          const verb = shortfallMode === 'member' ? 'sent to the member' : 'split among members';
          toast.success(`Shortfall ${verb}`);
          router.replace(`/group/${group.id}`);
          return;
        }
      } else if (kind === 'contribute') {
        // Phase F1: contribute via Stripe Checkout (real card) — credits applied automatically.
        // Phase F1.1: native uses deep-link bridge so the in-app browser auto-closes after payment.
        const origin =
          Platform.OS === 'web' && typeof window !== 'undefined'
            ? window.location.origin
            : (process.env.EXPO_PUBLIC_BACKEND_URL || '').replace(/\/api$/, '');
        let appReturnUrl: string | undefined;
        if (Platform.OS !== 'web') {
          try {
            const Linking = require('expo-linking');
            appReturnUrl = Linking.createURL(`/group/${group.id}/pay`);
          } catch {}
        }
        const r: any = await api.contribute(group.id, userId, amount, notifyOnSettled, origin, appReturnUrl);
        if (r.checkout_required === false) {
          // Fully covered by credits — no Stripe needed. Stash awarded
          // credits (if any) in a globalThis slot the success page reads.
          try {
            (globalThis as any).__SQUADPAY_AWARDED_CREDITS__ = r.awarded_credits || [];
          } catch {}
          router.replace(
            `/group/${group.id}/success?amount=${amount.toFixed(2)}&kind=contribute&via=credit`,
          );
          return;
        }
        // checkout_required: open Stripe Checkout URL
        if (Platform.OS === 'web' && typeof window !== 'undefined') {
          window.location.href = r.url;
        } else {
          try {
            const WebBrowser = require('expo-web-browser');
            // Use auth-session so the in-app browser auto-closes when it sees our deep link.
            const result = await WebBrowser.openAuthSessionAsync(r.url, appReturnUrl || origin);
            if (result?.type === 'success' && typeof result.url === 'string') {
              // Parse contrib_session_id (or stripe_cancel) from the redirected URL and forward
              try {
                const Linking = require('expo-linking');
                const parsed = Linking.parse(result.url);
                const qp: any = parsed?.queryParams || {};
                if (qp.stripe_cancel) {
                  setStripeBanner('Stripe payment was cancelled.');
                } else if (qp.contrib_session_id) {
                  // Update the URL on this screen so the existing polling effect picks it up.
                  router.replace(`/group/${group.id}/pay?kind=contribute&contrib_session_id=${encodeURIComponent(qp.contrib_session_id)}`);
                }
              } catch (parseErr) {
                // Fallback: refresh group, the webhook will finalize.
                try { setGroup(await api.getGroup(group.id)); } catch {}
              }
            } else if (result?.type === 'cancel' || result?.type === 'dismiss') {
              setStripeBanner('Stripe payment was cancelled or dismissed.');
              // Best-effort refresh in case payment actually completed via webhook.
              try { setGroup(await api.getGroup(group.id)); } catch {}
            }
          } catch {
            Alert.alert('Open in browser', r.url);
          }
        }
        return;
      } else {
        await api.repay(group.id, userId, amount);
      }
      router.replace(
        `/group/${group.id}/success?amount=${amount.toFixed(2)}&kind=${kind || 'repay'}`,
      );
    } catch (e: any) {
      Alert.alert('Payment failed', e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <KeyboardAvoidingView
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      style={{ flex: 1, backgroundColor: COLORS.bg }}
    >
      <SafeAreaView edges={['bottom']} style={{ flex: 1 }}>
        <ScrollView
          contentContainerStyle={styles.scroll}
          keyboardShouldPersistTaps="handled"
        >
          <Text style={styles.label}>{title}</Text>
          <Text style={styles.amount} testID="pay-amount">
            ${amount.toFixed(2)}
          </Text>
          {summary ? <Text style={styles.summary}>{summary}</Text> : null}

          {/* Wallet credits pill (only when user has balance and credits feature is on) */}
          {creditBalance > 0.01 && (kind === 'contribute' || kind === 'repay') ? (
            <View style={styles.creditPill} testID="pay-credit-pill">
              <Sparkles size={13} color={COLORS.primary} />
              <Text style={styles.creditPillText}>
                ${creditBalance.toFixed(2)} wallet credit available — auto-applied at checkout
              </Text>
            </View>
          ) : null}

          {/* Breakdown card — shows the math behind the amount */}
          <View style={[styles.breakdownCard, SHADOW.sm]} testID="pay-breakdown">
            <View style={styles.breakdownHeader}>
              <View style={styles.icon}>{actorIcon}</View>
              <View style={{ flex: 1 }}>
                <Text style={styles.rowTitle}>{actorTitle}</Text>
                {actorSub ? <Text style={styles.rowSub}>{actorSub}</Text> : null}
              </View>
            </View>

            <View style={styles.divider} />

            {kind === 'contribute' && myPer ? (
              <>
                <BreakRow label="Your share of food" value={myPer.food} />
                {(myPer.tax_tip || 0) > 0.001 && (
                  <BreakRow label="Tax & tip share" value={myPer.tax_tip} />
                )}
                {(myPer.platform_fee || 0) > 0.001 && (
                  <BreakRow label="Service fee" value={myPer.platform_fee} hint="Helps us keep SquadPay running" />
                )}
                {(myPer.shortfall_owed || 0) > 0.001 && (
                  <BreakRow label="Shortfall obligation" value={myPer.shortfall_owed} tone="warning" />
                )}
                {(myPer.contributed || 0) > 0.001 && (
                  <BreakRow label="Already contributed" value={-myPer.contributed} tone="success" />
                )}
                {creditBalance > 0.01 && (
                  <BreakRow
                    label="Wallet credits (max applied)"
                    value={-Math.min(creditBalance, amount)}
                    tone="primary"
                    hint="We'll apply automatically at checkout"
                  />
                )}
                <View style={styles.divider} />
                <View style={styles.totalRow}>
                  <Text style={styles.totalLabel}>You'll pay now</Text>
                  <Text style={styles.totalValue}>
                    ${Math.max(0, amount - Math.min(creditBalance, amount)).toFixed(2)}
                  </Text>
                </View>
              </>
            ) : kind === 'repay' && myPer ? (
              <>
                <BreakRow label="Owed to lead" value={myPer.outstanding} />
                {creditBalance > 0.01 && (
                  <BreakRow
                    label="Wallet credits"
                    value={-Math.min(creditBalance, amount)}
                    tone="primary"
                  />
                )}
                <View style={styles.divider} />
                <View style={styles.totalRow}>
                  <Text style={styles.totalLabel}>Total</Text>
                  <Text style={styles.totalValue}>
                    ${Math.max(0, amount - Math.min(creditBalance, amount)).toFixed(2)}
                  </Text>
                </View>
              </>
            ) : kind === 'lead' ? (
              <>
                <BreakRow label="Bill total" value={group.total} />
                <BreakRow
                  label="Group already covered"
                  value={-(group.funding?.total_contributed || 0)}
                  tone="success"
                />
                <View style={styles.divider} />
                <View style={styles.totalRow}>
                  <Text style={styles.totalLabel}>You'll pay merchant</Text>
                  <Text style={styles.totalValue}>${amount.toFixed(2)}</Text>
                </View>
              </>
            ) : null}

            <View style={styles.secureBadge}>
              <Lock size={12} color={COLORS.success} />
              <Text style={styles.secureBadgeText}>Encrypted · reversible</Text>
            </View>
          </View>

          {/* Inline verification block */}
          {!isVerified && verifyStep !== 'idle' && (
            <View style={styles.verifyCard} testID="pay-verify-card">
              <View style={styles.verifyHeader}>
                <View style={styles.verifyHeaderIcon}>
                  <ShieldCheck size={18} color={COLORS.primary} />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.verifyTitle}>Verify your phone</Text>
                  <Text style={styles.verifySub}>Required before any money moves.</Text>
                </View>
              </View>

              {verifyStep === 'phone' && (
                <>
                  <Text style={styles.fieldLabel}>Phone number</Text>
                  <TextInput
                    testID="pay-verify-phone-input"
                    value={phone}
                    onChangeText={setPhone}
                    placeholder="555 123 4567"
                    placeholderTextColor={COLORS.disabledText}
                    keyboardType="phone-pad"
                    style={styles.input}
                    autoFocus
                    returnKeyType="next"
                    onSubmitEditing={sendOtp}
                  />
                  <Button
                    title="Send code"
                    onPress={sendOtp}
                    loading={verifyLoading}
                    testID="pay-verify-send-btn"
                    style={{ marginTop: SPACING.sm }}
                  />
                </>
              )}

              {verifyStep === 'otp' && (
                <>
                  <Text style={styles.fieldLabel}>
                    Enter the code sent to {phone}.
                    {otpMocked ? (
                      <Text style={{ fontWeight: '700' }}> (Demo: 123456)</Text>
                    ) : null}
                  </Text>
                  <TextInput
                    testID="pay-verify-otp-input"
                    value={otp}
                    onChangeText={(t) => setOtp(t.replace(/\D/g, '').slice(0, 6))}
                    placeholder={otpMocked ? '123456' : '000000'}
                    placeholderTextColor={COLORS.disabledText}
                    keyboardType="number-pad"
                    style={[styles.input, styles.otpInput]}
                    autoFocus
                    maxLength={6}
                  />
                  <Button
                    title="Verify"
                    onPress={verifyCode}
                    loading={verifyLoading}
                    testID="pay-verify-confirm-btn"
                    style={{ marginTop: SPACING.sm }}
                  />
                  <Button
                    title="Use a different number"
                    variant="ghost"
                    onPress={() => {
                      setOtp('');
                      setVerifyStep('phone');
                    }}
                    testID="pay-verify-back-btn"
                    style={{ marginTop: 4 }}
                  />
                </>
              )}
            </View>
          )}

          {isVerified && (
            <View style={styles.verifiedBadge} testID="pay-verified-badge">
              <ShieldCheck size={14} color={COLORS.success} />
              <Text style={styles.verifiedText}>Phone verified</Text>
            </View>
          )}

          {/* Shortfall settlement chooser (lead pay only) */}
          {kind === 'lead' && (group.funding?.remaining_to_collect || 0) > 0.01 && (
            <View style={styles.settlementCard} testID="pay-settlement-card">
              <Text style={styles.settlementHeader}>Shortfall</Text>
              <Text style={styles.settlementAmount}>
                ${group.funding.remaining_to_collect.toFixed(2)}
              </Text>
              <Text style={styles.settlementSub}>
                Some Squad members haven't contributed yet. Pick how to settle the gap:
              </Text>

              {(
                [
                  {
                    k: 'lead' as const,
                    title: 'I cover it',
                    sub: 'You front the shortfall now.',
                  },
                  {
                    k: 'member' as const,
                    title: 'Ask a member',
                    sub: 'Pick someone to cover it.',
                  },
                  {
                    k: 'split_equal' as const,
                    title: 'Split equally',
                    sub: 'Spread across all who already contributed.',
                  },
                ]
              ).map((m) => {
                const active = shortfallMode === m.k;
                return (
                  <TouchableOpacity
                    key={m.k}
                    testID={`pay-settle-mode-${m.k}`}
                    style={[styles.settlementOption, active && styles.settlementOptionActive]}
                    onPress={() => setShortfallMode(m.k)}
                    activeOpacity={0.85}
                  >
                    <View style={[styles.radioOuter, active && styles.radioOuterActive]}>
                      {active ? <View style={styles.radioInner} /> : null}
                    </View>
                    <View style={{ flex: 1 }}>
                      <Text style={[styles.settlementOptionTitle, active && { color: COLORS.text }]}>
                        {m.title}
                      </Text>
                      <Text style={styles.settlementOptionSub}>{m.sub}</Text>
                    </View>
                  </TouchableOpacity>
                );
              })}

              {shortfallMode === 'member' && (
                <View style={styles.funderPicker}>
                  <Text style={styles.fieldLabel}>Pick the member</Text>
                  {group.members
                    .filter((mm) => mm.user_id !== group.lead_id).length === 0 ? (
                    <Text style={styles.emptyFunders}>
                      No other Squad members have joined yet. Choose another option.
                    </Text>
                  ) : (
                    group.members
                      .filter((mm) => mm.user_id !== group.lead_id)
                      .map((mm) => {
                        const active = funderMemberId === mm.user_id;
                        return (
                          <TouchableOpacity
                            key={mm.user_id}
                            testID={`pay-settle-funder-${mm.user_id}`}
                            style={[styles.funderRow, active && styles.funderRowActive]}
                            onPress={() => setFunderMemberId(mm.user_id)}
                            activeOpacity={0.85}
                          >
                            <View
                              style={[
                                styles.funderAvatar,
                                active && { backgroundColor: COLORS.primary },
                              ]}
                            >
                              <Text style={[styles.funderAvatarText, active && { color: '#fff' }]}>
                                {(mm.name || '?').slice(0, 1).toUpperCase()}
                              </Text>
                            </View>
                            <Text style={[styles.funderName, active && { color: COLORS.primary }]}>
                              {mm.name}
                            </Text>
                            {active && (
                              <View style={styles.funderCheck}>
                                <Check size={14} color="#fff" />
                              </View>
                            )}
                          </TouchableOpacity>
                        );
                      })
                  )}
                </View>
              )}

              {shortfallMode === 'lead' && (
                <View style={styles.loanGiftRow}>
                  <Text style={styles.fieldLabel}>Treat this as</Text>
                  <View style={{ flexDirection: 'row', gap: 8 }}>
                    <TouchableOpacity
                      testID="pay-settle-loan"
                      style={[styles.loanGiftCard, isLoan && styles.loanGiftCardActive]}
                      onPress={() => setIsLoan(true)}
                      activeOpacity={0.85}
                    >
                      <Text style={[styles.loanGiftTitle, isLoan && { color: '#fff' }]}>Loan</Text>
                      <Text style={[styles.loanGiftSub, isLoan && { color: '#EDE9FE' }]}>
                        Gets repaid
                      </Text>
                    </TouchableOpacity>
                    <TouchableOpacity
                      testID="pay-settle-gift"
                      style={[styles.loanGiftCard, !isLoan && styles.loanGiftCardActive]}
                      onPress={() => setIsLoan(false)}
                      activeOpacity={0.85}
                    >
                      <Text style={[styles.loanGiftTitle, !isLoan && { color: '#fff' }]}>Gift</Text>
                      <Text style={[styles.loanGiftSub, !isLoan && { color: '#EDE9FE' }]}>
                        No repayment
                      </Text>
                    </TouchableOpacity>
                  </View>
                </View>
              )}

              {shortfallMode === 'member' && (
                <Text style={styles.splitNote}>
                  💡 The selected member will get an SMS and see the shortfall as an additional bill to pay before the merchant is settled.
                </Text>
              )}

              {shortfallMode === 'split_equal' && (
                <Text style={styles.splitNote}>
                  💡 The shortfall will be split equally across all Squad members (including you, the lead). Each person gets an SMS and sees their share as an additional bill.
                </Text>
              )}
            </View>
          )}

          {/* Receipt opt-in (contribute kind only) */}
          {kind === 'contribute' && (
            <TouchableOpacity
              testID="pay-notify-toggle"
              activeOpacity={0.8}
              onPress={() => setNotifyOnSettled((v) => !v)}
              style={styles.notifyRow}
            >
              <View style={[styles.checkbox, notifyOnSettled && styles.checkboxOn]}>
                {notifyOnSettled ? <Check size={14} color="#fff" /> : null}
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.notifyTitle}>Send me the final receipt</Text>
                <Text style={styles.notifySub}>
                  We'll text you a payment update when this bill is fully settled.
                </Text>
              </View>
            </TouchableOpacity>
          )}
        </ScrollView>

        <View style={styles.bottomBar}>
          {stripeBanner ? (
            <View style={styles.stripeBanner} testID="stripe-banner">
              <Text style={styles.stripeBannerText}>{stripeBanner}</Text>
            </View>
          ) : null}
          {!isVerified && verifyStep === 'idle' ? (
            <GradientButton
              title="Verify phone to continue"
              onPress={() => setVerifyStep('phone')}
              testID="pay-start-verify-btn"
              icon={<ShieldCheck size={18} color="#fff" />}
            />
          ) : blockedNoAmount && kind === 'contribute' && (group.items?.length || 0) > 0 ? (
            // Member with $0 share & there are items to claim → guide them to
            // the items list instead of showing a useless disabled Pay button.
            <GradientButton
              title="Claim your items"
              onPress={() => router.push(`/group/${group.id}/items`)}
              testID="pay-claim-items-btn"
              icon={<Receipt size={18} color="#fff" />}
            />
          ) : (
            <>
              <GradientButton
                title={`Pay $${amount.toFixed(2)}`}
                loading={loading}
                onPress={doPay}
                testID="pay-submit-btn"
                icon={<CreditCard size={18} color="#fff" />}
                disabled={!isVerified || blockedNoAmount}
              />
              {kind === 'contribute' && isVerified && !blockedNoAmount && nativePayAvailable && Platform.OS !== 'web' && ((Platform.OS === 'ios' && walletFlags.apple) || (Platform.OS === 'android' && walletFlags.google)) && (
                <Button
                  title={
                    nativePayBusy
                      ? 'Opening wallet…'
                      : Platform.OS === 'ios'
                      ? `Pay with Apple Pay — $${amount.toFixed(2)}`
                      : `Pay with Google Pay — $${amount.toFixed(2)}`
                  }
                  variant="secondary"
                  onPress={onPayWithWallet}
                  loading={nativePayBusy}
                  testID="pay-wallet-btn"
                  leftIcon={Platform.OS === 'ios' ? <Apple size={16} color={COLORS.primary} fill={COLORS.primary} /> : <Smartphone size={16} color={COLORS.primary} />}
                  style={{ marginTop: SPACING.sm }}
                />
              )}
              {kind === 'lead' && isVerified && !blockedNoAmount && (group.funding?.remaining_to_collect || 0) > 0.01 ? (
                <Button
                  title={stripeBusy ? 'Opening Stripe…' : `Pay with Stripe — $${amount.toFixed(2)}`}
                  variant="secondary"
                  onPress={onPayWithStripe}
                  loading={stripeBusy}
                  testID="pay-stripe-btn"
                  leftIcon={<Lock size={16} color={COLORS.primary} />}
                  style={{ marginTop: SPACING.sm }}
                />
              ) : null}
            </>
          )}
          <Button
            title="Cancel"
            variant="ghost"
            onPress={() => {
              if (router.canGoBack && router.canGoBack()) {
                router.back();
              } else {
                router.replace(`/group/${id}/summary`);
              }
            }}
            testID="pay-cancel-btn"
            style={{ marginTop: SPACING.sm }}
          />
        </View>
      </SafeAreaView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  scroll: { padding: SPACING.lg, paddingBottom: SPACING.xl },
  label: {
    fontSize: FONT.sizes.xs,
    color: COLORS.subtext,
    textTransform: 'uppercase',
    letterSpacing: 1,
    fontWeight: FONT.weights.semibold,
  },
  amount: {
    fontSize: 64,
    fontWeight: FONT.weights.heavy,
    color: COLORS.text,
    letterSpacing: -2,
    marginTop: SPACING.xs,
  },
  summary: {
    marginTop: SPACING.sm,
    fontSize: FONT.sizes.md,
    color: COLORS.subtext,
    lineHeight: 22,
  },
  card: {
    marginTop: SPACING.xl,
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.lg,
    padding: SPACING.md,
    borderWidth: 1,
    borderColor: COLORS.border,
  },
  // Phase H4 — breakdown card
  creditPill: {
    flexDirection: 'row',
    alignItems: 'center',
    alignSelf: 'flex-start',
    gap: 6,
    marginTop: SPACING.sm,
    paddingHorizontal: 12,
    paddingVertical: 6,
    backgroundColor: COLORS.primaryLight,
    borderRadius: RADIUS.pill,
    borderWidth: 1,
    borderColor: COLORS.primarySoft,
  },
  creditPillText: {
    color: COLORS.primary,
    fontSize: FONT.sizes.xs,
    fontWeight: FONT.weights.bold,
    letterSpacing: 0.2,
  },
  breakdownCard: {
    marginTop: SPACING.lg,
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.lg,
    padding: SPACING.md,
    borderWidth: 1,
    borderColor: COLORS.border,
    gap: 4,
  },
  breakdownHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: SPACING.md,
    paddingVertical: SPACING.xs,
  },
  totalRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingTop: 4,
  },
  totalLabel: {
    fontSize: FONT.sizes.md,
    fontWeight: FONT.weights.bold,
    color: COLORS.text,
  },
  totalValue: {
    fontSize: FONT.sizes.xl,
    fontWeight: FONT.weights.heavy,
    color: COLORS.text,
    fontVariant: ['tabular-nums'] as any,
    letterSpacing: -0.3,
  },
  secureBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    alignSelf: 'flex-start',
    gap: 4,
    marginTop: SPACING.sm,
    paddingHorizontal: 10,
    paddingVertical: 4,
    backgroundColor: COLORS.successLight,
    borderRadius: RADIUS.pill,
  },
  secureBadgeText: {
    color: COLORS.success,
    fontSize: 11,
    fontWeight: FONT.weights.bold,
    letterSpacing: 0.3,
  },
  row: { flexDirection: 'row', alignItems: 'center', gap: SPACING.md, paddingVertical: SPACING.sm },
  icon: {
    width: 40,
    height: 40,
    borderRadius: 10,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: COLORS.primaryLight,
  },
  rowTitle: { fontSize: FONT.sizes.md, fontWeight: FONT.weights.semibold, color: COLORS.text },
  rowSub: { fontSize: FONT.sizes.sm, color: COLORS.subtext, marginTop: 2 },
  divider: { height: 1, backgroundColor: COLORS.border, marginVertical: SPACING.sm },
  verifyCard: {
    marginTop: SPACING.md,
    padding: SPACING.md,
    borderRadius: RADIUS.lg,
    backgroundColor: COLORS.surface,
    borderWidth: 1.5,
    borderColor: COLORS.primary,
  },
  verifyHeader: { flexDirection: 'row', alignItems: 'center', gap: SPACING.md, marginBottom: SPACING.md },
  verifyHeaderIcon: {
    width: 40,
    height: 40,
    borderRadius: 10,
    backgroundColor: COLORS.primaryLight,
    alignItems: 'center',
    justifyContent: 'center',
  },
  verifyTitle: { fontSize: FONT.sizes.md, fontWeight: FONT.weights.bold, color: COLORS.text },
  verifySub: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: 2 },
  fieldLabel: {
    fontSize: FONT.sizes.xs,
    color: COLORS.subtext,
    fontWeight: FONT.weights.medium,
    marginBottom: 6,
    lineHeight: 18,
  },
  input: {
    height: 48,
    borderRadius: RADIUS.md,
    borderWidth: 1.5,
    borderColor: COLORS.border,
    backgroundColor: COLORS.surface,
    paddingHorizontal: SPACING.md,
    fontSize: FONT.sizes.md,
    color: COLORS.text,
  },
  otpInput: {
    letterSpacing: 8,
    textAlign: 'center',
    fontWeight: FONT.weights.bold,
    fontSize: FONT.sizes.lg,
  },
  verifiedBadge: {
    flexDirection: 'row',
    alignSelf: 'flex-start',
    alignItems: 'center',
    gap: 6,
    marginTop: SPACING.md,
    backgroundColor: COLORS.successLight,
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: RADIUS.pill,
  },
  verifiedText: { color: COLORS.success, fontSize: FONT.sizes.xs, fontWeight: FONT.weights.semibold },
  notifyRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: SPACING.sm,
    marginTop: SPACING.lg,
    padding: SPACING.md,
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.md,
    borderWidth: 1,
    borderColor: COLORS.border,
  },
  checkbox: {
    width: 22,
    height: 22,
    borderRadius: 6,
    borderWidth: 2,
    borderColor: COLORS.border,
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: 2,
  },
  checkboxOn: { backgroundColor: COLORS.primary, borderColor: COLORS.primary },
  notifyTitle: { fontSize: FONT.sizes.md, fontWeight: FONT.weights.semibold, color: COLORS.text },
  notifySub: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: 2, lineHeight: 16 },
  settlementCard: {
    marginTop: SPACING.lg,
    padding: SPACING.lg,
    borderRadius: RADIUS.lg,
    backgroundColor: COLORS.surface,
    borderWidth: 1,
    borderColor: COLORS.border,
  },
  settlementHeader: {
    fontSize: FONT.sizes.xs,
    color: COLORS.warning,
    textTransform: 'uppercase',
    letterSpacing: 1,
    fontWeight: FONT.weights.bold,
  },
  settlementAmount: {
    fontSize: 36,
    fontWeight: FONT.weights.heavy,
    color: COLORS.text,
    letterSpacing: -1,
    marginTop: 2,
  },
  settlementSub: {
    fontSize: FONT.sizes.sm,
    color: COLORS.subtext,
    marginTop: 4,
    marginBottom: SPACING.md,
  },
  settlementOption: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: SPACING.md,
    padding: SPACING.md,
    borderRadius: RADIUS.md,
    backgroundColor: COLORS.bg,
    borderWidth: 1.5,
    borderColor: COLORS.border,
    marginBottom: 8,
  },
  settlementOptionActive: {
    backgroundColor: COLORS.primaryLight,
    borderColor: COLORS.primary,
  },
  settlementOptionTitle: {
    fontSize: FONT.sizes.md,
    fontWeight: FONT.weights.bold,
    color: COLORS.text,
  },
  settlementOptionSub: {
    fontSize: FONT.sizes.xs,
    color: COLORS.subtext,
    marginTop: 2,
  },
  radioOuter: {
    width: 22,
    height: 22,
    borderRadius: 11,
    borderWidth: 2,
    borderColor: COLORS.border,
    alignItems: 'center',
    justifyContent: 'center',
  },
  radioOuterActive: { borderColor: COLORS.primary },
  radioInner: { width: 12, height: 12, borderRadius: 6, backgroundColor: COLORS.primary },
  funderPicker: { marginTop: SPACING.sm, gap: 8 },
  funderRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: SPACING.md,
    padding: SPACING.sm,
    borderRadius: RADIUS.md,
    backgroundColor: COLORS.bg,
    borderWidth: 1.5,
    borderColor: COLORS.border,
  },
  funderRowActive: { backgroundColor: COLORS.primaryLight, borderColor: COLORS.primary },
  funderAvatar: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: COLORS.primaryLight,
    alignItems: 'center',
    justifyContent: 'center',
  },
  funderAvatarText: { color: COLORS.primary, fontWeight: FONT.weights.bold },
  funderName: {
    flex: 1,
    fontSize: FONT.sizes.md,
    fontWeight: FONT.weights.semibold,
    color: COLORS.text,
  },
  funderCheck: {
    width: 24,
    height: 24,
    borderRadius: 12,
    backgroundColor: COLORS.primary,
    alignItems: 'center',
    justifyContent: 'center',
  },
  emptyFunders: {
    fontSize: FONT.sizes.sm,
    color: COLORS.subtext,
    fontStyle: 'italic',
    padding: SPACING.sm,
  },
  loanGiftRow: { marginTop: SPACING.md, gap: 8 },
  loanGiftCard: {
    flex: 1,
    padding: SPACING.md,
    borderRadius: RADIUS.md,
    backgroundColor: COLORS.bg,
    borderWidth: 1.5,
    borderColor: COLORS.border,
    alignItems: 'flex-start',
  },
  loanGiftCardActive: { backgroundColor: COLORS.primary, borderColor: COLORS.primary },
  loanGiftTitle: { fontSize: FONT.sizes.md, fontWeight: FONT.weights.bold, color: COLORS.text },
  loanGiftSub: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: 2 },
  splitNote: {
    color: COLORS.primary,
    fontSize: FONT.sizes.xs,
    marginTop: SPACING.md,
    lineHeight: 16,
    fontWeight: FONT.weights.medium,
  },
  fieldLabel: {
    fontSize: FONT.sizes.xs,
    color: COLORS.subtext,
    fontWeight: FONT.weights.semibold,
    textTransform: 'uppercase',
    letterSpacing: 1,
    marginTop: SPACING.sm,
    marginBottom: 6,
  },
  bottomBar: {
    padding: SPACING.md,
    backgroundColor: COLORS.surface,
    borderTopWidth: 1,
    borderTopColor: COLORS.border,
    ...SHADOW.lg,
  },
  stripeBanner: {
    padding: SPACING.sm,
    marginBottom: SPACING.sm,
    backgroundColor: COLORS.primaryLight,
    borderRadius: RADIUS.sm,
    borderWidth: 1,
    borderColor: COLORS.primary,
  },
  stripeBannerText: {
    color: COLORS.primary,
    fontSize: FONT.sizes.xs,
    fontWeight: FONT.weights.semibold,
    textAlign: 'center',
  },
});

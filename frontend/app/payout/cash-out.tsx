/**
 * Lead Cash-Out flow (Phase 5b — June 2025).
 *
 * Routed at: /payout/cash-out?group_id=...
 *
 * State machine:
 *   loading        → fetch eligibility
 *   ineligible     → show reasons (e.g. group not paid yet)
 *   not_linked     → "Connect your payout account" — opens Stripe Account Link in a WebView
 *   onboarding     → WebView open; awaiting redirect/return
 *   sync_needed    → onboarding complete on Stripe; tap "I'm done" to sync cards
 *   pick_amount    → amount picker + card picker
 *   confirming     → push-to-card in flight (modal)
 *   success        → done; show payout id + last4
 *   error          → recoverable error with retry
 *
 * Designed for both lead (Stripe Connect Express) and (future) Astra users.
 * The backend `/payout/authorize-url` returns a `kind` that tells us if it's
 * `account_onboarding` (Stripe) or `oauth_authorize` (Astra). Stripe Connect
 * redirects to `return_url` with NO query params, so we just listen for the
 * navigation event and trigger sync. Astra adds `?code=&state=`.
 */
import { useLocalSearchParams, useRouter } from 'expo-router';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Modal,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
// Item 2 (June 2025) — react-native-webview throws "WebView does not
// support this platform" when bundled for web. Import it conditionally
// so the screen still mounts on web; we render an external-link
// fallback for the onboarding step instead.
let WebView: any = null;
type WebViewNavigation = any;
if (Platform.OS !== 'web') {
  try {
    // eslint-disable-next-line @typescript-eslint/no-var-requires, global-require
    WebView = require('react-native-webview').WebView;
  } catch (_e) {
    WebView = null;
  }
}
import {
  ArrowLeft,
  CheckCircle2,
  CreditCard,
  Wallet,
  Banknote,
  ExternalLink,
  RefreshCw,
  ShieldCheck,
} from 'lucide-react-native';
import { api } from '../../src/api';
import { loadUser, loadSessionId } from '../../src/session';
import { COLORS, FONT, RADIUS, SPACING } from '../../src/theme';
import { toast } from '../../src/components/Toast';

type Phase =
  | 'loading'
  | 'ineligible'
  | 'not_linked'
  | 'onboarding'
  | 'sync_needed'
  | 'pick_amount'
  | 'confirming'
  | 'success'
  | 'error';

type Card = {
  id: string;
  brand?: string;
  last4?: string;
  is_default?: boolean;
};

// Stripe Connect onboarding return URL — Stripe redirects here with no
// payload; the WebView nav listener fires and we move to sync_needed.
// We use the production getsquadpay.com universal-link domain. Stripe blocks
// custom-scheme URIs (squadpay://...) on AccountLinks for security reasons,
// so we MUST use https://. The /payout/return path is registered in both
// app.json (associatedDomains + Android intent filters) and the
// .well-known/apple-app-site-association manifest so iOS opens this URL
// straight into the app (skipping the browser).
const RETURN_URL = 'https://www.getsquadpay.com/payout/return';
const REFRESH_URL = 'https://www.getsquadpay.com/payout/refresh';

export default function CashOutScreen() {
  const { group_id } = useLocalSearchParams<{ group_id?: string }>();
  const router = useRouter();

  const [userId, setUserId] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);

  const [phase, setPhase] = useState<Phase>('loading');
  const [errMsg, setErrMsg] = useState('');
  const [eligibility, setEligibility] = useState<{
    available_usd: number;
    linked: boolean;
    payouts_enabled: boolean;
    reasons: string[];
    gateway_slug: string;
  } | null>(null);

  const [onboardingUrl, setOnboardingUrl] = useState<string | null>(null);
  const [cards, setCards] = useState<Card[]>([]);
  const [requirementsDue, setRequirementsDue] = useState<string[]>([]);

  const [amount, setAmount] = useState('');
  const [selectedCardId, setSelectedCardId] = useState<string | null>(null);
  const [successResult, setSuccessResult] = useState<{
    txn_id: string;
    amount: number;
    card_brand?: string;
    card_last4?: string;
    status: string;
  } | null>(null);

  const webViewRef = useRef<WebView>(null);

  // Subtle KYC auto-redirect (June 2025) — when the lead first lands on
  // the not_linked phase, we give them a few seconds to read the warm
  // reassurance message, then auto-open Stripe verification. They can
  // tap "Open Stripe Now" to skip the countdown, or "Give me a moment"
  // to cancel and read longer. We only auto-redirect ONCE per visit
  // (autoRedirectFired) so cancelling sticks for the rest of the
  // session.
  const AUTO_REDIRECT_SECONDS = 7;
  const [autoRedirectIn, setAutoRedirectIn] = useState<number | null>(null);
  const [autoRedirectFired, setAutoRedirectFired] = useState(false);
  const [autoRedirectCancelled, setAutoRedirectCancelled] = useState(false);
  // KYC incentive (June 2025) — fetched once on mount. We pick ONE random
  // message from the admin-configured pool so different leads see
  // different angles. The reward chip below shows the actual reward
  // strategy chosen by the admin — either a flat dollar discount on
  // the lead's NEXT squad, or a platform-fee waiver on their NEXT squad.
  // All admin-tunable via /admin/kyc-incentive. SquadPay never stores
  // value — the reward auto-applies to the next bill.
  const [kycIncentive, setKycIncentive] = useState<{
    enabled: boolean;
    reward_mode: 'credit_off_next_bill' | 'waive_platform_fees_next_bill';
    credit_amount: number;
    message: string | null;
  }>({ enabled: true, reward_mode: 'credit_off_next_bill', credit_amount: 10, message: null });
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const r = await fetch(`${process.env.EXPO_PUBLIC_BACKEND_URL || ''}/api/runtime/kyc-incentive`);
        if (!r.ok) return;
        const j = await r.json();
        if (!alive) return;
        const pool: string[] = (j.messages && j.messages.length) ? j.messages : [
          'Stripe handles it — SquadPay just makes sure your money gets back to you.',
        ];
        const picked = pool[Math.floor(Math.random() * pool.length)];
        setKycIncentive({
          enabled: j.enabled !== false,
          reward_mode: (j.reward_mode === 'waive_platform_fees_next_bill'
            ? 'waive_platform_fees_next_bill'
            : 'credit_off_next_bill'),
          credit_amount: Number(j.credit_amount || 0),
          message: picked,
        });
      } catch { /* fall back to default state */ }
    })();
    return () => { alive = false; };
  }, []);

  // ── Initial load: read session + fetch eligibility
  useEffect(() => {
    (async () => {
      const u = await loadUser();
      const sid = await loadSessionId();
      if (!u || !sid) {
        router.replace('/auth');
        return;
      }
      setUserId(u.id);
      setSessionId(sid);
      if (!group_id) {
        setPhase('error');
        setErrMsg('Squad ID is required to pay out.');
        return;
      }
      await runEligibility(u.id, sid, group_id);
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [group_id]);

  const runEligibility = useCallback(async (uid: string, sid: string, gid: string) => {
    setPhase('loading');
    try {
      const e = await api.payoutEligibility(uid, sid, gid);
      setEligibility({
        available_usd: e.available_usd,
        linked: e.linked,
        payouts_enabled: e.payouts_enabled,
        reasons: e.reasons,
        gateway_slug: e.gateway_slug,
      });
      if (!e.eligible) {
        setPhase('ineligible');
        return;
      }
      if (!e.linked || !e.payouts_enabled) {
        setPhase('not_linked');
        return;
      }
      const cardsResp = await api.payoutListCards(uid, sid);
      setCards(cardsResp.items as Card[]);
      const defaultCard = (cardsResp.items as Card[]).find((c) => c.is_default) || (cardsResp.items as Card[])[0];
      setSelectedCardId(defaultCard?.id || null);
      setPhase('pick_amount');
    } catch (e: any) {
      setPhase('error');
      setErrMsg(e?.message || 'Failed to load cash-out eligibility');
    }
  }, []);

  // Kick off the friendly auto-redirect timer the moment we enter the
  // not_linked phase. We only do this once per visit; if the lead taps
  // "Give me a moment" we leave the buttons in place and never auto-fire.
  useEffect(() => {
    if (phase !== 'not_linked') return;
    if (autoRedirectFired || autoRedirectCancelled) return;
    setAutoRedirectIn(AUTO_REDIRECT_SECONDS);
  }, [phase, autoRedirectFired, autoRedirectCancelled]);

  useEffect(() => {
    if (autoRedirectIn == null) return;
    if (autoRedirectCancelled) return;
    if (autoRedirectIn <= 0) {
      setAutoRedirectIn(null);
      setAutoRedirectFired(true);
      handleConnect();
      return;
    }
    const t = setTimeout(() => setAutoRedirectIn((s) => (s == null ? null : s - 1)), 1000);
    return () => clearTimeout(t);
  }, [autoRedirectIn, autoRedirectCancelled]);

  // ── "Connect" tap → fetch authorize URL → open WebView
  const handleConnect = async () => {
    if (!userId || !sessionId || !group_id) return;
    setAutoRedirectIn(null);
    setAutoRedirectFired(true);
    setPhase('loading');
    try {
      const r = await api.payoutAuthorizeUrl(userId, sessionId, RETURN_URL, REFRESH_URL, group_id);
      setOnboardingUrl(r.url);
      setPhase('onboarding');
    } catch (e: any) {
      setPhase('error');
      setErrMsg(e?.message || 'Could not start onboarding');
    }
  };

  // ── WebView navigation listener — detects Stripe redirect back to RETURN_URL
  const onNav = (nav: WebViewNavigation) => {
    if (!nav.url) return;
    if (nav.url.startsWith(RETURN_URL)) {
      setOnboardingUrl(null);
      setPhase('sync_needed');
    } else if (nav.url.startsWith(REFRESH_URL)) {
      // User bailed — re-mint the link
      handleConnect();
    }
  };

  // ── "I'm done" → call sync, fetch cards, advance
  const handleSync = async () => {
    if (!userId || !sessionId) return;
    setPhase('loading');
    try {
      const s = await api.payoutSyncAfterOnboarding(userId, sessionId);
      setCards(s.cards as Card[]);
      setRequirementsDue(s.requirements_due || []);
      if (!s.payouts_enabled) {
        // Stripe still needs more info from the user — send them back to the link.
        setErrMsg(
          (s.requirements_due && s.requirements_due.length > 0
            ? `Stripe still needs: ${s.requirements_due.join(', ')}.`
            : 'Stripe is still verifying your account.') +
            ' Please finish onboarding.',
        );
        setPhase('not_linked');
        return;
      }
      if (!s.cards || s.cards.length === 0) {
        setErrMsg('Onboarding complete but no debit card on file yet. Re-open onboarding to add one.');
        setPhase('not_linked');
        return;
      }
      const defaultCard = (s.cards as Card[]).find((c) => c.is_default) || (s.cards as Card[])[0];
      setSelectedCardId(defaultCard.id);
      setPhase('pick_amount');
    } catch (e: any) {
      setPhase('error');
      setErrMsg(e?.message || 'Sync failed');
    }
  };

  // ── "Confirm cash-out" → push-to-card
  const handlePush = async () => {
    if (!userId || !sessionId || !group_id || !selectedCardId) return;
    const amt = Number.parseFloat(amount);
    if (!Number.isFinite(amt) || amt <= 0) {
      toast.error('Enter a valid amount');
      return;
    }
    if (eligibility && amt > eligibility.available_usd) {
      toast.error(`Max available: $${eligibility.available_usd.toFixed(2)}`);
      return;
    }
    setPhase('confirming');
    try {
      const r = await api.payoutPushToCard(userId, sessionId, group_id, selectedCardId, amt);
      setSuccessResult({
        txn_id: r.txn_id,
        amount: r.amount,
        card_brand: r.card_brand,
        card_last4: r.card_last4,
        status: r.status,
      });
      setPhase('success');
    } catch (e: any) {
      setPhase('error');
      setErrMsg(e?.message || 'Cash-out failed');
    }
  };

  const reasonsHuman = useMemo(() => {
    if (!eligibility) return [];
    const map: Record<string, string> = {
      not_lead: 'You are not the lead of this squad.',
      group_not_paid: 'This squad isn’t fully funded by members yet.',
      funding_mode_not_group: 'Cash-out is only for member-funded squads.',
    };
    return eligibility.reasons.map((r) => map[r] || r);
  }, [eligibility]);

  // ───────── Render ─────────
  return (
    <SafeAreaView style={styles.safe} edges={['top', 'left', 'right']}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} hitSlop={12} accessibilityLabel="Back">
          <ArrowLeft size={24} color={COLORS.text} />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Pay Out to Debit Card</Text>
        <View style={{ width: 24 }} />
      </View>

      {phase === 'loading' && (
        <View style={styles.center}>
          <ActivityIndicator size="large" color={COLORS.primary} />
          <Text style={styles.loadingText}>Checking eligibility…</Text>
        </View>
      )}

      {phase === 'ineligible' && (
        <ScrollView contentContainerStyle={styles.body}>
          <View style={styles.statusCard}>
            <Text style={styles.statusEmoji}>⏳</Text>
            <Text style={styles.statusTitle}>Cash-out not available yet</Text>
            {reasonsHuman.map((r, i) => (
              <Text key={i} style={styles.statusReason}>• {r}</Text>
            ))}
            <Text style={styles.statusHint}>
              Cash-out unlocks once every member has fully paid their share of this squad.
            </Text>
          </View>
        </ScrollView>
      )}

      {phase === 'not_linked' && (
        <ScrollView contentContainerStyle={styles.body}>
          {!!errMsg && (
            <View style={[styles.statusCard, styles.errorCard]}>
              <Text style={styles.errorText}>{errMsg}</Text>
            </View>
          )}
          {!!requirementsDue?.length && (
            <View style={[styles.statusCard, { backgroundColor: '#FFF7ED' }]}>
              <Text style={{ ...FONT.subhead, color: '#9A3412', marginBottom: 6 }}>
                Stripe still needs:
              </Text>
              {requirementsDue.map((r, i) => (
                <Text key={i} style={styles.statusReason}>• {r}</Text>
              ))}
            </View>
          )}
          <View style={styles.balanceCard}>
            <Wallet size={28} color={COLORS.primary} />
            <Text style={styles.balanceLabel}>Available to pay out</Text>
            <Text style={styles.balanceAmount}>
              ${eligibility?.available_usd?.toFixed(2) || '0.00'}
            </Text>
          </View>
          {/* Short headline + 1-line rotating message from the admin
              pool. The reward chip just below is the real anchor — it
              gives the lead a concrete reason to KYC vs. just collecting
              via Venmo/Zelle outside the app. */}
          <Text style={styles.bodyHeader}>One quick check, then you're paid.</Text>
          <Text style={styles.bodyText}>
            {kycIncentive.message || 'Stripe handles it — SquadPay just makes sure your money gets back to you.'}
          </Text>

          {/* Reward chip — admin-tunable. Mode A = flat $ off the next
              squad. Mode B = platform-fee waiver on the next squad.
              The chip text reflects whichever mode admin picked. We
              never use the word "Wallet" — SquadPay does not hold
              stored value, only channels payments. */}
          {kycIncentive.enabled && (
            <View style={styles.rewardChip} testID="kyc-reward-chip">
              <Text style={styles.rewardChipBadge}>
                {kycIncentive.reward_mode === 'waive_platform_fees_next_bill'
                  ? 'NO FEES'
                  : `EARN $${kycIncentive.credit_amount.toFixed(0)}`}
              </Text>
              <Text style={styles.rewardChipText}>
                {kycIncentive.reward_mode === 'waive_platform_fees_next_bill'
                  ? 'We\'ll waive all SquadPay platform fees on your next Squad.'
                  : `$${kycIncentive.credit_amount.toFixed(0)} discount auto-applies to your next Squad bill.`}
              </Text>
            </View>
          )}

          {/* Auto-redirect banner. Counts down from AUTO_REDIRECT_SECONDS,
              then opens Stripe's hosted onboarding via handleConnect.
              The lead can tap "Open Stripe Now" to skip the countdown, or
              "Give me a moment" to cancel and read longer. */}
          {autoRedirectIn != null && !autoRedirectCancelled && (
            <View style={styles.autoRedirectCard} testID="kyc-auto-redirect">
              <ActivityIndicator color={COLORS.primary} />
              <Text style={styles.autoRedirectText}>
                Opening Stripe in <Text style={{ fontWeight: '800' }}>{autoRedirectIn}s</Text>…
              </Text>
              <TouchableOpacity
                onPress={() => { setAutoRedirectCancelled(true); setAutoRedirectIn(null); }}
                hitSlop={8}
                testID="kyc-give-me-a-moment"
              >
                <Text style={styles.autoRedirectCancel}>Wait</Text>
              </TouchableOpacity>
            </View>
          )}

          <TouchableOpacity style={styles.primaryBtn} onPress={handleConnect} testID="connect-stripe-btn">
            <ExternalLink size={18} color="#fff" />
            <Text style={styles.primaryBtnText}>
              {autoRedirectIn != null && !autoRedirectCancelled ? 'Open Stripe Now' : 'Continue with Stripe'}
            </Text>
          </TouchableOpacity>
          {/* Per spec: no third-party fee disclosures here. SquadPay's
              single platform fee is the only fee surface presented to
              users. */}
        </ScrollView>
      )}

      {phase === 'onboarding' && !!onboardingUrl && (
        <View style={{ flex: 1 }}>
          {WebView ? (
            <WebView
              ref={webViewRef}
              source={{ uri: onboardingUrl }}
              onNavigationStateChange={onNav}
              startInLoadingState
              renderLoading={() => (
                <View style={styles.center}>
                  <ActivityIndicator size="large" color={COLORS.primary} />
                </View>
              )}
              style={{ flex: 1 }}
            />
          ) : (
            // Item 2 (June 2025) — Web fallback. react-native-webview can't
            // render on web, so we open Stripe onboarding in a new tab and
            // wait for the user to return.
            <View style={styles.center}>
              <ExternalLink size={40} color={COLORS.primary} />
              <Text style={[styles.statusTitle, { marginTop: SPACING.md, textAlign: 'center' }]}>
                Stripe onboarding opens in a new tab
              </Text>
              <Text style={[styles.statusHint, { textAlign: 'center', marginBottom: SPACING.lg }]}>
                Finish setup with Stripe and then come back here to sync.
              </Text>
              <TouchableOpacity
                style={styles.primaryBtn}
                onPress={() => {
                  if (Platform.OS === 'web' && typeof window !== 'undefined') {
                    window.open(onboardingUrl, '_blank');
                  }
                }}
              >
                <ExternalLink size={18} color="#fff" />
                <Text style={styles.primaryBtnText}>Open Stripe onboarding</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[styles.secondaryBtn, { marginTop: SPACING.md }]}
                onPress={() => setPhase('sync_needed')}
              >
                <Text style={styles.secondaryBtnText}>I'm done — sync account</Text>
              </TouchableOpacity>
            </View>
          )}
          {WebView ? (
            <View style={styles.webviewFooter}>
              <TouchableOpacity onPress={() => setPhase('sync_needed')} hitSlop={10}>
                <Text style={styles.webviewFooterLink}>I'm done →</Text>
              </TouchableOpacity>
            </View>
          ) : null}
        </View>
      )}

      {phase === 'sync_needed' && (
        <ScrollView contentContainerStyle={styles.body}>
          <View style={styles.statusCard}>
            <CheckCircle2 size={40} color={COLORS.primary} />
            <Text style={styles.statusTitle}>Almost done</Text>
            <Text style={styles.statusHint}>
              Tap below to sync your Stripe account and load your debit card.
            </Text>
          </View>
          <TouchableOpacity style={styles.primaryBtn} onPress={handleSync} testID="sync-btn">
            <RefreshCw size={18} color="#fff" />
            <Text style={styles.primaryBtnText}>Sync account</Text>
          </TouchableOpacity>
        </ScrollView>
      )}

      {phase === 'pick_amount' && (
        <ScrollView contentContainerStyle={styles.body}>
          <View style={styles.balanceCard}>
            <Wallet size={28} color={COLORS.primary} />
            <Text style={styles.balanceLabel}>Available to pay out</Text>
            <Text style={styles.balanceAmount}>
              ${eligibility?.available_usd?.toFixed(2) || '0.00'}
            </Text>
          </View>

          <Text style={styles.bodyHeader}>Amount</Text>
          <View style={styles.amountRow}>
            <Text style={styles.dollarSign}>$</Text>
            <TextInput
              style={styles.amountInput}
              keyboardType="decimal-pad"
              value={amount}
              onChangeText={setAmount}
              placeholder="0.00"
              placeholderTextColor={COLORS.muted}
              testID="cashout-amount-input"
            />
            <TouchableOpacity
              onPress={() => setAmount((eligibility?.available_usd || 0).toFixed(2))}
              style={styles.maxBtn}
            >
              <Text style={styles.maxBtnText}>Max</Text>
            </TouchableOpacity>
          </View>

          <Text style={styles.bodyHeader}>To debit card</Text>
          {cards.map((c) => (
            <Pressable
              key={c.id}
              onPress={() => setSelectedCardId(c.id)}
              style={[styles.cardRow, selectedCardId === c.id && styles.cardRowSelected]}
              testID={`card-row-${c.id}`}
            >
              <CreditCard size={22} color={COLORS.text} />
              <View style={{ flex: 1, marginLeft: 10 }}>
                <Text style={styles.cardBrand}>
                  {(c.brand || 'card').toUpperCase()} •••• {c.last4 || '????'}
                </Text>
                {c.is_default && <Text style={styles.cardTag}>Default</Text>}
              </View>
              {selectedCardId === c.id && <CheckCircle2 size={20} color={COLORS.primary} />}
            </Pressable>
          ))}

          <TouchableOpacity
            style={[
              styles.primaryBtn,
              (!selectedCardId || !amount || Number.parseFloat(amount) <= 0) && styles.primaryBtnDisabled,
            ]}
            onPress={handlePush}
            disabled={!selectedCardId || !amount || Number.parseFloat(amount) <= 0}
            testID="confirm-cashout-btn"
          >
            <Banknote size={20} color="#fff" />
            <Text style={styles.primaryBtnText}>
              Pay Out ${amount && Number.parseFloat(amount) > 0 ? Number.parseFloat(amount).toFixed(2) : '0.00'}
            </Text>
          </TouchableOpacity>
          <Text style={styles.fineprint}>
            Funds typically arrive on your card within 30 minutes.
          </Text>
        </ScrollView>
      )}

      {phase === 'success' && successResult && (
        <ScrollView contentContainerStyle={styles.body}>
          <View style={[styles.statusCard, { backgroundColor: '#ECFDF5' }]}>
            <CheckCircle2 size={56} color={COLORS.primary} />
            <Text style={styles.statusTitle}>Pay-out submitted</Text>
            <Text style={styles.statusHint}>
              ${successResult.amount.toFixed(2)} sent to {(successResult.card_brand || '').toUpperCase()} ••••{' '}
              {successResult.card_last4}
            </Text>
            <Text style={[styles.statusHint, { marginTop: 4 }]}>
              Status: {successResult.status}
            </Text>
            <Text style={styles.statusHintMono}>Txn: {successResult.txn_id}</Text>
          </View>
          <TouchableOpacity style={styles.primaryBtn} onPress={() => router.back()}>
            <Text style={styles.primaryBtnText}>Back to dashboard</Text>
          </TouchableOpacity>
        </ScrollView>
      )}

      {phase === 'error' && (
        <ScrollView contentContainerStyle={styles.body}>
          <View style={[styles.statusCard, styles.errorCard]}>
            <Text style={styles.statusTitle}>Something went wrong</Text>
            <Text style={styles.errorText}>{errMsg}</Text>
          </View>
          <TouchableOpacity
            style={styles.primaryBtn}
            onPress={() => userId && sessionId && group_id && runEligibility(userId, sessionId, group_id)}
          >
            <RefreshCw size={18} color="#fff" />
            <Text style={styles.primaryBtnText}>Try again</Text>
          </TouchableOpacity>
        </ScrollView>
      )}

      {/* Confirming modal */}
      <Modal visible={phase === 'confirming'} transparent animationType="fade">
        <View style={styles.modalBackdrop}>
          <View style={styles.modalCard}>
            <ActivityIndicator size="large" color={COLORS.primary} />
            <Text style={styles.modalTitle}>Sending funds…</Text>
            <Text style={styles.modalText}>Please hold on. This usually takes a few seconds.</Text>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: COLORS.background },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: SPACING.lg,
    paddingVertical: SPACING.md,
    borderBottomWidth: 1,
    borderBottomColor: COLORS.border,
  },
  headerTitle: { ...FONT.subhead, fontWeight: '600' as const, color: COLORS.text },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  loadingText: { ...FONT.body, color: COLORS.muted, marginTop: SPACING.md },
  body: { padding: SPACING.lg, gap: SPACING.md },
  bodyHeader: { ...FONT.subhead, fontWeight: '600' as const, color: COLORS.text, marginTop: SPACING.sm },
  bodyText: { ...FONT.body, color: COLORS.muted, lineHeight: 20 },
  fineprint: { ...FONT.caption, color: COLORS.muted, textAlign: 'center', marginTop: SPACING.sm },
  // KYC reassurance card — calm primary-light tone, indented bullets,
  // sits between the body copy and the primary CTA so it doesn't
  // dominate the screen but is impossible to miss.
  kycCard: {
    marginTop: SPACING.md,
    backgroundColor: '#F4F1FF', // soft primary-light tint
    borderRadius: RADIUS.md,
    padding: SPACING.md,
    gap: SPACING.xs,
    borderWidth: 1,
    borderColor: 'rgba(124, 92, 246, 0.18)',
  },
  kycHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: SPACING.xs,
    marginBottom: SPACING.xs,
  },
  kycHeaderText: {
    ...FONT.subhead,
    color: COLORS.text,
    fontWeight: '700' as const,
  },
  kycRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 6,
  },
  kycBullet: {
    ...FONT.caption,
    color: COLORS.primary,
    fontWeight: '800' as const,
    fontSize: 14,
    lineHeight: 18,
  },
  kycText: {
    ...FONT.caption,
    color: COLORS.text,
    lineHeight: 18,
    flex: 1,
  },
  // Auto-redirect card — sits BETWEEN the trust strip and the green CTA.
  // Uses a soft white-on-bg so it doesn't compete with the warm copy
  // above, but the spinner + countdown make the auto-redirect feel
  // intentional, not pushy.
  autoRedirectCard: {
    marginTop: SPACING.md,
    flexDirection: 'row',
    alignItems: 'center',
    gap: SPACING.sm,
    backgroundColor: COLORS.card,
    borderRadius: RADIUS.md,
    paddingVertical: SPACING.sm,
    paddingHorizontal: SPACING.md,
    borderWidth: 1,
    borderColor: 'rgba(124, 92, 246, 0.12)',
  },
  autoRedirectText: {
    ...FONT.caption,
    color: COLORS.text,
    flex: 1,
  },
  autoRedirectCancel: {
    ...FONT.caption,
    color: COLORS.primary,
    fontWeight: '700' as const,
    textDecorationLine: 'underline',
  },
  // Reward chip — bright primary tint, two-line layout. Sits between
  // the rotating message and the auto-redirect banner so it's the
  // emotional anchor before the CTA.
  rewardChip: {
    marginTop: SPACING.md,
    backgroundColor: COLORS.primary,
    borderRadius: RADIUS.md,
    paddingVertical: SPACING.sm,
    paddingHorizontal: SPACING.md,
    flexDirection: 'row',
    alignItems: 'center',
    gap: SPACING.sm,
  },
  rewardChipBadge: {
    backgroundColor: '#fff',
    color: COLORS.primary,
    fontWeight: '900' as const,
    fontSize: 11,
    letterSpacing: 0.5,
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 6,
    overflow: 'hidden',
  },
  rewardChipText: {
    ...FONT.caption,
    color: '#fff',
    fontWeight: '600' as const,
    flex: 1,
  },
  statusCard: {
    backgroundColor: COLORS.card,
    padding: SPACING.lg,
    borderRadius: RADIUS.md,
    alignItems: 'center',
    gap: 6,
  },
  errorCard: { backgroundColor: '#FEF2F2' },
  errorText: { ...FONT.body, color: COLORS.danger, textAlign: 'center' },
  statusEmoji: { fontSize: 40, marginBottom: SPACING.xs },
  statusTitle: { ...FONT.title, fontWeight: '700' as const, color: COLORS.text, marginBottom: 4 },
  statusReason: { ...FONT.body, color: COLORS.muted, textAlign: 'center' },
  statusHint: { ...FONT.body, color: COLORS.muted, textAlign: 'center', marginTop: 4 },
  statusHintMono: {
    ...FONT.caption,
    color: COLORS.muted,
    marginTop: 6,
    fontFamily: Platform.select({ ios: 'Menlo', android: 'monospace', default: 'monospace' }),
  },
  balanceCard: {
    backgroundColor: COLORS.card,
    padding: SPACING.lg,
    borderRadius: RADIUS.md,
    alignItems: 'center',
    gap: 4,
  },
  balanceLabel: { ...FONT.caption, color: COLORS.muted, marginTop: 4 },
  balanceAmount: {
    fontSize: 36,
    fontWeight: '700' as const,
    color: COLORS.text,
    fontVariant: ['tabular-nums'],
  },
  amountRow: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: COLORS.card,
    borderRadius: RADIUS.md,
    paddingHorizontal: SPACING.md,
    paddingVertical: SPACING.sm,
    borderWidth: 1,
    borderColor: COLORS.border,
  },
  dollarSign: { fontSize: 28, color: COLORS.muted, marginRight: 6 },
  amountInput: {
    flex: 1,
    fontSize: 28,
    fontWeight: '600' as const,
    color: COLORS.text,
    fontVariant: ['tabular-nums'],
    paddingVertical: 4,
  },
  maxBtn: {
    paddingHorizontal: SPACING.sm,
    paddingVertical: 6,
    backgroundColor: COLORS.background,
    borderRadius: RADIUS.sm,
  },
  maxBtnText: { ...FONT.caption, fontWeight: '600' as const, color: COLORS.primary },
  cardRow: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: COLORS.card,
    padding: SPACING.md,
    borderRadius: RADIUS.md,
    borderWidth: 1,
    borderColor: COLORS.border,
  },
  cardRowSelected: { borderColor: COLORS.primary, borderWidth: 2 },
  cardBrand: { ...FONT.subhead, fontWeight: '600' as const, color: COLORS.text },
  cardTag: { ...FONT.caption, color: COLORS.muted, marginTop: 2 },
  primaryBtn: {
    backgroundColor: COLORS.primary,
    paddingVertical: SPACING.md,
    borderRadius: RADIUS.md,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    marginTop: SPACING.md,
    minHeight: 48,
  },
  primaryBtnDisabled: { opacity: 0.5 },
  primaryBtnText: { ...FONT.subhead, color: '#fff', fontWeight: '700' as const },
  webviewFooter: {
    paddingVertical: SPACING.sm,
    paddingHorizontal: SPACING.lg,
    borderTopWidth: 1,
    borderTopColor: COLORS.border,
    backgroundColor: COLORS.card,
    alignItems: 'flex-end',
  },
  webviewFooterLink: { ...FONT.body, color: COLORS.primary, fontWeight: '600' as const },
  modalBackdrop: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.5)',
    justifyContent: 'center',
    alignItems: 'center',
    padding: SPACING.lg,
  },
  modalCard: {
    backgroundColor: COLORS.card,
    padding: SPACING.lg,
    borderRadius: RADIUS.md,
    alignItems: 'center',
    gap: SPACING.sm,
    minWidth: 280,
  },
  modalTitle: { ...FONT.subhead, fontWeight: '600' as const, color: COLORS.text },
  modalText: { ...FONT.body, color: COLORS.muted, textAlign: 'center' },
});

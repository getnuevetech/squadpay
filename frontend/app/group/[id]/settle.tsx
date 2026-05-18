/**
 * Settle Screen — Lead's settlement decision point.
 *
 * Reached when the squad pool is fully funded. Respects the admin-configured
 * Settlement Mode:
 *   • virtual_card   → auto-route to Squad Card flow (no picker)
 *   • lead_card      → show Direct Payout form (no picker)
 *   • lead_choice    → show "Squad Card vs Direct Payout" picker first
 *
 * Direct Payout flow has two methods (tabs):
 *   • ACH (bank transfer)  — routing #, account #, holder name
 *   • Push-to-Debit-Card   — card #, exp, CVV, holder name
 *
 * Compliance posture (founder mandate):
 *   - DETAILS ARE TOKENIZED & DISCARDED at the backend boundary.
 *   - No AsyncStorage / no `useRef` persistence after submit.
 *   - All input state cleared once the POST completes.
 */
import { useLocalSearchParams, useRouter } from 'expo-router';
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
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
import { CreditCard, Landmark, Shield, ArrowLeft, Wallet, CheckCircle2, AlertCircle } from 'lucide-react-native';
import { Button } from '../../../src/Button';
import { loadUser, loadSessionId } from '../../../src/session';
import { COLORS, FONT, RADIUS, SPACING } from '../../../src/theme';
import { toast } from '../../../src/components/Toast';
import { CardCollector, type CardCollectorHandle } from '../../../src/components/CardCollector';

type Eligibility = {
  eligible: boolean;
  reasons: string[];
  fully_funded: boolean;
  settlement_mode: 'virtual_card' | 'lead_card' | 'lead_choice';
  funding_mode: string;
  available_cents: number;
  available_usd: number;
  supports_ach: boolean;
  supports_card: boolean;
  show_virtual_card_option: boolean;
  show_lead_payout_option: boolean;
};

type Stage = 'loading' | 'choose' | 'payout_method' | 'payout_form' | 'success';
type Method = 'ach' | 'push_to_card';

const BACKEND = process.env.EXPO_PUBLIC_BACKEND_URL || '';

export default function SettleScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [stage, setStage] = useState<Stage>('loading');
  const [elig, setElig] = useState<Eligibility | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [method, setMethod] = useState<Method>('ach');
  const [submitting, setSubmitting] = useState(false);

  // ACH inputs (cleared after submit — never persisted)
  const [routingNumber, setRoutingNumber] = useState('');
  const [accountNumber, setAccountNumber] = useState('');
  const [accountHolder, setAccountHolder] = useState('');
  const [accountType, setAccountType] = useState<'checking' | 'savings'>('checking');

  // Card inputs — now collected via Stripe Elements (web) / CardField (native).
  // We only retain the cardholder name in JS state; PAN/exp/CVV are owned by
  // the Stripe iframe / native view and never enter our memory.
  const [cardholderName, setCardholderName] = useState('');
  const cardRef = useRef<CardCollectorHandle | null>(null);
  const [cardReady, setCardReady] = useState(false);

  // Success state
  const [receipt, setReceipt] = useState<{ amount: number; method: string; last4: string; status: string } | null>(null);

  const loadEligibility = useCallback(async () => {
    try {
      const user = await loadUser();
      const sid = await loadSessionId();
      if (!user || !sid) {
        router.replace('/(auth)/login');
        return;
      }
      const r = await fetch(
        `${BACKEND}/api/group/${id}/lead-payout/eligibility?user_id=${user.id}&session_id=${sid}`,
      );
      if (!r.ok) {
        const j = await r.json().catch(() => ({}));
        throw new Error(j.detail || `HTTP ${r.status}`);
      }
      const j: Eligibility = await r.json();
      setElig(j);

      // Auto-routing decisions:
      if (!j.fully_funded) {
        setError('Squad isn\u2019t fully funded yet.');
        setStage('choose');
        return;
      }
      if (j.settlement_mode === 'virtual_card') {
        // No picker — route immediately to existing virtual-card flow.
        router.replace(`/group/${id}/pay?kind=lead`);
        return;
      }
      if (j.settlement_mode === 'lead_card') {
        // Skip choice — go straight to payout method picker.
        setStage('payout_method');
        return;
      }
      // lead_choice
      setStage('choose');
    } catch (e: any) {
      setError(e?.message || 'Could not load settlement options');
      setStage('choose');
    }
  }, [id, router]);

  useEffect(() => {
    loadEligibility();
  }, [loadEligibility]);

  const goToVirtualCard = () => {
    router.replace(`/group/${id}/pay?kind=lead`);
  };

  const goToPayoutMethod = () => {
    setStage('payout_method');
  };

  const pickMethod = (m: Method) => {
    setMethod(m);
    setStage('payout_form');
  };

  const clearAllInputs = () => {
    setRoutingNumber('');
    setAccountNumber('');
    setAccountHolder('');
    setCardholderName('');
    // Card iframe (web) / native field clears itself on unmount.
  };

  const validate = (): string | null => {
    if (method === 'ach') {
      if (!/^\d{9}$/.test(routingNumber)) return 'Routing number must be 9 digits';
      if (!/^\d{4,17}$/.test(accountNumber)) return 'Account number is invalid';
      if (accountHolder.trim().length < 2) return 'Enter the account holder name';
    } else {
      if (!cardReady) return 'Card form is still loading';
      if (cardholderName.trim().length < 2) return 'Enter the cardholder name';
      // CardCollector.tokenize() handles full card validation via Stripe.
    }
    return null;
  };

  const submit = async () => {
    const v = validate();
    if (v) {
      Alert.alert('Check details', v);
      return;
    }
    setSubmitting(true);
    try {
      const user = await loadUser();
      const sid = await loadSessionId();

      let payload: any;
      if (method === 'ach') {
        payload = {
          routing_number: routingNumber.trim(),
          account_number: accountNumber.trim(),
          account_holder_name: accountHolder.trim(),
          account_type: accountType,
        };
      } else {
        // Tokenize via Stripe Elements / native CardField BEFORE the network
        // call. The PAN never leaves the Stripe iframe / native view.
        if (!cardRef.current) throw new Error('Card form not ready');
        const tok = await cardRef.current.tokenize();
        payload = {
          card_token: tok.token,
          cardholder_name: cardholderName.trim() || undefined,
        };
      }

      const r = await fetch(`${BACKEND}/api/group/${id}/lead-payout/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id: user!.id,
          session_id: sid,
          method,
          payload,
        }),
      });
      const j = await r.json();
      if (!r.ok) throw new Error(j.detail || `HTTP ${r.status}`);

      // SECURITY: clear sensitive inputs immediately on success.
      clearAllInputs();

      setReceipt({
        amount: j.amount,
        method: j.method,
        last4: j.last4,
        status: j.status,
      });
      setStage('success');
      toast.success('Settlement initiated');
    } catch (e: any) {
      Alert.alert('Settlement failed', e?.message || 'Please try again');
    } finally {
      setSubmitting(false);
    }
  };

  // ─────── Render ───────
  if (stage === 'loading') {
    return (
      <SafeAreaView style={styles.container}>
        <View style={styles.loadingWrap}>
          <ActivityIndicator size="large" color={COLORS.primary} />
          <Text style={styles.loadingText}>Loading settlement options…</Text>
        </View>
      </SafeAreaView>
    );
  }

  if (stage === 'success' && receipt) {
    return (
      <SafeAreaView style={styles.container}>
        <View style={styles.successWrap}>
          <CheckCircle2 size={64} color={COLORS.success} />
          <Text style={styles.successTitle}>Settlement initiated</Text>
          <Text style={styles.successAmt}>${receipt.amount.toFixed(2)}</Text>
          <Text style={styles.successSub}>
            {receipt.method === 'ach' ? 'ACH transfer to bank' : 'Push-to-debit-card'} •••• {receipt.last4}
          </Text>
          <Text style={styles.successStatus}>Status: {receipt.status}</Text>
          <View style={{ height: SPACING.xl }} />
          <Button title="Back to Squad" onPress={() => router.replace(`/group/${id}/dashboard`)} />
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <KeyboardAvoidingView
        style={{ flex: 1 }}
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        keyboardVerticalOffset={Platform.OS === 'ios' ? 0 : 24}
      >
        {/* Header */}
        <View style={styles.header}>
          <TouchableOpacity onPress={() => router.back()} style={styles.backBtn} hitSlop={10} testID="settle-back-btn">
            <ArrowLeft size={22} color={COLORS.text} />
          </TouchableOpacity>
          <Text style={styles.headerTitle} testID="settle-header-title">Settle Squad</Text>
          <View style={{ width: 22 }} />
        </View>

        <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
          {/* Amount summary */}
          {elig && elig.fully_funded && (
            <View style={styles.amountCard}>
              <Text style={styles.amountLabel}>Ready to settle</Text>
              <Text style={styles.amountValue}>${elig.available_usd.toFixed(2)}</Text>
              <View style={styles.privacyRow}>
                <Shield size={12} color={COLORS.success} />
                <Text style={styles.privacyText}>
                  Details are tokenized and discarded after this single transfer.
                </Text>
              </View>
            </View>
          )}

          {error && (
            <View style={styles.errorCard}>
              <AlertCircle size={16} color={COLORS.danger} />
              <Text style={styles.errorText}>{error}</Text>
            </View>
          )}

          {/* STAGE: choose — virtual card vs direct payout */}
          {stage === 'choose' && elig?.fully_funded && (
            <View>
              <Text style={styles.sectionTitle}>How would you like to settle?</Text>
              {elig.show_virtual_card_option && (
                <TouchableOpacity style={styles.choiceCard} onPress={goToVirtualCard} activeOpacity={0.85} testID="settle-choice-virtual-card">
                  <View style={styles.choiceIconWrap}>
                    <Wallet size={24} color={COLORS.primary} />
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.choiceTitle}>Pay with Squad Card</Text>
                    <Text style={styles.choiceSub}>
                      Use the issued virtual card to pay the merchant directly.
                    </Text>
                  </View>
                </TouchableOpacity>
              )}
              {elig.show_lead_payout_option && (
                <TouchableOpacity style={styles.choiceCard} onPress={goToPayoutMethod} activeOpacity={0.85} testID="settle-choice-send-to-me">
                  <View style={styles.choiceIconWrap}>
                    <Landmark size={24} color={COLORS.primary} />
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.choiceTitle}>Send Money to Me</Text>
                    <Text style={styles.choiceSub}>
                      Push funds to your bank or debit card. You handle the merchant.
                    </Text>
                  </View>
                </TouchableOpacity>
              )}
            </View>
          )}

          {/* STAGE: payout_method — ACH vs Push-to-Card */}
          {stage === 'payout_method' && elig?.fully_funded && (
            <View>
              <Text style={styles.sectionTitle}>Where should we send the money?</Text>
              {elig.supports_ach && (
                <TouchableOpacity style={styles.choiceCard} onPress={() => pickMethod('ach')} activeOpacity={0.85} testID="settle-method-ach">
                  <View style={styles.choiceIconWrap}>
                    <Landmark size={24} color={COLORS.primary} />
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.choiceTitle}>Bank Transfer (ACH)</Text>
                    <Text style={styles.choiceSub}>1–2 business days · No fees</Text>
                  </View>
                </TouchableOpacity>
              )}
              {elig.supports_card && (
                <TouchableOpacity style={styles.choiceCard} onPress={() => pickMethod('push_to_card')} activeOpacity={0.85} testID="settle-method-card">
                  <View style={styles.choiceIconWrap}>
                    <CreditCard size={24} color={COLORS.primary} />
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.choiceTitle}>Debit Card (Instant)</Text>
                    <Text style={styles.choiceSub}>Within minutes · Small instant-payout fee may apply</Text>
                  </View>
                </TouchableOpacity>
              )}
            </View>
          )}

          {/* STAGE: payout_form — ACH or Card input */}
          {stage === 'payout_form' && method === 'ach' && (
            <View>
              <Text style={styles.sectionTitle}>Enter your bank details</Text>
              <Text style={styles.fieldLabel}>Account holder name</Text>
              <TextInput
                style={styles.input}
                value={accountHolder}
                onChangeText={setAccountHolder}
                placeholder="Full legal name"
                placeholderTextColor={COLORS.disabledText}
                autoCapitalize="words"
                testID="settle-ach-holder-input"
              />
              <Text style={styles.fieldLabel}>Routing number</Text>
              <TextInput
                style={styles.input}
                value={routingNumber}
                onChangeText={(t) => setRoutingNumber(t.replace(/\D/g, '').slice(0, 9))}
                placeholder="9 digits"
                placeholderTextColor={COLORS.disabledText}
                keyboardType="number-pad"
                maxLength={9}
                testID="settle-ach-routing-input"
              />
              <Text style={styles.fieldLabel}>Account number</Text>
              <TextInput
                style={styles.input}
                value={accountNumber}
                onChangeText={(t) => setAccountNumber(t.replace(/\D/g, '').slice(0, 17))}
                placeholder="Bank account number"
                placeholderTextColor={COLORS.disabledText}
                keyboardType="number-pad"
                secureTextEntry
                testID="settle-ach-account-input"
              />
              <Text style={styles.fieldLabel}>Account type</Text>
              <View style={styles.segRow}>
                {(['checking', 'savings'] as const).map((t) => (
                  <TouchableOpacity
                    key={t}
                    style={[styles.segBtn, accountType === t && styles.segBtnOn]}
                    onPress={() => setAccountType(t)}
                    testID={`settle-ach-acct-type-${t}`}
                  >
                    <Text style={[styles.segText, accountType === t && styles.segTextOn]}>
                      {t === 'checking' ? 'Checking' : 'Savings'}
                    </Text>
                  </TouchableOpacity>
                ))}
              </View>

              <View style={{ height: SPACING.lg }} />
              <Button
                title={submitting ? 'Submitting…' : `Send $${elig?.available_usd.toFixed(2)} via ACH`}
                onPress={submit}
                disabled={submitting}
                testID="settle-ach-submit-btn"
              />
              <TouchableOpacity onPress={() => setStage('payout_method')} style={styles.linkBtn} testID="settle-change-method-link-ach">
                <Text style={styles.linkText}>Change method</Text>
              </TouchableOpacity>
            </View>
          )}

          {stage === 'payout_form' && method === 'push_to_card' && (
            <View>
              <Text style={styles.sectionTitle}>Enter your debit card</Text>
              <Text style={styles.fieldLabel}>Cardholder name</Text>
              <TextInput
                style={styles.input}
                value={cardholderName}
                onChangeText={setCardholderName}
                placeholder="Name on card"
                placeholderTextColor={COLORS.disabledText}
                autoCapitalize="words"
                testID="settle-card-holder-input"
              />
              <Text style={styles.fieldLabel}>Card details</Text>
              <CardCollector
                ref={cardRef}
                cardholderName={cardholderName}
                onReady={setCardReady}
              />
              <Text style={styles.cardHint}>
                Card data is entered in a Stripe-hosted field; SquadPay never sees the card number or CVV.
              </Text>

              <View style={{ height: SPACING.lg }} />
              <Button
                title={submitting ? 'Submitting…' : `Send $${elig?.available_usd.toFixed(2)} to card`}
                onPress={submit}
                disabled={submitting || !cardReady}
                testID="settle-card-submit-btn"
              />
              <TouchableOpacity onPress={() => setStage('payout_method')} style={styles.linkBtn} testID="settle-change-method-link-card">
                <Text style={styles.linkText}>Change method</Text>
              </TouchableOpacity>
            </View>
          )}
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: COLORS.bg },
  loadingWrap: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  loadingText: { marginTop: SPACING.md, color: COLORS.subtext, fontSize: FONT.body },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: SPACING.lg,
    paddingVertical: SPACING.md,
    backgroundColor: COLORS.surface,
    borderBottomWidth: 1,
    borderBottomColor: COLORS.border,
  },
  backBtn: { padding: 4 },
  headerTitle: { fontSize: FONT.h3, fontWeight: '700', color: COLORS.text },
  scroll: { padding: SPACING.lg, paddingBottom: SPACING.xl * 2 },
  amountCard: {
    backgroundColor: COLORS.primaryLight,
    borderRadius: RADIUS.lg,
    padding: SPACING.lg,
    marginBottom: SPACING.lg,
    alignItems: 'center',
  },
  amountLabel: { fontSize: FONT.small, color: COLORS.subtext, marginBottom: 4 },
  amountValue: { fontSize: 36, fontWeight: '800', color: COLORS.primary, letterSpacing: -1 },
  privacyRow: { flexDirection: 'row', alignItems: 'center', marginTop: SPACING.sm, gap: 6 },
  privacyText: { fontSize: 11, color: COLORS.subtext, flex: 1, marginLeft: 4 },
  errorCard: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: COLORS.dangerLight,
    borderRadius: RADIUS.md,
    padding: SPACING.md,
    marginBottom: SPACING.md,
    gap: SPACING.sm,
  },
  errorText: { color: COLORS.danger, flex: 1, marginLeft: SPACING.sm },
  sectionTitle: { fontSize: FONT.h4, fontWeight: '700', color: COLORS.text, marginBottom: SPACING.md },
  choiceCard: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.lg,
    borderWidth: 1,
    borderColor: COLORS.border,
    padding: SPACING.lg,
    marginBottom: SPACING.md,
    gap: SPACING.md,
  },
  choiceIconWrap: {
    width: 48,
    height: 48,
    borderRadius: 24,
    backgroundColor: COLORS.primaryLight,
    alignItems: 'center',
    justifyContent: 'center',
  },
  choiceTitle: { fontSize: FONT.body, fontWeight: '700', color: COLORS.text },
  choiceSub: { fontSize: FONT.small, color: COLORS.subtext, marginTop: 2 },
  fieldLabel: { fontSize: FONT.small, color: COLORS.textMuted, marginBottom: 6, marginTop: SPACING.md, fontWeight: '600' },
  input: {
    borderWidth: 1,
    borderColor: COLORS.border,
    borderRadius: RADIUS.md,
    paddingHorizontal: SPACING.md,
    paddingVertical: Platform.OS === 'ios' ? 14 : 10,
    fontSize: FONT.body,
    color: COLORS.text,
    backgroundColor: COLORS.surface,
  },
  row: { flexDirection: 'row', alignItems: 'flex-start' },
  segRow: { flexDirection: 'row', gap: SPACING.sm },
  segBtn: {
    flex: 1,
    paddingVertical: 10,
    borderRadius: RADIUS.md,
    borderWidth: 1,
    borderColor: COLORS.border,
    alignItems: 'center',
    backgroundColor: COLORS.surface,
  },
  segBtnOn: { backgroundColor: COLORS.primary, borderColor: COLORS.primary },
  segText: { color: COLORS.textMuted, fontWeight: '600' },
  segTextOn: { color: '#fff' },
  linkBtn: { alignItems: 'center', padding: SPACING.md },
  linkText: { color: COLORS.primary, fontWeight: '600' },
  cardHint: { fontSize: 11, color: COLORS.subtext, marginTop: 8, lineHeight: 16 },
  successWrap: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: SPACING.xl },
  successTitle: { fontSize: FONT.h2, fontWeight: '800', color: COLORS.text, marginTop: SPACING.lg },
  successAmt: { fontSize: 40, fontWeight: '800', color: COLORS.primary, marginTop: SPACING.sm, letterSpacing: -1 },
  successSub: { fontSize: FONT.body, color: COLORS.subtext, marginTop: SPACING.sm, textAlign: 'center' },
  successStatus: { fontSize: FONT.small, color: COLORS.textMuted, marginTop: SPACING.xs, textTransform: 'capitalize' },
});

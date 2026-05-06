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
import { Check, CreditCard, Lock, Smartphone, Wallet, ShieldCheck } from 'lucide-react-native';
import { Button } from '../../../src/Button';
import { api, Group } from '../../../src/api';
import { refreshUser, saveUser } from '../../../src/session';
import { COLORS, FONT, RADIUS, SPACING } from '../../../src/theme';

type Kind = 'lead' | 'repay' | 'contribute';
type VerifyStep = 'idle' | 'phone' | 'otp';

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

  // Shortfall settlement (lead pay flow only)
  const [shortfallMode, setShortfallMode] = useState<'lead' | 'member' | 'split_equal'>('lead');
  const [isLoan, setIsLoan] = useState<boolean>(true);
  const [funderMemberId, setFunderMemberId] = useState<string | null>(null);

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
      const r = await api.createCheckoutSession(id, origin);
      if (Platform.OS === 'web' && typeof window !== 'undefined') {
        window.location.href = r.url;
      } else {
        try {
          const WebBrowser = require('expo-web-browser');
          await WebBrowser.openBrowserAsync(r.url);
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
    title = hasShortfall ? 'Pay your share + shortfall' : 'Contribute upfront';
    summary = hasShortfall
      ? `Includes your shortfall obligation of $${myShortfallOwed.toFixed(2)}. Pay so the bill can be settled.`
      : `Pay your share into the group wallet so the lead doesn't have to cover it.`;
    actorIcon = <Wallet color={COLORS.primary} size={18} />;
    actorTitle = 'Group wallet';
    actorSub = 'Funds held until the merchant is paid';
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
      await api.sendOtp(userId, cleaned);
      setVerifyStep('otp');
    } catch (e: any) {
      Alert.alert('Error', e.message);
    } finally {
      setVerifyLoading(false);
    }
  };

  const verifyCode = async () => {
    if (otp.length !== 6) {
      Alert.alert('Enter the 6-digit code');
      return;
    }
    setVerifyLoading(true);
    try {
      const u = await api.verifyOtp(userId, phone.trim(), otp);
      await saveUser(u);
      setIsVerified(true);
      setVerifyStep('idle');
      setOtp('');
    } catch (e: any) {
      Alert.alert('Invalid code', e.message);
    } finally {
      setVerifyLoading(false);
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
          Alert.alert(
            'Shortfall assigned',
            `Shortfall request ${verb}. They've been notified to pay before the bill can be settled.`,
          );
          router.replace(`/group/${group.id}`);
          return;
        }
      } else if (kind === 'contribute') {
        // Phase F1: contribute via Stripe Checkout (real card) — credits applied automatically.
        const origin =
          Platform.OS === 'web' && typeof window !== 'undefined'
            ? window.location.origin
            : (process.env.EXPO_PUBLIC_BACKEND_URL || '').replace(/\/api$/, '');
        const r: any = await api.contribute(group.id, userId, amount, notifyOnSettled, origin);
        if (r.checkout_required === false) {
          // Fully covered by credits — no Stripe needed
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
            await WebBrowser.openBrowserAsync(r.url);
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

          <View style={styles.card}>
            <View style={styles.row}>
              <View style={styles.icon}>{actorIcon}</View>
              <View style={{ flex: 1 }}>
                <Text style={styles.rowTitle}>{actorTitle}</Text>
                {actorSub ? <Text style={styles.rowSub}>{actorSub}</Text> : null}
              </View>
            </View>
            <View style={styles.divider} />
            <View style={styles.row}>
              <View style={[styles.icon, { backgroundColor: COLORS.disabledBg }]}>
                <Lock color={COLORS.subtext} size={18} />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.rowTitle}>Secure</Text>
                <Text style={styles.rowSub}>Encrypted • reversible</Text>
              </View>
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
                    placeholder="+1 555 123 4567"
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
                    Enter the code sent to {phone}.{' '}
                    <Text style={{ fontWeight: '700' }}>(Demo: 123456)</Text>
                  </Text>
                  <TextInput
                    testID="pay-verify-otp-input"
                    value={otp}
                    onChangeText={(t) => setOtp(t.replace(/\D/g, '').slice(0, 6))}
                    placeholder="123456"
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
                Some members haven't contributed yet. Pick how to settle the gap:
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
                      No other members have joined yet. Choose another option.
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
                      <Text style={[styles.loanGiftSub, isLoan && { color: '#E0E7FF' }]}>
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
                      <Text style={[styles.loanGiftSub, !isLoan && { color: '#E0E7FF' }]}>
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
                  💡 The shortfall will be split equally across all members (including you, the lead). Each person gets an SMS and sees their share as an additional bill.
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
            <Button
              title="Verify phone to continue"
              onPress={() => setVerifyStep('phone')}
              testID="pay-start-verify-btn"
              leftIcon={<ShieldCheck size={18} color="#fff" />}
            />
          ) : (
            <>
              <Button
                title={`Pay $${amount.toFixed(2)}`}
                loading={loading}
                onPress={doPay}
                testID="pay-submit-btn"
                leftIcon={<CreditCard size={18} color="#fff" />}
                disabled={!isVerified || blockedNoAmount}
              />
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
            onPress={() => router.back()}
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

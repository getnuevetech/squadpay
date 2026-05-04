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
  const { id, kind } = useLocalSearchParams<{ id: string; kind?: Kind }>();
  const router = useRouter();
  const [group, setGroup] = useState<Group | null>(null);
  const [userId, setUserId] = useState<string | null>(null);
  const [isVerified, setIsVerified] = useState(false);
  const [loading, setLoading] = useState(false);

  // Inline verification state
  const [verifyStep, setVerifyStep] = useState<VerifyStep>('idle');
  const [phone, setPhone] = useState('');
  const [otp, setOtp] = useState('');
  const [verifyLoading, setVerifyLoading] = useState(false);

  // Receipt-update opt-in (contribute flow only)
  const [notifyOnSettled, setNotifyOnSettled] = useState(true);

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
        : `Single-use virtual card for the full bill.`;
    actorIcon = <CreditCard color={COLORS.primary} size={18} />;
    actorTitle = 'Virtual Card';
    actorSub = 'Single-use card issued for this bill';
  } else if (kind === 'contribute') {
    const myShare = myPer?.total || 0;
    const myContrib = myPer?.contributed || 0;
    amount = Math.max(0, myShare - myContrib);
    title = 'Contribute upfront';
    summary = `Pay your share into the group wallet so the lead doesn't have to cover it.`;
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
        await api.payGroup(group.id, userId);
      } else if (kind === 'contribute') {
        await api.contribute(group.id, userId, amount, notifyOnSettled);
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
          {!isVerified && verifyStep === 'idle' ? (
            <Button
              title="Verify phone to continue"
              onPress={() => setVerifyStep('phone')}
              testID="pay-start-verify-btn"
              leftIcon={<ShieldCheck size={18} color="#fff" />}
            />
          ) : (
            <Button
              title={`Pay $${amount.toFixed(2)}`}
              loading={loading}
              onPress={doPay}
              testID="pay-submit-btn"
              leftIcon={<CreditCard size={18} color="#fff" />}
              disabled={!isVerified || blockedNoAmount}
            />
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
  bottomBar: {
    padding: SPACING.md,
    backgroundColor: COLORS.surface,
    borderTopWidth: 1,
    borderTopColor: COLORS.border,
  },
});

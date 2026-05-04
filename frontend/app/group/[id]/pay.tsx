import { useLocalSearchParams, useRouter } from 'expo-router';
import { useEffect, useState } from 'react';
import { Alert, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { CreditCard, Apple, Lock, Smartphone } from 'lucide-react-native';
import { Button } from '../../../src/Button';
import { api, Group } from '../../../src/api';
import { loadUser, refreshUser } from '../../../src/session';
import { COLORS, FONT, RADIUS, SPACING } from '../../../src/theme';

export default function PayScreen() {
  const { id, kind } = useLocalSearchParams<{ id: string; kind?: string }>();
  const router = useRouter();
  const [group, setGroup] = useState<Group | null>(null);
  const [userId, setUserId] = useState<string | null>(null);
  const [isVerified, setIsVerified] = useState(false);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    (async () => {
      const u = await refreshUser();
      if (!u) {
        router.replace('/auth');
        return;
      }
      setUserId(u.id);
      setIsVerified(u.verified);
      try {
        const g = await api.getGroup(id);
        setGroup(g);
      } catch (e: any) {
        Alert.alert('Error', e.message);
      }
    })();
  }, [id, router]);

  if (!group || !userId) return null;

  const isLead = userId === group.lead_id;
  const isLeadPay = kind === 'lead' && isLead;
  const myPer = group.per_user.find((p) => p.user_id === userId);
  const repaid = group.repayments.filter((r) => r.user_id === userId).reduce((s, r) => s + r.amount, 0);
  const myOutstanding = Math.max(0, (myPer?.total || 0) - repaid);

  const amount = isLeadPay ? group.total : myOutstanding;
  const label = isLeadPay ? 'Pay restaurant' : 'Pay your share';

  const doPay = async () => {
    if (!isLeadPay && !isVerified) {
      Alert.alert('Verify phone', 'Phone verification is required to pay. Go to Profile → Sign in and verify.');
      return;
    }
    setLoading(true);
    try {
      if (isLeadPay) {
        await api.payGroup(group.id, userId);
      } else {
        await api.repay(group.id, userId, amount);
      }
      router.replace(`/group/${group.id}/success?amount=${amount.toFixed(2)}&kind=${kind || 'repay'}`);
    } catch (e: any) {
      Alert.alert('Payment failed', e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <SafeAreaView edges={['bottom']} style={{ flex: 1, backgroundColor: COLORS.bg }}>
      <View style={styles.container}>
        <Text style={styles.label}>{label}</Text>
        <Text style={styles.amount} testID="pay-amount">${amount.toFixed(2)}</Text>

        <View style={styles.card}>
          <View style={styles.row}>
            <View style={styles.icon}>
              <Smartphone color={COLORS.primary} size={18} />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.rowTitle}>
                {isLeadPay ? 'Virtual Card' : 'In-app balance'}
              </Text>
              <Text style={styles.rowSub}>
                {isLeadPay
                  ? 'Single-use card issued for this bill'
                  : 'Repay the lead instantly'}
              </Text>
            </View>
          </View>
          <View style={styles.divider} />
          <View style={styles.row}>
            <View style={styles.icon}>
              <Lock color={COLORS.subtext} size={18} />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.rowTitle}>Secure</Text>
              <Text style={styles.rowSub}>Encrypted and reversible</Text>
            </View>
          </View>
        </View>

        {!isVerified && !isLeadPay && (
          <View style={styles.warn}>
            <Text style={styles.warnText}>
              Phone verification required before you can pay. Please sign out and verify.
            </Text>
          </View>
        )}

        <View style={styles.spacer} />

        <Button
          title={isLeadPay ? `Pay $${amount.toFixed(2)}` : `Pay $${amount.toFixed(2)}`}
          loading={loading}
          onPress={doPay}
          testID="pay-submit-btn"
          leftIcon={<CreditCard size={18} color="#fff" />}
        />
        <Button
          title="Cancel"
          variant="ghost"
          onPress={() => router.back()}
          testID="pay-cancel-btn"
          style={{ marginTop: SPACING.sm }}
        />
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: SPACING.lg, justifyContent: 'space-between' },
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
  warn: {
    marginTop: SPACING.md,
    padding: SPACING.md,
    borderRadius: RADIUS.md,
    backgroundColor: COLORS.warningLight,
  },
  warnText: { color: '#92400E', fontSize: FONT.sizes.sm, lineHeight: 20 },
  spacer: { flex: 1 },
});

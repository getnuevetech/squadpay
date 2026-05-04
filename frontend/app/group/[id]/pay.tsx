import { useLocalSearchParams, useRouter } from 'expo-router';
import { useEffect, useState } from 'react';
import { Alert, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { CreditCard, Lock, Smartphone, Wallet } from 'lucide-react-native';
import { Button } from '../../../src/Button';
import { api, Group } from '../../../src/api';
import { refreshUser } from '../../../src/session';
import { COLORS, FONT, RADIUS, SPACING } from '../../../src/theme';

type Kind = 'lead' | 'repay' | 'contribute';

export default function PayScreen() {
  const { id, kind } = useLocalSearchParams<{ id: string; kind?: Kind }>();
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

  const myPer = group.per_user.find((p) => p.user_id === userId);
  const isLead = userId === group.lead_id;

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
    // repay
    amount = myPer?.outstanding || 0;
    title = 'Pay your share';
    summary = `Reimburse the lead for what they covered upfront.`;
  }

  const blockedNoPhone = !isVerified;
  const blockedNoAmount = amount <= 0;

  const doPay = async () => {
    if (blockedNoPhone) {
      Alert.alert('Verify phone', 'Phone verification is required before paying.');
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
        await api.contribute(group.id, userId, amount);
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
    <SafeAreaView edges={['bottom']} style={{ flex: 1, backgroundColor: COLORS.bg }}>
      <View style={styles.container}>
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

        {blockedNoPhone && (
          <View style={styles.warn}>
            <Text style={styles.warnText}>
              Phone verification required before you can pay. Please sign out from Home and verify your phone.
            </Text>
          </View>
        )}

        <View style={styles.spacer} />

        <Button
          title={`Pay $${amount.toFixed(2)}`}
          loading={loading}
          onPress={doPay}
          testID="pay-submit-btn"
          leftIcon={<CreditCard size={18} color="#fff" />}
          disabled={blockedNoPhone || blockedNoAmount}
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
  warn: {
    marginTop: SPACING.md,
    padding: SPACING.md,
    borderRadius: RADIUS.md,
    backgroundColor: COLORS.warningLight,
  },
  warnText: { color: '#92400E', fontSize: FONT.sizes.sm, lineHeight: 20 },
  spacer: { flex: 1 },
});

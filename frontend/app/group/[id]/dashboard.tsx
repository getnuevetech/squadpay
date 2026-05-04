import { useLocalSearchParams, useRouter } from 'expo-router';
import { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { CheckCircle2, Clock, Zap, Landmark, TrendingUp, Plus } from 'lucide-react-native';
import { api, Group } from '../../../src/api';
import { loadUser } from '../../../src/session';
import { COLORS, FONT, RADIUS, SPACING } from '../../../src/theme';

export default function DashboardScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [group, setGroup] = useState<Group | null>(null);
  const [userId, setUserId] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    const u = await loadUser();
    if (!u) {
      router.replace('/auth');
      return;
    }
    setUserId(u.id);
    try {
      const g = await api.getGroup(id);
      setGroup(g);
    } catch (e: any) {
      Alert.alert('Error', e.message);
    }
  }, [id, router]);

  useEffect(() => {
    load();
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [load]);

  const onRefresh = async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  };

  if (!group || !userId) {
    return (
      <SafeAreaView style={styles.center}>
        <ActivityIndicator color={COLORS.primary} />
      </SafeAreaView>
    );
  }

  const repaidByUser = (uid: string) =>
    group.repayments.filter((r) => r.user_id === uid).reduce((s, r) => s + r.amount, 0);
  // Reflects both upfront contributions and post-payment repayments via per_user.outstanding.
  const totalCollected = (group.funding?.total_contributed || 0) + (group.funding?.total_repaid || 0);
  const totalOwed = group.per_user
    .filter((p) => p.user_id !== group.lead_id)
    .reduce((s, p) => s + p.total, 0);
  const pct = totalOwed > 0 ? Math.min(100, (totalCollected / totalOwed) * 100) : 100;
  const pendingMembers = group.members.filter((m) => {
    if (m.user_id === group.lead_id) return false;
    const per = group.per_user.find((p) => p.user_id === m.user_id);
    return (per?.outstanding || 0) > 0.01;
  });

  // Withdrawal eligibility:
  // - Group-funded (Option A): wallet went straight to merchant; lead is owed nothing → no withdraw.
  // - Lead-funded (Option B): lead loaned full bill → withdraw = repayments collected.
  // - Shortfall (Option C):  lead covered the gap  → withdraw = repayments collected.
  const leadFronted =
    group.status !== 'open' &&
    (group.funding_mode === 'lead' || group.funding_mode === 'shortfall') &&
    (group.lead_shortfall || 0) > 0.01;
  const withdrawable = leadFronted ? group.funding?.total_repaid || 0 : 0;

  const withdraw = (kind: 'instant' | 'standard') => {
    Alert.alert(
      kind === 'instant' ? 'Instant Withdraw' : 'Standard Withdraw',
      kind === 'instant'
        ? `$${withdrawable.toFixed(2)} will arrive in minutes. A 1.5% fee applies.`
        : `$${withdrawable.toFixed(2)} will arrive in 1–2 business days. No fee.`,
      [{ text: 'OK' }],
    );
  };

  return (
    <SafeAreaView edges={['bottom']} style={{ flex: 1, backgroundColor: COLORS.bg }}>
      <ScrollView
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={COLORS.primary} />}
        contentContainerStyle={{ padding: SPACING.md, paddingBottom: SPACING.xxl }}
      >
        <View style={styles.heroCard} testID="dashboard-hero">
          <Text style={styles.heroLabel}>Collected</Text>
          <View style={styles.heroRow}>
            <Text style={styles.heroAmount}>${totalCollected.toFixed(2)}</Text>
            <Text style={styles.heroOf}>/ ${totalOwed.toFixed(2)}</Text>
          </View>
          <View style={styles.progressBar}>
            <View style={[styles.progressFill, { width: `${Math.min(100, pct)}%` }]} />
          </View>
          <Text style={styles.heroFoot}>
            {pendingMembers.length === 0
              ? 'All repayments received 🎉'
              : `${pendingMembers.length} ${pendingMembers.length === 1 ? 'person' : 'people'} still owe`}
          </Text>
        </View>

        <Text style={styles.sectionTitle}>Withdraw</Text>
        {leadFronted ? (
          <>
            <View style={styles.withdrawHero} testID="dashboard-withdraw-hero">
              <View style={{ flex: 1 }}>
                <Text style={styles.withdrawHeroLabel}>Available to withdraw</Text>
                <Text style={styles.withdrawHeroAmount}>${withdrawable.toFixed(2)}</Text>
                <Text style={styles.withdrawHeroSub}>
                  You fronted ${(group.lead_shortfall || 0).toFixed(2)} for the group.
                  {pendingMembers.length > 0
                    ? ` ${pendingMembers.length} member${pendingMembers.length === 1 ? '' : 's'} still owe.`
                    : ' All settled.'}
                </Text>
              </View>
            </View>
            <View style={styles.withdrawRow}>
              <TouchableOpacity
                testID="dashboard-withdraw-instant"
                style={[styles.withdrawCard, { borderColor: COLORS.primary }]}
                onPress={() => withdraw('instant')}
                activeOpacity={0.85}
                disabled={withdrawable <= 0}
              >
                <View style={styles.withdrawIcon}>
                  <Zap size={22} color={COLORS.primary} />
                </View>
                <Text style={styles.withdrawTitle}>Instant</Text>
                <Text style={styles.withdrawSub}>Arrives in minutes</Text>
                <Text style={styles.withdrawFee}>1.5% fee</Text>
              </TouchableOpacity>
              <TouchableOpacity
                testID="dashboard-withdraw-standard"
                style={styles.withdrawCard}
                onPress={() => withdraw('standard')}
                activeOpacity={0.85}
                disabled={withdrawable <= 0}
              >
                <View style={styles.withdrawIcon}>
                  <Landmark size={22} color={COLORS.primary} />
                </View>
                <Text style={styles.withdrawTitle}>Standard</Text>
                <Text style={styles.withdrawSub}>1–2 business days</Text>
                <Text style={[styles.withdrawFee, { color: COLORS.success }]}>Free</Text>
              </TouchableOpacity>
            </View>
          </>
        ) : (
          <View style={styles.noWithdrawCard} testID="dashboard-no-withdraw">
            <View style={styles.noWithdrawIcon}>
              <Landmark size={20} color={COLORS.subtext} />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.noWithdrawTitle}>No withdrawal needed</Text>
              <Text style={styles.noWithdrawSub}>
                {group.status === 'open'
                  ? 'Withdrawal unlocks once you cover any shortfall when paying the merchant.'
                  : group.funding_mode === 'group'
                  ? 'Bill was fully group-funded — the wallet went straight to the merchant, so there is nothing to withdraw.'
                  : 'No outstanding amount to withdraw.'}
              </Text>
            </View>
          </View>
        )}

        <Text style={styles.sectionTitle}>Members</Text>
        <View style={styles.listCard}>
          {group.members.map((m, idx) => {
            if (m.user_id === group.lead_id) return null;
            const per = group.per_user.find((p) => p.user_id === m.user_id);
            const owed = per?.total || 0;
            const contributed = per?.contributed || 0;
            const paid = repaidByUser(m.user_id);
            const outstanding = per?.outstanding || 0;
            const done = outstanding <= 0.01;
            const settledLabel = contributed >= owed - 0.01 ? 'Contributed' : 'Paid';
            return (
              <View
                key={m.user_id}
                testID={`dashboard-member-${m.user_id}`}
                style={[styles.memberRow, idx !== 0 && { borderTopWidth: 1, borderTopColor: COLORS.border }]}
              >
                <View style={styles.avatar}>
                  <Text style={styles.avatarText}>{(m.name || '?').slice(0, 1).toUpperCase()}</Text>
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.memberName}>{m.name}</Text>
                  <View style={styles.statusRow}>
                    {done ? (
                      <>
                        <CheckCircle2 size={12} color={COLORS.success} />
                        <Text style={[styles.statusText, { color: COLORS.success }]}>{settledLabel}</Text>
                      </>
                    ) : (
                      <>
                        <Clock size={12} color={COLORS.warning} />
                        <Text style={[styles.statusText, { color: COLORS.warning }]}>
                          Owes ${outstanding.toFixed(2)}
                        </Text>
                      </>
                    )}
                  </View>
                </View>
                <Text style={styles.amount}>${owed.toFixed(2)}</Text>
              </View>
            );
          })}
        </View>

        {group.repayments.length > 0 && (
          <>
            <Text style={styles.sectionTitle}>Repayment history</Text>
            <View style={styles.listCard}>
              {group.repayments.map((r, idx) => {
                const m = group.members.find((x) => x.user_id === r.user_id);
                return (
                  <View
                    key={r.id}
                    style={[styles.memberRow, idx !== 0 && { borderTopWidth: 1, borderTopColor: COLORS.border }]}
                  >
                    <View style={[styles.avatar, { backgroundColor: COLORS.successLight }]}>
                      <TrendingUp size={16} color={COLORS.success} />
                    </View>
                    <View style={{ flex: 1 }}>
                      <Text style={styles.memberName}>{m?.name || 'Member'}</Text>
                      <Text style={styles.statusText}>{new Date(r.at).toLocaleString()}</Text>
                    </View>
                    <Text style={[styles.amount, { color: COLORS.success }]}>+${r.amount.toFixed(2)}</Text>
                  </View>
                );
              })}
            </View>
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: COLORS.bg },
  heroCard: {
    backgroundColor: COLORS.text,
    borderRadius: RADIUS.xl,
    padding: SPACING.lg,
    marginBottom: SPACING.lg,
  },
  heroLabel: {
    color: '#9CA3AF',
    fontSize: FONT.sizes.xs,
    textTransform: 'uppercase',
    letterSpacing: 1,
    fontWeight: FONT.weights.semibold,
  },
  heroRow: { flexDirection: 'row', alignItems: 'baseline', gap: 8, marginTop: 4 },
  heroAmount: {
    color: '#fff',
    fontSize: 52,
    fontWeight: FONT.weights.heavy,
    letterSpacing: -1,
  },
  heroOf: { color: '#9CA3AF', fontSize: FONT.sizes.lg, fontWeight: FONT.weights.medium },
  progressBar: {
    height: 8,
    backgroundColor: 'rgba(255,255,255,0.12)',
    borderRadius: RADIUS.pill,
    overflow: 'hidden',
    marginTop: SPACING.md,
  },
  progressFill: { height: '100%', backgroundColor: COLORS.success, borderRadius: RADIUS.pill },
  heroFoot: { color: '#9CA3AF', fontSize: FONT.sizes.sm, marginTop: SPACING.sm },
  sectionTitle: {
    fontSize: FONT.sizes.md,
    fontWeight: FONT.weights.bold,
    color: COLORS.text,
    marginBottom: SPACING.md,
    marginTop: SPACING.md,
  },
  withdrawRow: { flexDirection: 'row', gap: SPACING.sm, marginBottom: SPACING.md },
  withdrawHero: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: COLORS.successLight,
    borderRadius: RADIUS.md,
    padding: SPACING.md,
    marginBottom: SPACING.md,
  },
  withdrawHeroLabel: {
    color: COLORS.success,
    fontSize: FONT.sizes.xs,
    textTransform: 'uppercase',
    letterSpacing: 1,
    fontWeight: FONT.weights.semibold,
  },
  withdrawHeroAmount: {
    color: COLORS.text,
    fontSize: FONT.sizes.xxl,
    fontWeight: FONT.weights.heavy,
    letterSpacing: -0.5,
    marginTop: 2,
  },
  withdrawHeroSub: { color: COLORS.subtext, fontSize: FONT.sizes.xs, marginTop: 4, lineHeight: 16 },
  noWithdrawCard: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: SPACING.md,
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.md,
    padding: SPACING.md,
    borderWidth: 1,
    borderColor: COLORS.border,
    marginBottom: SPACING.md,
  },
  noWithdrawIcon: {
    width: 40,
    height: 40,
    borderRadius: 10,
    backgroundColor: COLORS.disabledBg,
    alignItems: 'center',
    justifyContent: 'center',
  },
  noWithdrawTitle: { fontSize: FONT.sizes.md, fontWeight: FONT.weights.bold, color: COLORS.text },
  noWithdrawSub: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: 2, lineHeight: 16 },
  addItemsBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: SPACING.md,
    backgroundColor: COLORS.surface,
    padding: SPACING.md,
    borderRadius: RADIUS.md,
    borderWidth: 1.5,
    borderColor: COLORS.border,
    borderStyle: 'dashed',
    marginBottom: SPACING.md,
  },
  addItemsIcon: {
    width: 36,
    height: 36,
    borderRadius: 10,
    backgroundColor: COLORS.primaryLight,
    alignItems: 'center',
    justifyContent: 'center',
  },
  addItemsTitle: { fontSize: FONT.sizes.md, fontWeight: FONT.weights.semibold, color: COLORS.text },
  addItemsSub: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: 2, lineHeight: 16 },
  withdrawCard: {
    flex: 1,
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.lg,
    padding: SPACING.md,
    borderWidth: 1.5,
    borderColor: COLORS.border,
    minHeight: 140,
  },
  withdrawIcon: {
    width: 40,
    height: 40,
    borderRadius: 10,
    backgroundColor: COLORS.primaryLight,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: SPACING.sm,
  },
  withdrawTitle: { fontSize: FONT.sizes.md, fontWeight: FONT.weights.bold, color: COLORS.text },
  withdrawSub: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: 2 },
  withdrawFee: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: 6, fontWeight: FONT.weights.medium },
  listCard: {
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.md,
    borderWidth: 1,
    borderColor: COLORS.border,
    marginBottom: SPACING.md,
  },
  memberRow: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: SPACING.md,
    gap: SPACING.md,
  },
  avatar: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: COLORS.primaryLight,
    alignItems: 'center',
    justifyContent: 'center',
  },
  avatarText: { color: COLORS.primary, fontWeight: FONT.weights.bold, fontSize: FONT.sizes.sm },
  memberName: { fontSize: FONT.sizes.md, fontWeight: FONT.weights.semibold, color: COLORS.text },
  statusRow: { flexDirection: 'row', alignItems: 'center', gap: 4, marginTop: 2 },
  statusText: { fontSize: FONT.sizes.xs, color: COLORS.subtext, fontWeight: FONT.weights.medium },
  amount: { fontSize: FONT.sizes.md, fontWeight: FONT.weights.bold, color: COLORS.text },
});

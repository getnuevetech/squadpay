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
import { Receipt, CheckCircle2, Clock, LayoutDashboard } from 'lucide-react-native';
import { Button } from '../../../src/Button';
import { api, Group } from '../../../src/api';
import { loadUser } from '../../../src/session';
import { COLORS, FONT, RADIUS, SPACING } from '../../../src/theme';

export default function SummaryScreen() {
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

  const isLead = group.lead_id === userId;
  const myPer = group.per_user.find((p) => p.user_id === userId);
  const myTotal = myPer?.total || 0;
  const myFood = myPer?.food || 0;
  const myExtras = myPer?.tax_tip || 0;

  const repaidByUser = (uid: string) =>
    group.repayments.filter((r) => r.user_id === uid).reduce((s, r) => s + r.amount, 0);

  const totalRepaid = group.repayments.reduce((s, r) => s + r.amount, 0);
  const totalOwedToLead = group.per_user
    .filter((p) => p.user_id !== group.lead_id)
    .reduce((s, p) => s + p.total, 0);

  const myRepaid = repaidByUser(userId);
  const myOutstanding = Math.max(0, myTotal - myRepaid);

  const handlePay = () => {
    if (group.status === 'open' && isLead) {
      // Lead pays full bill
      router.push(`/group/${group.id}/pay?kind=lead`);
    } else {
      // Member repays
      router.push(`/group/${group.id}/pay?kind=repay`);
    }
  };

  return (
    <SafeAreaView edges={['bottom']} style={{ flex: 1, backgroundColor: COLORS.bg }}>
      <ScrollView
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={COLORS.primary} />}
        contentContainerStyle={{ padding: SPACING.md, paddingBottom: 140 }}
      >
        {/* Your share card */}
        <View style={styles.yourCard} testID="summary-your-card">
          <Text style={styles.yourLabel}>Your share</Text>
          <Text style={styles.yourAmount}>${myTotal.toFixed(2)}</Text>
          <View style={styles.breakdownRow}>
            <Text style={styles.breakdownKey}>Items</Text>
            <Text style={styles.breakdownVal}>${myFood.toFixed(2)}</Text>
          </View>
          <View style={styles.breakdownRow}>
            <Text style={styles.breakdownKey}>Tax & tip</Text>
            <Text style={styles.breakdownVal}>${myExtras.toFixed(2)}</Text>
          </View>
          {group.status !== 'open' && (
            <View style={styles.breakdownRow}>
              <Text style={styles.breakdownKey}>Already paid</Text>
              <Text style={[styles.breakdownVal, { color: COLORS.success }]}>
                ${myRepaid.toFixed(2)}
              </Text>
            </View>
          )}
        </View>

        {/* Overall funding progress */}
        {group.status !== 'open' && (
          <View style={styles.progressCard} testID="summary-progress-card">
            <Text style={styles.sectionTitle}>Repayment progress</Text>
            <View style={styles.progressBar}>
              <View
                style={[
                  styles.progressFill,
                  {
                    width: `${Math.min(100, totalOwedToLead > 0 ? (totalRepaid / totalOwedToLead) * 100 : 100)}%`,
                  },
                ]}
              />
            </View>
            <Text style={styles.progressText}>
              ${totalRepaid.toFixed(2)} / ${totalOwedToLead.toFixed(2)} repaid
            </Text>
          </View>
        )}

        {/* Member list */}
        <View style={styles.memberCard}>
          <Text style={styles.sectionTitle}>Members</Text>
          {group.members.map((m) => {
            const per = group.per_user.find((p) => p.user_id === m.user_id);
            const amount = per?.total || 0;
            const paid = repaidByUser(m.user_id);
            const isLeadRow = m.user_id === group.lead_id;
            const done = isLeadRow ? group.status !== 'open' : paid >= amount - 0.01;
            const outstanding = Math.max(0, amount - paid);
            return (
              <View key={m.user_id} style={styles.memberRow} testID={`summary-member-${m.user_id}`}>
                <View style={styles.avatar}>
                  <Text style={styles.avatarText}>{(m.name || '?').slice(0, 1).toUpperCase()}</Text>
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.memberName}>
                    {m.name} {m.user_id === userId ? '(You)' : ''} {isLeadRow ? '• Lead' : ''}
                  </Text>
                  <View style={styles.statusRow}>
                    {done ? (
                      <>
                        <CheckCircle2 size={12} color={COLORS.success} />
                        <Text style={[styles.statusText, { color: COLORS.success }]}>
                          {isLeadRow ? 'Paid upfront' : 'Settled'}
                        </Text>
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
                <Text style={styles.amount}>${amount.toFixed(2)}</Text>
              </View>
            );
          })}
        </View>

        {group.unclaimed.length > 0 && group.split_mode !== 'fast' && (
          <View style={styles.warnCard}>
            <Receipt size={18} color={COLORS.warning} />
            <Text style={styles.warnText}>
              {group.unclaimed.length} items still unclaimed — go back and claim them.
            </Text>
          </View>
        )}
      </ScrollView>

      <View style={styles.bottomBar}>
        {group.status === 'open' && isLead && (
          <Button
            title={`Pay $${group.total.toFixed(2)} for group`}
            testID="summary-pay-btn"
            onPress={handlePay}
            disabled={!group.fully_claimed && group.split_mode !== 'fast'}
          />
        )}
        {group.status === 'open' && !isLead && (
          <Button
            title="Waiting for lead to pay..."
            onPress={() => {}}
            disabled
            testID="summary-waiting"
          />
        )}
        {group.status !== 'open' && !isLead && myOutstanding > 0 && (
          <Button
            title={`Pay $${myOutstanding.toFixed(2)}`}
            testID="summary-repay-btn"
            onPress={handlePay}
          />
        )}
        {group.status !== 'open' && isLead && (
          <Button
            title="View Lead Dashboard"
            testID="summary-dashboard-btn"
            onPress={() => router.push(`/group/${group.id}/dashboard`)}
            leftIcon={<LayoutDashboard size={18} color="#fff" />}
          />
        )}
        {group.status !== 'open' && !isLead && myOutstanding <= 0 && (
          <Button title="All settled" onPress={() => router.replace('/')} variant="secondary" />
        )}
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: COLORS.bg },
  yourCard: {
    backgroundColor: COLORS.primary,
    borderRadius: RADIUS.xl,
    padding: SPACING.lg,
    marginBottom: SPACING.md,
  },
  yourLabel: {
    color: '#E0E7FF',
    fontSize: FONT.sizes.sm,
    textTransform: 'uppercase',
    letterSpacing: 1,
    fontWeight: FONT.weights.semibold,
  },
  yourAmount: {
    color: '#fff',
    fontSize: 52,
    fontWeight: FONT.weights.heavy,
    letterSpacing: -1,
    marginTop: 2,
    marginBottom: SPACING.md,
  },
  breakdownRow: { flexDirection: 'row', justifyContent: 'space-between', paddingVertical: 4 },
  breakdownKey: { color: '#E0E7FF', fontSize: FONT.sizes.sm },
  breakdownVal: { color: '#fff', fontSize: FONT.sizes.sm, fontWeight: FONT.weights.semibold },
  progressCard: {
    backgroundColor: COLORS.surface,
    padding: SPACING.md,
    borderRadius: RADIUS.md,
    marginBottom: SPACING.md,
    borderWidth: 1,
    borderColor: COLORS.border,
  },
  sectionTitle: {
    fontSize: FONT.sizes.md,
    fontWeight: FONT.weights.bold,
    color: COLORS.text,
    marginBottom: SPACING.md,
  },
  progressBar: {
    height: 8,
    backgroundColor: COLORS.border,
    borderRadius: RADIUS.pill,
    overflow: 'hidden',
  },
  progressFill: { height: '100%', backgroundColor: COLORS.success, borderRadius: RADIUS.pill },
  progressText: {
    marginTop: SPACING.sm,
    fontSize: FONT.sizes.sm,
    color: COLORS.subtext,
    fontWeight: FONT.weights.medium,
  },
  memberCard: {
    backgroundColor: COLORS.surface,
    padding: SPACING.md,
    borderRadius: RADIUS.md,
    borderWidth: 1,
    borderColor: COLORS.border,
  },
  memberRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: SPACING.sm,
    gap: SPACING.md,
    borderTopWidth: 1,
    borderTopColor: COLORS.border,
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
  statusText: { fontSize: FONT.sizes.xs, fontWeight: FONT.weights.medium },
  amount: { fontSize: FONT.sizes.md, fontWeight: FONT.weights.bold, color: COLORS.text },
  warnCard: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    backgroundColor: COLORS.warningLight,
    padding: SPACING.md,
    borderRadius: RADIUS.md,
    marginTop: SPACING.md,
  },
  warnText: { color: '#92400E', fontSize: FONT.sizes.sm, flex: 1 },
  bottomBar: {
    position: 'absolute',
    bottom: 0,
    left: 0,
    right: 0,
    padding: SPACING.md,
    backgroundColor: COLORS.surface,
    borderTopWidth: 1,
    borderTopColor: COLORS.border,
  },
});

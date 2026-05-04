import { useLocalSearchParams, useRouter } from 'expo-router';
import { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Receipt, CheckCircle2, Clock, LayoutDashboard, Wallet, AlertCircle } from 'lucide-react-native';
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
  const myShare = myPer?.total || 0;
  const myFood = myPer?.food || 0;
  const myExtras = myPer?.tax_tip || 0;
  const myTransactionFee = myPer?.transaction_fee || 0;
  const myPlatformFee = myPer?.platform_fee || 0;
  const myContributed = myPer?.contributed || 0;
  const myRepaid = myPer?.repaid || 0;
  const myOutstanding = myPer?.outstanding || 0;

  const funding = group.funding;
  const collectedPct = group.total > 0 ? Math.min(100, (funding.total_contributed / group.total) * 100) : 0;
  const remaining = funding.remaining_to_collect;

  const fundingModeLabel = (() => {
    if (group.status === 'open') return null;
    if (group.funding_mode === 'group') return { text: 'Group-funded', color: COLORS.success, bg: COLORS.successLight };
    if (group.funding_mode === 'shortfall') return { text: 'Shortfall covered by lead', color: COLORS.warning, bg: COLORS.warningLight };
    return { text: 'Lead-funded', color: COLORS.primary, bg: COLORS.primaryLight };
  })();

  const handleContribute = () => {
    router.push(`/group/${group.id}/pay?kind=contribute`);
  };
  const handleLeadPay = () => {
    router.push(`/group/${group.id}/pay?kind=lead`);
  };
  const handleRepay = () => {
    router.push(`/group/${group.id}/pay?kind=repay`);
  };

  // Member CTA logic
  const memberHasFullyContributed = myContributed >= myShare - 0.01;
  const memberCanContribute = group.status === 'open' && !memberHasFullyContributed && myShare > 0;
  const memberCanRepay = group.status !== 'open' && myOutstanding > 0.01;

  return (
    <SafeAreaView edges={['bottom']} style={{ flex: 1, backgroundColor: COLORS.bg }}>
      <ScrollView
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={COLORS.primary} />}
        contentContainerStyle={{ padding: SPACING.md, paddingBottom: 140 }}
      >
        {/* Your share card */}
        <View style={styles.yourCard} testID="summary-your-card">
          <Text style={styles.yourLabel}>Your share</Text>
          <Text style={styles.yourAmount} testID="summary-your-amount">${myShare.toFixed(2)}</Text>
          <View style={styles.breakdownRow}>
            <Text style={styles.breakdownKey}>Items</Text>
            <Text style={styles.breakdownVal}>${myFood.toFixed(2)}</Text>
          </View>
          <View style={styles.breakdownRow}>
            <Text style={styles.breakdownKey}>Tax & tip</Text>
            <Text style={styles.breakdownVal}>${myExtras.toFixed(2)}</Text>
          </View>
          <View style={styles.breakdownRow}>
            <Text style={styles.breakdownKey}>Transaction fee (3%)</Text>
            <Text style={styles.breakdownVal}>${myTransactionFee.toFixed(2)}</Text>
          </View>
          <View style={styles.breakdownRow}>
            <Text style={styles.breakdownKey}>Platform fee</Text>
            <Text style={styles.breakdownVal}>${myPlatformFee.toFixed(2)}</Text>
          </View>
          {myContributed > 0 && (
            <View style={styles.breakdownRow}>
              <Text style={styles.breakdownKey}>Contributed upfront</Text>
              <Text style={[styles.breakdownVal, { color: '#A7F3D0' }]}>−${myContributed.toFixed(2)}</Text>
            </View>
          )}
          {myRepaid > 0 && (
            <View style={styles.breakdownRow}>
              <Text style={styles.breakdownKey}>Repaid</Text>
              <Text style={[styles.breakdownVal, { color: '#A7F3D0' }]}>−${myRepaid.toFixed(2)}</Text>
            </View>
          )}
          {(myContributed > 0 || myRepaid > 0) && (
            <View style={[styles.breakdownRow, { borderTopWidth: 1, borderTopColor: 'rgba(255,255,255,0.18)', marginTop: 6, paddingTop: 6 }]}>
              <Text style={[styles.breakdownKey, { fontWeight: FONT.weights.bold, color: '#fff' }]}>Outstanding</Text>
              <Text style={[styles.breakdownVal, { fontSize: FONT.sizes.lg }]}>${myOutstanding.toFixed(2)}</Text>
            </View>
          )}
        </View>

        {/* Funding progress card */}
        <View style={styles.progressCard} testID="summary-funding-card">
          <View style={styles.progressHeader}>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
              <Wallet size={16} color={COLORS.text} />
              <Text style={styles.sectionTitle}>
                {group.status === 'open' ? 'Group wallet' : 'Repayment progress'}
              </Text>
            </View>
            {fundingModeLabel && (
              <View style={[styles.pill, { backgroundColor: fundingModeLabel.bg }]}>
                <Text style={[styles.pillText, { color: fundingModeLabel.color }]}>
                  {fundingModeLabel.text}
                </Text>
              </View>
            )}
          </View>
          <View style={styles.progressBar}>
            <View
              style={[
                styles.progressFill,
                {
                  width: `${
                    group.status === 'open'
                      ? collectedPct
                      : group.total > 0
                      ? Math.min(100, ((funding.total_contributed + funding.total_repaid) / group.total) * 100)
                      : 100
                  }%`,
                },
              ]}
            />
          </View>
          {group.status === 'open' ? (
            <Text style={styles.progressText}>
              ${funding.total_contributed.toFixed(2)} / ${group.total.toFixed(2)} collected • ${remaining.toFixed(2)} remaining
            </Text>
          ) : (
            <Text style={styles.progressText}>
              ${(funding.total_contributed + funding.total_repaid).toFixed(2)} / ${group.total.toFixed(2)} settled
            </Text>
          )}
        </View>

        {/* Member list */}
        <View style={styles.memberCard}>
          <Text style={styles.sectionTitle}>Members</Text>
          {group.members.map((m, idx) => {
            const per = group.per_user.find((p) => p.user_id === m.user_id);
            const share = per?.total || 0;
            const contributed = per?.contributed || 0;
            const repaid = per?.repaid || 0;
            const outstanding = per?.outstanding || 0;
            const isLeadRow = m.user_id === group.lead_id;

            let status: { icon: any; text: string; color: string };
            if (isLeadRow) {
              if (group.status === 'open') {
                status = { icon: <Clock size={12} color={COLORS.subtext} />, text: 'Will cover any shortfall', color: COLORS.subtext };
              } else if (group.lead_shortfall && group.lead_shortfall > 0.01) {
                status = { icon: <CheckCircle2 size={12} color={COLORS.primary} />, text: `Covered $${group.lead_shortfall.toFixed(2)} shortfall`, color: COLORS.primary };
              } else {
                status = { icon: <CheckCircle2 size={12} color={COLORS.success} />, text: 'Paid merchant', color: COLORS.success };
              }
            } else if (outstanding <= 0.01 && (contributed > 0 || repaid > 0 || group.status === 'closed')) {
              status = { icon: <CheckCircle2 size={12} color={COLORS.success} />, text: contributed >= share - 0.01 ? 'Contributed' : 'Settled', color: COLORS.success };
            } else if (group.status === 'open') {
              status = { icon: <Clock size={12} color={COLORS.warning} />, text: contributed > 0 ? `Partial ($${contributed.toFixed(2)})` : 'Not yet paid', color: COLORS.warning };
            } else {
              status = { icon: <Clock size={12} color={COLORS.warning} />, text: `Owes $${outstanding.toFixed(2)}`, color: COLORS.warning };
            }

            return (
              <View key={m.user_id} style={[styles.memberRow, idx !== 0 && { borderTopWidth: 1, borderTopColor: COLORS.border }]} testID={`summary-member-${m.user_id}`}>
                <View style={styles.avatar}>
                  <Text style={styles.avatarText}>{(m.name || '?').slice(0, 1).toUpperCase()}</Text>
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.memberName}>
                    {m.name} {m.user_id === userId ? '(You)' : ''} {isLeadRow ? '• Lead' : ''}
                  </Text>
                  <View style={styles.statusRow}>
                    {status.icon}
                    <Text style={[styles.statusText, { color: status.color }]}>{status.text}</Text>
                  </View>
                </View>
                <Text style={styles.amount}>${share.toFixed(2)}</Text>
              </View>
            );
          })}
        </View>

        {group.unclaimed.length > 0 && group.split_mode !== 'fast' && group.status === 'open' && (
          <View style={styles.warnCard}>
            <Receipt size={18} color={COLORS.warning} />
            <Text style={styles.warnText}>
              {group.unclaimed.length} item{group.unclaimed.length === 1 ? '' : 's'} still unclaimed — go back and claim them.
            </Text>
          </View>
        )}

        {group.status === 'open' && isLead && remaining > 0.01 && (
          <View style={styles.infoCard}>
            <AlertCircle size={18} color={COLORS.primary} />
            <Text style={styles.infoText}>
              You'll cover the remaining ${remaining.toFixed(2)} when you pay the merchant. Group members can repay you after.
            </Text>
          </View>
        )}
      </ScrollView>

      <View style={styles.bottomBar}>
        {/* Lead actions */}
        {isLead && group.status === 'open' && (
          <Button
            title={
              remaining <= 0.01
                ? `Settle bill — fully funded`
                : funding.total_contributed > 0
                ? `Pay $${remaining.toFixed(2)} (cover shortfall)`
                : `Pay $${group.total.toFixed(2)} for group`
            }
            testID="summary-pay-btn"
            onPress={handleLeadPay}
            disabled={!group.fully_claimed && group.split_mode !== 'fast'}
          />
        )}
        {isLead && group.status === 'open' && memberCanContribute && (
          <Button
            title={`Contribute my share $${myShare.toFixed(2)}`}
            variant="ghost"
            testID="summary-contribute-btn"
            onPress={handleContribute}
            style={{ marginTop: SPACING.sm }}
          />
        )}
        {isLead && group.status !== 'open' && (
          <Button
            title="View Lead Dashboard"
            testID="summary-dashboard-btn"
            onPress={() => router.push(`/group/${group.id}/dashboard`)}
            leftIcon={<LayoutDashboard size={18} color="#fff" />}
          />
        )}

        {/* Member actions */}
        {!isLead && memberCanContribute && (
          <Button
            title={`Contribute $${(myShare - myContributed).toFixed(2)} now`}
            testID="summary-contribute-btn"
            onPress={handleContribute}
          />
        )}
        {!isLead && group.status === 'open' && memberHasFullyContributed && (
          <Button
            title={`Contributed ${myContributed.toFixed(2) === myShare.toFixed(2) ? '✓' : `$${myContributed.toFixed(2)}`} — waiting for lead`}
            onPress={() => {}}
            disabled
            testID="summary-waiting"
          />
        )}
        {!isLead && memberCanRepay && (
          <Button
            title={`Pay $${myOutstanding.toFixed(2)}`}
            testID="summary-repay-btn"
            onPress={handleRepay}
          />
        )}
        {!isLead && group.status !== 'open' && myOutstanding <= 0.01 && (
          <Button title="All settled" onPress={() => router.replace('/')} variant="secondary" testID="summary-settled-btn" />
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
  progressHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: SPACING.md },
  sectionTitle: {
    fontSize: FONT.sizes.md,
    fontWeight: FONT.weights.bold,
    color: COLORS.text,
  },
  pill: {
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: RADIUS.pill,
  },
  pillText: { fontSize: FONT.sizes.xs, fontWeight: FONT.weights.semibold },
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
  infoCard: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    backgroundColor: COLORS.primaryLight,
    padding: SPACING.md,
    borderRadius: RADIUS.md,
    marginTop: SPACING.md,
  },
  infoText: { color: COLORS.primary, fontSize: FONT.sizes.sm, flex: 1, lineHeight: 18 },
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

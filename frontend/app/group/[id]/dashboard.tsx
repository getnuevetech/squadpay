import { useLocalSearchParams, useRouter } from 'expo-router';
import { useCallback, useEffect, useState } from 'react';
import {
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { CheckCircle2, Clock, Zap, Landmark, TrendingUp, Plus, ArrowLeft, Receipt, UserPlus, CreditCard, ChevronDown, Wallet } from 'lucide-react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { api, Group } from '../../../src/api';
import { loadUser } from '../../../src/session';
import { COLORS, FONT, RADIUS, SPACING } from '../../../src/theme';
import { toast } from '../../../src/components/Toast';
import { Skeleton, SkeletonGroupRow } from '../../../src/components/Skeleton';

export default function DashboardScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [group, setGroup] = useState<Group | null>(null);
  const [userId, setUserId] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [itemsExpanded, setItemsExpanded] = useState(false);
  const [memberItemsOpen, setMemberItemsOpen] = useState<Record<string, boolean>>({});

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
      toast.error(e?.message || 'Could not load dashboard');
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
      <SafeAreaView style={styles.center} testID="dashboard-loading">
        <View style={{ width: '90%', gap: 16 }}>
          <Skeleton width={'50%'} height={14} />
          <Skeleton width={'70%'} height={48} />
          <Skeleton width={'100%'} height={120} radius={16} />
          <SkeletonGroupRow />
          <SkeletonGroupRow />
        </View>
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

  // ── Lead's personal share (mirrors the Your Share page so the merged
  //     dashboard surfaces what the lead themselves owes/contributed). ──
  const leadPer = group.per_user.find((p) => p.user_id === userId);
  const myShare = leadPer?.total || 0;
  const myFood = leadPer?.food || 0;
  const myExtras = leadPer?.tax_tip || 0;
  const myTransactionFee = leadPer?.transaction_fee || 0;
  const myPlatformFee = leadPer?.platform_fee || 0;
  const myContributed = leadPer?.contributed || 0;
  const myRepaid = leadPer?.repaid || 0;
  const myOutstanding = leadPer?.outstanding || 0;
  const myCreditApplied = (group.contributions || [])
    .filter((c: any) => c.user_id === userId)
    .reduce((s: number, c: any) => s + Number(c.credit_applied || 0), 0);
  const collectedPct = group.total > 0
    ? Math.min(100, ((group.funding?.total_contributed || 0) / group.total) * 100)
    : 0;

  const withdraw = (kind: 'instant' | 'standard') => {
    toast.info(
      kind === 'instant'
        ? `Instant withdraw of $${withdrawable.toFixed(2)} — arrives in minutes (1.5% fee)`
        : `Standard withdraw of $${withdrawable.toFixed(2)} — arrives in 1–2 business days`,
    );
  };

  return (
    <SafeAreaView edges={['bottom']} style={{ flex: 1, backgroundColor: COLORS.bg }}>
      <ScrollView
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={COLORS.primary} />}
        contentContainerStyle={{ padding: SPACING.md, paddingBottom: SPACING.xxl }}
      >
        <LinearGradient
          colors={['#3F1F8C', '#5B2BC8', '#7C3AED']}
          start={{ x: 0, y: 0 }}
          end={{ x: 1, y: 1 }}
          style={styles.heroCard}
          testID="dashboard-hero"
        >
          <View style={styles.heroHeader}>
            <TouchableOpacity
              onPress={() => router.replace('/')}
              style={styles.heroHomeBtn}
              activeOpacity={0.7}
              testID="dashboard-home-btn"
            >
              <ArrowLeft size={18} color="#fff" />
            </TouchableOpacity>
            <View style={{ flex: 1, alignItems: 'center' }}>
              <Text style={styles.heroSubLabel}>Lead Dashboard</Text>
              <Text style={styles.heroTitle} numberOfLines={1} testID="dashboard-bill-title">
                {group.name}
              </Text>
            </View>
            <View style={{ width: 32 }} />
          </View>
          <Text style={styles.heroLabelInline}>Collected</Text>
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
        </LinearGradient>

        {/* Quick actions: Items / Invite / Pay */}
        <View style={styles.quickActionsRow} testID="dashboard-quick-actions">
          <TouchableOpacity
            style={styles.quickAction}
            activeOpacity={0.85}
            onPress={() => router.push(`/group/${group.id}/items`)}
            testID="dashboard-action-items"
          >
            <View style={styles.quickActionIcon}>
              <Receipt size={18} color={COLORS.primary} />
            </View>
            <Text style={styles.quickActionText}>Items</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={styles.quickAction}
            activeOpacity={0.85}
            onPress={() => router.push(`/group/${group.id}`)}
            testID="dashboard-action-invite"
          >
            <View style={styles.quickActionIcon}>
              <UserPlus size={18} color={COLORS.primary} />
            </View>
            <Text style={styles.quickActionText}>Invite</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[styles.quickAction, group.status !== 'open' && styles.quickActionDisabled]}
            activeOpacity={0.85}
            disabled={group.status !== 'open'}
            onPress={() => router.push(`/group/${group.id}/pay`)}
            testID="dashboard-action-pay"
          >
            <View style={styles.quickActionIcon}>
              <CreditCard size={18} color={group.status !== 'open' ? COLORS.subtext : COLORS.primary} />
            </View>
            <Text style={[styles.quickActionText, group.status !== 'open' && { color: COLORS.subtext }]}>
              {group.status !== 'open' ? 'Paid' : 'Pay'}
            </Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={styles.quickAction}
            activeOpacity={0.85}
            onPress={() => router.push(`/group/${group.id}/card`)}
            testID="dashboard-action-card"
          >
            <View style={styles.quickActionIcon}>
              <Wallet size={18} color={COLORS.primary} />
            </View>
            <Text style={styles.quickActionText}>Card</Text>
          </TouchableOpacity>
        </View>

        {/* ── Lead's personal Your Share breakdown (merged from Your Share page) ── */}
        <View style={styles.shareCard} testID="dashboard-your-share">
          <View style={styles.shareHeaderRow}>
            <Text style={styles.shareLabel}>Your share (as lead)</Text>
            <Text style={styles.shareAmount}>${myShare.toFixed(2)}</Text>
          </View>
          <View style={styles.shareDivider} />
          {myFood > 0 && (
            <View style={styles.shareRow}>
              <Text style={styles.shareKey}>Items</Text>
              <Text style={styles.shareVal}>${myFood.toFixed(2)}</Text>
            </View>
          )}
          {myExtras > 0 && (
            <View style={styles.shareRow}>
              <Text style={styles.shareKey}>Tax & tip</Text>
              <Text style={styles.shareVal}>${myExtras.toFixed(2)}</Text>
            </View>
          )}
          {group.discount && Number(group.discount.amount || 0) > 0 ? (
            <View style={styles.shareRow}>
              <Text style={[styles.shareKey, { color: COLORS.success }]}>
                Discount {group.discount.type === 'percent' ? `(${group.discount.value}%)` : ''}
              </Text>
              <Text style={[styles.shareVal, { color: COLORS.success }]}>−${Number(group.discount.amount).toFixed(2)}</Text>
            </View>
          ) : null}
          <View style={styles.shareRow}>
            <Text style={styles.shareKey}>Transaction fee (3%)</Text>
            <Text style={styles.shareVal}>${myTransactionFee.toFixed(2)}</Text>
          </View>
          <View style={styles.shareRow}>
            <Text style={styles.shareKey}>Platform fee</Text>
            <Text style={styles.shareVal}>${myPlatformFee.toFixed(2)}</Text>
          </View>
          {myContributed > 0 && (
            <View style={styles.shareRow}>
              <Text style={styles.shareKey}>Contributed</Text>
              <Text style={[styles.shareVal, { color: COLORS.success }]}>−${myContributed.toFixed(2)}</Text>
            </View>
          )}
          {myRepaid > 0 && (
            <View style={styles.shareRow}>
              <Text style={styles.shareKey}>Repaid</Text>
              <Text style={[styles.shareVal, { color: COLORS.success }]}>−${myRepaid.toFixed(2)}</Text>
            </View>
          )}
          {myCreditApplied > 0 && (
            <View style={styles.shareRow}>
              <Text style={[styles.shareKey, { color: COLORS.success }]}>Credit applied</Text>
              <Text style={[styles.shareVal, { color: COLORS.success }]}>−${myCreditApplied.toFixed(2)}</Text>
            </View>
          )}
          {(myContributed > 0 || myRepaid > 0) && (
            <View style={[styles.shareRow, styles.shareOutstandingRow]}>
              <Text style={styles.shareOutstandingKey}>Outstanding</Text>
              <Text style={styles.shareOutstandingVal}>${myOutstanding.toFixed(2)}</Text>
            </View>
          )}
        </View>

        {/* ── Funding progress (mirrors Your Share's funding card) ── */}
        <View style={styles.fundCard} testID="dashboard-funding-progress">
          <View style={styles.fundHeader}>
            <View style={{ flex: 1 }}>
              <Text style={styles.fundTitle}>Funding progress</Text>
              <Text style={styles.fundSubtitle}>
                ${(group.funding?.total_contributed || 0).toFixed(2)} of ${Number(group.total || 0).toFixed(2)} collected
              </Text>
            </View>
            <Text style={styles.fundPct}>{Math.round(collectedPct)}%</Text>
          </View>
          <View style={styles.fundTrack}>
            <View style={[styles.fundFill, { width: `${Math.min(100, collectedPct)}%` }]} />
          </View>
          <Text style={styles.fundFoot}>
            {Math.max(0, (group.total || 0) - (group.funding?.total_contributed || 0)).toFixed(2)} remaining
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

        <Text style={styles.sectionTitle}>Members ({group.members.length})</Text>
        <View style={styles.listCard}>
          {group.members.map((m, idx) => {
            const isLead = m.user_id === group.lead_id;
            const isMe = m.user_id === userId;
            const per = group.per_user.find((p) => p.user_id === m.user_id);
            const owed = per?.total || 0;
            const contributed = per?.contributed || 0;
            const outstanding = per?.outstanding || 0;
            const done = outstanding <= 0.01;
            const settledLabel = contributed >= owed - 0.01 ? 'Contributed' : 'Paid';
            const memberClaims = group.assignments.filter((a) => a.user_id === m.user_id);
            const hasItems = (group as any).split_mode !== 'fast' && memberClaims.length > 0;
            const isOpen = !!memberItemsOpen[m.user_id];
            return (
              <View
                key={m.user_id}
                style={[idx !== 0 && { borderTopWidth: 1, borderTopColor: COLORS.border }]}
              >
                <TouchableOpacity
                  testID={`dashboard-member-${m.user_id}`}
                  style={styles.memberRow}
                  activeOpacity={hasItems ? 0.7 : 1}
                  disabled={!hasItems}
                  onPress={() => hasItems && setMemberItemsOpen((s) => ({ ...s, [m.user_id]: !isOpen }))}
                >
                  <View style={[styles.avatar, isLead && styles.avatarLead]}>
                    <Text style={[styles.avatarText, isLead && { color: '#fff' }]}>
                      {(m.name || '?').slice(0, 1).toUpperCase()}
                    </Text>
                  </View>
                  <View style={{ flex: 1 }}>
                    <View style={styles.nameRow}>
                      <Text style={styles.memberName} numberOfLines={1}>
                        {m.name}{isMe ? ' (You)' : ''}
                      </Text>
                      {isLead && (
                        <View style={styles.leadBadge}>
                          <Text style={styles.leadBadgeText}>LEAD</Text>
                        </View>
                      )}
                    </View>
                    <View style={styles.statusRow}>
                      {isLead ? (
                        <Text style={styles.statusText}>
                          {group.status === 'open'
                            ? 'Organising the bill'
                            : 'Paid the merchant'}
                        </Text>
                      ) : done ? (
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
                  {!isLead ? (
                    <Text style={styles.amount}>${owed.toFixed(2)}</Text>
                  ) : (
                    <Text style={[styles.amount, { color: COLORS.subtext, fontSize: FONT.sizes.xs }]}>
                      Lead
                    </Text>
                  )}
                  {hasItems && (
                    <View style={[{ marginLeft: 6 }, isOpen && { transform: [{ rotate: '180deg' }] }]}>
                      <ChevronDown size={16} color={COLORS.subtext} />
                    </View>
                  )}
                </TouchableOpacity>
                {hasItems && isOpen && (
                  <View style={styles.memberItemsInline} testID={`dashboard-member-items-${m.user_id}`}>
                    {memberClaims.map((a) => {
                      const it = group.items.find((i) => i.id === a.item_id);
                      if (!it) return null;
                      const cost = (it.price || 0) * (a.quantity || 0);
                      return (
                        <View key={`${a.item_id}-${m.user_id}`} style={styles.memberItemInlineRow}>
                          <Text style={styles.memberItemInlineName}>
                            {it.name} × {a.quantity}
                          </Text>
                          <Text style={styles.memberItemInlineAmt}>${cost.toFixed(2)}</Text>
                        </View>
                      );
                    })}
                  </View>
                )}
              </View>
            );
          })}
        </View>

        {/* Per-member items breakdown (collapsible) — visible whenever the
            bill has assignable items, regardless of phase. */}
        {/* The previous separate "Who's paying for what" collapsible card
            has been removed — items are now inline under each member row. */}
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
    backgroundColor: COLORS.primary, // fallback for non-gradient platforms
    borderRadius: RADIUS.xl,
    padding: SPACING.lg,
    marginBottom: SPACING.lg,
    shadowColor: '#3F1F8C',
    shadowOpacity: 0.3,
    shadowRadius: 20,
    shadowOffset: { width: 0, height: 12 },
    elevation: 8,
  },
  heroLabel: {
    color: '#fff',
    fontSize: FONT.sizes.md,
    fontWeight: FONT.weights.bold,
    flex: 1,
    textAlign: 'center',
    letterSpacing: -0.3,
  },
  heroTitle: {
    color: '#fff',
    fontSize: FONT.sizes.lg,
    fontWeight: FONT.weights.bold,
    letterSpacing: -0.3,
    marginTop: 2,
    maxWidth: '100%',
  },
  heroLabelInline: {
    color: '#D7C7FB',
    fontSize: FONT.sizes.xs,
    textTransform: 'uppercase',
    letterSpacing: 1,
    fontWeight: FONT.weights.semibold,
    marginTop: SPACING.md,
  },
  heroSubLabel: {
    color: '#D7C7FB',
    fontSize: FONT.sizes.xs,
    textTransform: 'uppercase',
    letterSpacing: 1,
    fontWeight: FONT.weights.semibold,
    marginTop: 4,
  },
  heroHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 8,
  },
  heroHomeBtn: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: 'rgba(255,255,255,0.18)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  heroRow: { flexDirection: 'row', alignItems: 'baseline', gap: 8, marginTop: 4 },
  heroAmount: {
    color: '#fff',
    fontSize: 52,
    fontWeight: FONT.weights.heavy,
    letterSpacing: -1,
  },
  heroOf: { color: '#D7C7FB', fontSize: FONT.sizes.lg, fontWeight: FONT.weights.medium },
  progressBar: {
    height: 8,
    backgroundColor: 'rgba(255,255,255,0.18)',
    borderRadius: RADIUS.pill,
    overflow: 'hidden',
    marginTop: SPACING.md,
  },
  progressFill: { height: '100%', backgroundColor: '#fff', borderRadius: RADIUS.pill },
  heroFoot: { color: '#D7C7FB', fontSize: FONT.sizes.sm, marginTop: SPACING.sm },

  // Quick action tiles row under the hero (Items / Invite / Pay / Summary)
  quickActionsRow: {
    flexDirection: 'row',
    gap: 8,
    marginBottom: SPACING.lg,
  },
  quickAction: {
    flex: 1,
    backgroundColor: COLORS.surface,
    borderWidth: 1,
    borderColor: COLORS.border,
    borderRadius: RADIUS.lg,
    paddingVertical: 14,
    paddingHorizontal: 8,
    alignItems: 'center',
    gap: 6,
  },
  quickActionDisabled: {
    opacity: 0.55,
  },
  quickActionIcon: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: COLORS.primaryLight,
    alignItems: 'center',
    justifyContent: 'center',
  },
  quickActionText: {
    fontSize: FONT.sizes.xs,
    color: COLORS.text,
    fontWeight: FONT.weights.semibold,
  },
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
  avatarLead: {
    backgroundColor: COLORS.primary,
  },
  avatarText: { color: COLORS.primary, fontWeight: FONT.weights.bold, fontSize: FONT.sizes.sm },
  memberName: { fontSize: FONT.sizes.md, fontWeight: FONT.weights.semibold, color: COLORS.text, flexShrink: 1 },
  nameRow: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  leadBadge: {
    backgroundColor: COLORS.primaryLight,
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 6,
  },
  leadBadgeText: {
    fontSize: 9,
    fontWeight: FONT.weights.bold,
    color: COLORS.primary,
    letterSpacing: 0.5,
  },
  statusRow: { flexDirection: 'row', alignItems: 'center', gap: 4, marginTop: 2 },
  statusText: { fontSize: FONT.sizes.xs, color: COLORS.subtext, fontWeight: FONT.weights.medium },
  amount: { fontSize: FONT.sizes.md, fontWeight: FONT.weights.bold, color: COLORS.text },
  // ── Inline per-member items panel (replaces the "Who's paying for what" card) ──
  memberItemsInline: {
    backgroundColor: COLORS.bg,
    paddingHorizontal: SPACING.md,
    paddingVertical: SPACING.sm,
    paddingLeft: 60,
  },
  memberItemInlineRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingVertical: 3,
  },
  memberItemInlineName: { color: COLORS.subtext, fontSize: FONT.sizes.xs, flex: 1 },
  memberItemInlineAmt: { color: COLORS.text, fontSize: FONT.sizes.xs, fontWeight: FONT.weights.medium },
  // ── Lead's Your Share card (light surface) ──
  shareCard: {
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.md,
    padding: SPACING.md,
    marginTop: SPACING.md,
    marginBottom: SPACING.md,
    borderWidth: 1,
    borderColor: COLORS.border,
  },
  shareHeaderRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  shareLabel: {
    color: COLORS.subtext,
    fontSize: FONT.sizes.xs,
    textTransform: 'uppercase',
    letterSpacing: 1,
    fontWeight: FONT.weights.semibold,
  },
  shareAmount: { color: COLORS.text, fontSize: 22, fontWeight: FONT.weights.heavy, letterSpacing: -0.4 },
  shareDivider: { height: 1, backgroundColor: COLORS.border, marginVertical: SPACING.sm },
  shareRow: { flexDirection: 'row', justifyContent: 'space-between', paddingVertical: 4 },
  shareKey: { color: COLORS.subtext, fontSize: FONT.sizes.sm },
  shareVal: { color: COLORS.text, fontSize: FONT.sizes.sm, fontWeight: FONT.weights.semibold },
  shareOutstandingRow: {
    borderTopWidth: 1,
    borderTopColor: COLORS.border,
    marginTop: 6,
    paddingTop: 8,
  },
  shareOutstandingKey: { color: COLORS.text, fontSize: FONT.sizes.sm, fontWeight: FONT.weights.bold },
  shareOutstandingVal: {
    color: COLORS.primary,
    fontSize: FONT.sizes.lg,
    fontWeight: FONT.weights.heavy,
  },
  // ── Funding progress card (light surface) ──
  fundCard: {
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.md,
    padding: SPACING.md,
    marginBottom: SPACING.md,
    borderWidth: 1,
    borderColor: COLORS.border,
  },
  fundHeader: { flexDirection: 'row', alignItems: 'center', marginBottom: 8 },
  fundTitle: { fontSize: FONT.sizes.md, fontWeight: FONT.weights.bold, color: COLORS.text },
  fundSubtitle: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: 2 },
  fundPct: { fontSize: FONT.sizes.lg, fontWeight: FONT.weights.heavy, color: COLORS.primary },
  fundTrack: {
    height: 8,
    borderRadius: 999,
    backgroundColor: COLORS.border,
    overflow: 'hidden',
  },
  fundFill: { height: '100%', backgroundColor: COLORS.primary, borderRadius: 999 },
  fundFoot: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: 6, textAlign: 'right' },
  // Items breakdown (collapsible, per-member)
  itemsBreakCard: {
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.md,
    borderWidth: 1,
    borderColor: COLORS.border,
    marginTop: SPACING.md,
    marginBottom: SPACING.md,
    overflow: 'hidden',
  },
  itemsBreakToggle: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: SPACING.md,
    gap: SPACING.sm,
  },
  itemsBreakTitle: { color: COLORS.text, fontWeight: FONT.weights.bold, fontSize: FONT.sizes.md },
  itemsBreakSub: { color: COLORS.subtext, fontSize: FONT.sizes.xs, marginTop: 2 },
  itemsBreakBody: {
    paddingHorizontal: SPACING.md,
    paddingBottom: SPACING.md,
    borderTopWidth: 1,
    borderTopColor: COLORS.border,
    paddingTop: SPACING.sm,
  },
  itemsBreakMember: { marginTop: SPACING.sm, paddingTop: SPACING.sm, borderTopWidth: 1, borderTopColor: COLORS.border },
  itemsBreakMemberHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 },
  itemsBreakMemberName: { color: COLORS.text, fontWeight: FONT.weights.semibold, fontSize: FONT.sizes.sm },
  itemsBreakMemberTotal: { color: COLORS.primary, fontWeight: FONT.weights.bold, fontSize: FONT.sizes.sm },
  itemsBreakEmpty: { color: COLORS.subtext, fontSize: FONT.sizes.xs, fontStyle: 'italic' },
  itemsBreakRow: { flexDirection: 'row', justifyContent: 'space-between', paddingVertical: 3, paddingLeft: 8 },
  itemsBreakItemName: { color: COLORS.subtext, fontSize: FONT.sizes.xs, flex: 1 },
  itemsBreakItemAmt: { color: COLORS.text, fontSize: FONT.sizes.xs, fontWeight: FONT.weights.medium },
});

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
import { CheckCircle2, Clock, Zap, Landmark, TrendingUp, Plus, ArrowLeft, Receipt, UserPlus, CreditCard, ChevronDown, Wallet, Eye, ShieldOff, Smartphone, Lock, Pencil } from 'lucide-react-native';
import { AvatarRing } from '../../../src/components/AvatarRing';
import { StatusBadge } from '../../../src/StatusBadge';
import { RevealCardModal } from '../../../src/RevealCardModal';
import { EditMetaModal } from '../../../src/EditMetaModal';
import { LinearGradient } from 'expo-linear-gradient';
import { api, Group } from '../../../src/api';
import { loadUser } from '../../../src/session';
import { COLORS, FONT, RADIUS, SPACING } from '../../../src/theme';
import { toast } from '../../../src/components/Toast';
import { Skeleton, SkeletonGroupRow } from '../../../src/components/Skeleton';
import { Button } from '../../../src/Button';

export default function DashboardScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [group, setGroup] = useState<Group | null>(null);
  const [userId, setUserId] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [itemsExpanded, setItemsExpanded] = useState(false);
  const [memberItemsOpen, setMemberItemsOpen] = useState<Record<string, boolean>>({});
  const [breakdownOpen, setBreakdownOpen] = useState(false);
  const [editTaxTipVisible, setEditTaxTipVisible] = useState(false);
  const [revealOpen, setRevealOpen] = useState(false);

  const load = useCallback(async () => {
    const u = await loadUser();
    if (!u) {
      router.replace('/auth');
      return;
    }
    setUserId(u.id);
    try {
      const g = await api.getGroup(id);
      // Strict role guard: only the lead may view the Lead Dashboard.
      // Members are redirected to their User Dashboard.
      if (g.lead_id !== u.id) {
        router.replace(`/group/${id}/summary`);
        return;
      }
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
  // Collected = how much of the non-lead members' debt has actually been
  // settled. Compute per-member as min(contributed+repaid, share) so a single
  // overpayment can never inflate the number past totalOwed. This avoids the
  // "$105 of $58 collected" bug when the lead pre-funded the whole bill.
  const nonLeadPer = group.per_user.filter((p) => p.user_id !== group.lead_id);
  const totalOwed = nonLeadPer.reduce((s, p) => s + (p.total || 0), 0);
  const totalCollected = nonLeadPer.reduce(
    (s, p) => s + Math.min(
      (Number(p.contributed) || 0) + (Number(p.repaid) || 0),
      Number(p.total) || 0,
    ),
    0,
  );
  const pct = totalOwed > 0 ? Math.min(100, (totalCollected / totalOwed) * 100) : 100;
  // Cap displayed % at 99 if anyone still has outstanding — collection
  // can't be "100%" while a member is unpaid.
  const totalOutstandingAll = (group.per_user || []).reduce(
    (s: number, p: any) => s + Number(p.outstanding || 0),
    0,
  );
  const displayedPct = totalOutstandingAll > 0.01 ? Math.min(99, pct) : pct;
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

  // ── Group-level totals (used by the Bill/Fund Breakdown card) ─────
  const groupItemsTotal = (group.items || []).reduce(
    (s: number, it: any) => s + Number(it.price || 0) * Number(it.quantity || 1),
    0,
  );
  const groupTransactionFees = (group.per_user || []).reduce(
    (s: number, p: any) => s + Number(p.transaction_fee || 0),
    0,
  );
  const groupPlatformFees = (group.per_user || []).reduce(
    (s: number, p: any) => s + Number(p.platform_fee || 0),
    0,
  );
  const groupContributedTotal = group.funding?.total_contributed || 0;
  const groupRepaidTotal = group.funding?.total_repaid || 0;
  const groupOutstandingTotal = (group.per_user || []).reduce(
    (s: number, p: any) => s + Number(p.outstanding || 0),
    0,
  );

  // ── Lead CTA helpers (mirrors User Dashboard bottom bar logic) ──
  // The lead must first contribute their personal share, then settle the
  // merchant. These flags drive the dynamic Button label in the footer.
  const funding = group.funding;
  const remaining = Number(funding?.remaining_to_collect ?? 0);
  const leadShareCovered = myContributed >= myShare - 0.01;
  const handleContribute = () => {
    router.push(`/group/${group.id}/pay?kind=contribute`);
  };
  const handleLeadPay = () => {
    router.push(`/group/${group.id}/pay?kind=lead`);
  };

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
        contentContainerStyle={{ padding: SPACING.md, paddingBottom: 140 }}
      >
        <LinearGradient
          colors={['#3F1F8C', '#5B2BC8', '#7C3AED']}
          start={{ x: 0, y: 0 }}
          end={{ x: 1, y: 1 }}
          style={styles.heroV2}
          testID="dashboard-hero"
        >
          <View style={styles.heroV2Top}>
            <View style={{ flex: 1 }}>
              <Text style={styles.heroV2GroupTitle} numberOfLines={2} testID="dashboard-bill-title">
                {group.title || group.name || 'Bill'}
              </Text>
              <Text style={styles.heroV2SubLabel}>Lead Dashboard</Text>
            </View>
            <StatusBadge status={group.derived_status} size="sm" testID="dashboard-status-badge" />
          </View>

          <View style={styles.heroV2AmountCol}>
            <Text style={styles.heroV2Label}>Your Share</Text>
            <Text style={styles.heroV2Amount} testID="dashboard-your-amount">
              ${myShare.toFixed(2)}
            </Text>
            <Text style={styles.heroV2Total} testID="dashboard-bill-total">
              of ${Number(group.total || 0).toFixed(2)} bill total
            </Text>
          </View>

          <View style={styles.heroV2Avatars}>
            {group.members.slice(0, 4).map((m, i) => (
              <View
                key={m.user_id}
                style={[styles.heroV2Avatar, { marginLeft: i === 0 ? 0 : -10, zIndex: 10 - i }]}
              >
                <AvatarRing
                  name={m.name || '?'}
                  seed={m.user_id}
                  size={32}
                  showLeadCrown={m.user_id === group.lead_id}
                />
              </View>
            ))}
            {group.members.length > 4 ? (
              <View style={[styles.heroV2Avatar, styles.heroV2AvatarMore, { marginLeft: -10 }]}>
                <Text style={styles.heroV2AvatarMoreText}>+{group.members.length - 4}</Text>
              </View>
            ) : null}
          </View>

          <View style={styles.heroV2Meta}>
            <Text style={styles.heroV2MetaPrimary}>
              ${totalCollected.toFixed(0)} of ${totalOwed.toFixed(0)} collected
            </Text>
            <Text style={styles.heroV2MetaSecondary}>{Math.round(displayedPct)}%</Text>
          </View>
          <View style={styles.heroV2Track}>
            <View style={[styles.heroV2Fill, { width: `${Math.min(100, displayedPct)}%` }]} />
          </View>
          <View style={styles.heroV2RemainingRow}>
            <Text style={styles.heroV2RemainingLabel}>Remaining</Text>
            <Text style={styles.heroV2RemainingValue}>
              ${Math.max(0, totalOwed - totalCollected).toFixed(2)}
            </Text>
          </View>
        </LinearGradient>

        {/* Lead-only Edit Tax & Tips — placed immediately after the top bar so
            the lead can adjust before reviewing quick actions / breakdown. */}
        {group.status === 'open' && (
          <TouchableOpacity
            testID="dashboard-edit-tax-tip"
            style={styles.editTaxTipBtn}
            onPress={() => setEditTaxTipVisible(true)}
            activeOpacity={0.7}
          >
            <Pencil size={14} color={COLORS.primary} />
            <Text style={styles.editTaxTipText}>
              Edit tax (${(group.tax || 0).toFixed(2)}) & tip (${(group.tip || 0).toFixed(2)})
            </Text>
          </TouchableOpacity>
        )}

        {/* Quick actions: Items / Invite / Card (Pay moved to bottom CTA) */}
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

        {/* ── Bill / Fund Breakdown — GROUP totals (collapsible) ── */}
        <View style={styles.shareCard} testID="dashboard-bill-breakdown">
          <TouchableOpacity
            onPress={() => setBreakdownOpen((v) => !v)}
            activeOpacity={0.7}
            style={styles.shareHeaderRow}
            testID="dashboard-breakdown-toggle"
          >
            <Text style={styles.shareLabel}>Bill / Fund Breakdown</Text>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
              <Text style={styles.shareAmount}>${Number(group.total || 0).toFixed(2)}</Text>
              <View style={[breakdownOpen && { transform: [{ rotate: '180deg' }] }]}>
                <ChevronDown size={18} color={COLORS.subtext} />
              </View>
            </View>
          </TouchableOpacity>
          {breakdownOpen ? (
            <View>
              <View style={styles.shareDivider} />
              <View style={styles.shareRow}>
                <Text style={styles.shareKey}>Items subtotal</Text>
                <Text style={styles.shareVal}>${groupItemsTotal.toFixed(2)}</Text>
              </View>
              <View style={styles.shareRow}>
                <Text style={styles.shareKey}>Tax</Text>
                <Text style={styles.shareVal}>${Number(group.tax || 0).toFixed(2)}</Text>
              </View>
              <View style={styles.shareRow}>
                <Text style={styles.shareKey}>Tip</Text>
                <Text style={styles.shareVal}>${Number(group.tip || 0).toFixed(2)}</Text>
              </View>
              {group.discount && Number(group.discount.amount || 0) > 0 ? (
                <View style={styles.shareRow}>
                  <Text style={[styles.shareKey, { color: COLORS.success }]}>
                    Discount{group.discount.type === 'percent' ? ` (${group.discount.value}%)` : ''}
                  </Text>
                  <Text style={[styles.shareVal, { color: COLORS.success }]}>
                    −${Number(group.discount.amount).toFixed(2)}
                  </Text>
                </View>
              ) : null}
              <View style={styles.shareRow}>
                <Text style={styles.shareKey}>Transaction fees (3%)</Text>
                <Text style={styles.shareVal}>${groupTransactionFees.toFixed(2)}</Text>
              </View>
              <View style={styles.shareRow}>
                <Text style={styles.shareKey}>Platform fees</Text>
                <Text style={styles.shareVal}>${groupPlatformFees.toFixed(2)}</Text>
              </View>
              <View style={styles.shareDivider} />
              <View style={styles.shareRow}>
                <Text style={[styles.shareKey, { fontWeight: FONT.weights.bold, color: COLORS.text }]}>
                  Bill total
                </Text>
                <Text style={[styles.shareVal, { color: COLORS.text, fontWeight: FONT.weights.bold }]}>
                  ${Number(group.total || 0).toFixed(2)}
                </Text>
              </View>
              {groupContributedTotal > 0 ? (
                <View style={styles.shareRow}>
                  <Text style={styles.shareKey}>Contributed</Text>
                  <Text style={[styles.shareVal, { color: COLORS.success }]}>
                    −${groupContributedTotal.toFixed(2)}
                  </Text>
                </View>
              ) : null}
              {groupRepaidTotal > 0 ? (
                <View style={styles.shareRow}>
                  <Text style={styles.shareKey}>Repaid</Text>
                  <Text style={[styles.shareVal, { color: COLORS.success }]}>
                    −${groupRepaidTotal.toFixed(2)}
                  </Text>
                </View>
              ) : null}
              <View style={[styles.shareRow, styles.shareOutstandingRow]}>
                <Text style={styles.shareOutstandingKey}>Outstanding</Text>
                <Text style={styles.shareOutstandingVal}>
                  ${groupOutstandingTotal.toFixed(2)}
                </Text>
              </View>
            </View>
          ) : null}
        </View>




        {leadFronted && withdrawable > 0.01 ? (
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
        ) : null}

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
                    <View style={{ alignItems: 'flex-end' }}>
                      <Text style={styles.amount}>${contributed.toFixed(2)}</Text>
                      <Text style={[styles.statusText, { fontSize: 9, marginTop: 2 }]}>contributed</Text>
                    </View>
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

        {/* The previous separate "Who's paying for what" collapsible card
            has been removed — items are now inline under each member row. */}
        {group.repayments && group.repayments.length > 0 && (
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

      {/* Bottom CTA — mirrors the User Dashboard's lead branch so the
          lead has one prominent action: Step 1 → Contribute their share,
          then Step 2 → settle the merchant. */}
      {group.status === 'open' && (
        <View style={styles.bottomBar}>
          {!leadShareCovered ? (
            <Button
              title={`Step 1 — Contribute your share $${myShare.toFixed(2)}`}
              testID="dashboard-contribute-btn"
              onPress={handleContribute}
            />
          ) : (
            <Button
              title={
                remaining <= 0.01
                  ? `Settle bill — fully funded`
                  : (funding?.total_contributed || 0) > 0
                  ? `Pay $${remaining.toFixed(2)} (cover shortfall)`
                  : `Pay $${Number(group.total || 0).toFixed(2)} for group`
              }
              testID="dashboard-pay-btn"
              onPress={handleLeadPay}
            />
          )}
        </View>
      )}
      <RevealCardModal
        visible={revealOpen}
        onClose={() => setRevealOpen(false)}
        groupId={String(group.id)}
      />
      <EditMetaModal
        visible={editTaxTipVisible}
        group={group}
        userId={userId}
        field="tax_tip"
        onClose={() => setEditTaxTipVisible(false)}
        onSaved={() => { setEditTaxTipVisible(false); load(); }}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: COLORS.bg },
  // ── New gradient hero (matches Your Share / Home Featured Bill Card) ──
  heroV2: {
    borderRadius: 24,
    paddingHorizontal: 18,
    paddingTop: 16,
    paddingBottom: 18,
    marginBottom: SPACING.md,
    shadowColor: '#3F1F8C',
    shadowOpacity: 0.32,
    shadowRadius: 24,
    shadowOffset: { width: 0, height: 16 },
    elevation: 10,
  },
  heroV2Top: { flexDirection: 'row', alignItems: 'flex-start', gap: 10, marginBottom: 10 },
  heroV2GroupTitle: {
    color: '#FFFFFF',
    fontWeight: FONT.weights.heavy,
    fontSize: 18,
    letterSpacing: -0.3,
    lineHeight: 22,
  },
  heroV2SubLabel: {
    color: '#D7C7FB',
    fontSize: 11,
    fontWeight: FONT.weights.semibold,
    letterSpacing: 1,
    textTransform: 'uppercase',
    marginTop: 4,
  },
  heroV2AmountRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-end' },
  heroV2AmountCol: { marginTop: 8 },
  heroV2AmountColRight: { alignItems: 'flex-end', marginLeft: 12 },
  heroV2Label: {
    color: '#fff',
    fontSize: 13,
    fontWeight: FONT.weights.semibold,
    letterSpacing: 0.5,
    textTransform: 'uppercase',
    paddingBottom: 4,
  },
  heroV2Amount: {
    color: '#fff',
    fontSize: 36,
    fontWeight: FONT.weights.heavy,
    letterSpacing: -1,
    lineHeight: 40,
  },
  heroV2Total: { color: '#D7C7FB', fontSize: 11, marginTop: 2, textAlign: 'right' },
  heroV2Avatars: { flexDirection: 'row', alignItems: 'center', marginTop: 14 },
  heroV2Avatar: { borderWidth: 2, borderColor: '#fff', borderRadius: 999 },
  heroV2AvatarMore: {
    minWidth: 32, height: 32, borderRadius: 16,
    backgroundColor: 'rgba(255,255,255,0.18)',
    paddingHorizontal: 8,
    alignItems: 'center', justifyContent: 'center',
  },
  heroV2AvatarMoreText: { color: '#fff', fontSize: 11, fontWeight: FONT.weights.bold },
  heroV2Meta: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginTop: 14 },
  heroV2MetaPrimary: { color: '#fff', fontWeight: FONT.weights.semibold, fontSize: 12 },
  heroV2MetaSecondary: { color: '#D7C7FB', fontSize: 12 },
  heroV2Track: { height: 6, borderRadius: 999, backgroundColor: 'rgba(255,255,255,0.18)', marginTop: 8, overflow: 'hidden' },
  heroV2Fill: { height: '100%', backgroundColor: '#fff', borderRadius: 999 },
  heroV2RemainingRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginTop: 10,
    paddingTop: 10,
    borderTopWidth: 1,
    borderTopColor: 'rgba(255,255,255,0.18)',
  },
  heroV2RemainingLabel: { color: '#D7C7FB', fontSize: 12, fontWeight: FONT.weights.semibold, textTransform: 'uppercase', letterSpacing: 0.6 },
  heroV2RemainingValue: { color: '#fff', fontSize: 18, fontWeight: FONT.weights.heavy },
  // Old hero styles kept for reference
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
  // Edit Tax/Tip CTA (placed above breakdown)
  editTaxTipBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    paddingVertical: 10,
    paddingHorizontal: 14,
    borderRadius: RADIUS.md,
    borderWidth: 1,
    borderColor: COLORS.primary,
    backgroundColor: COLORS.primaryLight,
    marginBottom: SPACING.sm,
  },
  editTaxTipText: { color: COLORS.primary, fontWeight: FONT.weights.semibold, fontSize: FONT.sizes.sm },
  // Embedded Virtual Card UI
  cardEmpty: {
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.md,
    borderWidth: 1,
    borderColor: COLORS.border,
    padding: SPACING.md,
    alignItems: 'center',
    gap: 8,
    marginBottom: SPACING.md,
  },
  cardEmptyIcon: {
    width: 56, height: 56, borderRadius: 28,
    backgroundColor: COLORS.primaryLight,
    alignItems: 'center', justifyContent: 'center',
  },
  cardEmptyTitle: { color: COLORS.text, fontSize: FONT.sizes.md, fontWeight: FONT.weights.bold },
  cardEmptyBody: { color: COLORS.subtext, fontSize: FONT.sizes.sm, textAlign: 'center', lineHeight: 18 },
  cardFace: {
    borderRadius: 18,
    padding: 16,
    minHeight: 180,
    justifyContent: 'space-between',
    marginBottom: 0,
  },
  cardChip: { width: 28, height: 20, borderRadius: 4, backgroundColor: 'rgba(255,255,255,0.35)' },
  cardFaceRow: { flexDirection: 'row', alignItems: 'center' },
  cardFaceBrand: { color: '#fff', fontWeight: FONT.weights.bold, fontSize: FONT.sizes.md },
  cardFaceSub: { color: 'rgba(255,255,255,0.85)', fontSize: 11, marginTop: 2 },
  cardStatusPill: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: 999 },
  cardPillActive: { backgroundColor: 'rgba(34,197,94,0.32)' },
  cardPillOff: { backgroundColor: 'rgba(255,255,255,0.18)' },
  cardStatusText: { color: '#fff', fontWeight: FONT.weights.bold, fontSize: 9, letterSpacing: 0.6 },
  cardNumber: { color: '#fff', fontWeight: FONT.weights.bold, letterSpacing: 2.4, fontSize: 18 },
  cardFaceFooter: { flexDirection: 'row', justifyContent: 'space-between' },
  cardTinyLabel: { color: 'rgba(255,255,255,0.7)', fontSize: 10, textTransform: 'uppercase', letterSpacing: 0.6 },
  cardValue: { color: '#fff', fontWeight: FONT.weights.bold, fontSize: FONT.sizes.sm, marginTop: 2 },
  cardSpendTrackWrap: { marginTop: 10, marginBottom: SPACING.sm },
  cardSpendTrack: { height: 6, borderRadius: 999, backgroundColor: COLORS.border, overflow: 'hidden' },
  cardSpendFill: { height: '100%', backgroundColor: COLORS.primary, borderRadius: 999 },
  cardSpendFoot: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: 4, textAlign: 'right' },
  cardActions: {
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.md,
    borderWidth: 1,
    borderColor: COLORS.border,
    overflow: 'hidden',
    marginBottom: SPACING.md,
  },
  cardActionRow: { flexDirection: 'row', alignItems: 'center', padding: SPACING.md, gap: 10 },
  cardActionIcon: { width: 32, height: 32, borderRadius: 16, alignItems: 'center', justifyContent: 'center' },
  cardActionTitle: { color: COLORS.text, fontWeight: FONT.weights.semibold, fontSize: FONT.sizes.sm, flex: 1 },
  cardActionDiv: { height: 1, backgroundColor: COLORS.border, marginLeft: 52 },
  cardWarn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    padding: SPACING.md,
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.md,
    borderWidth: 1,
    borderColor: COLORS.border,
    marginBottom: SPACING.md,
  },
  cardWarnText: { color: COLORS.subtext, fontSize: FONT.sizes.sm, flex: 1 },
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
  // Bottom CTA bar — mirrors the User Dashboard so the Lead Dashboard's
  // primary action (Contribute / Pay merchant) is always anchored at the
  // bottom of the screen, even when the page scrolls.
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

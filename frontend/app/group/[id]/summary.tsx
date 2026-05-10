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
import { Receipt, CheckCircle2, Clock, LayoutDashboard, Wallet, AlertCircle, Plus, Pencil, ChevronDown } from 'lucide-react-native';
import { Button } from '../../../src/Button';
import { api, Group } from '../../../src/api';
import { loadUser } from '../../../src/session';
import { COLORS, FONT, RADIUS, SPACING } from '../../../src/theme';
import { StatusBadge } from '../../../src/StatusBadge';
import { EditMetaModal } from '../../../src/EditMetaModal';
import { toast } from '../../../src/components/Toast';
import { Skeleton, SkeletonGroupRow } from '../../../src/components/Skeleton';

export default function SummaryScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [group, setGroup] = useState<Group | null>(null);
  const [userId, setUserId] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [editTaxTipVisible, setEditTaxTipVisible] = useState(false);
  const [itemsExpanded, setItemsExpanded] = useState(false);

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
      toast.error(e?.message || 'Could not load summary');
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
      <SafeAreaView style={styles.center} testID="summary-loading">
        <View style={{ width: '90%', gap: 16 }}>
          <Skeleton width={'70%'} height={28} />
          <Skeleton width={'40%'} height={48} />
          <Skeleton width={'100%'} height={120} radius={16} />
          <SkeletonGroupRow />
          <SkeletonGroupRow />
        </View>
      </SafeAreaView>
    );
  }

  const isLead = group.lead_id === userId;
  const myPer = group.per_user.find((p) => p.user_id === userId);
  // C2: aggregate credit_applied for this user across their contributions on this bill
  const myCreditApplied = (group.contributions || [])
    .filter((c: any) => c.user_id === userId)
    .reduce((s: number, c: any) => s + Number(c.credit_applied || 0), 0);
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

  const memberName = (uid?: string) => {
    if (!uid) return '';
    const m = group.members.find((x) => x.user_id === uid);
    return m?.name || 'a member';
  };

  const fundingModeLabel = (() => {
    if (group.status === 'open') return null;
    const settlement = group.shortfall_settlement;
    if (settlement && settlement.amount > 0.01) {
      if (settlement.mode === 'lead') {
        return { text: `Shortfall covered by lead${settlement.is_loan ? '' : ' (gift)'}`, color: COLORS.warning, bg: COLORS.warningLight };
      }
      if (settlement.mode === 'member') {
        return { text: `Shortfall covered by ${memberName(settlement.funder_id)}`, color: COLORS.warning, bg: COLORS.warningLight };
      }
      if (settlement.mode === 'split_equal') {
        return { text: 'Shortfall split among all members', color: COLORS.warning, bg: COLORS.warningLight };
      }
    }
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

  // Member CTA logic — outstanding already includes shortfall obligations
  const memberCanContribute = group.status === 'open' && myOutstanding > 0.01 && !isLead;
  const memberCanRepay = group.status !== 'open' && myOutstanding > 0.01;
  // Lead-specific: lead must contribute own share before paying merchant
  const leadShareCovered = isLead && myContributed >= myShare - 0.01;

  return (
    <SafeAreaView edges={['bottom']} style={{ flex: 1, backgroundColor: COLORS.bg }}>
      <ScrollView
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={COLORS.primary} />}
        contentContainerStyle={{ padding: SPACING.md, paddingBottom: 140 }}
      >
        {/* Mock-SMS / in-app notification for this user */}
        {(() => {
          const myNotifs = (group.notifications || []).filter((n) => n.user_id === userId).slice(-3);
          if (myNotifs.length === 0) return null;
          return (
            <View style={styles.notifCard} testID="summary-notif-card">
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                <AlertCircle size={16} color={COLORS.primary} />
                <Text style={styles.notifHeader}>📩 Notification (mock SMS)</Text>
              </View>
              {myNotifs.map((n) => (
                <Text key={n.id} style={styles.notifText}>• {n.message}</Text>
              ))}
            </View>
          );
        })()}
        {/* Your share card */}
        <View style={styles.yourCard} testID="summary-your-card">
          <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
            <Text style={styles.yourLabel}>Your share</Text>
            <StatusBadge status={group.derived_status} size="sm" testID="summary-status-badge" />
          </View>
          <Text style={styles.yourAmount} testID="summary-your-amount">${myShare.toFixed(2)}</Text>
          <View style={styles.totalChip} testID="summary-group-total-chip">
            <Receipt size={12} color="#fff" />
            <Text style={styles.totalChipLabel}>{group.title} · Bill total</Text>
            <Text style={styles.totalChipAmount}>${Number(group.total || 0).toFixed(2)}</Text>
          </View>
          <View style={styles.breakdownRow}>
            <Text style={styles.breakdownKey}>Items</Text>
            <Text style={styles.breakdownVal}>${myFood.toFixed(2)}</Text>
          </View>
          <View style={styles.breakdownRow}>
            <Text style={styles.breakdownKey}>Tax & tip</Text>
            <Text style={styles.breakdownVal}>${myExtras.toFixed(2)}</Text>
          </View>
          {group.discount && Number(group.discount.amount || 0) > 0 ? (
            <View style={styles.breakdownRow}>
              <Text style={[styles.breakdownKey, { color: '#A7F3D0' }]}>
                Discount {group.discount.type === 'percent' ? `(${group.discount.value}%)` : ''}
                {group.discount.note ? ` — ${group.discount.note}` : ''}
              </Text>
              <Text style={[styles.breakdownVal, { color: '#A7F3D0' }]}>−${Number(group.discount.amount).toFixed(2)}</Text>
            </View>
          ) : null}
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
          {myCreditApplied > 0 && (
            <View style={styles.breakdownRow}>
              <Text style={[styles.breakdownKey, { color: '#A7F3D0' }]}>Credit applied</Text>
              <Text style={[styles.breakdownVal, { color: '#A7F3D0' }]}>−${myCreditApplied.toFixed(2)}</Text>
            </View>
          )}
          {(myContributed > 0 || myRepaid > 0) && (
            <View style={[styles.breakdownRow, { borderTopWidth: 1, borderTopColor: 'rgba(255,255,255,0.18)', marginTop: 6, paddingTop: 6 }]}>
              <Text style={[styles.breakdownKey, { fontWeight: FONT.weights.bold, color: '#fff' }]}>Outstanding</Text>
              <Text style={[styles.breakdownVal, { fontSize: FONT.sizes.lg }]}>${myOutstanding.toFixed(2)}</Text>
            </View>
          )}
        </View>

        {/* Lead-only quick edit row for tax/tip */}
        {isLead && group.status === 'open' && (
          <TouchableOpacity
            testID="summary-edit-tax-tip"
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
            const obligationOwed = per?.shortfall_owed || 0;
            const settlement = group.shortfall_settlement;
            if (isLeadRow) {
              if (group.status === 'open') {
                if (obligationOwed > 0.01 && outstanding > 0.01) {
                  // Lead got a split-shortfall obligation too
                  status = { icon: <AlertCircle size={12} color={COLORS.warning} />, text: `Shortfall +$${obligationOwed.toFixed(2)} due`, color: COLORS.warning };
                } else {
                  status = { icon: <Clock size={12} color={COLORS.subtext} />, text: 'Shortfall to be decided', color: COLORS.subtext };
                }
              } else if (settlement && settlement.amount > 0.01 && settlement.mode === 'lead') {
                status = { icon: <CheckCircle2 size={12} color={COLORS.primary} />, text: `Covered $${settlement.amount.toFixed(2)} shortfall${settlement.is_loan ? '' : ' (gift)'}`, color: COLORS.primary };
              } else if (settlement && settlement.amount > 0.01 && settlement.mode === 'member') {
                status = { icon: <CheckCircle2 size={12} color={COLORS.success} />, text: `Paid merchant • shortfall by ${memberName(settlement.funder_id)}`, color: COLORS.success };
              } else if (settlement && settlement.amount > 0.01 && settlement.mode === 'split_equal') {
                status = { icon: <CheckCircle2 size={12} color={COLORS.success} />, text: 'Paid merchant • shortfall split among all', color: COLORS.success };
              } else {
                status = { icon: <CheckCircle2 size={12} color={COLORS.success} />, text: 'Paid merchant', color: COLORS.success };
              }
            } else if (obligationOwed > 0.01 && outstanding > 0.01) {
              // Member has been assigned a shortfall obligation
              status = { icon: <AlertCircle size={12} color={COLORS.warning} />, text: `Shortfall +$${obligationOwed.toFixed(2)} due`, color: COLORS.warning };
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

        {/* Item 14 — Collapsible per-member items breakdown.
            Visible whenever there are items + assignments, regardless of phase,
            so members can always see "who paid for what" — including during
            the open contribution phase (read-only). Equal-split bills (fast)
            don't have item assignments so this card is skipped. */}
        {group.split_mode !== 'fast' &&
          group.items.length > 0 &&
          group.assignments.length > 0 && (
            <View style={styles.breakdownCard} testID="summary-items-breakdown">
              <TouchableOpacity
                onPress={() => setItemsExpanded((v) => !v)}
                style={styles.breakdownToggle}
                activeOpacity={0.85}
                testID="summary-items-breakdown-toggle"
              >
                <View style={{ flex: 1 }}>
                  <Text style={styles.breakdownTitle}>Who's paying for what</Text>
                  <Text style={styles.breakdownSubtitle}>
                    Tap to {itemsExpanded ? 'collapse' : 'expand'} the per-member item list
                  </Text>
                </View>
                <View style={[styles.chev, itemsExpanded && { transform: [{ rotate: '180deg' }] }]}>
                  <ChevronDown size={18} color={COLORS.subtext} />
                </View>
              </TouchableOpacity>
              {itemsExpanded && (
                <View style={styles.breakdownBody}>
                  {group.members.map((m) => {
                    // For each member, find their claimed items
                    const claims = group.assignments.filter((a) => a.user_id === m.user_id);
                    if (claims.length === 0) {
                      return (
                        <View key={m.user_id} style={styles.breakdownMember}>
                          <Text style={styles.breakdownMemberName}>
                            {m.name} {m.user_id === userId ? '(You)' : ''}
                          </Text>
                          <Text style={styles.breakdownEmpty}>No items claimed yet</Text>
                        </View>
                      );
                    }
                    return (
                      <View key={m.user_id} style={styles.breakdownMember}>
                        <Text style={styles.breakdownMemberName}>
                          {m.name} {m.user_id === userId ? '(You)' : ''}
                        </Text>
                        {claims.map((a) => {
                          const it = group.items.find((i) => i.id === a.item_id);
                          if (!it) return null;
                          const cost = (it.price || 0) * (a.quantity || 0);
                          return (
                            <View key={`${a.item_id}-${m.user_id}`} style={styles.breakdownItemRow}>
                              <Text style={styles.breakdownItemName}>
                                {it.name} × {a.quantity}
                              </Text>
                              <Text style={styles.breakdownItemAmt}>${cost.toFixed(2)}</Text>
                            </View>
                          );
                        })}
                      </View>
                    );
                  })}
                </View>
              )}
            </View>
          )}

        {group.unclaimed.length > 0 && group.split_mode !== 'fast' && group.status === 'open' && (
          <View style={styles.warnCard}>
            <Receipt size={18} color={COLORS.warning} />
            <Text style={styles.warnText}>
              {group.unclaimed.length} item{group.unclaimed.length === 1 ? '' : 's'} unclaimed — these will count as a shortfall when you settle the bill.
            </Text>
          </View>
        )}

        {group.status === 'open' && isLead && !leadShareCovered && (
          <View style={styles.warnCard} testID="summary-lead-share-banner">
            <AlertCircle size={18} color={COLORS.warning} />
            <Text style={styles.warnText}>
              Contribute your own ${myShare.toFixed(2)} share into the group wallet first. Then you can settle with the merchant.
            </Text>
          </View>
        )}

        {group.status === 'open' && isLead && leadShareCovered && remaining > 0.01 && (
          <View style={styles.infoCard}>
            <AlertCircle size={18} color={COLORS.primary} />
            <Text style={styles.infoText}>
              You'll cover the remaining ${remaining.toFixed(2)} when you pay the merchant — choose how on the next screen.
            </Text>
          </View>
        )}

        {/* Lead-only: add more items as long as bill is not settled.
            Per UX: during the OPEN contribution phase we lock items so the
            list members are paying for can't change underneath them. The
            lead can resume editing once the bill is past contribution
            (e.g. paid the merchant and is now collecting repayments). */}
        {isLead && group.status !== 'open' && group.status !== 'closed' && (
          <TouchableOpacity
            testID="summary-add-items-btn"
            style={styles.addItemsBtn}
            onPress={() => router.push(`/group/${group.id}/items`)}
            activeOpacity={0.8}
          >
            <View style={styles.addItemsIcon}>
              <Plus size={16} color={COLORS.primary} />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.addItemsTitle}>Add more items</Text>
              <Text style={styles.addItemsSub}>
                {group.status === 'open'
                  ? 'Forgot something? Lead can still update the bill.'
                  : 'Lead can keep appending items until the bill is fully settled.'}
              </Text>
            </View>
          </TouchableOpacity>
        )}
      </ScrollView>

      <View style={styles.bottomBar}>
        {/* Lead must contribute their own share BEFORE paying the merchant */}
        {isLead && group.status === 'open' && !leadShareCovered && (
          <Button
            title={`Step 1 — Contribute your share $${myShare.toFixed(2)}`}
            testID="summary-contribute-btn"
            onPress={handleContribute}
          />
        )}
        {isLead && group.status === 'open' && leadShareCovered && (
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
            title={
              (myPer?.shortfall_owed || 0) > 0.01
                ? `Pay $${myOutstanding.toFixed(2)} (incl. shortfall)`
                : `Contribute $${myOutstanding.toFixed(2)} now`
            }
            testID="summary-contribute-btn"
            onPress={handleContribute}
          />
        )}
        {!isLead && group.status === 'open' && !memberCanContribute && myShare > 0 && (
          <Button
            title={`Contributed ✓ — waiting for lead`}
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

      {userId && (
        <EditMetaModal
          visible={editTaxTipVisible}
          onClose={() => setEditTaxTipVisible(false)}
          onSaved={(g) => setGroup(g)}
          group={group}
          userId={userId}
          field="tax_tip"
        />
      )}
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
    color: '#EDE9FE',
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
  totalChip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    backgroundColor: 'rgba(255,255,255,0.16)',
    borderColor: 'rgba(255,255,255,0.22)',
    borderWidth: 1,
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: RADIUS.md,
    marginBottom: SPACING.md,
  },
  totalChipLabel: {
    color: '#EDE9FE',
    fontSize: FONT.sizes.xs,
    fontWeight: FONT.weights.semibold,
    flex: 1,
  },
  totalChipAmount: {
    color: '#fff',
    fontSize: FONT.sizes.md,
    fontWeight: FONT.weights.bold,
  },
  breakdownRow: { flexDirection: 'row', justifyContent: 'space-between', paddingVertical: 4 },
  breakdownKey: { color: '#EDE9FE', fontSize: FONT.sizes.sm },
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
  editTaxTipBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    paddingVertical: SPACING.sm,
    paddingHorizontal: SPACING.md,
    borderRadius: RADIUS.md,
    borderWidth: 1,
    borderColor: COLORS.primaryLight,
    backgroundColor: COLORS.primaryLight,
    marginBottom: SPACING.md,
    alignSelf: 'flex-start',
  },
  editTaxTipText: { color: COLORS.primary, fontSize: FONT.sizes.sm, fontWeight: FONT.weights.semibold },
  breakdownCard: {
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.md,
    borderWidth: 1,
    borderColor: COLORS.border,
    marginBottom: SPACING.md,
    overflow: 'hidden',
  },
  breakdownToggle: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: SPACING.md,
    gap: SPACING.sm,
  },
  chev: {},
  breakdownTitle: { color: COLORS.text, fontWeight: FONT.weights.bold, fontSize: FONT.sizes.md },
  breakdownSubtitle: { color: COLORS.subtext, fontSize: FONT.sizes.xs, marginTop: 2 },
  breakdownBody: {
    paddingHorizontal: SPACING.md,
    paddingBottom: SPACING.md,
    borderTopWidth: 1,
    borderTopColor: COLORS.border,
    paddingTop: SPACING.sm,
  },
  breakdownMember: { marginTop: SPACING.sm, paddingTop: SPACING.sm, borderTopWidth: 1, borderTopColor: COLORS.border },
  breakdownMemberName: { color: COLORS.text, fontWeight: FONT.weights.semibold, fontSize: FONT.sizes.sm, marginBottom: 4 },
  breakdownEmpty: { color: COLORS.subtext, fontSize: FONT.sizes.xs, fontStyle: 'italic' },
  breakdownItemRow: { flexDirection: 'row', justifyContent: 'space-between', paddingVertical: 4 },
  breakdownItemName: { color: COLORS.text, fontSize: FONT.sizes.sm, flex: 1 },
  breakdownItemAmt: { color: COLORS.text, fontSize: FONT.sizes.sm, fontWeight: FONT.weights.semibold },
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
  notifCard: {
    backgroundColor: COLORS.primaryLight,
    padding: SPACING.md,
    borderRadius: RADIUS.md,
    borderWidth: 1,
    borderColor: COLORS.primary,
    marginBottom: SPACING.md,
  },
  notifHeader: { color: COLORS.primary, fontSize: FONT.sizes.sm, fontWeight: FONT.weights.bold },
  notifText: { color: COLORS.text, fontSize: FONT.sizes.sm, lineHeight: 20, marginTop: 2 },
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
    marginTop: SPACING.md,
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

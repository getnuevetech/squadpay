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
import { Receipt, CheckCircle2, Clock, LayoutDashboard, Wallet, AlertCircle, Plus, Pencil, ChevronDown, ArrowLeft, UserPlus } from 'lucide-react-native';
import { Button } from '../../../src/Button';
import { api, Group } from '../../../src/api';
import { loadUser } from '../../../src/session';
import { COLORS, FONT, RADIUS, SPACING } from '../../../src/theme';
import { EditMetaModal } from '../../../src/EditMetaModal';
import { toast } from '../../../src/components/Toast';
import { Skeleton, SkeletonGroupRow } from '../../../src/components/Skeleton';
import { HeroCard } from '../../../src/components/redesign/HeroCard';
import { BillBreakdown } from '../../../src/components/redesign/BillBreakdown';
import { useBillMath } from '../../../src/hooks/useBillMath';

export default function SummaryScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [group, setGroup] = useState<Group | null>(null);
  const [userId, setUserId] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [editTaxTipVisible, setEditTaxTipVisible] = useState(false);
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
      // Strict role guard: the lead always sees the Lead Dashboard.
      // Members stay on the Squad Dashboard (this screen).
      if (g.lead_id === u.id) {
        router.replace(`/group/${id}/dashboard`);
        return;
      }
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

  // Compute math BEFORE any early return so hooks order stays stable.
  // The hook returns zero-filled defaults while group is still loading.
  const {
    myShare,
    myContributed,
    myRepaid,
    myOutstanding,
    groupItemsTotal,
    groupTransactionFees,
    groupPlatformFees,
    extraFeesAgg,
    groupContributedTotal,
    groupRepaidTotal,
    grandTotal,
    groupOutstandingTotal,
    displayedPct,
    remaining,
    myPer,
  } = useBillMath(group, userId);

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
  // C2: aggregate credit_applied for this user across their contributions on this bill
  const myCreditApplied = (group.contributions || [])
    .filter((c: any) => c.user_id === userId)
    .reduce((s: number, c: any) => s + Number(c.credit_applied || 0), 0);

  // Per-user line-item helpers — kept here since they're only used by this screen.
  const myFood = myPer?.food || 0;
  const myExtras = myPer?.tax_tip || 0;
  const myTransactionFee = myPer?.transaction_fee || 0;
  const myPlatformFee = myPer?.platform_fee || 0;

  const funding = group.funding;

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
        return { text: 'Shortfall split among all Squad members', color: COLORS.warning, bg: COLORS.warningLight };
      }
    }
    if (group.funding_mode === 'group') return { text: 'Squad-funded', color: COLORS.success, bg: COLORS.successLight };
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
  // Lead-specific: lead must contribute own share before paying merchant.
  // CRITICAL: guard `myShare > 0.01` — when myShare == 0 (itemized + no
  // claims), `0 >= -0.01` would be TRUE and erroneously mark the lead as
  // covered, hiding the contribute CTA and surfacing a "Pay $X for group"
  // button despite no claims existing.
  const leadShareCovered = isLead && myShare > 0.01 && myContributed >= myShare - 0.01;

  // Detect "itemized but nothing claimed" state so we can swap CTAs.
  const isItemized = (group.split_mode || 'fast').toLowerCase() !== 'fast';
  const hasItems = (group.items || []).length > 0;
  const hasAnyClaims = (group.assignments || []).length > 0;
  const itemizedNeedsSetup = isItemized && (!hasItems || !hasAnyClaims);
  // June 2025 — Covering-member Pay Out CTA. When a non-lead member
  // covered a shortfall as a Loan and the owing member has since repaid
  // part/all of it, the covering member can withdraw the proportional
  // amount through Stripe Connect (same payout flow as Lead).
  const myCoverOutstanding = Number((myPer as any)?.cover_outstanding || 0);
  const myCoverRepaid = Number((myPer as any)?.cover_repaid || 0);
  const memberCanCashOutCover = !isLead && myCoverRepaid > 0.01;

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
        {/* Hero card — shared with Lead Dashboard so the two stay identical */}
        <HeroCard
          group={group}
          subLabel="Squad Dashboard"
          myShare={myShare}
          grandTotal={grandTotal}
          collectedAmount={funding.total_contributed}
          displayedPct={displayedPct}
          remaining={remaining}
          testIDPrefix="summary"
        />

        {/* Quick actions: Items / Invite — same icons as the Lead Dashboard
            so the user has a consistent way to view items and invite friends. */}
        <View style={styles.qaRow} testID="summary-quick-actions">
          <TouchableOpacity
            style={styles.qaBtn}
            activeOpacity={0.85}
            onPress={() => router.push(`/group/${group.id}/items`)}
            testID="summary-action-items"
          >
            <View style={styles.qaIcon}>
              <Receipt size={18} color={COLORS.primary} />
            </View>
            <Text style={styles.qaText}>Items</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={styles.qaBtn}
            activeOpacity={0.85}
            onPress={() => router.push(`/group/${group.id}`)}
            testID="summary-action-invite"
          >
            <View style={styles.qaIcon}>
              <UserPlus size={18} color={COLORS.primary} />
            </View>
            <Text style={styles.qaText}>Invite</Text>
          </TouchableOpacity>
        </View>

        {/* Lead-only quick edit row for tax/tip — placed BEFORE the breakdown
            so leads can edit before reviewing the resulting numbers. */}
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

        {/* Bill/Fund Breakdown — shared component, kept in sync across screens */}
        <BillBreakdown
          group={group}
          groupItemsTotal={groupItemsTotal}
          groupTransactionFees={groupTransactionFees}
          groupPlatformFees={groupPlatformFees}
          extraFeesAgg={extraFeesAgg}
          grandTotal={grandTotal}
          groupContributedTotal={groupContributedTotal}
          groupRepaidTotal={groupRepaidTotal}
          groupOutstandingTotal={groupOutstandingTotal}
          testIDPrefix="summary"
        />

        {/* Removed: separate "Group wallet / Repayment progress" card. The
            collected total + remaining are now visible directly inside the
            top hero so this section is redundant. */}

        {/* Member list — each row is tappable; tapping expands to show that
            member's per-item breakdown inline. Replaces the previous separate
            "Who's paying for what" card. */}
        <View style={styles.memberCard}>
          <Text style={styles.sectionTitle}>Squad ({group.members.length})</Text>
          {group.members.map((m, idx) => {
            const per = group.per_user.find((p) => p.user_id === m.user_id);
            const share = per?.total || 0;
            const contributed = per?.contributed || 0;
            const repaid = per?.repaid || 0;
            const outstanding = per?.outstanding || 0;
            const isLeadRow = m.user_id === group.lead_id;
            // Items this member has claimed
            const memberClaims = group.assignments.filter((a) => a.user_id === m.user_id);
            const hasItems = group.split_mode !== 'fast' && memberClaims.length > 0;
            const isOpen = !!memberItemsOpen[m.user_id];

            let status: { icon: any; text: string; color: string };
            const obligationOwed = per?.shortfall_owed || 0;
            const settlement = group.shortfall_settlement;
            if (isLeadRow) {
              if (group.status === 'open') {
                if (obligationOwed > 0.01 && outstanding > 0.01) {
                  status = { icon: <AlertCircle size={12} color={COLORS.warning} />, text: `Shortfall +$${obligationOwed.toFixed(2)} due`, color: COLORS.warning };
                } else if (isItemized && memberClaims.length === 0) {
                  status = { icon: <Clock size={12} color={COLORS.warning} />, text: 'No items claimed', color: COLORS.warning };
                } else if (share > 0.01 && contributed >= share - 0.01) {
                  status = { icon: <CheckCircle2 size={12} color={COLORS.success} />, text: 'Contributed', color: COLORS.success };
                } else {
                  // Mirror the member-row labels so the lead row uses the
                  // same "Not yet paid" / "Partial ($X)" copy.
                  status = {
                    icon: <Clock size={12} color={COLORS.warning} />,
                    text: contributed > 0 ? `Partial ($${contributed.toFixed(2)})` : 'Not yet paid',
                    color: COLORS.warning,
                  };
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
              status = { icon: <AlertCircle size={12} color={COLORS.warning} />, text: `Shortfall +$${obligationOwed.toFixed(2)} due`, color: COLORS.warning };
            } else if (outstanding <= 0.01 && (contributed > 0 || repaid > 0 || group.status === 'closed')) {
              status = { icon: <CheckCircle2 size={12} color={COLORS.success} />, text: contributed >= share - 0.01 ? 'Contributed' : 'Settled', color: COLORS.success };
            } else if (group.status === 'open') {
              status = { icon: <Clock size={12} color={COLORS.warning} />, text: contributed > 0 ? `Partial ($${contributed.toFixed(2)})` : 'Not yet paid', color: COLORS.warning };
            } else {
              status = { icon: <Clock size={12} color={COLORS.warning} />, text: `Owes $${outstanding.toFixed(2)}`, color: COLORS.warning };
            }

            return (
              <View key={m.user_id} style={[idx !== 0 && { borderTopWidth: 1, borderTopColor: COLORS.border }]} testID={`summary-member-${m.user_id}`}>
                <TouchableOpacity
                  style={styles.memberRow}
                  activeOpacity={hasItems ? 0.7 : 1}
                  disabled={!hasItems}
                  onPress={() => hasItems && setMemberItemsOpen((s) => ({ ...s, [m.user_id]: !isOpen }))}
                  testID={`summary-member-toggle-${m.user_id}`}
                >
                  <View style={[styles.avatar, isLeadRow && { backgroundColor: COLORS.primary }]}>
                    <Text style={[styles.avatarText, isLeadRow && { color: '#fff' }]}>
                      {(m.name || '?').slice(0, 1).toUpperCase()}
                    </Text>
                  </View>
                  <View style={{ flex: 1 }}>
                    <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
                      <Text style={styles.memberName} numberOfLines={1}>
                        {m.name}{m.user_id === userId ? ' (You)' : ''}
                      </Text>
                      {isLeadRow && (
                        <View style={styles.leadPill}>
                          <Text style={styles.leadPillText}>LEAD</Text>
                        </View>
                      )}
                    </View>
                    <View style={styles.statusRow}>
                      {status.icon}
                      <Text style={[styles.statusText, { color: status.color }]}>{status.text}</Text>
                    </View>
                  </View>
                  <Text style={styles.amount}>${share.toFixed(2)}</Text>
                  {hasItems && (
                    <View style={[{ marginLeft: 6 }, isOpen && { transform: [{ rotate: '180deg' }] }]}>
                      <ChevronDown size={16} color={COLORS.subtext} />
                    </View>
                  )}
                </TouchableOpacity>
                {hasItems && isOpen && (
                  <View style={styles.memberItemsBody} testID={`summary-member-items-${m.user_id}`}>
                    {memberClaims.map((a) => {
                      const it = group.items.find((i) => i.id === a.item_id);
                      if (!it) return null;
                      const cost = (it.price || 0) * (a.quantity || 0);
                      return (
                        <View key={`${a.item_id}-${m.user_id}`} style={styles.memberItemRow}>
                          <Text style={styles.memberItemName}>
                            {it.name} × {a.quantity}
                          </Text>
                          <Text style={styles.memberItemAmt}>${cost.toFixed(2)}</Text>
                        </View>
                      );
                    })}
                  </View>
                )}
              </View>
            );
          })}
        </View>

        {/* The previous separate "Who's paying for what" card has been
            removed — per-member item lists now appear inline as collapsibles
            attached to each member row above. */}

        {group.unclaimed.length > 0 && group.split_mode !== 'fast' && group.status === 'open' && (
          <View style={styles.warnCard}>
            <Receipt size={18} color={COLORS.warning} />
            <Text style={styles.warnText}>
              {group.unclaimed.length} item{group.unclaimed.length === 1 ? '' : 's'} unclaimed — these will count as a shortfall when you settle the bill.
            </Text>
          </View>
        )}

        {group.status === 'open' && isLead && !leadShareCovered && !itemizedNeedsSetup && myShare > 0.01 && (
          <View style={styles.warnCard} testID="summary-lead-share-banner">
            <AlertCircle size={18} color={COLORS.warning} />
            <Text style={styles.warnText}>
              Contribute your own ${myShare.toFixed(2)} share into the Squad
            </Text>
          </View>
        )}

        {/* June 2025 — Itemized setup banner. Replaces the "contribute your
            share" prompt when share == 0 because nothing's been claimed yet. */}
        {group.status === 'open' && itemizedNeedsSetup && (
          <View style={styles.warnCard} testID="summary-itemized-setup-banner">
            <AlertCircle size={18} color={COLORS.warning} />
            <Text style={styles.warnText}>
              {!hasItems
                ? 'Bill is in Itemized mode but no items added yet. Each share is $0 until items are added and claimed.'
                : 'No items claimed yet — each member\'s share will be $0 until they claim items.'}
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
        {/* June 2025 — itemized mode but no items / no claims. For LEAD only:
            surface a clear "Add / Claim items" CTA instead of the broken
            "Pay $X for group" button that fires when share == 0. */}
        {isLead && group.status === 'open' && itemizedNeedsSetup && (
          <Button
            title={!hasItems ? 'Add items to the bill' : 'Claim items to set shares'}
            testID="summary-itemized-setup-btn"
            onPress={() => router.push(`/group/${group.id}/items`)}
          />
        )}
        {/* Lead must contribute their own share BEFORE paying the merchant */}
        {isLead && group.status === 'open' && !itemizedNeedsSetup && !leadShareCovered && (
          <Button
            title={`Contribute Your Share\n$${myShare.toFixed(2)}`}
            testID="summary-contribute-btn"
            onPress={handleContribute}
          />
        )}
        {isLead && group.status === 'open' && !itemizedNeedsSetup && leadShareCovered && (
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
        {isLead && (
          <Button
            title="View Lead Dashboard"
            testID="summary-dashboard-btn"
            onPress={() => router.push(`/group/${group.id}/dashboard`)}
            leftIcon={<LayoutDashboard size={18} color="#fff" />}
            variant={group.status === 'open' ? 'secondary' : 'primary'}
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
        {/* June 2025 — non-lead in itemized mode with no items claimed yet:
            point them to the items screen to claim their items. Without this
            CTA the bottom bar would be empty (since share = 0 → memberCanContribute
            = false and "Contributed ✓ waiting for lead" requires share > 0). */}
        {!isLead && group.status === 'open' && itemizedNeedsSetup && (myPer?.contributed || 0) <= 0.01 && (
          <Button
            title="Claim your items"
            testID="summary-member-claim-btn"
            onPress={() => router.push(`/group/${group.id}/items`)}
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
        {!isLead && memberCanCashOutCover && (
          <Button
            title={`💰 Pay Out — $${myCoverRepaid.toFixed(2)} ready`}
            testID="summary-cover-payout-btn"
            onPress={() => router.push('/payout/cash-out')}
          />
        )}
        {!isLead && myCoverOutstanding > 0.01 && myCoverRepaid <= 0.01 && (
          <View style={{ padding: 12, backgroundColor: COLORS.warningLight, borderRadius: 8 }}>
            <Text style={{ color: COLORS.warning, fontWeight: '600' }}>
              You covered ${myCoverOutstanding.toFixed(2)} for the Squad
            </Text>
            <Text style={{ color: COLORS.muted, fontSize: 12, marginTop: 4 }}>
              You'll get a Pay Out button here once the owing member repays.
            </Text>
          </View>
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
  // Quick action buttons under the hero
  qaRow: { flexDirection: 'row', gap: 10, marginBottom: SPACING.md },
  qaBtn: {
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
  qaIcon: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: COLORS.primaryLight,
    alignItems: 'center',
    justifyContent: 'center',
  },
  qaText: { fontSize: FONT.sizes.xs, fontWeight: FONT.weights.bold, color: COLORS.text },

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
  memberName: { fontSize: FONT.sizes.md, fontWeight: FONT.weights.semibold, color: COLORS.text, flexShrink: 1 },
  leadPill: {
    backgroundColor: COLORS.primaryLight,
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 6,
  },
  leadPillText: {
    fontSize: 9,
    fontWeight: FONT.weights.bold,
    color: COLORS.primary,
    letterSpacing: 0.5,
  },
  memberItemsBody: {
    backgroundColor: COLORS.bg,
    borderRadius: RADIUS.sm,
    paddingHorizontal: SPACING.md,
    paddingVertical: SPACING.sm,
    marginTop: 0,
    marginBottom: SPACING.sm,
    marginLeft: 48,
  },
  memberItemRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingVertical: 3,
  },
  memberItemName: { color: COLORS.subtext, fontSize: FONT.sizes.xs, flex: 1 },
  memberItemAmt: { color: COLORS.text, fontSize: FONT.sizes.xs, fontWeight: FONT.weights.medium },
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

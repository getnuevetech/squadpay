/**
 * Lead Dashboard — cloned from the User Dashboard (summary.tsx) so the two
 * screens stay visually identical. Lead-specific differences:
 *   • Sub-label "Lead Dashboard" (User Dashboard says "User Dashboard")
 *   • Edit Tax & Tips button is rendered (User Dashboard also renders it for
 *     leads, but here it's always visible since the screen is lead-only).
 *   • Quick actions: Items / Invite / Card  (User Dashboard has Items / Invite)
 *   • Strict role guard redirects non-leads to /group/{id}/summary.
 */
import { useLocalSearchParams, useRouter } from 'expo-router';
import { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Swipeable } from 'react-native-gesture-handler';
import { Receipt, CheckCircle2, Clock, Wallet, AlertCircle, Plus, Pencil, ChevronDown, UserPlus, Trash2, Split } from 'lucide-react-native';
import { Button } from '../../../src/Button';
import { api, Group } from '../../../src/api';
import { loadUser } from '../../../src/session';
import { COLORS, FONT, RADIUS, SPACING } from '../../../src/theme';
import { EditMetaModal } from '../../../src/EditMetaModal';
import { ConfirmModal } from '../../../src/ConfirmModal';
import { toast } from '../../../src/components/Toast';
import { Skeleton, SkeletonGroupRow } from '../../../src/components/Skeleton';
import { HeroCard } from '../../../src/components/redesign/HeroCard';
import { BillBreakdown } from '../../../src/components/redesign/BillBreakdown';
import { useBillMath } from '../../../src/hooks/useBillMath';

export default function DashboardScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [group, setGroup] = useState<Group | null>(null);
  const [userId, setUserId] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [editTaxTipVisible, setEditTaxTipVisible] = useState(false);
  const [memberItemsOpen, setMemberItemsOpen] = useState<Record<string, boolean>>({});
  // Pending removal target — drives the cross-platform ConfirmModal.
  // We use a custom modal instead of Alert.alert because RN-Web silently
  // collapses multi-button alerts to a single OK, so the destructive
  // Remove button never fires on web.
  const [removeTarget, setRemoveTarget] = useState<{ id: string; name: string } | null>(null);
  const [removeBusy, setRemoveBusy] = useState(false);
  // June 2025 Item 3 — Lead can switch the split mode mid-flight via a
  // confirm modal (`splitModeTarget` is the proposed new mode). The backend
  // route rejects switches once any contribution has been made.
  const [splitModeTarget, setSplitModeTarget] = useState<'fast' | 'itemized' | null>(null);
  const [splitModeBusy, setSplitModeBusy] = useState(false);
  // Items 6 + 7 (June 2025) — Public runtime wallet/issuing config so we
  // can conditionally hide the per-squad Card button when the admin master
  // toggle is off. Fetched once on mount via the public endpoint. Defaults
  // to "issuing enabled" so we don't accidentally hide the card during
  // cold starts before the fetch resolves.
  const [walletConfig, setWalletConfig] = useState<{ apple_pay_enabled: boolean; google_pay_enabled: boolean; issuing_enabled: boolean }>(
    { apple_pay_enabled: false, google_pay_enabled: false, issuing_enabled: true },
  );
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const r = await fetch(`${process.env.EXPO_PUBLIC_BACKEND_URL || ''}/api/runtime/wallet-config`);
        if (!r.ok) return;
        const j = await r.json();
        if (alive) setWalletConfig({
          apple_pay_enabled: !!j.apple_pay_enabled,
          google_pay_enabled: !!j.google_pay_enabled,
          issuing_enabled: j.issuing_enabled !== false,
        });
      } catch {
        // silent — defaults already keep card visible
      }
    })();
    return () => { alive = false; };
  }, []);

  const load = useCallback(async () => {
    const u = await loadUser();
    if (!u) {
      router.replace('/auth');
      return;
    }
    setUserId(u.id);
    try {
      const g = await api.getGroup(id);
      // Strict role guard: non-leads are bounced to the User Dashboard.
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

  // Compute math BEFORE any early return so hooks order stays stable across renders.
  // The hook returns zero-filled defaults when `group` is still null (loading).
  const {
    myShare,
    myContributed,
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
    needsMoreMembers,
  } = useBillMath(group, userId);

  if (!group || !userId) {
    return (
      <SafeAreaView style={styles.center} testID="dashboard-loading">
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

  const isLead = group.lead_id === userId; // always true on this screen

  const funding = group.funding;

  const memberName = (uid?: string) => {
    if (!uid) return '';
    const m = group.members.find((x) => x.user_id === uid);
    return m?.name || 'a member';
  };

  const handleContribute = () => {
    router.push(`/group/${group.id}/pay?kind=contribute`);
  };
  const handleLeadPay = () => {
    router.push(`/group/${group.id}/pay?kind=lead`);
  };

  const handleRemoveMember = (targetId: string, name: string) => {
    // Open our cross-platform ConfirmModal. RN-Web's Alert.alert silently
    // drops multi-button alerts, which is why the previous implementation
    // appeared broken on web — the destructive callback never fired.
    setRemoveTarget({ id: targetId, name });
  };

  const performRemove = async () => {
    if (!removeTarget || !userId) return;
    setRemoveBusy(true);
    try {
      const updated = await api.removeMember(
        String(group.id),
        String(userId),
        removeTarget.id,
      );
      setGroup(updated);
      toast.success(`${removeTarget.name} removed`);
    } catch (e: any) {
      toast.error(e?.message || 'Could not remove member');
    } finally {
      setRemoveBusy(false);
      setRemoveTarget(null);
    }
  };

  // June 2025 Item 3 — apply the queued split-mode change. We keep the
  // existing item rows in the DB regardless of the switch (the backend's
  // recompute ignores them in "fast"/equal mode). If switching to itemized
  // and there are zero items, the bill total stays correct via the existing
  // total_amount, but we surface a hint so the lead knows to add items.
  const performSplitModeChange = async () => {
    if (!splitModeTarget || !userId || !group) return;
    setSplitModeBusy(true);
    try {
      const updated = await api.setSplitMode(group.id, userId, splitModeTarget);
      setGroup(updated);
      toast.success(
        `Split mode set to ${splitModeTarget === 'fast' ? 'Equal' : 'Itemized'}`,
      );
    } catch (e: any) {
      toast.error(e?.message || 'Could not change split mode');
    } finally {
      setSplitModeBusy(false);
      setSplitModeTarget(null);
    }
  };

  const leadShareCovered = myContributed >= myShare - 0.01;

  return (
    <SafeAreaView edges={['bottom']} style={{ flex: 1, backgroundColor: COLORS.bg }}>
      <ScrollView
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={COLORS.primary} />}
        contentContainerStyle={{ padding: SPACING.md, paddingBottom: 140 }}
      >
        {/* Notifications panel (mock SMS) */}
        {(() => {
          const myNotifs = (group.notifications || []).filter((n) => n.user_id === userId).slice(-3);
          if (myNotifs.length === 0) return null;
          return (
            <View style={styles.notifCard} testID="dashboard-notif-card">
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

        {/* Hero card — shared with User Dashboard so the two stay identical */}
        <HeroCard
          group={group}
          subLabel="Lead Dashboard"
          myShare={myShare}
          grandTotal={grandTotal}
          collectedAmount={funding.total_contributed}
          displayedPct={displayedPct}
          remaining={remaining}
          testIDPrefix="dashboard"
        />

        {/* Edit Tax & Tips + Split Mode pill — sit right under the hero card
            so the lead has quick access to the two attributes most likely
            to need adjusting before settlement. */}
        {group.status === 'open' && (
          <View style={styles.metaPillRow}>
            <TouchableOpacity
              testID="dashboard-edit-tax-tip"
              style={styles.metaPill}
              onPress={() => setEditTaxTipVisible(true)}
              activeOpacity={0.7}
            >
              <Pencil size={14} color={COLORS.primary} />
              <Text style={styles.metaPillText}>
                Edit tax (${(group.tax || 0).toFixed(2)}) & tip (${(group.tip || 0).toFixed(2)})
              </Text>
            </TouchableOpacity>
            {(() => {
              const currentMode = (group.split_mode || 'fast').toLowerCase();
              // "smart" — legacy intermediate mode — is treated as itemized
              // for the toggle UX since both flows rely on per-item claims.
              const isEqual = currentMode === 'fast';
              const label = isEqual ? 'Equal' : 'Itemized';
              const proposed: 'fast' | 'itemized' = isEqual ? 'itemized' : 'fast';
              return (
                <TouchableOpacity
                  testID="dashboard-split-mode-pill"
                  style={styles.metaPill}
                  onPress={() => setSplitModeTarget(proposed)}
                  activeOpacity={0.7}
                >
                  <Split size={14} color={COLORS.primary} />
                  <Text style={styles.metaPillText}>
                    Split: <Text style={{ fontWeight: FONT.weights.heavy }}>{label}</Text>
                  </Text>
                </TouchableOpacity>
              );
            })()}
          </View>
        )}

        {/* Quick actions: Items / Invite / Card OR Pay Out.
            Item 5/6 (June 2025) — The third slot is now CONTEXT-AWARE:
              • If the squad is fully funded and is using group funding,
                we show "Pay Out" (route → /payout/cash-out). This is the
                action the lead actually needs at that point — the card is
                already moot once funds need to leave the wallet.
              • Else if there's an existing virtual_card AND admin has
                Stripe Issuing enabled, we show "Card" (route → /card).
              • Otherwise the slot is hidden so we don't lead users to a
                dead "no card yet" page.
            We poll the public /runtime/wallet-config once on mount so the
            admin master toggle propagates without a redeploy. */}
        <View style={styles.qaRow} testID="dashboard-quick-actions">
          <TouchableOpacity
            style={styles.qaBtn}
            activeOpacity={0.85}
            onPress={() => router.push(`/group/${group.id}/items`)}
            testID="dashboard-action-items"
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
            testID="dashboard-action-invite"
          >
            <View style={styles.qaIcon}>
              <UserPlus size={18} color={COLORS.primary} />
            </View>
            <Text style={styles.qaText}>Invite</Text>
          </TouchableOpacity>
          {/* Item 5 + 6 (June 2025) — Card button is REMOVED from the
              quick-action row. The 3rd slot is now ALWAYS the Pay Out
              button (replaces the old Card button location). When the
              squad isn't payable yet (not fully funded, or lead is the
              one paying the merchant directly), the button still
              renders but is disabled & grayed-out — leads get a clear
              visual hint that Pay Out is the only action waiting for
              them. Access to the underlying squad card (if any) is
              still available via the "Squad card" pill in the lobby. */}
          {(() => {
            const isLead = group.lead_id === userId;
            const fullyFunded = group.status === 'paid' && (group.funding_mode || 'lead') === 'group';
            const payOutEligible = isLead && fullyFunded;
            return (
              <TouchableOpacity
                style={[styles.qaBtn, !payOutEligible && { opacity: 0.4 }]}
                activeOpacity={payOutEligible ? 0.85 : 1}
                onPress={() => payOutEligible && router.push(`/payout/cash-out?group_id=${group.id}`)}
                disabled={!payOutEligible}
                testID="dashboard-action-payout"
              >
                <View style={styles.qaIcon}>
                  <Wallet size={18} color={COLORS.primary} />
                </View>
                <Text style={styles.qaText}>Pay Out</Text>
              </TouchableOpacity>
            );
          })()}
        </View>

        {/* Item 1/3/4 (June 2025) — Lead "Pay Out" call-to-action banner.
            Visible only when bill is fully funded and uses group funding.
            Text + CTA are centered per design spec. */}
        {group.status === 'paid' && (group.funding_mode || 'lead') === 'group' && (
          <TouchableOpacity
            style={styles.cashOutCta}
            activeOpacity={0.9}
            onPress={() => router.push(`/payout/cash-out?group_id=${group.id}`)}
            testID="dashboard-cashout-cta"
            accessibilityRole="button"
            accessibilityLabel="Withdraw to debit card"
          >
            <View style={styles.cashOutIcon}>
              <Wallet size={20} color="#fff" />
            </View>
            <View style={styles.cashOutTextWrap}>
              <Text style={styles.cashOutTitle}>Withdraw To Debit Card</Text>
              <Text style={styles.cashOutSubtitle}>
                All Squad contributions are completed — withdraw to your debit card to settle the bill for your Squad.
              </Text>
            </View>
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
          testIDPrefix="dashboard"
        />

        {/* Member list — same as User Dashboard, tappable rows that expand */}
        <View style={styles.memberCard}>
          <Text style={styles.sectionTitle}>Squad ({group.members.length})</Text>
          {group.members.map((m, idx) => {
            const per = group.per_user.find((p) => p.user_id === m.user_id);
            const share = per?.total || 0;
            const contributed = per?.contributed || 0;
            const repaid = per?.repaid || 0;
            const outstanding = per?.outstanding || 0;
            const isLeadRow = m.user_id === group.lead_id;
            const memberClaims = group.assignments.filter((a) => a.user_id === m.user_id);
            const hasItems = group.split_mode !== 'fast' && memberClaims.length > 0;
            const isOpen = !!memberItemsOpen[m.user_id];
            // A non-lead member with zero contribution+repayment can be
            // removed by the lead while the bill is still open. This mirrors
            // the backend guard on /remove-member.
            const canRemove = (
              !isLeadRow
              && group.status === 'open'
              && (Number(per?.contributed) || 0) <= 0.01
              && (Number(per?.repaid) || 0) <= 0.01
            );

            let status: { icon: any; text: string; color: string };
            const obligationOwed = per?.shortfall_owed || 0;
            const settlement = group.shortfall_settlement;
            if (isLeadRow) {
              if (group.status === 'open') {
                if (obligationOwed > 0.01 && outstanding > 0.01) {
                  status = { icon: <AlertCircle size={12} color={COLORS.warning} />, text: `Shortfall +$${obligationOwed.toFixed(2)} due`, color: COLORS.warning };
                } else if (contributed >= share - 0.01) {
                  status = { icon: <CheckCircle2 size={12} color={COLORS.success} />, text: 'Contributed', color: COLORS.success };
                } else {
                  // Mirror the member-row copy so users see consistent
                  // labels — "Not yet paid" if zero, "Partial ($X)" if
                  // some money in but below their share.
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
              <View key={m.user_id} style={[idx !== 0 && { borderTopWidth: 1, borderTopColor: COLORS.border }]} testID={`dashboard-member-${m.user_id}`}>
                {(() => {
                  // Build the "swipe-revealed" delete action. We only attach
                  // the Swipeable wrapper when the row is actually removable —
                  // otherwise users could swipe a lead row or a contributing
                  // member and get a useless red panel.
                  const rowContent = (
                    <TouchableOpacity
                      style={styles.memberRow}
                      activeOpacity={hasItems ? 0.7 : 1}
                      disabled={!hasItems}
                      onPress={() => hasItems && setMemberItemsOpen((s) => ({ ...s, [m.user_id]: !isOpen }))}
                      testID={`dashboard-member-toggle-${m.user_id}`}
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
                      {/* Inline trash icon intentionally removed per UX request.
                          Removal is swipe-only — the Swipeable wrapping this
                          row reveals the red "Remove" panel, which routes
                          through the cross-platform ConfirmModal. */}
                    </TouchableOpacity>
                  );
                  if (!canRemove) return rowContent;
                  return (
                    <Swipeable
                      renderRightActions={() => (
                        <TouchableOpacity
                          style={styles.swipeDeleteBtn}
                          onPress={() => handleRemoveMember(m.user_id, m.name || 'this member')}
                          activeOpacity={0.85}
                          testID={`dashboard-remove-${m.user_id}`}
                        >
                          <Trash2 size={18} color="#fff" />
                          <Text style={styles.swipeDeleteText}>Remove</Text>
                        </TouchableOpacity>
                      )}
                      overshootRight={false}
                      friction={2}
                    >
                      {rowContent}
                    </Swipeable>
                  );
                })()}
                {hasItems && isOpen && (
                  <View style={styles.memberItemsBody} testID={`dashboard-member-items-${m.user_id}`}>
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

        {group.unclaimed.length > 0 && group.split_mode !== 'fast' && group.status === 'open' && (
          <View style={styles.warnCard}>
            <Receipt size={18} color={COLORS.warning} />
            <Text style={styles.warnText}>
              {group.unclaimed.length} item{group.unclaimed.length === 1 ? '' : 's'} unclaimed — these will count as a shortfall when you settle the bill.
            </Text>
          </View>
        )}

        {group.status === 'open' && needsMoreMembers && (
          <View style={styles.warnCard} testID="dashboard-need-members-banner">
            <UserPlus size={18} color={COLORS.warning} />
            <Text style={styles.warnText}>
              A Squad needs at least 2 members. Invite someone to start collecting contributions.
            </Text>
          </View>
        )}

        {group.status === 'open' && !leadShareCovered && !needsMoreMembers && (
          <View style={styles.warnCard} testID="dashboard-lead-share-banner">
            <AlertCircle size={18} color={COLORS.warning} />
            <Text style={styles.warnText}>
              Contribute your own ${myShare.toFixed(2)} share into the Squad
            </Text>
          </View>
        )}

        {group.status === 'open' && leadShareCovered && remaining > 0.01 && (
          <View style={styles.infoCard}>
            <AlertCircle size={18} color={COLORS.primary} />
            <Text style={styles.infoText}>
              You'll cover the remaining ${remaining.toFixed(2)} when you pay the merchant — choose how on the next screen.
            </Text>
          </View>
        )}

        {/* Lead-only: add more items as long as bill is not settled */}
        {group.status !== 'open' && group.status !== 'closed' && (
          <TouchableOpacity
            testID="dashboard-add-items-btn"
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
                Lead can keep appending items until the bill is fully settled.
              </Text>
            </View>
          </TouchableOpacity>
        )}
      </ScrollView>

      <View style={styles.bottomBar}>
        {/* When the group has only the lead, no contribute/pay flow is
            possible — surface a clear "Invite a member" CTA instead so
            the lead never hits a backend 400. */}
        {group.status === 'open' && needsMoreMembers && (
          <Button
            title="Invite a member to start"
            testID="dashboard-invite-btn"
            onPress={() => router.push(`/group/${group.id}`)}
          />
        )}
        {/* Lead must contribute their own share BEFORE paying the merchant */}
        {group.status === 'open' && !needsMoreMembers && !leadShareCovered && (
          <Button
            title={`Contribute Your Share\n$${myShare.toFixed(2)}`}
            testID="dashboard-contribute-btn"
            onPress={handleContribute}
          />
        )}
        {group.status === 'open' && !needsMoreMembers && leadShareCovered && (
          <Button
            title={
              remaining <= 0.01
                ? `Settle bill — fully funded`
                : funding.total_contributed > 0
                ? `Pay $${remaining.toFixed(2)} (cover shortfall)`
                : `Pay $${group.total.toFixed(2)} for group`
            }
            testID="dashboard-pay-btn"
            onPress={handleLeadPay}
          />
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

      {/* Cross-platform remove-member confirmation. Driven by `removeTarget`
          so the same code path fires on iOS, Android, and Web. */}
      <ConfirmModal
        visible={!!removeTarget}
        title={removeTarget ? `Remove ${removeTarget.name}?` : 'Remove member?'}
        message="They'll be removed from this bill. Their item claims will be released and everyone on the bill will be notified."
        confirmLabel={removeBusy ? 'Removing…' : 'Remove'}
        destructive
        onConfirm={performRemove}
        onClose={() => !removeBusy && setRemoveTarget(null)}
        testID="dashboard-remove-confirm"
      />

      {/* June 2025 Item 3 — Split-mode confirm. Warns the lead that switching
          modes affects how everyone's share is computed and that the change
          is blocked once contributions start. */}
      <ConfirmModal
        visible={!!splitModeTarget}
        title={
          splitModeTarget === 'fast'
            ? 'Switch to Equal split?'
            : 'Switch to Itemized split?'
        }
        message={
          splitModeTarget === 'fast'
            ? "Everyone will be charged an equal share of the bill total. Item assignments stay on the bill but won't affect each member's share. You can switch back any time before contributions start."
            : 'Each member will only pay for the items they claim. Make sure all items are added and assigned so the totals add up.'
        }
        confirmLabel={
          splitModeBusy
            ? 'Switching…'
            : splitModeTarget === 'fast'
            ? 'Switch to Equal'
            : 'Switch to Itemized'
        }
        onConfirm={performSplitModeChange}
        onClose={() => !splitModeBusy && setSplitModeTarget(null)}
        testID="dashboard-split-mode-confirm"
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: COLORS.bg },
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
  // Item 4 (June 2025) — Centralized layout: stack the green CTA vertically
  // so title + subtitle align under each other and read as a single
  // call-to-action rather than a two-column row.
  cashOutCta: {
    backgroundColor: COLORS.success,
    borderRadius: RADIUS.lg,
    padding: SPACING.md,
    alignItems: 'center',
    justifyContent: 'center',
    gap: SPACING.xs,
    marginTop: SPACING.xs,
    shadowColor: COLORS.success,
    shadowOpacity: 0.25,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 4 },
    elevation: 3,
  },
  cashOutIcon: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: 'rgba(255,255,255,0.18)',
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: SPACING.xs,
  },
  cashOutTextWrap: {
    alignItems: 'center',
  },
  cashOutTitle: {
    fontSize: FONT.sizes.md,
    fontWeight: FONT.weights.bold,
    color: '#fff',
    textAlign: 'center',
  },
  cashOutSubtitle: {
    fontSize: FONT.sizes.xs,
    color: 'rgba(255,255,255,0.92)',
    marginTop: 2,
    textAlign: 'center',
    paddingHorizontal: SPACING.md,
  },
  sectionTitle: {
    fontSize: FONT.sizes.md,
    fontWeight: FONT.weights.bold,
    color: COLORS.text,
  },
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
  // Compact pill row used to surface inline edits below the hero — keeps
  // the screen readable on phones by allowing the pills to wrap.
  metaPillRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
    marginBottom: SPACING.md,
  },
  metaPill: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    paddingVertical: 6,
    paddingHorizontal: 12,
    borderRadius: RADIUS.pill,
    backgroundColor: COLORS.primaryLight,
    borderWidth: 1,
    borderColor: COLORS.primaryLight,
  },
  metaPillText: {
    color: COLORS.primary,
    fontSize: FONT.sizes.sm,
    fontWeight: FONT.weights.semibold,
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
  // Swipe-revealed "Remove" panel behind a removable member row.
  swipeDeleteBtn: {
    backgroundColor: COLORS.danger,
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: 22,
    gap: 4,
  },
  swipeDeleteText: {
    color: '#fff',
    fontSize: FONT.sizes.xs,
    fontWeight: FONT.weights.bold,
    letterSpacing: 0.4,
  },
  // Always-visible trash icon — pairs with the swipe gesture so users on
  // web (where swipe is non-discoverable) still have a clear way to remove
  // a member.
  inlineRemoveBtn: {
    marginLeft: 8,
    padding: 6,
    borderRadius: 8,
    backgroundColor: 'rgba(220, 38, 38, 0.08)',
  },
});

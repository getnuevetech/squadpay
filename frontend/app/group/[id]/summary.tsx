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
import { LinearGradient } from 'expo-linear-gradient';
import { Button } from '../../../src/Button';
import { api, Group } from '../../../src/api';
import { loadUser } from '../../../src/session';
import { COLORS, FONT, RADIUS, SPACING } from '../../../src/theme';
import { StatusBadge } from '../../../src/StatusBadge';
import { EditMetaModal } from '../../../src/EditMetaModal';
import { toast } from '../../../src/components/Toast';
import { Skeleton, SkeletonGroupRow } from '../../../src/components/Skeleton';
import { AvatarRing } from '../../../src/components/AvatarRing';

export default function SummaryScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [group, setGroup] = useState<Group | null>(null);
  const [userId, setUserId] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [editTaxTipVisible, setEditTaxTipVisible] = useState(false);
  const [itemsExpanded, setItemsExpanded] = useState(false);
  const [memberItemsOpen, setMemberItemsOpen] = useState<Record<string, boolean>>({});
  const [breakdownOpen, setBreakdownOpen] = useState(false);

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
      // Members stay on the User Dashboard (this screen).
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

  // ── Group-level totals for the Bill/Fund Breakdown card ──
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
  // Grand total — sum of every breakdown row above so the math always adds
  // up on screen. Computed from the rendered numbers (not the backend's
  // legacy `group.total`, which historically excluded the SquadPay fees).
  const discountAmount = Number(group.discount?.amount || 0);
  const grandTotal = (
    groupItemsTotal
    + Number(group.tax || 0)
    + Number(group.tip || 0)
    - discountAmount
    + groupTransactionFees
    + groupPlatformFees
  );
  // Outstanding mirrors the "Remaining" pill in the hero so members never
  // see two different numbers for the same concept.
  const groupOutstandingTotal = Math.max(0, grandTotal - groupContributedTotal);
  const myShare = myPer?.total || 0;
  const myFood = myPer?.food || 0;
  const myExtras = myPer?.tax_tip || 0;
  const myTransactionFee = myPer?.transaction_fee || 0;
  const myPlatformFee = myPer?.platform_fee || 0;
  const myContributed = myPer?.contributed || 0;
  const myRepaid = myPer?.repaid || 0;
  const myOutstanding = myPer?.outstanding || 0;

  const funding = group.funding;
  const collectedPct = grandTotal > 0 ? Math.min(100, (funding.total_contributed / grandTotal) * 100) : 0;
  // If anyone still has outstanding, cap displayed % at 99 — collection
  // is only "100%" once every share is paid.
  const _outstandingTotal = (group.per_user || []).reduce(
    (s: number, p: any) => s + Number(p.outstanding || 0),
    0,
  );
  const displayedPct = _outstandingTotal > 0.01 ? Math.min(99, collectedPct) : collectedPct;
  // Remaining = bill total − what's been contributed so far. Keeps the math
  // intuitive and impossible to invert when the wallet is over-funded.
  const remaining = Math.max(0, grandTotal - (funding.total_contributed || 0));

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
        {/* New hero card — mirrors the home page Featured Bill Card so the
            user sees Group name • Your Share • Group Total • progress in
            the same familiar layout. */}
        <LinearGradient
          colors={['#3F1F8C', '#5B2BC8', '#7C3AED']}
          start={{ x: 0, y: 0 }}
          end={{ x: 1, y: 1 }}
          style={styles.heroV2}
          testID="summary-your-card"
        >
          <View style={styles.heroV2Top}>
            <View style={{ flex: 1 }}>
              <Text style={styles.heroV2GroupTitle} numberOfLines={2} testID="summary-group-title">
                {group.title || group.name || 'Bill'}
              </Text>
              <Text style={styles.heroV2SubLabel}>User Dashboard</Text>
            </View>
            <StatusBadge status={group.derived_status} size="sm" testID="summary-status-badge" />
          </View>

          <View style={styles.heroV2AmountCol}>
            <Text style={styles.heroV2Label}>Your Share</Text>
            <Text style={styles.heroV2Amount} testID="summary-your-amount">
              ${myShare.toFixed(2)}
            </Text>
            <Text style={styles.heroV2Total} testID="summary-bill-total">
              of ${grandTotal.toFixed(2)} bill total
            </Text>
          </View>

          {/* Avatars stack — same as home page */}
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

          {/* Progress: how much collected + how much still remaining */}
          <View style={styles.heroV2Meta}>
            <Text style={styles.heroV2MetaPrimary}>
              ${funding.total_contributed.toFixed(2)} of ${grandTotal.toFixed(2)} collected
            </Text>
            <Text style={styles.heroV2MetaSecondary}>
              {Math.round(displayedPct)}%
            </Text>
          </View>
          <View style={styles.heroV2Track}>
            <View
              style={[styles.heroV2Fill, { width: `${Math.min(100, displayedPct)}%` }]}
            />
          </View>
          <View style={styles.heroV2RemainingRow}>
            <Text style={styles.heroV2RemainingLabel}>Remaining</Text>
            <Text style={styles.heroV2RemainingValue}>${remaining.toFixed(2)}</Text>
          </View>
        </LinearGradient>

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

        {/* Detailed share breakdown — collapsible toggle */}
        <View style={styles.yourCard}>
          <TouchableOpacity
            onPress={() => setBreakdownOpen((v) => !v)}
            activeOpacity={0.7}
            style={styles.yourCardHeader}
            testID="summary-breakdown-toggle"
          >
            <Text style={styles.yourLabel}>Bill / Fund Breakdown</Text>
            <View style={[breakdownOpen && { transform: [{ rotate: '180deg' }] }]}>
              <ChevronDown size={18} color={COLORS.subtext} />
            </View>
          </TouchableOpacity>
          {breakdownOpen && (
            <>
              <View style={styles.breakdownRow}>
                <Text style={styles.breakdownKey}>Items subtotal</Text>
                <Text style={styles.breakdownVal}>${groupItemsTotal.toFixed(2)}</Text>
              </View>
              <View style={styles.breakdownRow}>
                <Text style={styles.breakdownKey}>Tax</Text>
                <Text style={styles.breakdownVal}>${Number(group.tax || 0).toFixed(2)}</Text>
              </View>
              <View style={styles.breakdownRow}>
                <Text style={styles.breakdownKey}>Tip</Text>
                <Text style={styles.breakdownVal}>${Number(group.tip || 0).toFixed(2)}</Text>
              </View>
              {group.discount && Number(group.discount.amount || 0) > 0 ? (
                <View style={styles.breakdownRow}>
                  <Text style={[styles.breakdownKey, { color: COLORS.success }]}>
                    Discount{group.discount.type === 'percent' ? ` (${group.discount.value}%)` : ''}
                  </Text>
                  <Text style={[styles.breakdownVal, { color: COLORS.success }]}>−${Number(group.discount.amount).toFixed(2)}</Text>
                </View>
              ) : null}
              <View style={styles.breakdownRow}>
                <Text style={styles.breakdownKey}>Transaction fees (3%)</Text>
                <Text style={styles.breakdownVal}>${groupTransactionFees.toFixed(2)}</Text>
              </View>
              <View style={styles.breakdownRow}>
                <Text style={styles.breakdownKey}>Platform fees</Text>
                <Text style={styles.breakdownVal}>${groupPlatformFees.toFixed(2)}</Text>
              </View>
              <View style={[styles.breakdownRow, { borderTopWidth: 1, borderTopColor: COLORS.border, marginTop: 6, paddingTop: 6 }]}>
                <Text style={[styles.breakdownKey, { fontWeight: FONT.weights.bold, color: COLORS.text }]}>Bill total</Text>
                <Text style={[styles.breakdownVal, { color: COLORS.text, fontWeight: FONT.weights.bold }]}>${grandTotal.toFixed(2)}</Text>
              </View>
              {groupContributedTotal > 0 ? (
                <View style={styles.breakdownRow}>
                  <Text style={styles.breakdownKey}>Contributed</Text>
                  <Text style={[styles.breakdownVal, { color: COLORS.success }]}>−${groupContributedTotal.toFixed(2)}</Text>
                </View>
              ) : null}
              {groupRepaidTotal > 0 ? (
                <View style={styles.breakdownRow}>
                  <Text style={styles.breakdownKey}>Repaid</Text>
                  <Text style={[styles.breakdownVal, { color: COLORS.success }]}>−${groupRepaidTotal.toFixed(2)}</Text>
                </View>
              ) : null}
              <View style={[styles.breakdownRow, { borderTopWidth: 1, borderTopColor: COLORS.border, marginTop: 6, paddingTop: 6 }]}>
                <Text style={[styles.breakdownKey, { fontWeight: FONT.weights.bold, color: COLORS.text }]}>Outstanding</Text>
                <Text style={[styles.breakdownVal, { fontSize: FONT.sizes.lg, color: COLORS.primary, fontWeight: FONT.weights.heavy }]}>${groupOutstandingTotal.toFixed(2)}</Text>
              </View>
            </>
          )}
        </View>

        {/* Removed: separate "Group wallet / Repayment progress" card. The
            collected total + remaining are now visible directly inside the
            top hero so this section is redundant. */}

        {/* Member list — each row is tappable; tapping expands to show that
            member's per-item breakdown inline. Replaces the previous separate
            "Who's paying for what" card. */}
        <View style={styles.memberCard}>
          <Text style={styles.sectionTitle}>Members ({group.members.length})</Text>
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
  // ── New gradient hero (matches home FeaturedBillCard) ──
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
  heroV2Top: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    marginBottom: 10,
  },
  heroV2Back: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: 'rgba(255,255,255,0.18)',
    alignItems: 'center',
    justifyContent: 'center',
  },
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
  heroV2AmountCol: { marginTop: 8, alignItems: 'flex-end' },
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
    fontSize: 44,
    fontWeight: FONT.weights.heavy,
    letterSpacing: -1,
    lineHeight: 48,
  },
  heroV2Total: { color: '#D7C7FB', fontSize: 12, marginTop: 4 },
  heroV2Avatars: { flexDirection: 'row', alignItems: 'center', marginTop: 14 },
  heroV2Avatar: { borderWidth: 2, borderColor: '#fff', borderRadius: 999 },
  heroV2AvatarMore: {
    minWidth: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: 'rgba(255,255,255,0.18)',
    paddingHorizontal: 8,
    alignItems: 'center',
    justifyContent: 'center',
  },
  heroV2AvatarMoreText: { color: '#fff', fontSize: 11, fontWeight: FONT.weights.bold },
  heroV2Meta: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginTop: 14 },
  heroV2MetaPrimary: { color: '#fff', fontWeight: FONT.weights.semibold, fontSize: 12 },
  heroV2MetaSecondary: { color: '#D7C7FB', fontSize: 12 },
  heroV2Track: {
    height: 6,
    borderRadius: 999,
    backgroundColor: 'rgba(255,255,255,0.18)',
    marginTop: 8,
    overflow: 'hidden',
  },
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

  // ── Light "Your share breakdown" card (formerly the violet block) ──
  yourCard: {
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.md,
    padding: SPACING.md,
    marginBottom: SPACING.md,
    borderWidth: 1,
    borderColor: COLORS.border,
  },
  yourCardHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  yourLabel: {
    color: COLORS.subtext,
    fontSize: FONT.sizes.xs,
    textTransform: 'uppercase',
    letterSpacing: 1,
    fontWeight: FONT.weights.semibold,
    marginBottom: SPACING.sm,
  },
  yourAmount: {
    color: COLORS.text,
    fontSize: 28,
    fontWeight: FONT.weights.heavy,
    letterSpacing: -0.5,
    marginBottom: SPACING.sm,
  },
  totalChip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    backgroundColor: COLORS.primaryLight,
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: RADIUS.md,
    marginBottom: SPACING.md,
  },
  totalChipLabel: {
    color: COLORS.primary,
    fontSize: FONT.sizes.xs,
    fontWeight: FONT.weights.semibold,
    flex: 1,
  },
  totalChipAmount: {
    color: COLORS.primary,
    fontSize: FONT.sizes.md,
    fontWeight: FONT.weights.bold,
  },
  breakdownRow: { flexDirection: 'row', justifyContent: 'space-between', paddingVertical: 4 },
  breakdownKey: { color: COLORS.subtext, fontSize: FONT.sizes.sm },
  breakdownVal: { color: COLORS.text, fontSize: FONT.sizes.sm, fontWeight: FONT.weights.semibold },
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

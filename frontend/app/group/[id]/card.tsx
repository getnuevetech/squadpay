/**
 * Lead-only Virtual Card page.
 *
 * Houses everything related to the group's Stripe-issued virtual card:
 *   - Card face (last-4, exp, brand, nickname)
 *   - Spent / cap progress
 *   - Reveal full PAN + CVV (modal — re-uses existing component)
 *   - Add to Apple/Google Pay (push provisioning hand-off)
 *   - Disable / freeze (when active)
 *   - Empty-state when the card hasn't been provisioned yet, with a helpful
 *     explanation of when it will be issued automatically.
 */
import { useLocalSearchParams, useRouter } from 'expo-router';
import { useCallback, useEffect, useState } from 'react';
import {
  Platform,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { ArrowLeft, CreditCard, Eye, Lock, ShieldOff, Smartphone, Wallet } from 'lucide-react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { api, Group } from '../../../src/api';
import { loadUser } from '../../../src/session';
import { COLORS, FONT, RADIUS, SHADOW, SPACING } from '../../../src/theme';
import { toast } from '../../../src/components/Toast';
import { Skeleton } from '../../../src/components/Skeleton';
import { RevealCardModal } from '../../../src/RevealCardModal';
import { Button } from '../../../src/Button';

export default function GroupCardScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [group, setGroup] = useState<Group | null>(null);
  const [userId, setUserId] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [revealOpen, setRevealOpen] = useState(false);
  const [busy, setBusy] = useState(false);

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
      // Lead-only guard
      if (g.lead_id !== u.id) {
        toast.error('Only the bill lead can view this card.');
        router.replace(`/group/${id}/summary`);
        return;
      }
      // Auto-issue: if the group is fully funded but no card exists yet,
      // attempt to provision the card immediately (covers cases where the
      // contribute path failed silently or the bill was funded before the
      // auto-issue code shipped).
      const vc: any = g.virtual_card || null;
      if (!vc?.stripe_card_id) {
        const collected = (g.funding?.total_contributed || 0);
        const total = Number(g.total || 0);
        if (total > 0 && collected + 0.01 >= total) {
          try {
            const base = process.env.EXPO_PUBLIC_BACKEND_URL || '';
            const res = await fetch(`${base}/api/groups/${id}/issue-card`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ user_id: u.id }),
            });
            if (res.ok) {
              const data = await res.json();
              if (data?.virtual_card) {
                // Refresh group to pick up the newly minted card
                const fresh = await api.getGroup(id);
                setGroup(fresh);
                if (!data?.already_issued) toast.success('Virtual card provisioned!');
              }
            }
          } catch (e) {
            // Silent — the empty-state will still show with a Refresh button
          }
        }
      }
    } catch (e: any) {
      toast.error(e?.message || 'Could not load card');
    }
  }, [id, router]);

  useEffect(() => {
    load();
  }, [load]);

  const onRefresh = async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  };

  const onAddToWallet = async () => {
    setBusy(true);
    const provider = Platform.OS === 'ios' ? 'apple' : 'google';
    try {
      const base = process.env.EXPO_PUBLIC_BACKEND_URL || '';
      const res = await fetch(`${base}/api/groups/${id}/wallet/${provider}/start`, {
        method: 'POST',
      });
      const data = await res.json();
      if (data?.status === 'enrolled') toast.success('Card added to wallet');
      else if (data?.status === 'pending') toast.info('Wallet enrolment pending verification');
      else toast.error(data?.message || 'Wallet provisioning failed');
    } catch (e: any) {
      toast.error(e?.message || 'Could not enrol wallet');
    } finally {
      setBusy(false);
    }
  };

  const onDisable = async () => {
    setBusy(true);
    try {
      const base = process.env.EXPO_PUBLIC_BACKEND_URL || '';
      await fetch(`${base}/api/groups/${id}/disable-card`, { method: 'POST' });
      await load();
      toast.success('Card disabled');
    } catch (e: any) {
      toast.error(e?.message || 'Could not disable card');
    } finally {
      setBusy(false);
    }
  };

  if (!group || !userId) {
    return (
      <SafeAreaView style={styles.center} testID="card-loading">
        <View style={{ width: '90%', gap: 16 }}>
          <Skeleton width={'40%'} height={14} />
          <Skeleton width={'100%'} height={180} radius={16} />
          <Skeleton width={'70%'} height={48} />
        </View>
      </SafeAreaView>
    );
  }

  const vc: any = group.virtual_card || null;
  const hasCard = !!(vc && vc.stripe_card_id);
  const collected = group.funding?.total_contributed || 0;
  const total = group.total || 0;
  const fullyFunded = collected >= total - 0.01;
  const isActive = hasCard && vc.status === 'active';
  const isDisabled = hasCard && vc.status === 'inactive';
  // Card "balance" is what members have actually contributed (not the
  // expected total), minus any spend.
  const cap = collected;
  const spent = Number(vc?.spent || 0);
  const available = Math.max(0, cap - spent);
  const spendPct = cap > 0 ? Math.min(100, (spent / cap) * 100) : 0;

  return (
    <SafeAreaView style={styles.container} edges={['top']} testID="card-screen">
      {/* Header */}
      <View style={styles.header}>
        <TouchableOpacity
          onPress={() => router.back()}
          style={styles.iconBtn}
          activeOpacity={0.7}
          testID="card-back-btn"
        >
          <ArrowLeft size={20} color={COLORS.text} />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Virtual Card</Text>
        <View style={{ width: 40 }} />
      </View>

      <ScrollView
        contentContainerStyle={styles.scroll}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} />}
        testID="card-scroll"
      >
        <Text style={styles.groupTitle} numberOfLines={1}>
          {group.title}
        </Text>

        {hasCard ? (
          <>
            {/* Card face */}
            <LinearGradient
              colors={isDisabled ? ['#475569', '#334155'] : ['#3F1F8C', '#5B2BC8', '#7C3AED']}
              start={{ x: 0, y: 0 }}
              end={{ x: 1, y: 1 }}
              style={[styles.cardFace, SHADOW.lg]}
              testID="card-face"
            >
              <View style={styles.cardChip} />
              <View style={styles.cardRow}>
                <CreditCard size={22} color="rgba(255,255,255,0.95)" />
                <View style={{ flex: 1, marginLeft: 10 }}>
                  <Text style={styles.cardBrand}>SquadPay</Text>
                  <Text style={styles.cardGroupName} numberOfLines={1}>
                    {group.title}
                  </Text>
                </View>
                <View style={[styles.statusPill, isActive ? styles.pillActive : styles.pillOff]}>
                  <Text style={styles.statusPillText}>
                    {isDisabled ? 'DISABLED' : isActive ? 'ACTIVE' : 'FUNDING'}
                  </Text>
                </View>
              </View>
              <Text style={styles.cardNumber}>•••• •••• •••• {vc.last4}</Text>
              <View style={styles.cardFooter}>
                <View>
                  <Text style={styles.cardTinyLabel}>Spent</Text>
                  <Text style={styles.cardValue}>${spent.toFixed(2)}</Text>
                </View>
                <View>
                  <Text style={styles.cardTinyLabel}>Available</Text>
                  <Text style={styles.cardValue}>${available.toFixed(2)}</Text>
                </View>
                <View>
                  <Text style={styles.cardTinyLabel}>Funded</Text>
                  <Text style={styles.cardValue}>${cap.toFixed(2)}</Text>
                </View>
              </View>
            </LinearGradient>

            {/* Spend progress */}
            <View style={styles.section}>
              <View style={styles.sectionHeader}>
                <Text style={styles.sectionTitle}>Spend</Text>
                <Text style={styles.sectionPct}>{Math.round(spendPct)}%</Text>
              </View>
              <View style={styles.track}>
                <View style={[styles.fill, { width: `${spendPct}%` }]} />
              </View>
              <Text style={styles.sectionFoot}>
                ${spent.toFixed(2)} of ${cap.toFixed(2)} spent
              </Text>
            </View>

            {/* Actions */}
            {isActive ? (
              <View style={styles.actionsCard}>
                <TouchableOpacity
                  onPress={() => setRevealOpen(true)}
                  style={styles.actionRow}
                  activeOpacity={0.7}
                  testID="card-reveal-btn"
                >
                  <View style={[styles.actionIcon, { backgroundColor: COLORS.primaryLight }]}>
                    <Eye size={18} color={COLORS.primary} />
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.actionTitle}>Reveal full card details</Text>
                    <Text style={styles.actionSub}>Show PAN, CVV and expiry</Text>
                  </View>
                </TouchableOpacity>
                <View style={styles.divider} />
                <TouchableOpacity
                  onPress={onAddToWallet}
                  style={styles.actionRow}
                  activeOpacity={0.7}
                  disabled={busy}
                  testID="card-wallet-btn"
                >
                  <View style={[styles.actionIcon, { backgroundColor: '#E0F2FE' }]}>
                    <Smartphone size={18} color="#0284C7" />
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.actionTitle}>
                      Add to {Platform.OS === 'ios' ? 'Apple Pay' : 'Google Pay'}
                    </Text>
                    <Text style={styles.actionSub}>Tap-to-pay enrolment</Text>
                  </View>
                </TouchableOpacity>
                <View style={styles.divider} />
                <TouchableOpacity
                  onPress={onDisable}
                  style={styles.actionRow}
                  activeOpacity={0.7}
                  disabled={busy}
                  testID="card-disable-btn"
                >
                  <View style={[styles.actionIcon, { backgroundColor: COLORS.warningLight }]}>
                    <ShieldOff size={18} color={COLORS.warning} />
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={[styles.actionTitle, { color: COLORS.warning }]}>Disable card</Text>
                    <Text style={styles.actionSub}>Stops new charges immediately</Text>
                  </View>
                </TouchableOpacity>
              </View>
            ) : isDisabled ? (
              <View style={styles.warnBanner}>
                <Lock size={18} color={COLORS.subtext} />
                <Text style={styles.warnText}>
                  This card is disabled. Past transactions are still visible in admin history.
                </Text>
              </View>
            ) : (
              <View style={styles.warnBanner}>
                <Wallet size={18} color={COLORS.warning} />
                <Text style={styles.warnText}>
                  Card is funding — it will activate once the group reaches full funding (
                  ${collected.toFixed(2)} of ${total.toFixed(2)} collected).
                </Text>
              </View>
            )}
          </>
        ) : (
          // No card has been issued yet
          <View style={styles.emptyCard} testID="card-empty">
            <View style={styles.emptyIcon}>
              <CreditCard size={32} color={COLORS.primary} />
            </View>
            <Text style={styles.emptyTitle}>No virtual card yet</Text>
            <Text style={styles.emptyBody}>
              {fullyFunded
                ? 'Your bill is fully funded but the card hasn\'t been issued. Try refreshing — Stripe Issuing usually takes a few seconds.'
                : `A Stripe-issued virtual card will be created automatically once your bill is fully funded ($${collected.toFixed(
                    2,
                  )} of $${total.toFixed(2)} collected).`}
            </Text>
            <Button title="Refresh" variant="secondary" onPress={onRefresh} testID="card-empty-refresh" />
            <Button
              title="Back to Dashboard"
              variant="ghost"
              onPress={() => router.replace(`/group/${id}/dashboard`)}
              style={{ marginTop: SPACING.sm }}
            />
          </View>
        )}
      </ScrollView>

      {hasCard && (
        <RevealCardModal
          visible={revealOpen}
          onClose={() => setRevealOpen(false)}
          groupId={String(id)}
        />
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: COLORS.bg },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: COLORS.bg },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: SPACING.md,
    paddingTop: SPACING.sm,
    paddingBottom: SPACING.sm,
  },
  iconBtn: { width: 40, height: 40, borderRadius: 20, alignItems: 'center', justifyContent: 'center' },
  headerTitle: { fontSize: FONT.sizes.lg, fontWeight: FONT.weights.bold, color: COLORS.text },
  scroll: { padding: SPACING.md, paddingBottom: SPACING.xl },
  groupTitle: {
    fontSize: FONT.sizes.xs,
    color: COLORS.subtext,
    textTransform: 'uppercase',
    letterSpacing: 1,
    fontWeight: FONT.weights.semibold,
    marginBottom: SPACING.md,
  },
  cardFace: {
    borderRadius: 18,
    padding: 18,
    minHeight: 200,
    justifyContent: 'space-between',
  },
  cardChip: { width: 32, height: 22, borderRadius: 4, backgroundColor: 'rgba(255,255,255,0.35)' },
  cardRow: { flexDirection: 'row', alignItems: 'center' },
  cardBrand: { color: '#fff', fontWeight: FONT.weights.bold, fontSize: FONT.sizes.md },
  cardGroupName: { color: 'rgba(255,255,255,0.85)', fontSize: 11, marginTop: 2 },
  statusPill: {
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 999,
  },
  pillActive: { backgroundColor: 'rgba(34,197,94,0.32)' },
  pillOff: { backgroundColor: 'rgba(255,255,255,0.18)' },
  statusPillText: { color: '#fff', fontWeight: FONT.weights.bold, fontSize: 9, letterSpacing: 0.6 },
  cardNumber: { color: '#fff', fontWeight: FONT.weights.bold, letterSpacing: 2.4, fontSize: 18 },
  cardFooter: { flexDirection: 'row', justifyContent: 'space-between' },
  cardTinyLabel: { color: 'rgba(255,255,255,0.7)', fontSize: 10, textTransform: 'uppercase', letterSpacing: 0.6 },
  cardValue: { color: '#fff', fontWeight: FONT.weights.bold, fontSize: FONT.sizes.sm, marginTop: 2 },

  section: { marginTop: SPACING.lg },
  sectionHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  sectionTitle: { color: COLORS.text, fontSize: FONT.sizes.md, fontWeight: FONT.weights.bold },
  sectionPct: { color: COLORS.primary, fontSize: FONT.sizes.md, fontWeight: FONT.weights.heavy },
  sectionFoot: { color: COLORS.subtext, fontSize: FONT.sizes.xs, marginTop: 6 },
  track: { height: 8, borderRadius: 999, backgroundColor: COLORS.border, overflow: 'hidden', marginTop: 6 },
  fill: { height: '100%', backgroundColor: COLORS.primary, borderRadius: 999 },

  actionsCard: {
    marginTop: SPACING.lg,
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.md,
    borderWidth: 1,
    borderColor: COLORS.border,
    overflow: 'hidden',
  },
  actionRow: { flexDirection: 'row', alignItems: 'center', padding: SPACING.md, gap: 12 },
  actionIcon: { width: 36, height: 36, borderRadius: 18, alignItems: 'center', justifyContent: 'center' },
  actionTitle: { color: COLORS.text, fontWeight: FONT.weights.semibold, fontSize: FONT.sizes.sm },
  actionSub: { color: COLORS.subtext, fontSize: FONT.sizes.xs, marginTop: 2 },
  divider: { height: 1, backgroundColor: COLORS.border, marginLeft: 60 },

  warnBanner: {
    flexDirection: 'row',
    gap: 10,
    alignItems: 'center',
    backgroundColor: COLORS.warningLight,
    padding: SPACING.md,
    borderRadius: RADIUS.md,
    marginTop: SPACING.lg,
  },
  warnText: { color: '#92400E', fontSize: FONT.sizes.sm, flex: 1 },

  emptyCard: {
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.lg,
    borderWidth: 1,
    borderColor: COLORS.border,
    padding: SPACING.lg,
    alignItems: 'center',
    gap: SPACING.md,
  },
  emptyIcon: {
    width: 64,
    height: 64,
    borderRadius: 32,
    backgroundColor: COLORS.primaryLight,
    alignItems: 'center',
    justifyContent: 'center',
  },
  emptyTitle: { color: COLORS.text, fontSize: FONT.sizes.lg, fontWeight: FONT.weights.bold },
  emptyBody: { color: COLORS.subtext, fontSize: FONT.sizes.sm, textAlign: 'center', lineHeight: 20 },
});

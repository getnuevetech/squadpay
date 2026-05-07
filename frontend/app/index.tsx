import { useRouter } from 'expo-router';
import { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  FlatList,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Receipt, Plus, Link2, QrCode, ChevronRight, Sparkles, LogOut, Gift, Wallet, ShieldAlert } from 'lucide-react-native';
import { Button } from '../src/Button';
import { api } from '../src/api';
import { clearUser, loadUser, refreshUser } from '../src/session';
import { COLORS, FONT, RADIUS, SPACING, SHADOW } from '../src/theme';
import { StatusBadge } from '../src/StatusBadge';
import { PressableScale } from '../src/components/PressableScale';
import { SkeletonGroupRow, Skeleton } from '../src/components/Skeleton';
import { EmptyState } from '../src/components/EmptyState';

export default function HomeScreen() {
  const router = useRouter();
  const [user, setUser] = useState<Awaited<ReturnType<typeof loadUser>>>(null);
  const [groups, setGroups] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [features, setFeatures] = useState<{ credits_enabled: boolean; invite_friends_enabled: boolean }>({
    credits_enabled: true,
    invite_friends_enabled: true,
  });

  const load = useCallback(async () => {
    const u = await refreshUser();
    setUser(u);
    api.getAppFeatures().then(setFeatures).catch(() => {});
    if (u) {
      try {
        const gs = await api.getUserGroups(u.id);
        setGroups(gs);
      } catch (e) {
        console.log('Failed to load groups', e);
      }
    } else {
      setGroups([]);
    }
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  const onRefresh = async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  };

  // ───── Loading state (Home: skeleton hero + group rows) ─────
  if (loading && !user) {
    return (
      <SafeAreaView style={{ flex: 1, backgroundColor: COLORS.bg }} testID="home-loading">
        <ScrollView contentContainerStyle={{ padding: SPACING.md }}>
          <Skeleton width={140} height={28} style={{ marginBottom: SPACING.md }} />
          <Skeleton width={'100%'} height={140} radius={20} style={{ marginBottom: SPACING.lg }} />
          <Skeleton width={120} height={14} style={{ marginVertical: SPACING.md }} />
          <SkeletonGroupRow />
          <SkeletonGroupRow />
        </ScrollView>
      </SafeAreaView>
    );
  }

  // ───── Welcome (unauth) ─────
  if (!user) {
    return (
      <SafeAreaView style={styles.container} testID="home-unauth">
        <ScrollView contentContainerStyle={styles.welcomeContent}>
          <View style={styles.welcomeIconWrap}>
            <Sparkles color={COLORS.primary} size={36} strokeWidth={2.2} />
          </View>
          <Text style={styles.welcomeTitle}>SquadPay</Text>
          <Text style={styles.welcomeSub}>
            Split restaurant bills instantly. No more chasing friends for money.
          </Text>
          <View style={styles.welcomeFeatures}>
            {[
              { icon: <QrCode color={COLORS.primary} size={20} />, text: 'Share a QR or link to split' },
              { icon: <Receipt color={COLORS.primary} size={20} />, text: 'Claim only the items you ordered' },
              { icon: <Link2 color={COLORS.primary} size={20} />, text: 'Track repayments automatically' },
            ].map((f, i) => (
              <View key={i} style={styles.welcomeFeatureRow}>
                <View style={styles.welcomeFeatureIcon}>{f.icon}</View>
                <Text style={styles.welcomeFeatureText}>{f.text}</Text>
              </View>
            ))}
          </View>
          {/* Dual CTA at the bottom — primary "Start" + secondary "Join" */}
          <View style={styles.welcomeCtaRow}>
            <PressableScale
              testID="home-get-started-btn"
              onPress={() => router.push('/auth')}
              style={[styles.welcomeStartBtn, SHADOW.primary]}
            >
              <View>
                <Plus color="#fff" size={18} strokeWidth={2.6} />
                <Text style={styles.welcomeStartText}>Start a bill</Text>
              </View>
            </PressableScale>
            <PressableScale
              testID="home-join-btn-unauth"
              onPress={() => router.push('/auth?intent=join')}
              style={styles.welcomeJoinBtn}
            >
              <View>
                <QrCode color={COLORS.primary} size={18} />
                <Text style={styles.welcomeJoinText}>Join a bill</Text>
              </View>
            </PressableScale>
          </View>
        </ScrollView>
      </SafeAreaView>
    );
  }

  // ───── Authenticated home ─────
  const activeCount = groups.filter(g => ((g as any).derived_status || g.status) !== 'settled' && g.status !== 'closed' && g.status !== 'bill_settled').length;
  const settledCount = groups.length - activeCount;

  return (
    <SafeAreaView style={styles.container} edges={['top']} testID="home-auth">
      <ScrollView
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={COLORS.primary} />}
        contentContainerStyle={{ padding: SPACING.md, paddingBottom: SPACING.xxl }}
      >
        {/* Header */}
        <View style={styles.header}>
          <View>
            <Text style={styles.hello} testID="home-hello">Hello,</Text>
            <Text style={styles.name}>{user.name}</Text>
            {!user.verified ? (
              <TouchableOpacity
                onPress={() => router.push(`/auth?mode=verify&user_id=${user.id}`)}
                style={styles.verifyCta}
                testID="home-verify-cta"
                activeOpacity={0.85}
              >
                <ShieldAlert size={14} color={COLORS.warning} />
                <Text style={styles.verifyCtaText}>Verify phone to pay</Text>
                <ChevronRight size={14} color={COLORS.warning} />
              </TouchableOpacity>
            ) : null}
          </View>
          <TouchableOpacity
            testID="home-logout-btn"
            onPress={async () => {
              await clearUser();
              setUser(null);
              setGroups([]);
            }}
            style={styles.iconBtn}
            activeOpacity={0.7}
          >
            <LogOut color={COLORS.text} size={18} />
          </TouchableOpacity>
        </View>

        {/* Hero — active bills */}
        <View style={[styles.heroCard, SHADOW.lg]} testID="home-hero-card">
          <View style={styles.heroTop}>
            <Text style={styles.heroLabel}>Active bills</Text>
            <View style={styles.heroDot} />
          </View>
          <Text style={styles.heroAmount}>{activeCount}</Text>
          <View style={styles.heroFooter}>
            <View style={styles.heroChip}>
              <Text style={styles.heroChipText}>{settledCount} settled</Text>
            </View>
            <Text style={styles.heroFooterText}>{groups.length} total</Text>
          </View>
        </View>

        {/* Action cards — Start (primary) + Join (secondary) */}
        <View style={styles.actionsRow}>
          <PressableScale
            testID="home-start-bill-btn"
            onPress={() => router.push('/create')}
            style={[styles.actionCard, styles.actionPrimary, SHADOW.primary]}
          >
            <View style={styles.actionIconWhite}>
              <Plus color="#FFFFFF" size={26} strokeWidth={2.6} />
            </View>
            <Text style={styles.actionPrimaryTitle}>Start a Bill</Text>
            <Text style={styles.actionPrimarySub}>Scan or enter total</Text>
          </PressableScale>

          <PressableScale
            testID="home-join-bill-btn"
            onPress={() => router.push('/join/code')}
            style={[styles.actionCard, styles.actionSecondary, SHADOW.sm]}
          >
            <View style={styles.actionIcon}>
              <QrCode color={COLORS.primary} size={24} />
            </View>
            <Text style={styles.actionTitle}>Join a Bill</Text>
            <Text style={styles.actionSub}>Enter code or link</Text>
          </PressableScale>
        </View>

        {/* Recent activity */}
        <Text style={styles.sectionTitle}>Recent Activity</Text>
        {refreshing && groups.length === 0 ? (
          <>
            <SkeletonGroupRow testID="home-skel-1" />
            <SkeletonGroupRow testID="home-skel-2" />
            <SkeletonGroupRow testID="home-skel-3" />
          </>
        ) : groups.length === 0 ? (
          <EmptyState
            Icon={Receipt}
            title="No bills yet"
            subtitle="Start your first bill to split with friends — it's free and takes under a minute."
            cta={{ label: 'Start your first bill', onPress: () => router.push('/create'), testID: 'home-empty-cta' }}
            testID="home-empty"
          />
        ) : (
          <FlatList
            data={groups}
            keyExtractor={(g) => g.id}
            scrollEnabled={false}
            renderItem={({ item }) => (
              <PressableScale
                testID={`home-group-${item.id}`}
                onPress={() => router.push(`/group/${item.id}`)}
                style={[styles.groupRow, SHADOW.sm]}
                scaleTo={0.99}
              >
                <View style={{ flexDirection: 'row', alignItems: 'center', gap: SPACING.md }}>
                  <View style={styles.groupIcon}>
                    <Receipt color={COLORS.primary} size={20} />
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.groupTitle} numberOfLines={1}>{item.title}</Text>
                    <Text style={styles.groupMeta}>
                      {item.member_count} {item.member_count === 1 ? 'member' : 'members'} · ${Number(item.total || 0).toFixed(2)}
                    </Text>
                  </View>
                  <StatusBadge status={(item as any).derived_status || (item.status === 'closed' ? 'settled' : item.status === 'paid' ? 'repaying' : 'contributing')} testID={`home-status-${item.id}`} />
                  <ChevronRight color={COLORS.subtext} size={18} />
                </View>
              </PressableScale>
            )}
          />
        )}

        {/* Secondary actions — Referrals + Credits */}
        {(features.invite_friends_enabled || features.credits_enabled) ? (
          <View style={styles.secondaryRow}>
            {features.invite_friends_enabled ? (
              <TouchableOpacity
                testID="home-invite-btn"
                style={styles.textBtn}
                onPress={() => router.push('/invite')}
                activeOpacity={0.7}
              >
                <Gift color={COLORS.primary} size={16} />
                <Text style={styles.textBtnLabel}>Referrals</Text>
              </TouchableOpacity>
            ) : null}
            {features.credits_enabled ? (
              <TouchableOpacity
                testID="home-credits-btn"
                style={styles.textBtn}
                onPress={() => router.push('/credits')}
                activeOpacity={0.7}
              >
                <Wallet color={COLORS.primary} size={16} />
                <Text style={styles.textBtnLabel}>My Credits</Text>
              </TouchableOpacity>
            ) : null}
          </View>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: COLORS.bg },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: COLORS.bg },

  // Welcome (unauth)
  welcomeContent: {
    padding: SPACING.lg,
    paddingTop: SPACING.xl,
    flexGrow: 1,
  },
  welcomeIconWrap: {
    width: 72,
    height: 72,
    borderRadius: 20,
    backgroundColor: COLORS.primaryLight,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: SPACING.lg,
  },
  welcomeTitle: {
    fontSize: FONT.sizes.huge,
    fontWeight: FONT.weights.heavy,
    color: COLORS.text,
    letterSpacing: -1,
  },
  welcomeSub: {
    marginTop: SPACING.sm,
    fontSize: FONT.sizes.md,
    color: COLORS.subtext,
    lineHeight: 24,
  },
  welcomeFeatures: { marginTop: SPACING.xl, gap: SPACING.md, flex: 1 },
  welcomeFeatureRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: SPACING.md,
    backgroundColor: COLORS.surface,
    paddingVertical: SPACING.md,
    paddingHorizontal: SPACING.md,
    borderRadius: RADIUS.md,
    borderWidth: 1,
    borderColor: COLORS.border,
  },
  welcomeFeatureIcon: {
    width: 40,
    height: 40,
    borderRadius: 12,
    backgroundColor: COLORS.primaryLight,
    alignItems: 'center',
    justifyContent: 'center',
  },
  welcomeFeatureText: { fontSize: FONT.sizes.md, color: COLORS.text, flex: 1, fontWeight: FONT.weights.medium },
  welcomeCtaRow: {
    flexDirection: 'row',
    gap: SPACING.md,
    marginTop: SPACING.xl,
  },
  welcomeStartBtn: {
    flex: 1.4,
    backgroundColor: COLORS.primary,
    borderRadius: RADIUS.lg,
    paddingVertical: 18,
    paddingHorizontal: SPACING.lg,
    alignItems: 'center',
    justifyContent: 'center',
  },
  welcomeStartText: { color: '#fff', fontWeight: FONT.weights.bold, fontSize: FONT.sizes.md, marginTop: 6, textAlign: 'center' },
  welcomeJoinBtn: {
    flex: 1,
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.lg,
    paddingVertical: 18,
    paddingHorizontal: SPACING.lg,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1.5,
    borderColor: COLORS.primary,
  },
  welcomeJoinText: { color: COLORS.primary, fontWeight: FONT.weights.bold, fontSize: FONT.sizes.md, marginTop: 6, textAlign: 'center' },

  // Auth header
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    marginBottom: SPACING.lg,
  },
  hello: { color: COLORS.subtext, fontSize: FONT.sizes.sm },
  name: { color: COLORS.text, fontSize: FONT.sizes.xxl, fontWeight: FONT.weights.bold },
  verifyHint: { color: COLORS.warning, fontSize: FONT.sizes.xs, marginTop: 2, fontWeight: FONT.weights.semibold },
  // Phase H6.3 — verify-phone CTA pill on home (replaces the static hint text).
  verifyCta: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    alignSelf: 'flex-start',
    marginTop: 6,
    paddingHorizontal: 12,
    paddingVertical: 6,
    backgroundColor: COLORS.warningLight,
    borderRadius: RADIUS.pill,
    borderWidth: 1,
    borderColor: COLORS.warning,
  },
  verifyCtaText: {
    color: COLORS.warning,
    fontSize: FONT.sizes.xs,
    fontWeight: FONT.weights.bold,
    letterSpacing: 0.2,
  },
  iconBtn: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: COLORS.surface,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
    borderColor: COLORS.border,
  },

  // Hero
  heroCard: {
    backgroundColor: COLORS.slate900,
    borderRadius: RADIUS.xl,
    padding: SPACING.lg,
    marginBottom: SPACING.lg,
    overflow: 'hidden',
  },
  heroTop: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  heroLabel: { color: COLORS.slate400, fontSize: FONT.sizes.xs, textTransform: 'uppercase', letterSpacing: 1.2, fontWeight: FONT.weights.semibold },
  heroDot: { width: 8, height: 8, borderRadius: 4, backgroundColor: COLORS.success },
  heroAmount: {
    color: '#fff',
    fontSize: FONT.sizes.display,
    fontWeight: FONT.weights.heavy,
    marginTop: 6,
    letterSpacing: -2,
    lineHeight: 64,
  },
  heroFooter: { marginTop: SPACING.md, flexDirection: 'row', alignItems: 'center', gap: SPACING.sm },
  heroChip: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: RADIUS.pill, backgroundColor: 'rgba(255,255,255,0.1)' },
  heroChipText: { color: '#fff', fontSize: FONT.sizes.xs, fontWeight: FONT.weights.semibold },
  heroFooterText: { color: COLORS.slate400, fontSize: FONT.sizes.sm },

  // Action cards
  actionsRow: { flexDirection: 'row', gap: SPACING.md, marginBottom: SPACING.lg },
  actionCard: {
    flex: 1,
    borderRadius: RADIUS.lg,
    padding: SPACING.lg,
    minHeight: 152,
  },
  actionPrimary: { backgroundColor: COLORS.primary },
  actionSecondary: { backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border },
  actionIcon: {
    width: 48, height: 48, borderRadius: 14,
    backgroundColor: COLORS.primaryLight,
    alignItems: 'center', justifyContent: 'center',
  },
  actionIconWhite: {
    width: 48, height: 48, borderRadius: 14,
    backgroundColor: 'rgba(255,255,255,0.18)',
    alignItems: 'center', justifyContent: 'center',
  },
  actionPrimaryTitle: { marginTop: SPACING.md, color: '#fff', fontSize: FONT.sizes.lg, fontWeight: FONT.weights.bold },
  actionPrimarySub: { color: '#E0E7FF', fontSize: FONT.sizes.xs, marginTop: 2 },
  actionTitle: { marginTop: SPACING.md, color: COLORS.text, fontSize: FONT.sizes.lg, fontWeight: FONT.weights.bold },
  actionSub: { color: COLORS.subtext, fontSize: FONT.sizes.xs, marginTop: 2 },

  sectionTitle: {
    fontSize: FONT.sizes.lg,
    fontWeight: FONT.weights.bold,
    color: COLORS.text,
    marginBottom: SPACING.md,
  },

  // Group rows
  groupRow: {
    backgroundColor: COLORS.surface,
    padding: SPACING.md,
    borderRadius: RADIUS.md,
    marginBottom: SPACING.sm,
    borderWidth: 1,
    borderColor: COLORS.border,
  },
  groupIcon: {
    width: 40, height: 40, borderRadius: 12,
    backgroundColor: COLORS.primaryLight,
    alignItems: 'center', justifyContent: 'center',
  },
  groupTitle: { color: COLORS.text, fontWeight: FONT.weights.semibold, fontSize: FONT.sizes.md },
  groupMeta: { color: COLORS.subtext, fontSize: FONT.sizes.xs, marginTop: 2 },

  // Secondary text-only buttons
  secondaryRow: {
    flexDirection: 'row',
    justifyContent: 'center',
    alignItems: 'center',
    gap: SPACING.xl,
    marginTop: SPACING.xl,
    marginBottom: SPACING.lg,
    paddingVertical: SPACING.md,
  },
  textBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    paddingVertical: 8,
    paddingHorizontal: 12,
  },
  textBtnLabel: {
    fontSize: FONT.sizes.md,
    color: COLORS.primary,
    fontWeight: FONT.weights.semibold,
  },
});

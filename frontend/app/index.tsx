/**
 * SquadPay Home (post-redesign) — matches the reference mocks:
 *   • Unauth (light) → landing with phone-frame illustration, big serif
 *     headline "Split the bill. Pay together.", and a footer pill CTA.
 *   • Auth (adapted dark) → violet-gradient hero panel with brand mark,
 *     profile avatar, "Live Squad Session" pill, headline, and a featured
 *     bill card; below the hero, the existing groups list keeps the light
 *     theme and stacked-avatar rows.
 *
 * Rollback layers:
 *   1. Env flag — set EXPO_PUBLIC_REDESIGN=off in /app/frontend/.env. The
 *      original screen at /app/frontend/_legacy_backup/index.legacy.tsx
 *      will be rendered instead (re-exported via dynamic require).
 *   2. File backup — /app/frontend/_legacy_backup/index.legacy.tsx is the
 *      pre-redesign source; copy it back over this file to fully revert.
 */
import { useRouter } from 'expo-router';
import { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  FlatList,
  Platform,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  Receipt,
  Plus,
  ChevronRight,
  ShieldAlert,
  QrCode,
  Sparkles,
} from 'lucide-react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { api } from '../src/api';
import { refreshUser } from '../src/session';
import { COLORS, FONT, RADIUS, SPACING } from '../src/theme';
import { StatusBadge } from '../src/StatusBadge';
import { Skeleton, SkeletonGroupRow } from '../src/components/Skeleton';
import { AvatarRing } from '../src/components/AvatarRing';
import { SquadPayMark } from '../src/components/redesign/SquadPayMark';
import { HeroPhoneFrame } from '../src/components/redesign/HeroPhoneFrame';
import { LiveSessionPill } from '../src/components/redesign/LiveSessionPill';
import { FeaturedBillCard } from '../src/components/redesign/FeaturedBillCard';
import { BottomTabBar } from '../src/components/redesign/BottomTabBar';

// Feature flag — flip to "off" in .env to render legacy screen via the backup file.
const REDESIGN_ON = (process.env.EXPO_PUBLIC_REDESIGN || 'on').toLowerCase() !== 'off';

export default function HomeScreen() {
  const router = useRouter();
  const [user, setUser] = useState<Awaited<ReturnType<typeof refreshUser>>>(null);
  const [groups, setGroups] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    const u = await refreshUser();
    setUser(u);
    if (u) {
      try {
        const gs = await api.getUserGroups(u.id);
        setGroups(gs);
      } catch (e) { console.log('Failed to load groups', e); }
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

  // Rollback hatch — render legacy screen verbatim.
  if (!REDESIGN_ON) {
    // Lazy require so legacy module is only loaded when flag is off.
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const Legacy = require('../_legacy_backup/index.legacy').default;
    return <Legacy />;
  }

  // ───── Loading skeleton ─────
  if (loading && !user) {
    return (
      <SafeAreaView style={{ flex: 1, backgroundColor: COLORS.bg }} testID="home-loading">
        <ScrollView contentContainerStyle={{ padding: SPACING.md }}>
          <Skeleton width={140} height={28} style={{ marginBottom: SPACING.md }} />
          <Skeleton width={'100%'} height={220} radius={24} style={{ marginBottom: SPACING.lg }} />
          <SkeletonGroupRow />
          <SkeletonGroupRow />
        </ScrollView>
      </SafeAreaView>
    );
  }

  // ─────────────────────────────────────────────────────────────
  // UNAUTH → Landing (Image 1 redesign)
  // ─────────────────────────────────────────────────────────────
  if (!user) {
    return (
      <SafeAreaView style={styles.landingWrap} testID="home-unauth">
        <ScrollView
          contentContainerStyle={styles.landingScroll}
          showsVerticalScrollIndicator={false}
          bounces={Platform.OS !== 'web'}
        >
          {/* Phone-frame illustration with hashtag chips + dots */}
          <View style={styles.heroFrameSlot}>
            <HeroPhoneFrame height={260} />
          </View>

          {/* Brand mark + wordmark */}
          <View style={styles.brandRow}>
            <SquadPayMark size={48} testID="landing-brand-mark" />
          </View>

          {/* Headline (matches the reference exactly) */}
          <Text style={styles.headline}>
            <Text style={styles.headlineDark}>Split the bill.{'\n'}</Text>
            <Text style={styles.headlineViolet}>Pay together.</Text>
          </Text>
          <Text style={styles.subhead}>
            Scan a receipt, share a link, and only pay for what you ordered.
          </Text>

          {/* Footer share-pill CTA */}
          <Pressable
            onPress={() => router.push('/auth')}
            style={({ pressed }) => [styles.footerPill, pressed && { opacity: 0.94 }]}
            testID="landing-share-pill"
          >
            <View style={styles.footerPillIcon}>
              <Plus color={COLORS.primary} size={18} strokeWidth={2.6} />
            </View>
            <Text style={styles.footerPillText}>Share a QR or link to split</Text>
          </Pressable>

          {/* Secondary actions */}
          <Pressable
            onPress={() => router.push('/auth?intent=join')}
            style={styles.secondaryRow}
            testID="landing-join-btn"
          >
            <QrCode size={16} color={COLORS.primary} />
            <Text style={styles.secondaryText}>Join a bill via QR or code</Text>
          </Pressable>

          <Pressable
            onPress={() => router.push('/auth?intent=signin')}
            style={styles.signinRow}
            testID="landing-signin"
          >
            <Text style={styles.signinPrompt}>Already have an account? </Text>
            <Text style={styles.signinAction}>Sign in</Text>
          </Pressable>

          {/* Legal footer */}
          <View style={styles.legalRow}>
            <Text testID="home-footer-support" style={styles.legalLink} onPress={() => router.push('/legal/support')}>Support</Text>
            <Text style={styles.legalDot}>·</Text>
            <Text testID="home-footer-privacy" style={styles.legalLink} onPress={() => router.push('/legal/privacy')}>Privacy</Text>
            <Text style={styles.legalDot}>·</Text>
            <Text testID="home-footer-terms" style={styles.legalLink} onPress={() => router.push('/legal/terms')}>Terms</Text>
          </View>
          <Text style={styles.copyright}>© 2026 — SquadPay by NueveTech</Text>
        </ScrollView>
      </SafeAreaView>
    );
  }

  // ─────────────────────────────────────────────────────────────
  // AUTH → Adapted-dark hero + light list (Image 2 redesign)
  // ─────────────────────────────────────────────────────────────
  const isActive = (g: any) => {
    const s = (g as any).derived_status || g.status;
    return s !== 'settled' && s !== 'closed' && s !== 'bill_settled';
  };
  const featured = groups.find(isActive) || groups[0];
  const otherGroups = groups.filter((g) => g.id !== featured?.id);
  const firstName = (user.name || '').split(' ')[0] || 'there';

  return (
    <View style={{ flex: 1, backgroundColor: COLORS.bg }} testID="home-auth">
      <ScrollView
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor="#fff" />}
        contentContainerStyle={{ paddingBottom: 110 }}
      >
        {/* ───── Hero panel (violet gradient, adapted-dark) ───── */}
        <LinearGradient
          colors={['#3F1F8C', '#5B2BC8', '#7C3AED']}
          start={{ x: 0, y: 0 }}
          end={{ x: 1, y: 1 }}
          style={styles.hero}
        >
          <SafeAreaView edges={['top']}>
            <View style={styles.heroHeader}>
              <SquadPayMark size={32} variant="onDark" testID="home-brand-mark" />
              <TouchableOpacity
                onPress={() => router.push('/settings')}
                activeOpacity={0.85}
                style={styles.profileBtn}
                testID="home-profile-btn"
              >
                <AvatarRing
                  name={user.name || '?'}
                  seed={user.id || 'me'}
                  size={36}
                />
              </TouchableOpacity>
            </View>

            {/* Live session pill */}
            {featured && isActive(featured) ? (
              <View style={{ marginTop: SPACING.md, marginHorizontal: SPACING.md }}>
                <LiveSessionPill testID="home-live-pill" />
              </View>
            ) : null}

            {/* Big headline */}
            <View style={{ paddingHorizontal: SPACING.md, marginTop: SPACING.md }}>
              <Text style={styles.heroHello}>Hello {firstName},</Text>
              <Text style={styles.heroHeadline}>
                <Text style={styles.heroHeadlineWhite}>Split bills{'\n'}with your </Text>
                <Text style={styles.heroHeadlineLavender}>squad.</Text>
              </Text>
              <Text style={styles.heroSub}>
                Scan, split, and settle — all in one place. No more awkward money talks.
              </Text>
            </View>

            {/* Verify-phone nudge */}
            {!user.verified ? (
              <TouchableOpacity
                onPress={() => router.push(`/auth?mode=verify&user_id=${user.id}`)}
                style={styles.verifyChip}
                testID="home-verify-cta"
                activeOpacity={0.85}
              >
                <ShieldAlert size={14} color="#FCD34D" />
                <Text style={styles.verifyChipText}>Verify phone to pay or repay</Text>
                <ChevronRight size={14} color="#FCD34D" />
              </TouchableOpacity>
            ) : null}

            {/* Featured bill card */}
            {featured ? (
              <View style={{ paddingHorizontal: SPACING.md, marginTop: SPACING.lg }}>
                <FeaturedBillCard
                  testID="home-featured-card"
                  title={featured.title}
                  total={Number(featured.total || 0)}
                  paidAmount={Number((featured as any).funding?.contributed_total || 0)}
                  remainingAmount={Number((featured as any).funding?.remaining_to_collect || 0)}
                  paidCount={Number((featured as any).paid_count || 0)}
                  totalCount={Number(featured.member_count || 0)}
                  leadId={featured.lead_id}
                  members={(featured as any).members_preview || []}
                  onPress={() => router.push(`/group/${featured.id}/dashboard`)}
                  onPay={() => router.push(`/group/${featured.id}/pay`)}
                  onShare={() => router.push(`/group/${featured.id}/dashboard?share=1`)}
                  onAddMember={() => router.push(`/group/${featured.id}/dashboard?invite=1`)}
                />
              </View>
            ) : (
              <View style={{ paddingHorizontal: SPACING.md, marginTop: SPACING.lg }}>
                <Pressable
                  onPress={() => router.push('/create')}
                  style={styles.emptyHero}
                  testID="home-empty-cta"
                >
                  <View style={styles.emptyHeroIcon}>
                    <Sparkles color="#fff" size={20} />
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.emptyHeroTitle}>Start your first split</Text>
                    <Text style={styles.emptyHeroSub}>Tap to scan a receipt or enter an amount.</Text>
                  </View>
                  <ChevronRight color="#fff" size={18} />
                </Pressable>
              </View>
            )}

            <View style={{ height: SPACING.lg }} />
          </SafeAreaView>
        </LinearGradient>

        {/* ───── Light list section ───── */}
        <View style={{ padding: SPACING.md }}>
          <View style={styles.listHeader}>
            <Text style={styles.listTitle}>Your bills</Text>
            <TouchableOpacity onPress={() => router.push('/activity')} activeOpacity={0.7} testID="home-see-all">
              <Text style={styles.listSeeAll}>See all</Text>
            </TouchableOpacity>
          </View>

          {otherGroups.length === 0 ? (
            <View style={styles.listEmpty}>
              <Receipt color={COLORS.subtext} size={20} />
              <Text style={styles.listEmptyText}>No other bills yet.</Text>
            </View>
          ) : (
            <FlatList
              data={otherGroups}
              keyExtractor={(g) => g.id}
              scrollEnabled={false}
              renderItem={({ item }) => (
                <Pressable
                  onPress={() => router.push(`/group/${item.id}/dashboard`)}
                  style={({ pressed }) => [styles.groupRow, pressed && { opacity: 0.95 }]}
                  testID={`home-group-row-${item.id}`}
                >
                  <View style={styles.groupIcon}>
                    <Receipt color={COLORS.primary} size={18} />
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.groupTitle} numberOfLines={1}>{item.title}</Text>
                    <Text style={styles.groupMeta}>
                      {item.member_count} members · ${Number(item.total || 0).toFixed(2)}
                    </Text>
                    {item.members_preview && item.members_preview.length > 0 ? (
                      <View style={styles.memberStack}>
                        {item.members_preview.slice(0, 4).map((m: any, idx: number) => (
                          <View key={m.user_id} style={[styles.memberStackItem, { marginLeft: idx === 0 ? 0 : -10, zIndex: 10 - idx }]}>
                            <AvatarRing name={m.name || '?'} seed={m.user_id} size={24} showLeadCrown={m.user_id === item.lead_id} />
                          </View>
                        ))}
                        {item.member_count > 4 ? (
                          <View style={[styles.memberStackItem, styles.memberStackMore, { marginLeft: -10 }]}>
                            <Text style={styles.memberStackMoreText}>+{item.member_count - 4}</Text>
                          </View>
                        ) : null}
                      </View>
                    ) : null}
                  </View>
                  <StatusBadge
                    status={(item as any).derived_status || (item.status === 'closed' ? 'settled' : item.status === 'paid' ? 'repaying' : 'contributing')}
                    testID={`home-status-${item.id}`}
                  />
                  <ChevronRight color={COLORS.subtext} size={16} />
                </Pressable>
              )}
            />
          )}
        </View>
      </ScrollView>
      <BottomTabBar active="home" />
    </View>
  );
}

const styles = StyleSheet.create({
  // ─── Landing ───
  landingWrap: { flex: 1, backgroundColor: '#FAF7FF' },
  landingScroll: { padding: SPACING.lg, paddingBottom: SPACING.xl, alignItems: 'stretch' },
  heroFrameSlot: { alignItems: 'center', marginTop: SPACING.md, marginBottom: SPACING.lg },
  brandRow: { flexDirection: 'row', justifyContent: 'center', alignItems: 'center', marginTop: 4, marginBottom: SPACING.md },
  headline: { textAlign: 'center', fontSize: 36, fontWeight: FONT.weights.bold, lineHeight: 44, letterSpacing: -1 },
  headlineDark: { color: '#0E0726' },
  headlineViolet: { color: COLORS.primary },
  subhead: {
    textAlign: 'center',
    fontSize: 15,
    color: COLORS.subtext,
    marginTop: SPACING.md,
    paddingHorizontal: SPACING.lg,
    lineHeight: 22,
  },
  footerPill: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 14,
    backgroundColor: '#fff',
    paddingHorizontal: SPACING.md,
    paddingVertical: 14,
    borderRadius: 18,
    marginTop: SPACING.xl,
    borderWidth: 1,
    borderColor: '#EFE7FE',
    shadowColor: '#1F1240',
    shadowOpacity: 0.06,
    shadowRadius: 14,
    shadowOffset: { width: 0, height: 6 },
    elevation: 3,
  },
  footerPillIcon: {
    width: 36,
    height: 36,
    borderRadius: 12,
    backgroundColor: '#F1ECFE',
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1.5,
    borderColor: COLORS.primary,
  },
  footerPillText: { color: '#0E0726', fontWeight: FONT.weights.bold, fontSize: 15 },
  secondaryRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    marginTop: SPACING.lg,
  },
  secondaryText: { color: COLORS.primary, fontWeight: FONT.weights.semibold, fontSize: 14 },
  signinRow: { flexDirection: 'row', justifyContent: 'center', marginTop: SPACING.md },
  signinPrompt: { color: COLORS.subtext, fontSize: 14 },
  signinAction: { color: COLORS.primary, fontWeight: FONT.weights.bold, fontSize: 14 },
  legalRow: { flexDirection: 'row', justifyContent: 'center', alignItems: 'center', gap: 10, marginTop: SPACING.lg },
  legalLink: { color: COLORS.subtext, fontSize: 12, fontWeight: FONT.weights.medium },
  legalDot: { color: COLORS.subtext },
  copyright: { textAlign: 'center', fontSize: 11, color: COLORS.subtext, marginTop: 8 },

  // ─── Auth hero ───
  hero: {
    paddingBottom: SPACING.lg,
    borderBottomLeftRadius: 28,
    borderBottomRightRadius: 28,
  },
  heroHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: SPACING.md,
    paddingTop: SPACING.sm,
  },
  profileBtn: { padding: 2, borderRadius: 999 },
  heroHello: { color: '#D7C7FB', fontSize: 14, fontWeight: FONT.weights.semibold, letterSpacing: 0.3 },
  heroHeadline: { fontSize: 36, fontWeight: FONT.weights.bold, lineHeight: 42, letterSpacing: -1, marginTop: 4 },
  heroHeadlineWhite: { color: '#fff' },
  heroHeadlineLavender: { color: '#C4B5FD' },
  heroSub: { color: '#D7C7FB', fontSize: 14, lineHeight: 20, marginTop: SPACING.sm },
  verifyChip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    alignSelf: 'flex-start',
    backgroundColor: 'rgba(252,211,77,0.12)',
    borderColor: 'rgba(252,211,77,0.4)',
    borderWidth: 1,
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 999,
    marginHorizontal: SPACING.md,
    marginTop: SPACING.md,
  },
  verifyChipText: { color: '#FCD34D', fontWeight: FONT.weights.bold, fontSize: 12 },
  emptyHero: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    backgroundColor: 'rgba(255,255,255,0.12)',
    borderRadius: 18,
    padding: 14,
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.18)',
  },
  emptyHeroIcon: {
    width: 40,
    height: 40,
    borderRadius: 12,
    backgroundColor: 'rgba(255,255,255,0.16)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  emptyHeroTitle: { color: '#fff', fontWeight: FONT.weights.bold, fontSize: 14 },
  emptyHeroSub: { color: '#D7C7FB', fontSize: 12, marginTop: 2 },

  // ─── Light list ───
  listHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: SPACING.sm },
  listTitle: { fontSize: 18, fontWeight: FONT.weights.bold, color: COLORS.text, letterSpacing: -0.3 },
  listSeeAll: { color: COLORS.primary, fontWeight: FONT.weights.bold, fontSize: 13 },
  listEmpty: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    padding: SPACING.md,
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.lg,
    borderWidth: 1,
    borderColor: COLORS.border,
  },
  listEmptyText: { color: COLORS.subtext, fontSize: 13 },
  groupRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    padding: SPACING.md,
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.lg,
    borderWidth: 1,
    borderColor: COLORS.border,
    marginBottom: SPACING.sm,
  },
  groupIcon: { width: 38, height: 38, borderRadius: 12, backgroundColor: COLORS.primaryLight, alignItems: 'center', justifyContent: 'center' },
  groupTitle: { fontSize: 15, fontWeight: FONT.weights.bold, color: COLORS.text },
  groupMeta: { fontSize: 12, color: COLORS.subtext, marginTop: 2 },
  memberStack: { flexDirection: 'row', alignItems: 'center', marginTop: 6 },
  memberStackItem: { borderWidth: 2, borderColor: COLORS.surface, borderRadius: 999 },
  memberStackMore: {
    minWidth: 24,
    height: 24,
    borderRadius: 12,
    backgroundColor: COLORS.primaryLight,
    paddingHorizontal: 6,
    alignItems: 'center',
    justifyContent: 'center',
  },
  memberStackMoreText: { color: COLORS.primary, fontSize: 10, fontWeight: FONT.weights.bold },
});

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
import { Receipt, Plus, Link2, QrCode, ChevronRight, Sparkles, LogOut, Gift } from 'lucide-react-native';
import { Button } from '../src/Button';
import { api } from '../src/api';
import { clearUser, loadUser, refreshUser } from '../src/session';
import { COLORS, FONT, RADIUS, SPACING } from '../src/theme';
import { StatusBadge } from '../src/StatusBadge';

export default function HomeScreen() {
  const router = useRouter();
  const [user, setUser] = useState<Awaited<ReturnType<typeof loadUser>>>(null);
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
      } catch (e) {
        console.log('Failed to load groups', e);
      }
    } else {
      setGroups([]);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const onRefresh = async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  };

  if (loading) {
    return (
      <SafeAreaView style={styles.center} testID="home-loading">
        <ActivityIndicator color={COLORS.primary} />
      </SafeAreaView>
    );
  }

  if (!user) {
    return (
      <SafeAreaView style={styles.container} testID="home-unauth">
        <ScrollView contentContainerStyle={styles.welcomeContent}>
          <View style={styles.welcomeIconWrap}>
            <Sparkles color={COLORS.primary} size={40} />
          </View>
          <Text style={styles.welcomeTitle}>GroupPay</Text>
          <Text style={styles.welcomeSub}>
            Split restaurant bills instantly. No more chasing friends for money.
          </Text>
          <View style={styles.welcomeFeatures}>
            {[
              { icon: <QrCode color={COLORS.primary} size={18} />, text: 'Share QR to split the bill' },
              { icon: <Receipt color={COLORS.primary} size={18} />, text: 'Claim items you ordered' },
              { icon: <Link2 color={COLORS.primary} size={18} />, text: 'Track repayments automatically' },
            ].map((f, i) => (
              <View key={i} style={styles.welcomeFeatureRow}>
                <View style={styles.welcomeFeatureIcon}>{f.icon}</View>
                <Text style={styles.welcomeFeatureText}>{f.text}</Text>
              </View>
            ))}
          </View>
          <Button
            title="Get Started"
            testID="home-get-started-btn"
            onPress={() => router.push('/auth')}
            style={{ marginTop: SPACING.lg }}
          />
        </ScrollView>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.container} edges={['top']} testID="home-auth">
      <ScrollView
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={COLORS.primary} />}
        contentContainerStyle={{ padding: SPACING.md, paddingBottom: SPACING.xxl }}
      >
        <View style={styles.header}>
          <View>
            <Text style={styles.hello} testID="home-hello">Hello,</Text>
            <Text style={styles.name}>{user.name}</Text>
            {!user.verified ? (
              <Text style={styles.verifyHint}>Verify phone to pay</Text>
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
          >
            <LogOut color={COLORS.text} size={18} />
          </TouchableOpacity>
        </View>

        <View style={styles.heroCard} testID="home-hero-card">
          <Text style={styles.heroLabel}>Active bills</Text>
          <Text style={styles.heroAmount}>{groups.filter(g => ((g as any).derived_status || g.status) !== 'settled' && g.status !== 'closed').length}</Text>
          <View style={styles.heroFooter}>
            <Text style={styles.heroFooterText}>
              {groups.filter(g => ((g as any).derived_status || (g.status === 'closed' ? 'settled' : '')) === 'settled').length} settled • {groups.length} total
            </Text>
          </View>
        </View>

        <View style={styles.actionsRow}>
          <TouchableOpacity
            testID="home-start-bill-btn"
            style={[styles.actionCard, styles.actionPrimary]}
            onPress={() => router.push('/create')}
            activeOpacity={0.9}
          >
            <View style={styles.actionIconWhite}>
              <Plus color={COLORS.primary} size={22} />
            </View>
            <Text style={styles.actionPrimaryTitle}>Start a Bill</Text>
            <Text style={styles.actionPrimarySub}>Scan or enter total</Text>
          </TouchableOpacity>

          <TouchableOpacity
            testID="home-join-bill-btn"
            style={[styles.actionCard, styles.actionSecondary]}
            onPress={() => router.push('/join/code')}
            activeOpacity={0.9}
          >
            <View style={styles.actionIcon}>
              <QrCode color={COLORS.primary} size={22} />
            </View>
            <Text style={styles.actionTitle}>Join a Bill</Text>
            <Text style={styles.actionSub}>Enter code or link</Text>
          </TouchableOpacity>
        </View>

        {/* C1: invite friends entry point */}
        <TouchableOpacity
          testID="home-invite-btn"
          style={styles.inviteCard}
          onPress={() => router.push('/invite')}
          activeOpacity={0.85}
        >
          <View style={styles.inviteIcon}>
            <Gift color={COLORS.primary} size={20} />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.inviteTitle}>Invite friends</Text>
            <Text style={styles.inviteSub}>
              {user.referral_code ? `Your code: ${user.referral_code}` : 'Share your code & track invites'}
            </Text>
          </View>
          <ChevronRight color={COLORS.subtext} size={18} />
        </TouchableOpacity>

        <Text style={styles.sectionTitle}>Recent Activity</Text>
        {groups.length === 0 ? (
          <View style={styles.empty}>
            <Receipt color={COLORS.border} size={48} />
            <Text style={styles.emptyText}>No bills yet</Text>
            <Text style={styles.emptySub}>Start your first bill to split with friends</Text>
          </View>
        ) : (
          <FlatList
            data={groups}
            keyExtractor={(g) => g.id}
            scrollEnabled={false}
            renderItem={({ item }) => (
              <TouchableOpacity
                testID={`home-group-${item.id}`}
                style={styles.groupRow}
                onPress={() => router.push(`/group/${item.id}`)}
                activeOpacity={0.7}
              >
                <View style={styles.groupIcon}>
                  <Receipt color={COLORS.primary} size={20} />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.groupTitle}>{item.title}</Text>
                  <Text style={styles.groupMeta}>
                    {item.member_count} {item.member_count === 1 ? 'member' : 'members'} • ${Number(item.total || 0).toFixed(2)}
                  </Text>
                </View>
                <StatusBadge status={(item as any).derived_status || (item.status === 'closed' ? 'settled' : item.status === 'paid' ? 'repaying' : 'contributing')} testID={`home-status-${item.id}`} />
                <ChevronRight color={COLORS.subtext} size={18} />
              </TouchableOpacity>
            )}
          />
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: COLORS.bg },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: COLORS.bg },
  welcomeContent: {
    padding: SPACING.lg,
    paddingTop: SPACING.xxl,
    flexGrow: 1,
  },
  welcomeIconWrap: {
    width: 72,
    height: 72,
    borderRadius: 18,
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
  welcomeFeatures: { marginTop: SPACING.xl, gap: SPACING.md },
  welcomeFeatureRow: { flexDirection: 'row', alignItems: 'center', gap: SPACING.md },
  welcomeFeatureIcon: {
    width: 36,
    height: 36,
    borderRadius: 10,
    backgroundColor: COLORS.primaryLight,
    alignItems: 'center',
    justifyContent: 'center',
  },
  welcomeFeatureText: { fontSize: FONT.sizes.md, color: COLORS.text, flex: 1 },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    marginBottom: SPACING.lg,
  },
  hello: { color: COLORS.subtext, fontSize: FONT.sizes.sm },
  name: { color: COLORS.text, fontSize: FONT.sizes.xxl, fontWeight: FONT.weights.bold },
  verifyHint: { color: COLORS.warning, fontSize: FONT.sizes.xs, marginTop: 2, fontWeight: FONT.weights.medium },
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
  heroCard: {
    backgroundColor: COLORS.text,
    borderRadius: RADIUS.xl,
    padding: SPACING.lg,
    marginBottom: SPACING.lg,
  },
  heroLabel: { color: '#9CA3AF', fontSize: FONT.sizes.sm, textTransform: 'uppercase', letterSpacing: 1 },
  heroAmount: {
    color: '#fff',
    fontSize: 56,
    fontWeight: FONT.weights.heavy,
    marginTop: 4,
    letterSpacing: -2,
  },
  heroFooter: { marginTop: SPACING.md },
  heroFooterText: { color: '#9CA3AF', fontSize: FONT.sizes.sm },
  actionsRow: { flexDirection: 'row', gap: SPACING.md, marginBottom: SPACING.lg },
  inviteCard: { flexDirection: 'row', alignItems: 'center', gap: SPACING.md, padding: SPACING.md, marginBottom: SPACING.lg, backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.primary, borderRadius: RADIUS.md },
  inviteIcon: { width: 40, height: 40, borderRadius: 20, backgroundColor: COLORS.primaryLight, alignItems: 'center', justifyContent: 'center' },
  inviteTitle: { fontSize: FONT.sizes.md, fontWeight: FONT.weights.bold, color: COLORS.text },
  inviteSub: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: 2 },
  actionCard: {
    flex: 1,
    borderRadius: RADIUS.lg,
    padding: SPACING.md,
    minHeight: 130,
  },
  actionPrimary: { backgroundColor: COLORS.primary },
  actionSecondary: {
    backgroundColor: COLORS.surface,
    borderWidth: 1,
    borderColor: COLORS.border,
  },
  actionIcon: {
    width: 40,
    height: 40,
    borderRadius: 10,
    backgroundColor: COLORS.primaryLight,
    alignItems: 'center',
    justifyContent: 'center',
  },
  actionIconWhite: {
    width: 40,
    height: 40,
    borderRadius: 10,
    backgroundColor: '#fff',
    alignItems: 'center',
    justifyContent: 'center',
  },
  actionPrimaryTitle: {
    marginTop: SPACING.md,
    color: '#fff',
    fontSize: FONT.sizes.lg,
    fontWeight: FONT.weights.bold,
  },
  actionPrimarySub: { color: '#E0E7FF', fontSize: FONT.sizes.xs, marginTop: 2 },
  actionTitle: {
    marginTop: SPACING.md,
    color: COLORS.text,
    fontSize: FONT.sizes.lg,
    fontWeight: FONT.weights.bold,
  },
  actionSub: { color: COLORS.subtext, fontSize: FONT.sizes.xs, marginTop: 2 },
  sectionTitle: {
    fontSize: FONT.sizes.lg,
    fontWeight: FONT.weights.bold,
    color: COLORS.text,
    marginBottom: SPACING.md,
  },
  empty: {
    alignItems: 'center',
    paddingVertical: SPACING.xl,
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.lg,
    borderWidth: 1,
    borderColor: COLORS.border,
  },
  emptyText: {
    marginTop: SPACING.md,
    fontSize: FONT.sizes.md,
    fontWeight: FONT.weights.semibold,
    color: COLORS.text,
  },
  emptySub: { marginTop: 4, fontSize: FONT.sizes.sm, color: COLORS.subtext },
  groupRow: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: COLORS.surface,
    padding: SPACING.md,
    borderRadius: RADIUS.md,
    marginBottom: SPACING.sm,
    borderWidth: 1,
    borderColor: COLORS.border,
    gap: SPACING.md,
  },
  groupIcon: {
    width: 40,
    height: 40,
    borderRadius: 10,
    backgroundColor: COLORS.primaryLight,
    alignItems: 'center',
    justifyContent: 'center',
  },
  groupTitle: { color: COLORS.text, fontWeight: FONT.weights.semibold, fontSize: FONT.sizes.md },
  groupMeta: { color: COLORS.subtext, fontSize: FONT.sizes.xs, marginTop: 2 },
  statusPill: {
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: RADIUS.pill,
  },
  statusPillText: { fontSize: FONT.sizes.xs, fontWeight: FONT.weights.semibold },
  statusOpen: { backgroundColor: COLORS.warningLight },
  statusPaid: { backgroundColor: COLORS.primaryLight },
  statusClosed: { backgroundColor: COLORS.successLight },
});

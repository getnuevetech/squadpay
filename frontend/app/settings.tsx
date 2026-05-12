/**
 * Settings stub screen — hub for profile, credits, legal, sign out, and (when
 * applicable) admin entry. Designed for the bottom tab bar destination.
 */
import { useEffect, useState } from 'react';
import {
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
  ScrollView,
  Alert,
  Platform,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useRouter } from 'expo-router';
import {
  ArrowLeft,
  Wallet,
  Gift,
  ShieldCheck,
  FileText,
  HelpCircle,
  LogOut,
  ChevronRight,
  Lock,
  ShieldAlert,
} from 'lucide-react-native';
import { COLORS, FONT, RADIUS, SPACING } from '../src/theme';
import { refreshUser, clearUser } from '../src/session';
import { api } from '../src/api';
import { formatUid } from '../src/ids';
import { AvatarRing } from '../src/components/AvatarRing';
import { BottomTabBar } from '../src/components/redesign/BottomTabBar';
import { SquadPayMark } from '../src/components/redesign/SquadPayMark';

type Row = {
  key: string;
  label: string;
  sub?: string;
  icon: React.ComponentType<{ size: number; color: string }>;
  onPress: () => void;
  destructive?: boolean;
  hidden?: boolean;
};

export default function SettingsScreen() {
  const router = useRouter();
  const [user, setUser] = useState<Awaited<ReturnType<typeof refreshUser>>>(null);
  const [features, setFeatures] = useState<{ credits_enabled: boolean; invite_friends_enabled: boolean }>({ credits_enabled: true, invite_friends_enabled: true });

  useEffect(() => {
    (async () => {
      const u = await refreshUser();
      if (!u) {
        router.replace('/');
        return;
      }
      setUser(u);
      api.getAppFeatures().then(setFeatures).catch(() => {});
    })();
  }, [router]);

  const onLogout = async () => {
    const doLogout = async () => {
      try { await api.logout(user?.id || ''); } catch {}
      await clearUser();
      router.replace('/');
    };
    if (Platform.OS === 'web') {
      doLogout();
    } else {
      Alert.alert('Sign out?', 'You will be signed out of SquadPay on this device.', [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Sign out', style: 'destructive', onPress: doLogout },
      ]);
    }
  };

  const rows: Row[] = [
    {
      key: 'credits',
      label: 'Credits & rewards',
      sub: 'See your pending and available credits.',
      icon: Wallet,
      onPress: () => router.push('/credits' as any),
      // June 2025 — always visible now that the credit-rules engine ships
      // pending/available balances per user.
    },
    {
      key: 'invite',
      label: 'Invite friends',
      sub: 'Share your code, both earn credits.',
      icon: Gift,
      onPress: () => router.push('/invite'),
      hidden: !features.invite_friends_enabled,
    },
    {
      key: 'verify',
      label: 'Verify phone',
      sub: 'Required to pay or repay.',
      icon: ShieldAlert,
      onPress: () => router.push(`/auth?mode=verify&user_id=${user?.id || ''}`),
      hidden: !!user?.verified,
    },
    {
      key: 'support',
      label: 'Support',
      sub: 'FAQ and contact options.',
      icon: HelpCircle,
      onPress: () => router.push('/legal/support'),
    },
    {
      key: 'privacy',
      label: 'Privacy Policy',
      icon: ShieldCheck,
      onPress: () => router.push('/legal/privacy'),
    },
    {
      key: 'terms',
      label: 'Terms & Conditions',
      icon: FileText,
      onPress: () => router.push('/legal/terms'),
    },
    {
      key: 'logout',
      label: 'Sign out',
      icon: LogOut,
      onPress: onLogout,
      destructive: true,
    },
  ];

  return (
    <SafeAreaView style={styles.container} edges={['top']} testID="settings-screen">
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.replace('/')} style={styles.iconBtn} activeOpacity={0.7} testID="settings-home-btn">
          <ArrowLeft size={20} color={COLORS.text} />
        </TouchableOpacity>
        <SquadPayMark size={28} />
        <View style={{ width: 40 }} />
      </View>

      <ScrollView contentContainerStyle={{ padding: SPACING.md, paddingBottom: 120 }}>
        <Text style={styles.heading}>Settings</Text>
        <Text style={styles.subheading}>Manage your account and preferences.</Text>

        {/* Profile card */}
        <View style={styles.profile}>
          <AvatarRing name={user?.name || '?'} seed={user?.id || 'me'} size={56} />
          <View style={{ flex: 1, marginLeft: 12 }}>
            <Text style={styles.profileName}>{user?.name || '—'}</Text>
            <Text style={styles.profileMeta}>{user?.phone || 'no phone on file'}</Text>
            {user?.id ? (
              <Text style={styles.profileUid} testID="settings-uid" selectable>
                {formatUid(user.id)}
              </Text>
            ) : null}
            <Text style={[styles.profileBadge, user?.verified ? styles.verifiedOk : styles.verifiedNo]}>
              {user?.verified ? '● Verified' : '● Unverified'}
            </Text>
          </View>
        </View>

        {rows.filter(r => !r.hidden).map((r) => {
          const Icon = r.icon;
          return (
            <TouchableOpacity
              key={r.key}
              onPress={r.onPress}
              activeOpacity={0.85}
              style={[styles.row, r.destructive && styles.rowDestructive]}
              testID={`settings-row-${r.key}`}
            >
              <View style={[styles.rowIcon, r.destructive ? styles.rowIconDanger : styles.rowIconNormal]}>
                <Icon size={18} color={r.destructive ? COLORS.danger : COLORS.primary} />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={[styles.rowLabel, r.destructive && styles.rowLabelDanger]}>{r.label}</Text>
                {r.sub ? <Text style={styles.rowSub}>{r.sub}</Text> : null}
              </View>
              {!r.destructive ? <ChevronRight size={16} color={COLORS.subtext} /> : null}
            </TouchableOpacity>
          );
        })}

        <Text style={styles.copyright}>© 2026 — SquadPay by NueveTech</Text>
      </ScrollView>
      <BottomTabBar active="settings" />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: COLORS.bg },
  header: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: SPACING.md, paddingTop: SPACING.sm },
  iconBtn: { width: 40, height: 40, borderRadius: 20, alignItems: 'center', justifyContent: 'center' },
  heading: { fontSize: 28, fontWeight: FONT.weights.bold, color: COLORS.text, letterSpacing: -0.5 },
  subheading: { fontSize: FONT.sizes.sm, color: COLORS.subtext, marginTop: 4, marginBottom: SPACING.md },
  profile: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: SPACING.md,
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.lg,
    borderWidth: 1,
    borderColor: COLORS.border,
    marginBottom: SPACING.md,
  },
  profileName: { fontSize: FONT.sizes.lg, fontWeight: FONT.weights.bold, color: COLORS.text },
  profileMeta: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: 2 },
  profileUid: {
    fontSize: 11,
    color: COLORS.subtext,
    marginTop: 2,
    fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace',
    letterSpacing: 0.6,
  },
  profileBadge: { fontSize: 11, fontWeight: FONT.weights.bold, marginTop: 4 },
  verifiedOk: { color: COLORS.success },
  verifiedNo: { color: COLORS.warning },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    padding: SPACING.md,
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.lg,
    borderWidth: 1,
    borderColor: COLORS.border,
    marginBottom: 8,
  },
  rowDestructive: { borderColor: COLORS.dangerLight, backgroundColor: COLORS.dangerLight },
  rowIcon: { width: 38, height: 38, borderRadius: 12, alignItems: 'center', justifyContent: 'center' },
  rowIconNormal: { backgroundColor: COLORS.primaryLight },
  rowIconDanger: { backgroundColor: '#fff' },
  rowLabel: { fontSize: FONT.sizes.md, fontWeight: FONT.weights.semibold, color: COLORS.text },
  rowLabelDanger: { color: COLORS.danger },
  rowSub: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: 2 },
  copyright: { textAlign: 'center', fontSize: 11, color: COLORS.subtext, marginTop: SPACING.lg },
});

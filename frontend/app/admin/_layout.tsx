import { Stack, useRouter, usePathname } from 'expo-router';
import { useEffect, useState } from 'react';
import { View, Text, TouchableOpacity, StyleSheet, Platform, ActivityIndicator } from 'react-native';
import { LayoutDashboard, ScrollText, Users, LogOut, Shield, UserCog, Receipt, Gift, Plug, Wallet, RefreshCw } from 'lucide-react-native';
import { adminApi, AdminProfile, getProfile, getToken, clearSession } from '../../src/adminApi';
import { COLORS, FONT, RADIUS, SPACING } from '../../src/theme';

const NAV_ITEMS = [
  { href: '/admin/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { href: '/admin/users', label: 'Users', icon: UserCog },
  { href: '/admin/groups', label: 'Groups', icon: Receipt },
  { href: '/admin/referrals', label: 'Referrals', icon: Gift },
  { href: '/admin/integrations', label: 'Integrations', icon: Plug },
  { href: '/admin/reconciliations', label: 'Reconciliations', icon: RefreshCw },
  { href: '/admin/master-account', label: 'Master Account', icon: Wallet },
  { href: '/admin/audit', label: 'Audit log', icon: ScrollText },
  { href: '/admin/admins', label: 'Admins', icon: Users, requireRole: ['super_admin'] as const },
];

function AdminSidebar({ profile, onLogout }: { profile: AdminProfile | null; onLogout: () => void }) {
  const router = useRouter();
  const pathname = usePathname();
  return (
    <View style={styles.sidebar}>
      <View style={styles.sidebarHeader}>
        <Shield size={20} color={COLORS.primary} />
        <Text style={styles.sidebarTitle}>GroupPay Admin</Text>
      </View>
      <View style={{ flex: 1, gap: 4 }}>
        {NAV_ITEMS.filter((it) => !it.requireRole || (profile && (it.requireRole as readonly string[]).includes(profile.role))).map((it) => {
          const Icon = it.icon;
          const active = pathname?.startsWith(it.href);
          return (
            <TouchableOpacity
              key={it.href}
              testID={`admin-nav-${it.label.toLowerCase().replace(/\s+/g,'-')}`}
              onPress={() => router.replace(it.href as any)}
              style={[styles.navItem, active && styles.navItemActive]}
              activeOpacity={0.7}
            >
              <Icon size={16} color={active ? '#fff' : COLORS.subtext} />
              <Text style={[styles.navLabel, active && { color: '#fff' }]}>{it.label}</Text>
            </TouchableOpacity>
          );
        })}
      </View>
      <View style={styles.sidebarFooter}>
        <Text style={styles.profileName} numberOfLines={1}>{profile?.name || '—'}</Text>
        <Text style={styles.profileMeta}>{profile?.email}</Text>
        <Text style={styles.profileRole}>{profile?.role}</Text>
        <TouchableOpacity testID="admin-logout" onPress={onLogout} style={styles.logoutBtn} activeOpacity={0.85}>
          <LogOut size={14} color={COLORS.danger} />
          <Text style={styles.logoutText}>Sign out</Text>
        </TouchableOpacity>
      </View>
    </View>
  );
}

export default function AdminLayout() {
  const router = useRouter();
  const pathname = usePathname();
  const [profile, setProfile] = useState<AdminProfile | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    (async () => {
      const onLogin = pathname === '/admin/login' || pathname === '/admin';
      const token = await getToken();
      if (!token) {
        if (!onLogin) router.replace('/admin/login');
        setReady(true);
        return;
      }
      try {
        const me = await adminApi.me();
        setProfile(me);
        if (onLogin) router.replace('/admin/dashboard');
      } catch {
        await clearSession();
        if (!onLogin) router.replace('/admin/login');
      } finally {
        setReady(true);
      }
    })();
  }, [pathname]);

  if (!ready) {
    return (
      <View style={[styles.shell, styles.center]}>
        <ActivityIndicator color={COLORS.primary} />
      </View>
    );
  }

  // Login route renders without sidebar shell
  if (pathname === '/admin/login' || !profile) {
    return (
      <Stack
        screenOptions={{
          headerShown: false,
          contentStyle: { backgroundColor: COLORS.bg },
        }}
      />
    );
  }

  const onLogout = async () => {
    await adminApi.logout();
    setProfile(null);
    router.replace('/admin/login');
  };

  return (
    <View style={styles.shell}>
      <AdminSidebar profile={profile} onLogout={onLogout} />
      <View style={styles.content}>
        <Stack
          screenOptions={{
            headerShown: false,
            contentStyle: { backgroundColor: COLORS.bg },
          }}
        />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  shell: {
    flex: 1,
    backgroundColor: COLORS.bg,
    flexDirection: Platform.OS === 'web' ? 'row' : 'column',
    minHeight: '100%' as any,
  },
  center: { alignItems: 'center', justifyContent: 'center' },
  sidebar: {
    width: Platform.OS === 'web' ? 240 : '100%',
    backgroundColor: COLORS.surface,
    borderRightWidth: 1,
    borderRightColor: COLORS.border,
    paddingHorizontal: SPACING.md,
    paddingVertical: SPACING.lg,
    gap: SPACING.md,
  },
  sidebarHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    paddingBottom: SPACING.md,
    borderBottomWidth: 1,
    borderBottomColor: COLORS.border,
  },
  sidebarTitle: { fontSize: FONT.sizes.md, fontWeight: FONT.weights.bold, color: COLORS.text },
  navItem: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    paddingHorizontal: SPACING.md,
    paddingVertical: 10,
    borderRadius: RADIUS.md,
  },
  navItemActive: { backgroundColor: COLORS.primary },
  navLabel: { fontSize: FONT.sizes.sm, color: COLORS.subtext, fontWeight: FONT.weights.medium },
  sidebarFooter: {
    borderTopWidth: 1,
    borderTopColor: COLORS.border,
    paddingTop: SPACING.md,
    gap: 2,
  },
  profileName: { fontSize: FONT.sizes.sm, color: COLORS.text, fontWeight: FONT.weights.semibold },
  profileMeta: { fontSize: FONT.sizes.xs, color: COLORS.subtext },
  profileRole: {
    fontSize: 10,
    color: COLORS.primary,
    backgroundColor: COLORS.primaryLight,
    alignSelf: 'flex-start',
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: RADIUS.pill,
    marginTop: 4,
    fontWeight: FONT.weights.bold,
    textTransform: 'uppercase',
  },
  logoutBtn: { flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: SPACING.sm },
  logoutText: { color: COLORS.danger, fontSize: FONT.sizes.sm, fontWeight: FONT.weights.medium },
  content: { flex: 1, padding: SPACING.lg },
});

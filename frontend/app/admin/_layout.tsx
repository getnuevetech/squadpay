import { Stack, useRouter, usePathname } from 'expo-router';
import { useEffect, useMemo, useState } from 'react';
import { View, Text, TouchableOpacity, StyleSheet, Platform, ActivityIndicator, ScrollView } from 'react-native';
import {
  LayoutDashboard, ScrollText, Users, LogOut, Shield, UserCog, Receipt, Gift,
  Plug, Wallet, RefreshCw, Lock, BarChart3, FileText, KeyRound, Percent,
  Megaphone, MessageSquare, Coins, Inbox, ShieldCheck, ShieldAlert, CircleDollarSign, Layers,
} from 'lucide-react-native';
import { adminApi, AdminProfile, getProfile, getToken, clearSession } from '../../src/adminApi';
import { COLORS, FONT, RADIUS, SPACING } from '../../src/theme';
import { AdminSearchBar } from '../../src/components/admin/AdminSearchBar';

// ---------------------------------------------------------------------------
// Module-key → icon mapping. The labels + paths now come from the backend
// (/api/admin/me/modules), but icons must be bundled with the frontend.
// ---------------------------------------------------------------------------
const ICON_BY_KEY: Record<string, any> = {
  dashboard: LayoutDashboard,
  analytics: BarChart3,
  users: UserCog,
  squads: Receipt,
  customer_service: Inbox,
  referrals: Gift,
  integrations: Plug,
  notifications: Megaphone,
  bulk_sms: MessageSquare,
  credit_rules: Coins,
  platform_fees: Percent,
  income_fees: CircleDollarSign,
  reconciliations: RefreshCw,
  master_account: Wallet,
  security: Lock,
  audit: ScrollText,
  legal_pages: FileText,
  admins: Users,
  access: ShieldCheck,
  capabilities: Layers,
};

type ModuleEntry = {
  key: string; label: string; group: string; path: string; sensitive: boolean;
};

// ---------------------------------------------------------------------------
// Legacy NAV_ITEMS export (kept for AdminSearchBar fuzzy nav matching).
// We hand it the same shape it expects, derived from the modules response.
// ---------------------------------------------------------------------------
let LATEST_NAV_ITEMS: Array<{ href: string; label: string; icon: any; key?: string }> = [];
export const NAV_ITEMS = new Proxy([] as any, {
  get(_t, p) {
    // Always re-read so consumers see the freshest list.
    return (LATEST_NAV_ITEMS as any)[p];
  },
});

function AdminSidebar({
  profile,
  modules,
  groupOrder,
  onLogout,
}: {
  profile: AdminProfile | null;
  modules: ModuleEntry[];
  groupOrder: string[];
  onLogout: () => void;
}) {
  const router = useRouter();
  const pathname = usePathname();

  // Group the modules by their .group attribute, preserving registry order.
  const grouped = useMemo(() => {
    const out: Record<string, ModuleEntry[]> = {};
    for (const g of groupOrder) out[g] = [];
    for (const m of modules) {
      if (!out[m.group]) out[m.group] = [];
      out[m.group].push(m);
    }
    return out;
  }, [modules, groupOrder]);

  return (
    <View style={styles.sidebar}>
      <View style={styles.sidebarHeader}>
        <Shield size={20} color={COLORS.primary} />
        <Text style={styles.sidebarTitle}>SquadPay Admin</Text>
      </View>
      <ScrollView
        style={styles.navScroll}
        contentContainerStyle={{ paddingBottom: SPACING.md }}
        showsVerticalScrollIndicator={false}
      >
        {groupOrder.map((g) => {
          const items = grouped[g] || [];
          if (items.length === 0) return null;
          return (
            <View key={g} style={styles.navGroup}>
              <Text style={styles.navGroupTitle}>{g}</Text>
              {items.map((it) => {
                const Icon = ICON_BY_KEY[it.key] || LayoutDashboard;
                const active = pathname?.startsWith(it.path);
                return (
                  <TouchableOpacity
                    key={it.key}
                    testID={`admin-nav-${it.key}`}
                    onPress={() => router.replace(it.path as any)}
                    style={[styles.navItem, active && styles.navItemActive]}
                    activeOpacity={0.7}
                  >
                    <Icon size={16} color={active ? '#fff' : COLORS.subtext} />
                    <Text style={[styles.navLabel, active && { color: '#fff' }]} numberOfLines={1}>
                      {it.label}
                    </Text>
                    {it.sensitive ? (
                      <ShieldAlert
                        size={11}
                        color={active ? '#fff' : COLORS.warning}
                        style={{ marginLeft: 'auto' }}
                      />
                    ) : null}
                  </TouchableOpacity>
                );
              })}
            </View>
          );
        })}
      </ScrollView>
      <View style={styles.sidebarFooter}>
        <Text style={styles.profileName} numberOfLines={1}>{profile?.name || '—'}</Text>
        <Text style={styles.profileMeta}>{profile?.email}</Text>
        <Text style={styles.profileRole}>{profile?.role}</Text>
        <TouchableOpacity
          testID="admin-change-password-link"
          onPress={() => router.push('/admin/change-password')}
          style={styles.changePwdBtn}
          activeOpacity={0.85}
        >
          <KeyRound size={14} color={COLORS.primary} />
          <Text style={styles.changePwdText}>Change password</Text>
        </TouchableOpacity>
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
  const [modules, setModules] = useState<ModuleEntry[]>([]);
  const [groupOrder, setGroupOrder] = useState<string[]>(
    ['Overview', 'Operations', 'Marketing', 'Finance', 'System'],
  );

  useEffect(() => {
    (async () => {
      const onLogin =
        pathname === '/admin/login' ||
        pathname === '/admin' ||
        pathname === '/admin/forgot-password' ||
        pathname === '/admin/reset-password';
      const token = await getToken();
      if (!token) {
        if (!onLogin) router.replace('/admin/login');
        setReady(true);
        return;
      }
      try {
        const me = await adminApi.me();
        setProfile(me);
        try {
          const mods = await adminApi.myModules();
          setModules(mods.modules);
          setGroupOrder(mods.group_order || groupOrder);
          // Update legacy NAV_ITEMS proxy data for AdminSearchBar.
          LATEST_NAV_ITEMS = mods.modules.map((m) => ({
            href: m.path,
            label: m.label,
            icon: ICON_BY_KEY[m.key] || LayoutDashboard,
            key: m.key,
          }));
        } catch {
          // Non-fatal — sidebar simply stays empty until next reload.
        }
        if (pathname === '/admin/login' || pathname === '/admin') router.replace('/admin/dashboard');
      } catch {
        await clearSession();
        if (!onLogin) router.replace('/admin/login');
      } finally {
        setReady(true);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname]);

  if (!ready) {
    return (
      <View style={[styles.shell, styles.center]}>
        <ActivityIndicator color={COLORS.primary} />
      </View>
    );
  }

  const isPublicRoute =
    pathname === '/admin/login' ||
    pathname === '/admin/forgot-password' ||
    pathname === '/admin/reset-password';
  if (isPublicRoute || !profile) {
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
      <AdminSidebar
        profile={profile}
        modules={modules}
        groupOrder={groupOrder}
        onLogout={onLogout}
      />
      <View style={styles.content}>
        <View style={styles.topbar}>
          <View style={{ flex: 1, maxWidth: 520 }}>
            <AdminSearchBar
              navItems={modules.map((m) => ({
                href: m.path,
                label: m.label,
                icon: ICON_BY_KEY[m.key] || LayoutDashboard,
              }))}
            />
          </View>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
            <Text style={styles.topbarEmail} numberOfLines={1}>{profile.email}</Text>
            <TouchableOpacity onPress={onLogout} style={styles.topbarLogout} activeOpacity={0.7} testID="admin-topbar-logout">
              <LogOut size={14} color={COLORS.danger} />
            </TouchableOpacity>
          </View>
        </View>
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
    gap: SPACING.sm,
    flexDirection: 'column',
    height: Platform.OS === 'web' ? ('100vh' as any) : '100%',
  },
  navScroll: { flex: 1, marginHorizontal: -SPACING.xs },
  navGroup: { marginBottom: SPACING.sm },
  navGroupTitle: {
    fontSize: 10,
    color: COLORS.subtext,
    fontWeight: FONT.weights.bold,
    textTransform: 'uppercase',
    letterSpacing: 0.8,
    paddingHorizontal: SPACING.md,
    paddingVertical: 4,
    marginTop: 4,
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
    paddingVertical: 8,
    borderRadius: RADIUS.md,
  },
  navItemActive: { backgroundColor: COLORS.primary },
  navLabel: { fontSize: FONT.sizes.sm, color: COLORS.subtext, fontWeight: FONT.weights.medium, flex: 1 },
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
  changePwdBtn: { flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: SPACING.sm },
  changePwdText: { color: COLORS.primary, fontSize: FONT.sizes.sm, fontWeight: FONT.weights.medium },
  content: { flex: 1, padding: SPACING.lg },
  topbar: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: SPACING.md,
    paddingHorizontal: SPACING.lg,
    paddingVertical: SPACING.sm,
    borderBottomWidth: 1,
    borderBottomColor: COLORS.border,
    backgroundColor: COLORS.surface,
    zIndex: 50,
  },
  topbarEmail: { color: COLORS.subtext, fontSize: FONT.sizes.xs, fontWeight: FONT.weights.semibold, maxWidth: 220 },
  topbarLogout: { width: 32, height: 32, borderRadius: 16, alignItems: 'center', justifyContent: 'center', backgroundColor: COLORS.dangerLight },
});

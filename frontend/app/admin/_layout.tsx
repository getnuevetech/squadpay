import { Stack, useRouter, usePathname } from 'expo-router';
import { useEffect, useMemo, useState } from 'react';
import { View, Text, TouchableOpacity, StyleSheet, Platform, ActivityIndicator, ScrollView } from 'react-native';
import {
  LayoutDashboard, ScrollText, Users, LogOut, Shield, UserCog, Receipt, Gift,
  Plug, Wallet, RefreshCw, Lock, BarChart3, FileText, KeyRound, Percent,
  Megaphone, MessageSquare, Coins, Inbox, ShieldCheck, ShieldAlert, CircleDollarSign, Layers, Hash, BellRing,
} from 'lucide-react-native';
import { adminApi, AdminProfile, getProfile, getToken, clearSession, adminActivityApi } from '../../src/adminApi';
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
  notification_config: BellRing,
  bulk_sms: MessageSquare,
  credit_rules: Coins,
  platform_fees: Percent,
  income_fees: CircleDollarSign,
  reconciliations: RefreshCw,
  master_account: Wallet,
  security: Lock,
  audit: ScrollText,
  legal_pages: FileText,
  cms_pages: FileText,
  ocr_config: ScrollText,
  wallets: Wallet,
  join_code: Hash,
  admins: Users,
  access: ShieldCheck,
  capabilities: Layers,
  gateways: Plug,
};

type ModuleEntry = {
  key: string; label: string; group: string; path: string; sensitive: boolean;
};

// ---------------------------------------------------------------------------
// Static FALLBACK module list (June 2025).
//
// Used when /api/admin/me/modules fails (network blip, 502 from CDN, CORS in
// a misconfigured deployment, etc). Keeps the sidebar usable instead of
// rendering blank. Permission checks still happen on the BACKEND, so even
// if a non-super-admin sees these links here, the backend will 403 on entry.
//
// Keep this list in sync with the master MODULES list in
// /app/backend/admin_modules.py — only label/path/group are mirrored, not
// the role assignments.
// ---------------------------------------------------------------------------
const FALLBACK_MODULES: ModuleEntry[] = [
  { key: 'dashboard',         label: 'Dashboard',        group: 'Overview',   path: '/admin/dashboard',         sensitive: false },
  { key: 'analytics',         label: 'Analytics',        group: 'Overview',   path: '/admin/analytics',         sensitive: false },
  { key: 'users',             label: 'Users',            group: 'Operations', path: '/admin/users',             sensitive: false },
  { key: 'squads',            label: 'Squads',           group: 'Operations', path: '/admin/squads',            sensitive: false },
  { key: 'customer_service',  label: 'Customer Service', group: 'Operations', path: '/admin/customer-service',  sensitive: false },
  { key: 'notifications',     label: 'Notifications',    group: 'Marketing',  path: '/admin/notifications',     sensitive: false },
  { key: 'notification_config', label: 'Notification Config', group: 'Marketing', path: '/admin/notification-config', sensitive: false },
  { key: 'bulk_sms',          label: 'Bulk SMS',         group: 'Marketing',  path: '/admin/bulk-sms',          sensitive: false },
  { key: 'credit_rules',      label: 'Credit Rules',     group: 'Marketing',  path: '/admin/credit-rules',      sensitive: false },
  { key: 'referrals',         label: 'Referrals',        group: 'Marketing',  path: '/admin/referrals',         sensitive: false },
  { key: 'platform_fees',     label: 'Platform Fees',    group: 'Finance',    path: '/admin/platform-fees',     sensitive: true  },
  { key: 'income_fees',       label: 'Income & Fees',    group: 'Finance',    path: '/admin/income-fees',       sensitive: true  },
  { key: 'master_account',    label: 'Master Account',   group: 'Finance',    path: '/admin/master-account',    sensitive: true  },
  { key: 'reconciliations',   label: 'Reconciliations',  group: 'Finance',    path: '/admin/reconciliations',   sensitive: false },
  { key: 'integrations',      label: 'Integrations',     group: 'System',     path: '/admin/integrations',      sensitive: true  },
  { key: 'security',          label: 'Security',         group: 'System',     path: '/admin/security',          sensitive: true  },
  { key: 'audit',             label: 'Audit Log',        group: 'System',     path: '/admin/audit',             sensitive: false },
  { key: 'legal_pages',       label: 'Legal Pages',      group: 'System',     path: '/admin/legal-pages',       sensitive: false },
  { key: 'cms_pages',         label: 'CMS Pages',        group: 'System',     path: '/admin/cms-pages',         sensitive: false },
  { key: 'ocr_config',        label: 'Receipt OCR',      group: 'System',     path: '/admin/ocr-config',        sensitive: false },
  { key: 'wallets',           label: 'Wallets',          group: 'System',     path: '/admin/wallets',           sensitive: false },
  { key: 'join_code',         label: 'Join Codes',       group: 'System',     path: '/admin/join-code-config',  sensitive: false },
  { key: 'admins',            label: 'Admins',           group: 'System',     path: '/admin/admins',            sensitive: true  },
  { key: 'access',            label: 'Access Roles',     group: 'System',     path: '/admin/access',            sensitive: true  },
  { key: 'capabilities',      label: 'Capabilities',     group: 'System',     path: '/admin/capabilities',      sensitive: true  },
  { key: 'gateways',          label: 'Payment Gateways', group: 'System',     path: '/admin/gateways',          sensitive: true  },
];

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
  const [modulesError, setModulesError] = useState<string | null>(null);
  const [modulesLoading, setModulesLoading] = useState(false);

  // Phase 5b+ — split out modules fetching so we can retry it independently
  // from the profile/auth check. The earlier `try/catch with empty body` hid
  // network/CORS/server errors and left the sidebar mysteriously blank.
  //
  // P2 (June 2025) — Auto-retry-with-backoff. FastAPI's hot-reload window
  // (~1.5–3s during dev) briefly returns 404 for /api/admin/me/modules,
  // which made the sidebar flip to the fallback list and surface a
  // confusing red banner. We now silently retry transient 404/502/503
  // errors up to 4 times with exponential backoff (300ms→600→1200→2400),
  // and only show the error UI if every attempt fails.
  const TRANSIENT_STATUSES = [0, 404, 502, 503, 504];
  const fetchModulesWithRetry = async (maxAttempts = 4): Promise<{ ok: boolean; lastErr?: any }> => {
    let lastErr: any = null;
    for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
      try {
        const mods = await adminApi.myModules();
        setModules(mods.modules);
        setGroupOrder(mods.group_order || groupOrder);
        LATEST_NAV_ITEMS = mods.modules.map((m) => ({
          href: m.path,
          label: m.label,
          icon: ICON_BY_KEY[m.key] || LayoutDashboard,
          key: m.key,
        }));
        setModulesError(null);
        return { ok: true };
      } catch (e: any) {
        lastErr = e;
        const status = Number(e?.status || e?.response?.status || 0);
        const isTransient = TRANSIENT_STATUSES.includes(status) || /Network|Failed to fetch|timeout/i.test(String(e?.message || ''));
        if (attempt < maxAttempts && isTransient) {
          // Exponential backoff with jitter
          const delay = 300 * Math.pow(2, attempt - 1) + Math.floor(Math.random() * 150);
          // eslint-disable-next-line no-console
          console.warn(`[admin/sidebar] modules fetch failed (status=${status}, attempt=${attempt}/${maxAttempts}). Retrying in ${delay}ms…`);
          await new Promise((r) => setTimeout(r, delay));
          continue;
        }
        break;
      }
    }
    return { ok: false, lastErr };
  };

  const fetchModules = async () => {
    setModulesLoading(true);
    const { ok, lastErr } = await fetchModulesWithRetry();
    if (!ok) {
      // eslint-disable-next-line no-console
      console.error('[admin/sidebar] /admin/me/modules failed after retries:', lastErr);
      setModulesError(lastErr?.message || String(lastErr) || 'Unknown error');
      if (modules.length === 0) {
        setModules(FALLBACK_MODULES);
        LATEST_NAV_ITEMS = FALLBACK_MODULES.map((m) => ({
          href: m.path,
          label: m.label,
          icon: ICON_BY_KEY[m.key] || LayoutDashboard,
          key: m.key,
        }));
      }
    }
    setModulesLoading(false);
  };

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
        // C3 — record an "admin.session_active" activity event whenever the
        // session is rehydrated (after login or page refresh). Fire-and-forget
        // so failures never break the dashboard.
        adminActivityApi.record('admin.session_active', { pathname });
        await fetchModules();
        if (pathname === '/admin/login' || pathname === '/admin') router.replace('/admin/dashboard');
      } catch (e: any) {
        // eslint-disable-next-line no-console
        console.error('[admin/sidebar] /admin/auth/me failed:', e);
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
        {modulesError && (
          <View style={styles.modulesErrorBanner} testID="admin-modules-error-banner">
            <ShieldAlert size={14} color={COLORS.warning} />
            <Text style={styles.modulesErrorText} numberOfLines={2}>
              Could not load the live sidebar from the server — showing offline menu.
              <Text style={styles.modulesErrorDetail}>{`  (${modulesError})`}</Text>
            </Text>
            <TouchableOpacity
              onPress={fetchModules}
              disabled={modulesLoading}
              style={styles.modulesRetryBtn}
              testID="admin-modules-retry"
            >
              {modulesLoading ? (
                <ActivityIndicator size="small" color={COLORS.primary} />
              ) : (
                <RefreshCw size={14} color={COLORS.primary} />
              )}
              <Text style={styles.modulesRetryText}>Retry</Text>
            </TouchableOpacity>
          </View>
        )}
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
  modulesErrorBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    backgroundColor: '#FEF3C7',
    borderBottomWidth: 1,
    borderBottomColor: '#FCD34D',
    paddingHorizontal: SPACING.lg,
    paddingVertical: 6,
  },
  modulesErrorText: { flex: 1, color: '#92400E', fontSize: FONT.sizes.xs, fontWeight: FONT.weights.medium },
  modulesErrorDetail: { fontWeight: FONT.weights.medium, color: '#A16207' },
  modulesRetryBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    backgroundColor: COLORS.primaryLight,
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: RADIUS.sm,
  },
  modulesRetryText: { color: COLORS.primary, fontSize: FONT.sizes.xs, fontWeight: FONT.weights.bold },
});

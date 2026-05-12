/**
 * /admin/access — Access Control center (super_admin only).
 *
 * Lets a super_admin:
 *   • See every admin and the role they currently hold.
 *   • Switch any admin's role (super_admin / manager / support).
 *   • Toggle per-admin module overrides (grant/deny) without changing role.
 *   • Spot sensitive modules (those marked sensitive=true get a warning badge).
 *
 * The matrix UI is a {admin × module} table — admins on rows, modules on
 * columns grouped by module.group. Each cell is a 3-state chip:
 *
 *   default  → admin inherits from their role's default_roles
 *   grant    → admin has explicit grant (override)
 *   deny     → admin has explicit deny  (override)
 *
 * Saving an admin's row only sends the fields that changed.
 */
import { useEffect, useMemo, useState, useCallback } from 'react';
import {
  View, Text, TouchableOpacity, ScrollView, StyleSheet, ActivityIndicator, Alert,
} from 'react-native';
import { useRouter } from 'expo-router';
import { ShieldAlert, ChevronDown, Check, Lock } from 'lucide-react-native';
import { adminApi, AdminRole, getProfile, AdminProfile } from '../../src/adminApi';
import { COLORS, FONT, RADIUS, SPACING } from '../../src/theme';
import { formatUid } from '../../src/ids';

type Module = {
  key: string; label: string; group: string; path: string;
  default_roles: AdminRole[]; sensitive: boolean;
};

type AdminRow = {
  id: string;
  email: string;
  name: string;
  role: AdminRole;
  is_active: boolean;
  module_overrides: Record<string, 'grant' | 'deny'>;
  accessible_modules: string[];
  last_login_at: string | null;
};

const ROLE_OPTIONS: AdminRole[] = ['super_admin', 'manager', 'support'];

export default function AccessControlPage() {
  const router = useRouter();
  const [me, setMe] = useState<AdminProfile | null>(null);
  const [registry, setRegistry] = useState<{ modules: Module[]; group_order: string[] } | null>(null);
  const [admins, setAdmins] = useState<AdminRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [savingId, setSavingId] = useState<string | null>(null);
  const [dirty, setDirty] = useState<Record<string, AdminRow>>({});
  const [expanded, setExpanded] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [reg, adm, profile] = await Promise.all([
        adminApi.accessRegistry(),
        adminApi.accessAdmins(),
        getProfile(),
      ]);
      setRegistry({ modules: reg.modules, group_order: reg.group_order });
      setAdmins(adm.items);
      setMe(profile);
      setDirty({});
    } catch (e: any) {
      Alert.alert('Failed to load', e?.message || 'Could not load access settings.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const isSuper = (me?.role || '').toLowerCase() === 'super_admin';

  /** Returns the working copy of the admin (dirty overrides original). */
  const current = (a: AdminRow): AdminRow => dirty[a.id] ?? a;

  const setOverride = (admin: AdminRow, moduleKey: string, next: 'default' | 'grant' | 'deny') => {
    const working: AdminRow = JSON.parse(JSON.stringify(current(admin)));
    const overrides = { ...(working.module_overrides || {}) };
    if (next === 'default') delete overrides[moduleKey];
    else overrides[moduleKey] = next;
    working.module_overrides = overrides;
    setDirty((d) => ({ ...d, [admin.id]: working }));
  };

  const setRole = (admin: AdminRow, role: AdminRole) => {
    const working: AdminRow = { ...current(admin), role };
    setDirty((d) => ({ ...d, [admin.id]: working }));
  };

  const cancelEdit = (id: string) => {
    setDirty((d) => { const next = { ...d }; delete next[id]; return next; });
  };

  const saveAdmin = async (admin: AdminRow) => {
    const working = current(admin);
    const body: any = {};
    if (working.role !== admin.role) body.role = working.role;
    if (JSON.stringify(working.module_overrides || {}) !== JSON.stringify(admin.module_overrides || {})) {
      body.module_overrides = working.module_overrides || {};
    }
    if (Object.keys(body).length === 0) {
      cancelEdit(admin.id);
      return;
    }
    setSavingId(admin.id);
    try {
      const res = await adminApi.setAdminAccess(admin.id, body);
      if (res.admin) {
        setAdmins((prev) => prev.map((a) => (a.id === admin.id ? { ...a, ...res.admin } : a)));
      }
      cancelEdit(admin.id);
    } catch (e: any) {
      Alert.alert('Save failed', e?.message || 'Could not save access changes.');
    } finally {
      setSavingId(null);
    }
  };

  /** State of a cell: default / grant / deny. */
  const cellState = (admin: AdminRow, m: Module): 'default' | 'grant' | 'deny' => {
    const ov = (current(admin).module_overrides || {})[m.key];
    if (ov === 'grant') return 'grant';
    if (ov === 'deny') return 'deny';
    return 'default';
  };

  /** Is the user effectively able to access this module right now (in working state)? */
  const effectiveAccess = (admin: AdminRow, m: Module): boolean => {
    const working = current(admin);
    if (working.role === 'super_admin') return true;
    const ov = (working.module_overrides || {})[m.key];
    if (ov === 'grant') return true;
    if (ov === 'deny') return false;
    return m.default_roles.includes(working.role);
  };

  const cycleCell = (admin: AdminRow, m: Module) => {
    const s = cellState(admin, m);
    if (current(admin).role === 'super_admin') {
      Alert.alert('Super admin', 'super_admin always has access to every module. Demote first to apply overrides.');
      return;
    }
    const next: 'default' | 'grant' | 'deny' =
      s === 'default' ? (m.default_roles.includes(current(admin).role) ? 'deny' : 'grant')
      : s === 'grant' ? 'deny'
      : 'default';
    setOverride(admin, m.key, next);
  };

  const grouped = useMemo(() => {
    if (!registry) return {} as Record<string, Module[]>;
    const out: Record<string, Module[]> = {};
    for (const g of registry.group_order) out[g] = [];
    for (const m of registry.modules) {
      if (!out[m.group]) out[m.group] = [];
      out[m.group].push(m);
    }
    return out;
  }, [registry]);

  if (loading || !registry) {
    return (
      <View style={styles.center}>
        <ActivityIndicator color={COLORS.primary} />
      </View>
    );
  }

  if (!isSuper) {
    return (
      <View style={styles.center}>
        <Lock size={32} color={COLORS.subtext} />
        <Text style={styles.gateTitle}>Super admin only</Text>
        <Text style={styles.gateBody}>
          Only super_admin accounts can manage Access Control. Ask a super_admin
          to grant you the role you need.
        </Text>
      </View>
    );
  }

  return (
    <ScrollView style={styles.root} contentContainerStyle={styles.container}>
      <Text style={styles.h1}>Access Control</Text>
      <Text style={styles.sub}>
        Manage which admin can open which module. Roles set baseline access;
        per-admin overrides flip individual modules.
      </Text>

      <View style={styles.legendRow}>
        <View style={[styles.chipDot, { backgroundColor: COLORS.surface, borderColor: COLORS.border }]} />
        <Text style={styles.legendText}>Default (inherits from role)</Text>
        <View style={[styles.chipDot, { backgroundColor: COLORS.successLight || '#DCFCE7', borderColor: COLORS.success }]} />
        <Text style={styles.legendText}>Grant</Text>
        <View style={[styles.chipDot, { backgroundColor: COLORS.dangerLight || '#FEE2E2', borderColor: COLORS.danger }]} />
        <Text style={styles.legendText}>Deny</Text>
      </View>

      {admins.map((a) => {
        const working = current(a);
        const isDirty = !!dirty[a.id];
        const open = expanded === a.id || isDirty;
        return (
          <View key={a.id} style={styles.adminCard} testID={`access-admin-${a.id}`}>
            <TouchableOpacity
              onPress={() => setExpanded(open ? null : a.id)}
              activeOpacity={0.7}
              style={styles.adminHeader}
            >
              <View style={{ flex: 1 }}>
                <Text style={styles.adminName} numberOfLines={1}>{a.name || a.email}</Text>
                <Text style={styles.adminMeta}>{a.email}</Text>
                <Text style={styles.adminUid} selectable>{formatUid(a.id)}</Text>
              </View>
              <View style={[
                styles.roleBadge,
                { backgroundColor: working.role === 'super_admin' ? '#7C3AED' : working.role === 'manager' ? COLORS.primary : COLORS.subtext },
              ]}>
                <Text style={styles.roleBadgeText}>{working.role}</Text>
              </View>
              <ChevronDown
                size={18}
                color={COLORS.subtext}
                style={{ transform: [{ rotate: open ? '180deg' : '0deg' }] }}
              />
            </TouchableOpacity>

            {open ? (
              <View style={styles.adminBody}>
                {/* Role picker */}
                <Text style={styles.label}>Role</Text>
                <View style={styles.roleRow}>
                  {ROLE_OPTIONS.map((r) => {
                    const active = working.role === r;
                    const disabled = me?.id === a.id && r !== 'super_admin' && a.role === 'super_admin';
                    return (
                      <TouchableOpacity
                        key={r}
                        onPress={() => !disabled && setRole(a, r)}
                        style={[styles.roleOption, active && styles.roleOptionActive, disabled && { opacity: 0.4 }]}
                        activeOpacity={0.7}
                        testID={`access-role-${a.id}-${r}`}
                      >
                        <Text style={[styles.roleOptionText, active && { color: '#fff' }]}>{r}</Text>
                      </TouchableOpacity>
                    );
                  })}
                </View>

                {/* Module matrix */}
                {registry.group_order.map((g) => {
                  const mods = grouped[g] || [];
                  if (mods.length === 0) return null;
                  return (
                    <View key={g} style={{ marginTop: SPACING.md }}>
                      <Text style={styles.groupTitle}>{g}</Text>
                      <View style={styles.cellRow}>
                        {mods.map((m) => {
                          const s = cellState(a, m);
                          const eff = effectiveAccess(a, m);
                          const bg =
                            s === 'grant' ? (COLORS.successLight || '#DCFCE7')
                            : s === 'deny' ? (COLORS.dangerLight || '#FEE2E2')
                            : COLORS.surface;
                          const borderColor =
                            s === 'grant' ? COLORS.success
                            : s === 'deny' ? COLORS.danger
                            : COLORS.border;
                          return (
                            <TouchableOpacity
                              key={m.key}
                              onPress={() => cycleCell(a, m)}
                              activeOpacity={0.7}
                              style={[styles.cell, { backgroundColor: bg, borderColor }]}
                              testID={`access-cell-${a.id}-${m.key}`}
                            >
                              <Text style={[styles.cellLabel, !eff && { textDecorationLine: 'line-through', opacity: 0.6 }]} numberOfLines={1}>
                                {m.label}
                              </Text>
                              {m.sensitive ? (
                                <ShieldAlert size={10} color={COLORS.warning} style={{ marginLeft: 4 }} />
                              ) : null}
                              {s !== 'default' ? (
                                <Text style={[styles.cellState, s === 'grant' ? { color: COLORS.success } : { color: COLORS.danger }]}>
                                  {s.toUpperCase()}
                                </Text>
                              ) : null}
                            </TouchableOpacity>
                          );
                        })}
                      </View>
                    </View>
                  );
                })}

                {/* Save / cancel */}
                {isDirty ? (
                  <View style={styles.actionRow}>
                    <TouchableOpacity
                      onPress={() => cancelEdit(a.id)}
                      style={[styles.btn, styles.btnGhost]}
                      activeOpacity={0.8}
                    >
                      <Text style={styles.btnGhostText}>Cancel</Text>
                    </TouchableOpacity>
                    <TouchableOpacity
                      onPress={() => saveAdmin(a)}
                      style={[styles.btn, styles.btnPrimary]}
                      activeOpacity={0.8}
                      disabled={savingId === a.id}
                      testID={`access-save-${a.id}`}
                    >
                      {savingId === a.id ? (
                        <ActivityIndicator color="#fff" />
                      ) : (
                        <>
                          <Check size={14} color="#fff" />
                          <Text style={styles.btnPrimaryText}>Save</Text>
                        </>
                      )}
                    </TouchableOpacity>
                  </View>
                ) : null}
              </View>
            ) : null}
          </View>
        );
      })}
    </ScrollView>
  );
}

const styles: any = StyleSheet.create({
  root: { flex: 1, backgroundColor: COLORS.bg },
  container: { padding: SPACING.lg, gap: SPACING.md, maxWidth: 1100, alignSelf: 'stretch', width: '100%' },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: SPACING.xl, gap: 8, backgroundColor: COLORS.bg },
  gateTitle: { fontSize: FONT.sizes.lg, fontWeight: FONT.weights.bold, color: COLORS.text, marginTop: 12 },
  gateBody: { fontSize: FONT.sizes.sm, color: COLORS.subtext, textAlign: 'center', maxWidth: 360 },
  h1: { fontSize: FONT.sizes.xl, fontWeight: FONT.weights.bold, color: COLORS.text },
  sub: { fontSize: FONT.sizes.sm, color: COLORS.subtext },
  legendRow: {
    flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', gap: 6,
    paddingVertical: 4, marginBottom: 4,
  },
  chipDot: { width: 12, height: 12, borderRadius: 6, borderWidth: 1, marginLeft: 8 },
  legendText: { fontSize: 11, color: COLORS.subtext, marginRight: 4 },
  adminCard: {
    backgroundColor: COLORS.surface, borderRadius: RADIUS.lg, borderWidth: 1, borderColor: COLORS.border,
    overflow: 'hidden',
  },
  adminHeader: {
    flexDirection: 'row', alignItems: 'center', gap: 12, padding: SPACING.md,
  },
  adminName: { fontSize: FONT.sizes.md, fontWeight: FONT.weights.semibold, color: COLORS.text },
  adminMeta: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: 2 },
  adminUid: { fontSize: 11, color: COLORS.subtext, marginTop: 2, fontFamily: 'monospace', letterSpacing: 0.5 },
  roleBadge: {
    paddingHorizontal: 10, paddingVertical: 4, borderRadius: 999,
  },
  roleBadgeText: { fontSize: 10, color: '#fff', fontWeight: FONT.weights.bold, textTransform: 'uppercase' },
  adminBody: { borderTopWidth: 1, borderTopColor: COLORS.border, padding: SPACING.md },
  label: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginBottom: 4, fontWeight: FONT.weights.semibold },
  roleRow: { flexDirection: 'row', gap: 6 },
  roleOption: {
    paddingHorizontal: 14, paddingVertical: 8, borderRadius: RADIUS.md,
    backgroundColor: COLORS.bg, borderWidth: 1, borderColor: COLORS.border,
  },
  roleOptionActive: { backgroundColor: COLORS.primary, borderColor: COLORS.primary },
  roleOptionText: { fontSize: FONT.sizes.sm, fontWeight: FONT.weights.semibold, color: COLORS.text, textTransform: 'lowercase' },
  groupTitle: { fontSize: FONT.sizes.xs, color: COLORS.subtext, fontWeight: FONT.weights.bold, textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 6 },
  cellRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  cell: {
    flexDirection: 'row', alignItems: 'center', gap: 6,
    paddingHorizontal: 10, paddingVertical: 6, borderRadius: RADIUS.md,
    borderWidth: 1, minHeight: 32,
  },
  cellLabel: { fontSize: FONT.sizes.xs, color: COLORS.text, fontWeight: FONT.weights.semibold },
  cellState: { fontSize: 9, fontWeight: FONT.weights.bold, marginLeft: 4 },
  actionRow: { flexDirection: 'row', gap: 8, marginTop: SPACING.lg, justifyContent: 'flex-end' },
  btn: { flexDirection: 'row', alignItems: 'center', gap: 6, paddingHorizontal: 18, paddingVertical: 10, borderRadius: RADIUS.md, minHeight: 40 },
  btnGhost: { backgroundColor: COLORS.bg, borderWidth: 1, borderColor: COLORS.border },
  btnGhostText: { fontWeight: FONT.weights.semibold, color: COLORS.text },
  btnPrimary: { backgroundColor: COLORS.primary },
  btnPrimaryText: { fontWeight: FONT.weights.bold, color: '#fff' },
});

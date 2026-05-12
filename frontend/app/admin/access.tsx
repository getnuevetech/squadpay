/**
 * /admin/access — Access Role Management (super_admin only).
 *
 * Manages ROLES (not individual admins). Each role declares which modules
 * are visible to any admin assigned to it. Admin user assignments are managed
 * in /admin/admins where a role dropdown picks from this registry.
 *
 *   ┌─────────────────────────────────────────────────────────────────┐
 *   │  Role list  (left)                                              │
 *   │   ┌─ Super Admin       (system, immutable)                      │
 *   │   ├─ Manager           (8 admins)                               │
 *   │   ├─ Support           (3 admins)                               │
 *   │   └─ + New role                                                 │
 *   │                                                                 │
 *   │  Role editor (right)                                            │
 *   │   ▢ Name                                                        │
 *   │   ▢ Description                                                 │
 *   │   ▢ Modules — grouped checkboxes                                │
 *   │   [Save]  [Delete]                                              │
 *   └─────────────────────────────────────────────────────────────────┘
 */
import { useEffect, useMemo, useState, useCallback } from 'react';
import {
  View, Text, TouchableOpacity, ScrollView, StyleSheet, ActivityIndicator,
  Alert, TextInput, Platform,
} from 'react-native';
import { Plus, Save, Trash2, ShieldAlert, ShieldCheck, Lock, Users, Check } from 'lucide-react-native';
import { adminApi, getProfile, AdminProfile } from '../../src/adminApi';
import { COLORS, FONT, RADIUS, SPACING } from '../../src/theme';

type Module = { key: string; label: string; group: string; path: string; sensitive: boolean };
type Role = {
  id: string;
  slug: string;
  name: string;
  description: string | null;
  modules: string[];
  is_system: boolean;
  assigned_admin_count: number;
  created_at?: string;
  updated_at?: string;
};

const SUPER_ADMIN_SLUG = 'super_admin';

export default function AccessRoleManagementPage() {
  const [me, setMe] = useState<AdminProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [creating, setCreating] = useState(false);
  const [registry, setRegistry] = useState<{ modules: Module[]; group_order: string[] } | null>(null);
  const [roles, setRoles] = useState<Role[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  // Working edits (only meaningful while a role is selected).
  const [draft, setDraft] = useState<{
    name: string;
    description: string;
    modules: Set<string>;
  }>({ name: '', description: '', modules: new Set() });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [reg, list, profile] = await Promise.all([
        adminApi.accessRegistry(),
        adminApi.listRoles(),
        getProfile(),
      ]);
      setRegistry({ modules: reg.modules, group_order: reg.group_order });
      setRoles(list.items);
      setMe(profile);
      // Auto-select the first non-super_admin role on first load so the editor
      // isn't blank. Falls back to super_admin if it's the only thing.
      if (!selectedId) {
        const first = list.items.find((r) => r.slug !== SUPER_ADMIN_SLUG) || list.items[0];
        if (first) selectInto(first);
      } else {
        const refreshed = list.items.find((r) => r.id === selectedId);
        if (refreshed) selectInto(refreshed);
      }
    } catch (e: any) {
      Alert.alert('Failed to load', e?.message || 'Could not load Access Roles.');
    } finally {
      setLoading(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => { load(); }, [load]);

  const selectInto = (role: Role) => {
    setSelectedId(role.id);
    setDraft({
      name: role.name,
      description: role.description || '',
      modules: new Set(role.modules || []),
    });
  };

  const selected = useMemo(() => roles.find((r) => r.id === selectedId) || null, [roles, selectedId]);
  const isSuper = (me?.role || '').toLowerCase() === SUPER_ADMIN_SLUG;
  const isLocked = !!selected && selected.slug === SUPER_ADMIN_SLUG;
  const isDirty = useMemo(() => {
    if (!selected) return false;
    return (
      draft.name !== selected.name ||
      (draft.description || '') !== (selected.description || '') ||
      !setsEqual(draft.modules, new Set(selected.modules))
    );
  }, [draft, selected]);

  const groupedModules = useMemo(() => {
    if (!registry) return {} as Record<string, Module[]>;
    const out: Record<string, Module[]> = {};
    for (const g of registry.group_order) out[g] = [];
    for (const m of registry.modules) {
      if (!out[m.group]) out[m.group] = [];
      out[m.group].push(m);
    }
    return out;
  }, [registry]);

  const toggleModule = (key: string) => {
    if (isLocked) return;
    setDraft((d) => {
      const next = new Set(d.modules);
      if (next.has(key)) next.delete(key); else next.add(key);
      return { ...d, modules: next };
    });
  };

  const toggleGroup = (groupKey: string, value: boolean) => {
    if (isLocked || !registry) return;
    const keys = (groupedModules[groupKey] || []).map((m) => m.key);
    setDraft((d) => {
      const next = new Set(d.modules);
      for (const k of keys) {
        if (value) next.add(k); else next.delete(k);
      }
      return { ...d, modules: next };
    });
  };

  const onCreateRole = () => {
    const promptText = 'Name of the new role (e.g. "Operations Lead")';
    const askName = async (initial = '') => {
      if (Platform.OS === 'web') {
        // eslint-disable-next-line no-alert
        const v = window.prompt(promptText, initial);
        return v;
      }
      // RN doesn't have a prompt — fall back to Alert with a single confirm.
      return new Promise<string | null>((resolve) => {
        Alert.alert('New role', promptText, [
          { text: 'Cancel', style: 'cancel', onPress: () => resolve(null) },
          { text: 'Create', onPress: () => resolve('New role') },
        ]);
      });
    };
    askName().then(async (name) => {
      if (!name || !name.trim()) return;
      setCreating(true);
      try {
        const newRole = await adminApi.createRole({
          name: name.trim(),
          description: '',
          modules: ['dashboard'], // sensible default — every role can see Dashboard
        });
        await load();
        // Select the new role.
        setTimeout(() => {
          setSelectedId(newRole.id);
          setDraft({
            name: newRole.name,
            description: newRole.description || '',
            modules: new Set(newRole.modules),
          });
        }, 50);
      } catch (e: any) {
        Alert.alert('Could not create role', e?.message || 'Unknown error');
      } finally {
        setCreating(false);
      }
    });
  };

  const onSave = async () => {
    if (!selected) return;
    setSaving(true);
    try {
      const updated = await adminApi.updateRole(selected.id, {
        name: draft.name.trim(),
        description: draft.description.trim(),
        modules: Array.from(draft.modules),
      });
      setRoles((prev) => prev.map((r) => (r.id === updated.id ? { ...r, ...updated } : r)));
      selectInto({ ...selected, ...updated });
    } catch (e: any) {
      Alert.alert('Save failed', e?.message || 'Could not save.');
    } finally {
      setSaving(false);
    }
  };

  const onDelete = async () => {
    if (!selected || selected.is_system) return;
    if (selected.assigned_admin_count > 0) {
      Alert.alert(
        'Cannot delete',
        `${selected.assigned_admin_count} admin user(s) are assigned to this role. Reassign them to another role first.`,
      );
      return;
    }
    const doDelete = async () => {
      setDeleting(true);
      try {
        await adminApi.deleteRole(selected.id);
        setRoles((prev) => prev.filter((r) => r.id !== selected.id));
        setSelectedId(null);
      } catch (e: any) {
        Alert.alert('Delete failed', e?.message || 'Could not delete role.');
      } finally {
        setDeleting(false);
      }
    };
    if (Platform.OS === 'web') {
      // eslint-disable-next-line no-alert
      if (window.confirm(`Delete role "${selected.name}"? This can't be undone.`)) doDelete();
    } else {
      Alert.alert('Delete role?', `"${selected.name}" will be removed.`, [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Delete', style: 'destructive', onPress: doDelete },
      ]);
    }
  };

  if (loading || !registry) {
    return <View style={styles.center}><ActivityIndicator color={COLORS.primary} /></View>;
  }

  if (!isSuper) {
    return (
      <View style={styles.center}>
        <Lock size={32} color={COLORS.subtext} />
        <Text style={styles.gateTitle}>Super admin only</Text>
        <Text style={styles.gateBody}>
          Only super_admin accounts can manage Access Roles.
        </Text>
      </View>
    );
  }

  return (
    <View style={styles.root}>
      {/* LEFT: role list */}
      <ScrollView style={styles.left} contentContainerStyle={{ padding: SPACING.md, gap: SPACING.sm }}>
        <Text style={styles.h1}>Access Role Management</Text>
        <Text style={styles.sub}>Create roles, pick the modules each role can see, then assign roles to admin users from the Admin Users page.</Text>

        <TouchableOpacity
          style={styles.newRoleBtn}
          activeOpacity={0.8}
          onPress={onCreateRole}
          disabled={creating}
          testID="access-new-role"
        >
          {creating ? <ActivityIndicator color="#fff" /> : <Plus size={16} color="#fff" />}
          <Text style={styles.newRoleText}>New role</Text>
        </TouchableOpacity>

        {roles.map((r) => {
          const active = r.id === selectedId;
          return (
            <TouchableOpacity
              key={r.id}
              activeOpacity={0.7}
              style={[styles.roleCard, active && styles.roleCardActive]}
              onPress={() => selectInto(r)}
              testID={`access-role-card-${r.slug}`}
            >
              <View style={{ flex: 1 }}>
                <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
                  <Text style={[styles.roleName, active && { color: '#fff' }]} numberOfLines={1}>
                    {r.name}
                  </Text>
                  {r.is_system ? (
                    <ShieldCheck size={13} color={active ? '#fff' : COLORS.success} />
                  ) : null}
                </View>
                <Text style={[styles.roleSub, active && { color: '#fff', opacity: 0.85 }]} numberOfLines={1}>
                  {r.modules.length} module{r.modules.length === 1 ? '' : 's'} • {r.assigned_admin_count} admin{r.assigned_admin_count === 1 ? '' : 's'}
                </Text>
              </View>
              <Users size={14} color={active ? '#fff' : COLORS.subtext} />
            </TouchableOpacity>
          );
        })}
      </ScrollView>

      {/* RIGHT: editor */}
      <ScrollView style={styles.right} contentContainerStyle={{ padding: SPACING.lg, gap: SPACING.md }}>
        {!selected ? (
          <View style={styles.center}>
            <Text style={styles.sub}>Select a role on the left, or create a new one.</Text>
          </View>
        ) : (
          <>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }}>
              <View style={{ flex: 1 }}>
                <Text style={styles.h2}>{selected.name}</Text>
                <Text style={styles.sub}>
                  slug <Text style={{ fontFamily: 'monospace' }}>{selected.slug}</Text>
                  {selected.is_system ? ' • system role' : ''}
                  {' • '}
                  {selected.assigned_admin_count} admin user{selected.assigned_admin_count === 1 ? '' : 's'} assigned
                </Text>
              </View>
              {isLocked ? (
                <View style={styles.lockBadge}>
                  <Lock size={12} color={COLORS.warning} />
                  <Text style={styles.lockText}>Immutable</Text>
                </View>
              ) : null}
            </View>

            <View>
              <Text style={styles.label}>Display name</Text>
              <TextInput
                value={draft.name}
                onChangeText={(t) => setDraft((d) => ({ ...d, name: t }))}
                editable={!isLocked && !saving}
                style={[styles.input, isLocked && { opacity: 0.6 }]}
                placeholder="e.g. Operations Lead"
                placeholderTextColor={COLORS.subtext}
                testID="role-name-input"
              />
            </View>

            <View>
              <Text style={styles.label}>Description</Text>
              <TextInput
                value={draft.description}
                onChangeText={(t) => setDraft((d) => ({ ...d, description: t }))}
                editable={!isLocked && !saving}
                multiline
                style={[styles.input, styles.inputMulti, isLocked && { opacity: 0.6 }]}
                placeholder="What does this role do?"
                placeholderTextColor={COLORS.subtext}
                maxLength={300}
              />
            </View>

            <Text style={styles.label}>Modules ({draft.modules.size}/{registry.modules.length})</Text>
            {registry.group_order.map((g) => {
              const mods = groupedModules[g] || [];
              if (mods.length === 0) return null;
              const allOn = mods.every((m) => draft.modules.has(m.key));
              return (
                <View key={g} style={styles.groupBlock}>
                  <View style={styles.groupHeader}>
                    <Text style={styles.groupTitle}>{g}</Text>
                    <TouchableOpacity
                      onPress={() => toggleGroup(g, !allOn)}
                      activeOpacity={0.7}
                      disabled={isLocked}
                      style={styles.groupToggle}
                      testID={`role-group-toggle-${g}`}
                    >
                      <Text style={[styles.groupToggleText, isLocked && { opacity: 0.4 }]}>
                        {allOn ? 'Clear all' : 'Select all'}
                      </Text>
                    </TouchableOpacity>
                  </View>
                  <View style={styles.moduleRow}>
                    {mods.map((m) => {
                      const on = draft.modules.has(m.key);
                      return (
                        <TouchableOpacity
                          key={m.key}
                          onPress={() => toggleModule(m.key)}
                          activeOpacity={0.7}
                          disabled={isLocked}
                          style={[
                            styles.chip,
                            on && styles.chipOn,
                            isLocked && { opacity: 0.6 },
                          ]}
                          testID={`role-chip-${selected.slug}-${m.key}`}
                        >
                          {on ? <Check size={12} color="#fff" /> : null}
                          <Text style={[styles.chipText, on && { color: '#fff' }]} numberOfLines={1}>
                            {m.label}
                          </Text>
                          {m.sensitive ? (
                            <ShieldAlert size={10} color={on ? '#fff' : COLORS.warning} />
                          ) : null}
                        </TouchableOpacity>
                      );
                    })}
                  </View>
                </View>
              );
            })}

            {!isLocked ? (
              <View style={styles.actionRow}>
                {!selected.is_system ? (
                  <TouchableOpacity
                    onPress={onDelete}
                    style={[styles.btn, styles.btnDanger]}
                    activeOpacity={0.8}
                    disabled={deleting || selected.assigned_admin_count > 0}
                    testID="role-delete"
                  >
                    {deleting ? <ActivityIndicator color="#fff" /> : <Trash2 size={14} color="#fff" />}
                    <Text style={styles.btnDangerText}>Delete role</Text>
                  </TouchableOpacity>
                ) : <View style={{ flex: 1 }} />}
                <TouchableOpacity
                  onPress={onSave}
                  style={[
                    styles.btn, styles.btnPrimary,
                    (!isDirty || saving) && { opacity: 0.5 },
                  ]}
                  activeOpacity={0.8}
                  disabled={!isDirty || saving}
                  testID="role-save"
                >
                  {saving ? <ActivityIndicator color="#fff" /> : <Save size={14} color="#fff" />}
                  <Text style={styles.btnPrimaryText}>Save changes</Text>
                </TouchableOpacity>
              </View>
            ) : null}
          </>
        )}
      </ScrollView>
    </View>
  );
}

function setsEqual<T>(a: Set<T>, b: Set<T>): boolean {
  if (a.size !== b.size) return false;
  for (const x of a) if (!b.has(x)) return false;
  return true;
}

const styles = StyleSheet.create({
  root: { flex: 1, flexDirection: Platform.OS === 'web' ? 'row' : 'column', backgroundColor: COLORS.bg },
  left: {
    width: Platform.OS === 'web' ? 320 : '100%',
    borderRightWidth: Platform.OS === 'web' ? 1 : 0,
    borderRightColor: COLORS.border,
    backgroundColor: COLORS.surface,
    flexGrow: 0,
  },
  right: { flex: 1 },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: SPACING.xl, gap: 8 },
  gateTitle: { fontSize: FONT.sizes.lg, fontWeight: FONT.weights.bold, color: COLORS.text, marginTop: 12 },
  gateBody: { fontSize: FONT.sizes.sm, color: COLORS.subtext, textAlign: 'center', maxWidth: 360 },
  h1: { fontSize: FONT.sizes.xl, fontWeight: FONT.weights.bold, color: COLORS.text },
  h2: { fontSize: FONT.sizes.lg, fontWeight: FONT.weights.bold, color: COLORS.text },
  sub: { fontSize: FONT.sizes.sm, color: COLORS.subtext, lineHeight: 18 },
  newRoleBtn: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6,
    paddingVertical: 10, borderRadius: RADIUS.md, backgroundColor: COLORS.primary,
    marginVertical: SPACING.sm,
  },
  newRoleText: { color: '#fff', fontWeight: FONT.weights.bold },
  roleCard: {
    flexDirection: 'row', alignItems: 'center', gap: 8,
    padding: SPACING.md, borderRadius: RADIUS.md,
    backgroundColor: COLORS.bg, borderWidth: 1, borderColor: COLORS.border,
  },
  roleCardActive: { backgroundColor: COLORS.primary, borderColor: COLORS.primary },
  roleName: { fontSize: FONT.sizes.md, color: COLORS.text, fontWeight: FONT.weights.semibold },
  roleSub: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: 2 },
  label: { fontSize: FONT.sizes.xs, color: COLORS.subtext, fontWeight: FONT.weights.semibold, marginBottom: 4 },
  input: {
    borderWidth: 1, borderColor: COLORS.border, borderRadius: RADIUS.md,
    paddingHorizontal: 12, paddingVertical: 10, color: COLORS.text,
    fontSize: FONT.sizes.md, backgroundColor: COLORS.surface,
  },
  inputMulti: { minHeight: 60, textAlignVertical: 'top' },
  groupBlock: { marginTop: 4 },
  groupHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 },
  groupTitle: { fontSize: FONT.sizes.xs, color: COLORS.text, fontWeight: FONT.weights.bold, textTransform: 'uppercase', letterSpacing: 0.5 },
  groupToggle: { paddingHorizontal: 6, paddingVertical: 2 },
  groupToggleText: { fontSize: FONT.sizes.xs, color: COLORS.primary, fontWeight: FONT.weights.semibold },
  moduleRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  chip: {
    flexDirection: 'row', alignItems: 'center', gap: 6,
    paddingHorizontal: 12, paddingVertical: 6, borderRadius: 999,
    borderWidth: 1, borderColor: COLORS.border, backgroundColor: COLORS.surface,
    minHeight: 32,
  },
  chipOn: { backgroundColor: COLORS.primary, borderColor: COLORS.primary },
  chipText: { fontSize: FONT.sizes.xs, color: COLORS.text, fontWeight: FONT.weights.semibold },
  lockBadge: {
    flexDirection: 'row', alignItems: 'center', gap: 4,
    paddingHorizontal: 8, paddingVertical: 4, borderRadius: 999,
    backgroundColor: COLORS.warningLight || '#FEF3C7',
  },
  lockText: { fontSize: 10, color: COLORS.warning, fontWeight: FONT.weights.bold, textTransform: 'uppercase' },
  actionRow: { flexDirection: 'row', gap: 8, marginTop: SPACING.lg, justifyContent: 'space-between' },
  btn: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6, paddingHorizontal: 18, paddingVertical: 10, borderRadius: RADIUS.md, minHeight: 40 },
  btnPrimary: { backgroundColor: COLORS.primary },
  btnPrimaryText: { color: '#fff', fontWeight: FONT.weights.bold },
  btnDanger: { backgroundColor: COLORS.danger },
  btnDangerText: { color: '#fff', fontWeight: FONT.weights.bold },
});

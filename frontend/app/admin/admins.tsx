import { useEffect, useState } from 'react';
import { View, Text, ScrollView, TouchableOpacity, TextInput, StyleSheet, Alert, ActivityIndicator, Modal, Platform } from 'react-native';
import * as Clipboard from 'expo-clipboard';
import { adminApi, AdminProfile } from '../../src/adminApi';
import { COLORS, FONT, RADIUS, SPACING } from '../../src/theme';
import { Plus, Power, KeyRound, UserCog, ShieldCheck } from 'lucide-react-native';

type RoleOption = { id: string; slug: string; name: string; description: string | null; is_system: boolean };

export default function AdminUsers() {
  const [admins, setAdmins] = useState<AdminProfile[]>([]);
  const [roles, setRoles] = useState<RoleOption[]>([]);
  const [busy, setBusy] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [role, setRole] = useState<string>('support');

  // Push-reset modal state
  const [resetTarget, setResetTarget] = useState<AdminProfile | null>(null);
  const [altEmail, setAltEmail] = useState('');
  const [resetBusy, setResetBusy] = useState(false);

  // Change-role modal state
  const [roleTarget, setRoleTarget] = useState<AdminProfile | null>(null);
  const [pendingRole, setPendingRole] = useState<string>('support');
  const [roleBusy, setRoleBusy] = useState(false);

  const load = async () => {
    setBusy(true);
    try {
      const [adm, lookup] = await Promise.all([adminApi.listAdmins(), adminApi.rolesLookup()]);
      setAdmins(adm);
      setRoles(lookup.items);
      // Default the create-form role to first non-super_admin role.
      const fallback = lookup.items.find((r) => r.slug !== 'super_admin') || lookup.items[0];
      if (fallback) setRole((cur) => cur === 'support' ? fallback.slug : cur);
    } finally {
      setBusy(false);
    }
  };
  useEffect(() => { load(); }, []);

  const submit = async () => {
    if (!name.trim() || !email.trim() || password.length < 8) { Alert.alert('Missing/invalid', 'Name, email, and 8+ char password required.'); return; }
    if (!role) { Alert.alert('Pick a role', 'A role is required for every admin user.'); return; }
    try {
      await adminApi.createAdmin({ name: name.trim(), email: email.trim().toLowerCase(), password, role });
      setShowForm(false); setName(''); setEmail(''); setPassword('');
      await load();
    } catch (e: any) { Alert.alert('Could not create admin', e?.message || ''); }
  };

  const toggle = async (a: AdminProfile) => {
    try { await adminApi.toggleAdmin(a.id, !a.is_active); await load(); } catch (e: any) { Alert.alert('Could not update', e?.message || ''); }
  };

  const openPushReset = (a: AdminProfile) => {
    setResetTarget(a);
    setAltEmail('');
  };

  const roleLabel = (slug: string): string => {
    const r = roles.find((x) => x.slug === slug);
    return r?.name || slug;
  };

  const submitPushReset = async (returnLink: boolean) => {
    if (!resetTarget) return;
    setResetBusy(true);
    try {
      const r = await adminApi.pushAdminPasswordReset(resetTarget.id, {
        alternate_email: altEmail.trim() || undefined,
        return_link: returnLink,
      });
      const lines = [
        `Delivered to: ${r.delivered_to}`,
        `Email status: ${r.email_status}${r.email_error ? ` (${r.email_error})` : ''}`,
        `Expires in: ${r.expires_in_minutes} min`,
      ];
      if (r.reset_url) {
        try { await Clipboard.setStringAsync(r.reset_url); } catch {}
        lines.push('', 'Reset link copied to clipboard.');
      }
      Alert.alert('Reset link sent', lines.join('\n'));
      setResetTarget(null);
    } catch (e: any) {
      Alert.alert('Could not send reset', e?.message || '');
    } finally {
      setResetBusy(false);
    }
  };

  const openChangeRole = (a: AdminProfile) => {
    setRoleTarget(a);
    setPendingRole(a.role);
  };

  const submitChangeRole = async () => {
    if (!roleTarget) return;
    if (pendingRole === roleTarget.role) { setRoleTarget(null); return; }
    setRoleBusy(true);
    try {
      await adminApi.changeAdminRole(roleTarget.id, pendingRole);
      setRoleTarget(null);
      await load();
    } catch (e: any) {
      Alert.alert('Could not change role', e?.message || '');
    } finally {
      setRoleBusy(false);
    }
  };

  return (
    <ScrollView contentContainerStyle={{ paddingBottom: 80 }}>
      <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: SPACING.sm }}>
        <Text style={styles.heading} testID="admin-admins-heading">Admins</Text>
        <TouchableOpacity onPress={() => setShowForm((v) => !v)} style={styles.addBtn} activeOpacity={0.85} testID="admin-admins-add-btn">
          <Plus size={16} color="#fff" /><Text style={{ color: '#fff', fontWeight: FONT.weights.semibold }}>{showForm ? 'Close' : 'Add admin'}</Text>
        </TouchableOpacity>
      </View>
      <Text style={styles.subheading}>Only super-admins can add, toggle, push reset, or change role.</Text>
      {showForm ? (
        <View style={styles.form}>
          <Text style={styles.label}>Name</Text><TextInput style={styles.input} value={name} onChangeText={setName} placeholder="Jane Doe" placeholderTextColor={COLORS.disabledText} testID="admin-create-name" />
          <Text style={styles.label}>Email</Text><TextInput style={styles.input} value={email} onChangeText={setEmail} autoCapitalize="none" keyboardType="email-address" placeholder="[email protected]" placeholderTextColor={COLORS.disabledText} testID="admin-create-email" />
          <Text style={styles.label}>Password</Text><TextInput style={styles.input} value={password} onChangeText={setPassword} secureTextEntry placeholder="min 8 chars" placeholderTextColor={COLORS.disabledText} testID="admin-create-password" />
          <Text style={styles.label}>Role</Text>
          <View style={styles.rolePickerWrap} testID="admin-create-role-wrap">
            {roles.map((r) => (
              <TouchableOpacity
                key={r.slug}
                onPress={() => setRole(r.slug)}
                style={[styles.roleChip, role === r.slug && styles.roleChipActive]}
                activeOpacity={0.85}
                testID={`admin-create-role-${r.slug}`}
              >
                {r.is_system ? <ShieldCheck size={11} color={role === r.slug ? '#fff' : COLORS.success} /> : null}
                <Text style={[styles.roleChipText, role === r.slug && { color: '#fff' }]}>{r.name}</Text>
              </TouchableOpacity>
            ))}
          </View>
          <Text style={styles.helperTxt}>Roles are defined in Access Role Management. Each role decides which modules the new admin sees.</Text>
          <TouchableOpacity onPress={submit} style={styles.submitBtn} activeOpacity={0.85} testID="admin-create-submit"><Text style={{ color: '#fff', fontWeight: FONT.weights.bold }}>Create admin</Text></TouchableOpacity>
        </View>
      ) : null}
      {busy ? <ActivityIndicator color={COLORS.primary} style={{ marginTop: 16 }} /> : null}
      {admins.map((a) => (
        <View key={a.id} style={styles.row} testID={`admin-row-${a.id}`}>
          <View style={{ flex: 1 }}>
            <Text style={styles.name}>{a.name} <Text style={styles.role}>{roleLabel(a.role)}</Text></Text>
            <Text style={styles.metaTxt}>{a.email}</Text>
            <Text style={styles.metaTxt}>last login: {a.last_login_at ? new Date(a.last_login_at).toLocaleString() : 'never'}</Text>
            <View style={styles.rowActions}>
              <TouchableOpacity
                onPress={() => openPushReset(a)}
                style={styles.actionBtn}
                activeOpacity={0.85}
                testID={`admin-push-reset-${a.id}`}
              >
                <KeyRound size={12} color={COLORS.primary} />
                <Text style={styles.actionBtnText}>Push reset</Text>
              </TouchableOpacity>
              <TouchableOpacity
                onPress={() => openChangeRole(a)}
                style={styles.actionBtn}
                activeOpacity={0.85}
                testID={`admin-change-role-${a.id}`}
              >
                <UserCog size={12} color={COLORS.primary} />
                <Text style={styles.actionBtnText}>Change role</Text>
              </TouchableOpacity>
            </View>
          </View>
          <TouchableOpacity onPress={() => toggle(a)} style={[styles.toggle, !a.is_active && { backgroundColor: COLORS.danger + '22', borderColor: COLORS.danger }]} activeOpacity={0.85} testID={`admin-toggle-${a.id}`}>
            <Power size={14} color={a.is_active ? COLORS.success : COLORS.danger} />
            <Text style={[styles.toggleText, { color: a.is_active ? COLORS.success : COLORS.danger }]}>{a.is_active ? 'Active' : 'Disabled'}</Text>
          </TouchableOpacity>
        </View>
      ))}

      {/* Push reset modal */}
      <Modal visible={!!resetTarget} transparent animationType="fade" onRequestClose={() => setResetTarget(null)}>
        <View style={styles.modalBackdrop}>
          <View style={styles.modalCard} testID="admin-push-reset-modal">
            <Text style={styles.modalTitle}>Push password reset</Text>
            {resetTarget ? (
              <Text style={styles.modalSub}>Send a one-time reset link to <Text style={{ fontWeight: FONT.weights.semibold }}>{resetTarget.email}</Text>. Link expires in 30 minutes.</Text>
            ) : null}
            <Text style={styles.label}>Override email (optional)</Text>
            <TextInput
              style={styles.input}
              value={altEmail}
              onChangeText={setAltEmail}
              autoCapitalize="none"
              keyboardType="email-address"
              placeholder={resetTarget?.email || ''}
              placeholderTextColor={COLORS.disabledText}
              testID="admin-push-reset-alt-email"
            />
            <Text style={styles.helperTxt}>Use this if the registered admin email isn't deliverable (e.g. same-domain Gmail routing).</Text>
            <View style={{ flexDirection: 'row', gap: 8, marginTop: SPACING.md }}>
              <TouchableOpacity onPress={() => setResetTarget(null)} style={[styles.modalBtn, styles.modalBtnGhost]} activeOpacity={0.85}>
                <Text style={styles.modalBtnGhostText}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity
                onPress={() => submitPushReset(false)}
                style={[styles.modalBtn, styles.modalBtnPrimary]}
                activeOpacity={0.85}
                disabled={resetBusy}
                testID="admin-push-reset-send"
              >
                <Text style={styles.modalBtnPrimaryText}>{resetBusy ? 'Sending…' : 'Send email'}</Text>
              </TouchableOpacity>
            </View>
            <TouchableOpacity
              onPress={() => submitPushReset(true)}
              style={[styles.modalBtn, styles.modalBtnGhost, { marginTop: 8 }]}
              activeOpacity={0.85}
              disabled={resetBusy}
              testID="admin-push-reset-copy-link"
            >
              <Text style={styles.modalBtnGhostText}>Send + copy link to clipboard</Text>
            </TouchableOpacity>
          </View>
        </View>
      </Modal>

      {/* Change role modal */}
      <Modal visible={!!roleTarget} transparent animationType="fade" onRequestClose={() => setRoleTarget(null)}>
        <View style={styles.modalBackdrop}>
          <View style={styles.modalCard} testID="admin-change-role-modal">
            <Text style={styles.modalTitle}>Change role</Text>
            {roleTarget ? (
              <Text style={styles.modalSub}>{roleTarget.name} ({roleTarget.email})</Text>
            ) : null}
            <View style={[styles.rolePickerWrap, { marginTop: SPACING.sm }]}>
              {roles.map((r) => (
                <TouchableOpacity
                  key={r.slug}
                  onPress={() => setPendingRole(r.slug)}
                  style={[styles.roleChip, pendingRole === r.slug && styles.roleChipActive]}
                  activeOpacity={0.85}
                  testID={`admin-change-role-chip-${r.slug}`}
                >
                  {r.is_system ? <ShieldCheck size={11} color={pendingRole === r.slug ? '#fff' : COLORS.success} /> : null}
                  <Text style={[styles.roleChipText, pendingRole === r.slug && { color: '#fff' }]}>{r.name}</Text>
                </TouchableOpacity>
              ))}
            </View>
            <View style={{ flexDirection: 'row', gap: 8, marginTop: SPACING.md }}>
              <TouchableOpacity onPress={() => setRoleTarget(null)} style={[styles.modalBtn, styles.modalBtnGhost]} activeOpacity={0.85}>
                <Text style={styles.modalBtnGhostText}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity
                onPress={submitChangeRole}
                style={[styles.modalBtn, styles.modalBtnPrimary]}
                activeOpacity={0.85}
                disabled={roleBusy}
                testID="admin-change-role-save"
              >
                <Text style={styles.modalBtnPrimaryText}>{roleBusy ? 'Saving…' : 'Save'}</Text>
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  heading: { fontSize: FONT.sizes.xl, fontWeight: FONT.weights.bold, color: COLORS.text },
  subheading: { fontSize: FONT.sizes.sm, color: COLORS.subtext, marginBottom: SPACING.md },
  addBtn: { flexDirection: 'row', alignItems: 'center', gap: 6, backgroundColor: COLORS.primary, paddingHorizontal: SPACING.md, paddingVertical: 8, borderRadius: RADIUS.md },
  form: { backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border, borderRadius: RADIUS.md, padding: SPACING.md, marginBottom: SPACING.md, gap: 4 },
  label: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: SPACING.sm, marginBottom: 4 },
  input: { height: 40, borderRadius: RADIUS.md, borderWidth: 1, borderColor: COLORS.border, paddingHorizontal: SPACING.md, color: COLORS.text, backgroundColor: COLORS.bg },
  roleChip: { flexDirection: 'row', alignItems: 'center', gap: 4, paddingHorizontal: SPACING.md, paddingVertical: 8, borderRadius: RADIUS.pill, borderWidth: 1, borderColor: COLORS.border },
  roleChipActive: { backgroundColor: COLORS.primary, borderColor: COLORS.primary },
  roleChipText: { color: COLORS.subtext, fontSize: FONT.sizes.sm, fontWeight: FONT.weights.semibold },
  rolePickerWrap: { flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginTop: 4 },
  submitBtn: { marginTop: SPACING.md, height: 42, borderRadius: RADIUS.md, backgroundColor: COLORS.primary, alignItems: 'center', justifyContent: 'center' },
  row: { flexDirection: 'row', alignItems: 'center', gap: 10, padding: SPACING.md, borderBottomWidth: 1, borderBottomColor: COLORS.border },
  name: { fontSize: FONT.sizes.md, fontWeight: FONT.weights.semibold, color: COLORS.text },
  role: { fontSize: 11, color: COLORS.primary, backgroundColor: COLORS.primaryLight, paddingHorizontal: 6, paddingVertical: 1, borderRadius: 4, fontWeight: FONT.weights.bold, textTransform: 'uppercase' },
  metaTxt: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: 2 },
  toggle: { flexDirection: 'row', alignItems: 'center', gap: 4, paddingHorizontal: SPACING.sm, paddingVertical: 6, borderRadius: RADIUS.pill, borderWidth: 1, borderColor: COLORS.success, backgroundColor: COLORS.success + '22' },
  toggleText: { fontSize: FONT.sizes.xs, fontWeight: FONT.weights.bold },
  rowActions: { flexDirection: 'row', gap: 6, marginTop: SPACING.sm, flexWrap: 'wrap' },
  actionBtn: { flexDirection: 'row', alignItems: 'center', gap: 4, paddingHorizontal: SPACING.sm, paddingVertical: 4, borderRadius: RADIUS.pill, borderWidth: 1, borderColor: COLORS.primary + '55', backgroundColor: COLORS.primaryLight },
  actionBtnText: { fontSize: 11, fontWeight: FONT.weights.semibold, color: COLORS.primary },
  helperTxt: { fontSize: 11, color: COLORS.subtext, marginTop: 2, lineHeight: 14 },
  modalBackdrop: { flex: 1, backgroundColor: 'rgba(0,0,0,0.45)', justifyContent: 'center', padding: SPACING.lg },
  modalCard: { backgroundColor: COLORS.surface, borderRadius: RADIUS.lg, padding: SPACING.lg, ...Platform.select({ ios: { shadowColor: '#000', shadowOpacity: 0.25, shadowRadius: 16, shadowOffset: { width: 0, height: 8 } }, android: { elevation: 8 } }) },
  modalTitle: { fontSize: FONT.sizes.lg, fontWeight: FONT.weights.bold, color: COLORS.text, marginBottom: 4 },
  modalSub: { fontSize: FONT.sizes.sm, color: COLORS.subtext, marginBottom: SPACING.sm },
  modalBtn: { flex: 1, height: 42, borderRadius: RADIUS.md, alignItems: 'center', justifyContent: 'center', flexDirection: 'row' },
  modalBtnPrimary: { backgroundColor: COLORS.primary },
  modalBtnPrimaryText: { color: '#fff', fontWeight: FONT.weights.bold },
  modalBtnGhost: { borderWidth: 1, borderColor: COLORS.border },
  modalBtnGhostText: { color: COLORS.text, fontWeight: FONT.weights.semibold },
});

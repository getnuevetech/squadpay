import { useEffect, useState } from 'react';
import { View, Text, ScrollView, TouchableOpacity, TextInput, StyleSheet, Alert, ActivityIndicator } from 'react-native';
import { adminApi, AdminProfile, AdminRole } from '../../src/adminApi';
import { COLORS, FONT, RADIUS, SPACING } from '../../src/theme';
import { Plus, Power } from 'lucide-react-native';

export default function AdminUsers() {
  const [admins, setAdmins] = useState<AdminProfile[]>([]);
  const [busy, setBusy] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [role, setRole] = useState<AdminRole>('support');

  const load = async () => { setBusy(true); try { setAdmins(await adminApi.listAdmins()); } finally { setBusy(false); } };
  useEffect(() => { load(); }, []);

  const submit = async () => {
    if (!name.trim() || !email.trim() || password.length < 8) { Alert.alert('Missing/invalid', 'Name, email, and 8+ char password required.'); return; }
    try {
      await adminApi.createAdmin({ name: name.trim(), email: email.trim().toLowerCase(), password, role });
      setShowForm(false); setName(''); setEmail(''); setPassword(''); setRole('support');
      await load();
    } catch (e: any) { Alert.alert('Could not create admin', e?.message || ''); }
  };

  const toggle = async (a: AdminProfile) => {
    try { await adminApi.toggleAdmin(a.id, !a.is_active); await load(); } catch (e: any) { Alert.alert('Could not update', e?.message || ''); }
  };

  return (
    <ScrollView contentContainerStyle={{ paddingBottom: 80 }}>
      <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: SPACING.sm }}>
        <Text style={styles.heading} testID="admin-admins-heading">Admins</Text>
        <TouchableOpacity onPress={() => setShowForm((v) => !v)} style={styles.addBtn} activeOpacity={0.85} testID="admin-admins-add-btn">
          <Plus size={16} color="#fff" /><Text style={{ color: '#fff', fontWeight: FONT.weights.semibold }}>{showForm ? 'Close' : 'Add admin'}</Text>
        </TouchableOpacity>
      </View>
      <Text style={styles.subheading}>Only super-admins can add or toggle.</Text>
      {showForm ? (
        <View style={styles.form}>
          <Text style={styles.label}>Name</Text><TextInput style={styles.input} value={name} onChangeText={setName} placeholder="Jane Doe" placeholderTextColor={COLORS.disabledText} testID="admin-create-name" />
          <Text style={styles.label}>Email</Text><TextInput style={styles.input} value={email} onChangeText={setEmail} autoCapitalize="none" keyboardType="email-address" placeholder="[email protected]" placeholderTextColor={COLORS.disabledText} testID="admin-create-email" />
          <Text style={styles.label}>Password</Text><TextInput style={styles.input} value={password} onChangeText={setPassword} secureTextEntry placeholder="min 8 chars" placeholderTextColor={COLORS.disabledText} testID="admin-create-password" />
          <Text style={styles.label}>Role</Text>
          <View style={{ flexDirection: 'row', gap: 8 }}>
            {(['super_admin','manager','support'] as AdminRole[]).map((r) => (
              <TouchableOpacity key={r} onPress={() => setRole(r)} style={[styles.roleChip, role === r && styles.roleChipActive]} activeOpacity={0.85} testID={`admin-create-role-${r}`}>
                <Text style={[styles.roleChipText, role === r && { color: '#fff' }]}>{r}</Text>
              </TouchableOpacity>
            ))}
          </View>
          <TouchableOpacity onPress={submit} style={styles.submitBtn} activeOpacity={0.85} testID="admin-create-submit"><Text style={{ color: '#fff', fontWeight: FONT.weights.bold }}>Create admin</Text></TouchableOpacity>
        </View>
      ) : null}
      {busy ? <ActivityIndicator color={COLORS.primary} style={{ marginTop: 16 }} /> : null}
      {admins.map((a) => (
        <View key={a.id} style={styles.row} testID={`admin-row-${a.id}`}>
          <View style={{ flex: 1 }}>
            <Text style={styles.name}>{a.name} <Text style={styles.role}>{a.role}</Text></Text>
            <Text style={styles.metaTxt}>{a.email}</Text>
            <Text style={styles.metaTxt}>last login: {a.last_login_at ? new Date(a.last_login_at).toLocaleString() : 'never'}</Text>
          </View>
          <TouchableOpacity onPress={() => toggle(a)} style={[styles.toggle, !a.is_active && { backgroundColor: COLORS.danger + '22', borderColor: COLORS.danger }]} activeOpacity={0.85} testID={`admin-toggle-${a.id}`}>
            <Power size={14} color={a.is_active ? COLORS.success : COLORS.danger} />
            <Text style={[styles.toggleText, { color: a.is_active ? COLORS.success : COLORS.danger }]}>{a.is_active ? 'Active' : 'Disabled'}</Text>
          </TouchableOpacity>
        </View>
      ))}
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
  roleChip: { paddingHorizontal: SPACING.md, paddingVertical: 8, borderRadius: RADIUS.pill, borderWidth: 1, borderColor: COLORS.border },
  roleChipActive: { backgroundColor: COLORS.primary, borderColor: COLORS.primary },
  roleChipText: { color: COLORS.subtext, fontSize: FONT.sizes.sm, fontWeight: FONT.weights.semibold },
  submitBtn: { marginTop: SPACING.md, height: 42, borderRadius: RADIUS.md, backgroundColor: COLORS.primary, alignItems: 'center', justifyContent: 'center' },
  row: { flexDirection: 'row', alignItems: 'center', gap: 10, padding: SPACING.md, borderBottomWidth: 1, borderBottomColor: COLORS.border },
  name: { fontSize: FONT.sizes.md, fontWeight: FONT.weights.semibold, color: COLORS.text },
  role: { fontSize: 11, color: COLORS.primary, backgroundColor: COLORS.primaryLight, paddingHorizontal: 6, paddingVertical: 1, borderRadius: 4, fontWeight: FONT.weights.bold, textTransform: 'uppercase' },
  metaTxt: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: 2 },
  toggle: { flexDirection: 'row', alignItems: 'center', gap: 4, paddingHorizontal: SPACING.sm, paddingVertical: 6, borderRadius: RADIUS.pill, borderWidth: 1, borderColor: COLORS.success, backgroundColor: COLORS.success + '22' },
  toggleText: { fontSize: FONT.sizes.xs, fontWeight: FONT.weights.bold },
});

import { useState } from 'react';
import { View, Text, TextInput, TouchableOpacity, StyleSheet, Alert, ActivityIndicator } from 'react-native';
import { useRouter } from 'expo-router';
import { Shield } from 'lucide-react-native';
import { adminApi } from '../../src/adminApi';
import { COLORS, FONT, RADIUS, SPACING } from '../../src/theme';

export default function AdminLogin() {
  const router = useRouter();
  const [email, setEmail] = useState('[email protected]');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!email.trim() || !password) {
      Alert.alert('Missing fields', 'Enter email and password.');
      return;
    }
    setBusy(true);
    try {
      await adminApi.login(email.trim().toLowerCase(), password);
      router.replace('/admin/dashboard');
    } catch (e: any) {
      Alert.alert('Sign-in failed', e?.message || 'Try again');
    } finally { setBusy(false); }
  };

  return (
    <View style={styles.wrap}>
      <View style={styles.card}>
        <View style={styles.brandRow}><Shield color={COLORS.primary} size={24} /><Text style={styles.brand}>SquadPay Admin</Text></View>
        <Text style={styles.subtitle}>Sign in with your admin email</Text>
        <Text style={styles.label}>Email</Text>
        <TextInput testID="admin-login-email" style={styles.input} value={email} onChangeText={setEmail} autoCapitalize="none" keyboardType="email-address" placeholder="[email protected]" placeholderTextColor={COLORS.disabledText} />
        <Text style={styles.label}>Password</Text>
        <TextInput testID="admin-login-password" style={styles.input} value={password} onChangeText={setPassword} secureTextEntry placeholder="••••••••" placeholderTextColor={COLORS.disabledText} />
        <TouchableOpacity testID="admin-login-submit" style={[styles.btn, busy && { opacity: 0.6 }]} onPress={submit} disabled={busy} activeOpacity={0.85}>
          {busy ? <ActivityIndicator color="#fff" /> : <Text style={styles.btnText}>Sign in</Text>}
        </TouchableOpacity>
        <TouchableOpacity
          testID="admin-login-forgot"
          onPress={() => router.push('/admin/forgot-password')}
          activeOpacity={0.7}
          style={{ alignSelf: 'center', marginTop: 8 }}
        >
          <Text style={styles.forgotLink}>Forgot password?</Text>
        </TouchableOpacity>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: SPACING.lg, backgroundColor: COLORS.bg, minHeight: '100%' as any },
  card: { backgroundColor: COLORS.surface, padding: SPACING.lg, borderRadius: RADIUS.lg, borderWidth: 1, borderColor: COLORS.border, width: 380, maxWidth: '100%', gap: 4 },
  brandRow: { flexDirection: 'row', alignItems: 'center', gap: 10, marginBottom: 6 },
  brand: { fontSize: FONT.sizes.lg, fontWeight: FONT.weights.bold, color: COLORS.text },
  subtitle: { fontSize: FONT.sizes.sm, color: COLORS.subtext, marginBottom: SPACING.md },
  label: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: SPACING.sm, marginBottom: 4 },
  input: { height: 44, borderRadius: RADIUS.md, borderWidth: 1.5, borderColor: COLORS.border, paddingHorizontal: SPACING.md, color: COLORS.text, fontSize: FONT.sizes.md, backgroundColor: COLORS.bg },
  btn: { marginTop: SPACING.md, height: 46, borderRadius: RADIUS.md, backgroundColor: COLORS.primary, alignItems: 'center', justifyContent: 'center' },
  btnText: { color: '#fff', fontWeight: FONT.weights.bold, fontSize: FONT.sizes.md },
  hint: { fontSize: 11, color: COLORS.subtext, marginTop: SPACING.md, lineHeight: 16 },
  forgotLink: { fontSize: FONT.sizes.sm, color: COLORS.primary, fontWeight: FONT.weights.semibold },
});

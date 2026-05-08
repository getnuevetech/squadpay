import { useState } from 'react';
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  ActivityIndicator,
} from 'react-native';
import { useRouter } from 'expo-router';
import { Lock, ShieldAlert, Sparkles } from 'lucide-react-native';
import { adminApi } from '../../src/adminApi';
import { COLORS, FONT, RADIUS, SPACING } from '../../src/theme';

type Banner = {
  kind: 'error' | 'lock' | 'reset';
  message: string;
} | null;

export default function AdminLogin() {
  const router = useRouter();
  const [email, setEmail] = useState('admin@squadpay.us');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [banner, setBanner] = useState<Banner>(null);

  const submit = async () => {
    setBanner(null);
    if (!email.trim() || !password) {
      setBanner({ kind: 'error', message: 'Enter email and password to continue.' });
      return;
    }
    setBusy(true);
    try {
      await adminApi.login(email.trim().toLowerCase(), password);
      router.replace('/admin/dashboard');
    } catch (e: any) {
      // The adminApi attaches `code` and `data` from the backend's structured detail.
      const code = e?.code as string | undefined;
      const message: string = e?.message || 'Sign-in failed. Please try again.';

      if (code === 'password_reset_required') {
        setBanner({ kind: 'reset', message });
      } else if (code === 'locked') {
        setBanner({ kind: 'lock', message });
      } else if (code === 'invalid_credentials') {
        setBanner({ kind: 'error', message });
      } else {
        // Generic fallback (network / 500 / unknown).
        setBanner({ kind: 'error', message });
      }
      setPassword(''); // clear the password field on every failure
    } finally {
      setBusy(false);
    }
  };

  return (
    <View style={styles.wrap} testID="admin-login">
      <View style={styles.card}>
        <View style={styles.brandRow}>
          <View style={styles.brandIcon}>
            <Sparkles color={COLORS.primary} size={20} strokeWidth={2.4} />
          </View>
          <Text style={styles.brand}>SquadPay Admin</Text>
        </View>
        <Text style={styles.subtitle}>Sign in with your admin email</Text>

        {banner && (
          <View
            style={[
              styles.banner,
              banner.kind === 'lock' && styles.bannerLock,
              banner.kind === 'reset' && styles.bannerReset,
            ]}
            testID={`admin-login-banner-${banner.kind}`}
          >
            {banner.kind === 'reset' ? (
              <ShieldAlert color={COLORS.danger} size={18} />
            ) : banner.kind === 'lock' ? (
              <Lock color={COLORS.warning} size={18} />
            ) : (
              <ShieldAlert color={COLORS.danger} size={18} />
            )}
            <Text
              style={[
                styles.bannerText,
                banner.kind === 'lock' && { color: '#92400E' },
                banner.kind === 'reset' && { color: COLORS.danger },
              ]}
            >
              {banner.message}
            </Text>
          </View>
        )}

        <Text style={styles.label}>Email</Text>
        <TextInput
          testID="admin-login-email"
          style={styles.input}
          value={email}
          onChangeText={(t) => {
            setEmail(t);
            if (banner) setBanner(null);
          }}
          autoCapitalize="none"
          autoCorrect={false}
          keyboardType="email-address"
          placeholder="admin@squadpay.us"
          placeholderTextColor={COLORS.disabledText}
        />

        <Text style={styles.label}>Password</Text>
        <TextInput
          testID="admin-login-password"
          style={styles.input}
          value={password}
          onChangeText={(t) => {
            setPassword(t);
            if (banner) setBanner(null);
          }}
          secureTextEntry
          placeholder="••••••••"
          placeholderTextColor={COLORS.disabledText}
          onSubmitEditing={submit}
        />

        <TouchableOpacity
          testID="admin-login-submit"
          style={[styles.btn, (busy || banner?.kind === 'reset') && { opacity: 0.6 }]}
          onPress={submit}
          disabled={busy || banner?.kind === 'reset'}
          activeOpacity={0.85}
        >
          {busy ? <ActivityIndicator color="#fff" /> : <Text style={styles.btnText}>Sign in</Text>}
        </TouchableOpacity>

        <TouchableOpacity
          testID="admin-login-forgot"
          onPress={() => router.push('/admin/forgot-password')}
          activeOpacity={0.7}
          style={styles.forgotBtn}
        >
          <Text style={styles.forgotLink}>
            {banner?.kind === 'reset' ? 'Reset password now →' : 'Forgot password?'}
          </Text>
        </TouchableOpacity>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: SPACING.lg,
    backgroundColor: COLORS.bg,
    minHeight: '100%' as any,
  },
  card: {
    backgroundColor: COLORS.surface,
    padding: SPACING.lg,
    borderRadius: RADIUS.lg,
    borderWidth: 1,
    borderColor: COLORS.border,
    width: 380,
    maxWidth: '100%',
    gap: 4,
  },
  brandRow: { flexDirection: 'row', alignItems: 'center', gap: 10, marginBottom: 6 },
  brandIcon: {
    width: 36,
    height: 36,
    borderRadius: 12,
    backgroundColor: COLORS.primaryLight,
    alignItems: 'center',
    justifyContent: 'center',
  },
  brand: { fontSize: FONT.sizes.lg, fontWeight: FONT.weights.bold, color: COLORS.text },
  subtitle: { fontSize: FONT.sizes.sm, color: COLORS.subtext, marginBottom: SPACING.md },
  banner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    padding: 12,
    borderRadius: RADIUS.md,
    backgroundColor: COLORS.dangerLight,
    borderWidth: 1,
    borderColor: COLORS.danger,
    marginBottom: 4,
  },
  bannerLock: {
    backgroundColor: COLORS.warningLight,
    borderColor: COLORS.warning,
  },
  bannerReset: {
    backgroundColor: COLORS.dangerLight,
    borderColor: COLORS.danger,
  },
  bannerText: {
    flex: 1,
    fontSize: FONT.sizes.sm,
    color: COLORS.danger,
    lineHeight: 18,
    fontWeight: FONT.weights.medium,
  },
  label: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: SPACING.sm, marginBottom: 4 },
  input: {
    height: 44,
    borderRadius: RADIUS.md,
    borderWidth: 1.5,
    borderColor: COLORS.border,
    paddingHorizontal: SPACING.md,
    color: COLORS.text,
    fontSize: FONT.sizes.md,
    backgroundColor: COLORS.bg,
  },
  btn: {
    marginTop: SPACING.md,
    height: 46,
    borderRadius: RADIUS.md,
    backgroundColor: COLORS.primary,
    alignItems: 'center',
    justifyContent: 'center',
  },
  btnText: { color: '#fff', fontWeight: FONT.weights.bold, fontSize: FONT.sizes.md },
  forgotBtn: { alignSelf: 'center', marginTop: 10, paddingVertical: 4 },
  forgotLink: { fontSize: FONT.sizes.sm, color: COLORS.primary, fontWeight: FONT.weights.semibold },
});

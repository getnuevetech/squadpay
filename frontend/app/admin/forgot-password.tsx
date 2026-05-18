import { useRouter } from 'expo-router';
import { useState } from 'react';
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import { ChevronLeft, MailCheck, Sparkles } from 'lucide-react-native';
import { api } from '../../src/api';
import { COLORS, FONT, RADIUS, SHADOW, SPACING } from '../../src/theme';

export default function AdminForgotPasswordScreen() {
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setError(null);
    const trimmed = email.trim().toLowerCase();
    if (!trimmed || !trimmed.includes('@')) {
      setError('Please enter a valid email address');
      return;
    }
    setBusy(true);
    try {
      await api.adminForgotPassword(trimmed);
      setSent(true);
    } catch (e: any) {
      // Backend always returns 200 to avoid email enumeration, so any error
      // here is a network issue or a 4xx from validation.
      setError(e?.message || 'Could not send reset email. Please try again.');
    } finally {
      setBusy(false);
    }
  };

  if (sent) {
    return (
      <View style={styles.wrap} testID="admin-forgot-sent">
        <View style={[styles.card, SHADOW.md]}>
          <View style={styles.successIcon}>
            <MailCheck color={COLORS.success} size={28} strokeWidth={2.4} />
          </View>
          <Text style={styles.title}>Check your email</Text>
          <Text style={styles.body}>
            If <Text style={styles.bodyEmail}>{email.trim().toLowerCase()}</Text> matches an admin
            account, we just sent a password reset link to it. The link expires in 30 minutes.
          </Text>
          <Text style={styles.bodyMuted}>
            Didn't get it? Check your spam folder, or wait a minute and try again.
          </Text>
          <TouchableOpacity
            testID="admin-forgot-back-to-login"
            style={[styles.btn, { marginTop: SPACING.md }]}
            onPress={() => router.replace('/admin/login')}
            activeOpacity={0.85}
          >
            <Text style={styles.btnText}>Back to sign in</Text>
          </TouchableOpacity>
        </View>
      </View>
    );
  }

  return (
    <KeyboardAvoidingView
      style={{ flex: 1 }}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <View style={styles.wrap} testID="admin-forgot">
        <View style={[styles.card, SHADOW.md]}>
          <TouchableOpacity
            testID="admin-forgot-back"
            onPress={() => router.replace('/admin/login')}
            style={styles.backRow}
            activeOpacity={0.7}
          >
            <ChevronLeft color={COLORS.subtext} size={18} />
            <Text style={styles.backText}>Back to sign in</Text>
          </TouchableOpacity>

          <View style={styles.brandRow}>
            <View style={styles.brandIcon}>
              <Sparkles color={COLORS.primary} size={20} strokeWidth={2.4} />
            </View>
            <Text style={styles.brand}>SquadPay Admin</Text>
          </View>

          <Text style={styles.title}>Forgot your password?</Text>
          <Text style={styles.body}>
            Enter the email tied to your admin account. We'll send you a secure link to set a new
            password.
          </Text>

          <Text style={styles.label}>Email</Text>
          <TextInput
            testID="admin-forgot-email"
            style={styles.input}
            value={email}
            onChangeText={setEmail}
            autoCapitalize="none"
            autoCorrect={false}
            keyboardType="email-address"
            placeholder="admin@getsquadpay.com"
            placeholderTextColor={COLORS.disabledText}
            onSubmitEditing={submit}
          />

          {error ? (
            <Text style={styles.errorText} testID="admin-forgot-error">
              {error}
            </Text>
          ) : null}

          <TouchableOpacity
            testID="admin-forgot-submit"
            style={[styles.btn, busy && { opacity: 0.6 }]}
            onPress={submit}
            disabled={busy}
            activeOpacity={0.85}
          >
            {busy ? (
              <ActivityIndicator color="#fff" />
            ) : (
              <Text style={styles.btnText}>Send reset link</Text>
            )}
          </TouchableOpacity>
        </View>
      </View>
    </KeyboardAvoidingView>
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
  backRow: { flexDirection: 'row', alignItems: 'center', gap: 4, alignSelf: 'flex-start', marginBottom: 8 },
  backText: { color: COLORS.subtext, fontSize: FONT.sizes.sm, fontWeight: FONT.weights.medium },
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
  title: { fontSize: FONT.sizes.xl, fontWeight: FONT.weights.heavy, color: COLORS.text, marginTop: 6 },
  body: { fontSize: FONT.sizes.sm, color: COLORS.subtext, lineHeight: 20, marginTop: 6 },
  bodyMuted: { fontSize: FONT.sizes.xs, color: COLORS.subtext, lineHeight: 18, marginTop: 8 },
  bodyEmail: { color: COLORS.text, fontWeight: FONT.weights.semibold },
  label: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: SPACING.md, marginBottom: 4 },
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
  errorText: { fontSize: FONT.sizes.sm, color: COLORS.danger, marginTop: 8 },
  btn: {
    marginTop: SPACING.md,
    height: 46,
    borderRadius: RADIUS.md,
    backgroundColor: COLORS.primary,
    alignItems: 'center',
    justifyContent: 'center',
  },
  btnText: { color: '#fff', fontWeight: FONT.weights.bold, fontSize: FONT.sizes.md },
  successIcon: {
    width: 56,
    height: 56,
    borderRadius: 18,
    backgroundColor: COLORS.successLight,
    alignSelf: 'flex-start',
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 8,
  },
});

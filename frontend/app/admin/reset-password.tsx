import { useLocalSearchParams, useRouter } from 'expo-router';
import { useEffect, useMemo, useState } from 'react';
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
import { CheckCircle2, Eye, EyeOff, ShieldAlert, Sparkles } from 'lucide-react-native';
import { api } from '../../src/api';
import { COLORS, FONT, RADIUS, SHADOW, SPACING } from '../../src/theme';

type ValidateState = 'loading' | 'valid' | 'invalid' | 'expired';

export default function AdminResetPasswordScreen() {
  const router = useRouter();
  const { token } = useLocalSearchParams<{ token?: string }>();

  const [state, setState] = useState<ValidateState>('loading');
  const [pw1, setPw1] = useState('');
  const [pw2, setPw2] = useState('');
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!token) {
        setState('invalid');
        return;
      }
      try {
        const r = await api.adminValidateResetToken(token);
        if (cancelled) return;
        if (r.valid) {
          setState('valid');
        } else {
          setState(r.reason === 'expired' ? 'expired' : 'invalid');
        }
      } catch {
        if (!cancelled) setState('invalid');
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token]);

  // Cheap client-side strength hint mirrors backend rules.
  const pwError = useMemo(() => {
    if (!pw1) return null;
    if (pw1.length < 10) return 'Password must be at least 10 characters';
    if (pw1.toLowerCase() === pw1 || pw1.toUpperCase() === pw1)
      return 'Mix upper- and lower-case letters';
    if (![...pw1].some((c) => c >= '0' && c <= '9'))
      return 'Include at least one number';
    return null;
  }, [pw1]);

  const submit = async () => {
    setError(null);
    if (!token) return;
    if (pwError) {
      setError(pwError);
      return;
    }
    if (pw1 !== pw2) {
      setError("Passwords don't match");
      return;
    }
    setBusy(true);
    try {
      await api.adminResetPassword(token, pw1);
      setSuccess(true);
    } catch (e: any) {
      setError(e?.message || 'Could not reset password. Please request a new link.');
    } finally {
      setBusy(false);
    }
  };

  // ────────── Loading / invalid / expired states ──────────
  if (state === 'loading') {
    return (
      <View style={styles.wrap}>
        <ActivityIndicator color={COLORS.primary} />
      </View>
    );
  }

  if (state === 'invalid' || state === 'expired') {
    return (
      <View style={styles.wrap} testID="admin-reset-invalid">
        <View style={[styles.card, SHADOW.md]}>
          <View style={styles.warnIcon}>
            <ShieldAlert color={COLORS.danger} size={28} strokeWidth={2.4} />
          </View>
          <Text style={styles.title}>
            {state === 'expired' ? 'Link expired' : 'Invalid link'}
          </Text>
          <Text style={styles.body}>
            {state === 'expired'
              ? 'This reset link has expired. Reset links are valid for 30 minutes — please request a fresh one.'
              : "We couldn't validate this reset link. It may have already been used or copied incorrectly."}
          </Text>
          <TouchableOpacity
            testID="admin-reset-request-new"
            style={[styles.btn, { marginTop: SPACING.md }]}
            onPress={() => router.replace('/admin/forgot-password')}
            activeOpacity={0.85}
          >
            <Text style={styles.btnText}>Request a new link</Text>
          </TouchableOpacity>
        </View>
      </View>
    );
  }

  // ────────── Success state ──────────
  if (success) {
    return (
      <View style={styles.wrap} testID="admin-reset-success">
        <View style={[styles.card, SHADOW.md]}>
          <View style={styles.successIcon}>
            <CheckCircle2 color={COLORS.success} size={28} strokeWidth={2.4} />
          </View>
          <Text style={styles.title}>Password updated</Text>
          <Text style={styles.body}>
            Your admin password has been changed. Sessions on every device have been signed out for
            your security.
          </Text>
          <TouchableOpacity
            testID="admin-reset-go-login"
            style={[styles.btn, { marginTop: SPACING.md }]}
            onPress={() => router.replace('/admin/login')}
            activeOpacity={0.85}
          >
            <Text style={styles.btnText}>Sign in with new password</Text>
          </TouchableOpacity>
        </View>
      </View>
    );
  }

  // ────────── Form (valid token) ──────────
  return (
    <KeyboardAvoidingView
      style={{ flex: 1 }}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <View style={styles.wrap} testID="admin-reset">
        <View style={[styles.card, SHADOW.md]}>
          <View style={styles.brandRow}>
            <View style={styles.brandIcon}>
              <Sparkles color={COLORS.primary} size={20} strokeWidth={2.4} />
            </View>
            <Text style={styles.brand}>SquadPay Admin</Text>
          </View>

          <Text style={styles.title}>Set a new password</Text>
          <Text style={styles.body}>
            Choose a strong password (10+ chars, mix of cases and a number).
          </Text>

          <Text style={styles.label}>New password</Text>
          <View style={styles.inputRow}>
            <TextInput
              testID="admin-reset-pw1"
              style={[styles.input, { flex: 1, paddingRight: 44 }]}
              value={pw1}
              onChangeText={setPw1}
              secureTextEntry={!show}
              placeholder="••••••••••"
              placeholderTextColor={COLORS.disabledText}
            />
            <TouchableOpacity
              onPress={() => setShow((s) => !s)}
              style={styles.eyeBtn}
              hitSlop={10}
            >
              {show ? (
                <EyeOff color={COLORS.subtext} size={18} />
              ) : (
                <Eye color={COLORS.subtext} size={18} />
              )}
            </TouchableOpacity>
          </View>

          <Text style={styles.label}>Confirm new password</Text>
          <TextInput
            testID="admin-reset-pw2"
            style={styles.input}
            value={pw2}
            onChangeText={setPw2}
            secureTextEntry={!show}
            placeholder="••••••••••"
            placeholderTextColor={COLORS.disabledText}
            onSubmitEditing={submit}
          />

          {(error || pwError) && pw1 ? (
            <Text style={styles.errorText} testID="admin-reset-error">
              {error || pwError}
            </Text>
          ) : null}

          <TouchableOpacity
            testID="admin-reset-submit"
            style={[styles.btn, busy && { opacity: 0.6 }]}
            onPress={submit}
            disabled={busy}
            activeOpacity={0.85}
          >
            {busy ? (
              <ActivityIndicator color="#fff" />
            ) : (
              <Text style={styles.btnText}>Update password</Text>
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
  label: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: SPACING.md, marginBottom: 4 },
  inputRow: { position: 'relative', justifyContent: 'center' },
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
  eyeBtn: { position: 'absolute', right: 12, top: 13, padding: 2 },
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
  warnIcon: {
    width: 56,
    height: 56,
    borderRadius: 18,
    backgroundColor: COLORS.dangerLight,
    alignSelf: 'flex-start',
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 8,
  },
});

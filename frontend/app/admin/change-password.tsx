/**
 * Admin — Change password.
 * Soft-nudge target page for super-admins still on the seeded default password.
 * URL: /admin/change-password
 */
import { useState } from 'react';
import {
  ActivityIndicator,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import { useRouter } from 'expo-router';
import { ArrowLeft, KeyRound, Eye, EyeOff, AlertTriangle, CheckCircle2 } from 'lucide-react-native';
import { adminApi } from '../../src/adminApi';
import { COLORS, FONT, RADIUS, SPACING } from '../../src/theme';

export default function AdminChangePasswordPage() {
  const router = useRouter();
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [showPwd, setShowPwd] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const validate = (): string | null => {
    if (!current) return 'Enter your current password.';
    if (!next || next.length < 8) return 'New password must be at least 8 characters.';
    if (next === current) return 'New password must differ from current password.';
    if (next !== confirm) return 'Confirmation does not match the new password.';
    return null;
  };

  const onSubmit = async () => {
    const err = validate();
    if (err) {
      setError(err);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await adminApi.changePassword(current, next);
      setDone(true);
      setTimeout(() => router.replace('/admin/dashboard'), 1500);
    } catch (e: any) {
      setError(e?.message || 'Failed to change password');
    } finally {
      setBusy(false);
    }
  };

  return (
    <ScrollView contentContainerStyle={{ paddingBottom: 80 }} testID="admin-change-password">
      <TouchableOpacity onPress={() => router.back()} style={styles.backBtn} activeOpacity={0.7}>
        <ArrowLeft size={16} color={COLORS.subtext} />
        <Text style={styles.backText}>Back</Text>
      </TouchableOpacity>

      <View style={styles.card}>
        <View style={styles.header}>
          <View style={styles.iconBubble}>
            <KeyRound size={20} color={COLORS.primary} />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.title}>Change password</Text>
            <Text style={styles.subtitle}>
              Rotate the seeded default to something only you know. Used immediately on next sign-in.
            </Text>
          </View>
        </View>

        <Text style={styles.label}>Current password</Text>
        <View style={styles.inputRow}>
          <TextInput
            value={current}
            onChangeText={setCurrent}
            secureTextEntry={!showPwd}
            placeholder="Current password"
            placeholderTextColor={COLORS.disabledText}
            style={styles.input}
            autoCapitalize="none"
            autoCorrect={false}
            testID="admin-cp-current"
          />
        </View>

        <Text style={styles.label}>New password</Text>
        <View style={styles.inputRow}>
          <TextInput
            value={next}
            onChangeText={setNext}
            secureTextEntry={!showPwd}
            placeholder="At least 8 characters"
            placeholderTextColor={COLORS.disabledText}
            style={styles.input}
            autoCapitalize="none"
            autoCorrect={false}
            testID="admin-cp-new"
          />
        </View>

        <Text style={styles.label}>Confirm new password</Text>
        <View style={styles.inputRow}>
          <TextInput
            value={confirm}
            onChangeText={setConfirm}
            secureTextEntry={!showPwd}
            placeholder="Re-type new password"
            placeholderTextColor={COLORS.disabledText}
            style={styles.input}
            autoCapitalize="none"
            autoCorrect={false}
            testID="admin-cp-confirm"
            onSubmitEditing={onSubmit}
            returnKeyType="done"
          />
        </View>

        <TouchableOpacity
          onPress={() => setShowPwd((p) => !p)}
          style={styles.showRow}
          activeOpacity={0.7}
          testID="admin-cp-toggle-visibility"
        >
          {showPwd ? <EyeOff size={14} color={COLORS.subtext} /> : <Eye size={14} color={COLORS.subtext} />}
          <Text style={styles.showText}>{showPwd ? 'Hide passwords' : 'Show passwords'}</Text>
        </TouchableOpacity>

        {error ? (
          <View style={styles.errBox} testID="admin-cp-error">
            <AlertTriangle size={14} color={COLORS.danger} />
            <Text style={styles.errText}>{error}</Text>
          </View>
        ) : null}

        {done ? (
          <View style={styles.okBox} testID="admin-cp-success">
            <CheckCircle2 size={14} color={COLORS.success} />
            <Text style={styles.okText}>Password updated. Redirecting…</Text>
          </View>
        ) : null}

        <TouchableOpacity
          onPress={onSubmit}
          style={[styles.submitBtn, (busy || done) && { opacity: 0.6 }]}
          activeOpacity={0.85}
          disabled={busy || done}
          testID="admin-cp-submit"
        >
          {busy ? (
            <ActivityIndicator color="#fff" />
          ) : (
            <>
              <KeyRound size={14} color="#fff" />
              <Text style={styles.submitText}>Update password</Text>
            </>
          )}
        </TouchableOpacity>
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  backBtn: { flexDirection: 'row', alignItems: 'center', gap: 4, marginBottom: SPACING.md },
  backText: { color: COLORS.subtext, fontSize: FONT.sizes.sm, fontWeight: FONT.weights.medium },
  card: {
    maxWidth: 540,
    padding: SPACING.lg,
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.lg,
    borderWidth: 1,
    borderColor: COLORS.border,
    gap: SPACING.sm,
  },
  header: { flexDirection: 'row', alignItems: 'flex-start', gap: 12, marginBottom: SPACING.md },
  iconBubble: {
    width: 44,
    height: 44,
    borderRadius: 14,
    backgroundColor: COLORS.primaryLight,
    alignItems: 'center',
    justifyContent: 'center',
  },
  title: { fontSize: FONT.sizes.lg, fontWeight: FONT.weights.bold, color: COLORS.text },
  subtitle: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: 2 },
  label: {
    fontSize: FONT.sizes.xs,
    fontWeight: FONT.weights.semibold,
    color: COLORS.subtext,
    marginTop: 6,
    textTransform: 'uppercase',
    letterSpacing: 0.4,
  },
  inputRow: {
    flexDirection: 'row',
    alignItems: 'center',
    borderRadius: RADIUS.md,
    borderWidth: 1,
    borderColor: COLORS.border,
    backgroundColor: COLORS.bg,
    paddingHorizontal: SPACING.md,
    height: 44,
  },
  input: { flex: 1, color: COLORS.text, height: 44, fontSize: FONT.sizes.md, outlineStyle: 'none' as any },
  showRow: { flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 4 },
  showText: { color: COLORS.subtext, fontSize: FONT.sizes.xs },
  errBox: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    paddingHorizontal: 12,
    paddingVertical: 8,
    backgroundColor: COLORS.dangerLight,
    borderRadius: RADIUS.md,
    borderWidth: 1,
    borderColor: COLORS.danger,
    marginTop: 6,
  },
  errText: { color: COLORS.danger, fontSize: FONT.sizes.sm, flex: 1 },
  okBox: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    paddingHorizontal: 12,
    paddingVertical: 8,
    backgroundColor: COLORS.successLight,
    borderRadius: RADIUS.md,
    borderWidth: 1,
    borderColor: COLORS.success,
    marginTop: 6,
  },
  okText: { color: COLORS.success, fontSize: FONT.sizes.sm, flex: 1 },
  submitBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    height: 44,
    borderRadius: RADIUS.md,
    backgroundColor: COLORS.primary,
    marginTop: SPACING.md,
  },
  submitText: { color: '#fff', fontWeight: FONT.weights.bold, fontSize: FONT.sizes.sm },
});

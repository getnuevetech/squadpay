import { useRouter } from 'expo-router';
import { useState, useEffect } from 'react';
import {
  Alert,
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import { Button } from '../src/Button';
import { api } from '../src/api';
import { saveUser } from '../src/session';
import { COLORS, FONT, RADIUS, SPACING } from '../src/theme';

type Step = 'name' | 'phone' | 'otp';

export default function AuthScreen() {
  const router = useRouter();
  const [step, setStep] = useState<Step>('name');
  const [name, setName] = useState('');
  const [phone, setPhone] = useState('');
  const [otp, setOtp] = useState('');
  const [userId, setUserId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  // C1: optional referral code at signup
  const [showRefCode, setShowRefCode] = useState(false);
  const [refCode, setRefCode] = useState('');
  const [refValidated, setRefValidated] = useState<{ name: string; bonus: number } | null>(null);
  const [refError, setRefError] = useState<string | null>(null);
  // Polish: resend timer for OTP
  const [resendIn, setResendIn] = useState(0);
  const [resending, setResending] = useState(false);
  useEffect(() => {
    if (step !== 'otp') return;
    if (resendIn <= 0) return;
    const t = setTimeout(() => setResendIn((s) => Math.max(0, s - 1)), 1000);
    return () => clearTimeout(t);
  }, [step, resendIn]);
  const startResendCooldown = () => setResendIn(30);
  const onResend = async () => {
    if (!userId || !phone || resendIn > 0) return;
    setResending(true);
    try {
      await api.sendOtp(userId, phone);
      startResendCooldown();
    } catch (e: any) {
      Alert.alert('Could not resend', e?.message || 'Try again');
    } finally {
      setResending(false);
    }
  };

  const validateRefCode = async (code: string) => {
    const c = code.trim().toUpperCase();
    if (!c) {
      setRefValidated(null);
      setRefError(null);
      return;
    }
    try {
      const r = await api.lookupReferral(c);
      setRefValidated({ name: r.referrer_name, bonus: r.settings?.enabled ? r.settings.referee_credit : 0 });
      setRefError(null);
    } catch (e: any) {
      setRefValidated(null);
      setRefError(e?.message || 'Invalid code');
    }
  };

  const submitName = async () => {
    if (!name.trim()) {
      Alert.alert('Name required');
      return;
    }
    if (refError) {
      Alert.alert('Referral code', refError);
      return;
    }
    setLoading(true);
    try {
      const u = await api.register(name.trim(), refCode.trim() ? refCode.trim().toUpperCase() : undefined);
      setUserId(u.id);
      await saveUser(u);
      setStep('phone');
    } catch (e: any) {
      Alert.alert('Error', e.message);
    } finally {
      setLoading(false);
    }
  };

  const submitPhone = async () => {
    if (!userId) return;
    const cleaned = phone.trim();
    if (cleaned.length < 7) {
      Alert.alert('Enter a valid phone number');
      return;
    }
    setLoading(true);
    try {
      await api.sendOtp(userId, cleaned);
      setStep('otp');
      startResendCooldown();
    } catch (e: any) {
      Alert.alert('Error', e.message);
    } finally {
      setLoading(false);
    }
  };

  const submitOtp = async () => {
    if (!userId) return;
    if (otp.length !== 6) {
      Alert.alert('Enter 6-digit code');
      return;
    }
    setLoading(true);
    try {
      const verified = await api.verifyOtp(userId, phone.trim(), otp);
      await saveUser(verified);
      router.replace('/');
    } catch (e: any) {
      Alert.alert('Invalid code', e.message);
    } finally {
      setLoading(false);
    }
  };

  const skipPhone = async () => {
    // Let user proceed with just name; they will be forced to verify before paying
    router.replace('/');
  };

  return (
    <KeyboardAvoidingView
      behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
      style={{ flex: 1, backgroundColor: COLORS.bg }}
    >
      <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
        {step === 'name' && (
          <View testID="auth-step-name">
            <Text style={styles.title}>What's your name?</Text>
            <Text style={styles.sub}>Friends will see this when you join a bill.</Text>
            <TextInput
              testID="auth-name-input"
              value={name}
              onChangeText={setName}
              placeholder="Alex"
              placeholderTextColor={COLORS.disabledText}
              style={styles.input}
              autoFocus
              returnKeyType="next"
              onSubmitEditing={submitName}
            />
            {/* C1: optional referral code */}
            {!showRefCode ? (
              <Text
                onPress={() => setShowRefCode(true)}
                style={styles.refToggle}
                testID="auth-ref-toggle"
              >
                Have a referral code?
              </Text>
            ) : (
              <View style={styles.refBox} testID="auth-ref-box">
                <Text style={styles.refLabel}>Referral code (optional)</Text>
                <TextInput
                  testID="auth-ref-input"
                  value={refCode}
                  onChangeText={(t) => {
                    const v = t.replace(/[^A-Za-z0-9]/g, '').toUpperCase().slice(0, 8);
                    setRefCode(v);
                  }}
                  onBlur={() => validateRefCode(refCode)}
                  placeholder="ABC123"
                  placeholderTextColor={COLORS.disabledText}
                  style={[styles.input, { letterSpacing: 4, textAlign: 'center', height: 48, fontSize: FONT.sizes.lg }]}
                  autoCapitalize="characters"
                  maxLength={8}
                />
                {refValidated ? (
                  <Text style={styles.refOk} testID="auth-ref-valid">
                    ✓ Invited by {refValidated.name}
                    {refValidated.bonus > 0 ? ` — get $${refValidated.bonus.toFixed(2)} welcome bonus` : ''}
                  </Text>
                ) : refError ? (
                  <Text style={styles.refErr} testID="auth-ref-err">{refError}</Text>
                ) : (
                  <Text style={styles.refHint}>Code given by a friend? Paste it here.</Text>
                )}
              </View>
            )}
            <Button
              title="Continue"
              onPress={submitName}
              loading={loading}
              testID="auth-name-continue-btn"
              style={{ marginTop: SPACING.lg }}
            />
          </View>
        )}

        {step === 'phone' && (
          <View testID="auth-step-phone">
            <Text style={styles.title}>Add your phone</Text>
            <Text style={styles.sub}>
              Required to pay or receive money. We'll send a 6-digit code.
            </Text>
            <TextInput
              testID="auth-phone-input"
              value={phone}
              onChangeText={setPhone}
              placeholder="+1 555 123 4567"
              placeholderTextColor={COLORS.disabledText}
              style={styles.input}
              keyboardType="phone-pad"
              autoFocus
              returnKeyType="next"
              onSubmitEditing={submitPhone}
            />
            <Button
              title="Send code"
              onPress={submitPhone}
              loading={loading}
              testID="auth-phone-continue-btn"
              style={{ marginTop: SPACING.lg }}
            />
            <Button
              title="Skip for now"
              onPress={skipPhone}
              variant="ghost"
              testID="auth-phone-skip-btn"
              style={{ marginTop: SPACING.sm }}
            />
          </View>
        )}

        {step === 'otp' && (
          <View testID="auth-step-otp">
            <Text style={styles.title}>Enter the code</Text>
            <Text style={styles.sub}>
              We sent a 6-digit code to {phone}. For demo, use <Text style={{ fontWeight: '700' }}>123456</Text>.
            </Text>
            <TextInput
              testID="auth-otp-input"
              value={otp}
              onChangeText={(t) => setOtp(t.replace(/\D/g, '').slice(0, 6))}
              placeholder="123456"
              placeholderTextColor={COLORS.disabledText}
              style={[styles.input, styles.otpInput]}
              keyboardType="number-pad"
              autoFocus
              maxLength={6}
            />
            <Button
              title="Verify"
              onPress={submitOtp}
              loading={loading}
              testID="auth-otp-verify-btn"
              style={{ marginTop: SPACING.lg }}
            />
            <TouchableOpacity
              onPress={onResend}
              disabled={resendIn > 0 || resending}
              activeOpacity={0.7}
              style={{ alignSelf: 'center', marginTop: SPACING.md }}
              testID="auth-otp-resend"
            >
              <Text style={[styles.resendText, (resendIn > 0 || resending) && { color: COLORS.disabledText }]}>
                {resending ? 'Sending…' : resendIn > 0 ? `Resend code in ${resendIn}s` : 'Didn\u2019t get the code? Resend'}
              </Text>
            </TouchableOpacity>
          </View>
        )}
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  content: { padding: SPACING.lg, paddingTop: SPACING.xl },
  title: {
    fontSize: FONT.sizes.xxl,
    fontWeight: FONT.weights.bold,
    color: COLORS.text,
    marginBottom: SPACING.sm,
    letterSpacing: -0.5,
  },
  sub: { fontSize: FONT.sizes.md, color: COLORS.subtext, marginBottom: SPACING.lg, lineHeight: 22 },
  input: {
    height: 56,
    borderRadius: RADIUS.md,
    borderWidth: 1.5,
    borderColor: COLORS.border,
    paddingHorizontal: SPACING.md,
    fontSize: FONT.sizes.lg,
    color: COLORS.text,
    backgroundColor: COLORS.surface,
  },
  otpInput: {
    letterSpacing: 8,
    textAlign: 'center',
    fontWeight: FONT.weights.bold,
  },
  refToggle: { color: COLORS.primary, fontSize: FONT.sizes.sm, fontWeight: FONT.weights.semibold, marginTop: SPACING.md, textDecorationLine: 'underline' },
  refBox: { marginTop: SPACING.md, padding: SPACING.md, backgroundColor: COLORS.primaryLight, borderRadius: RADIUS.md, borderWidth: 1, borderColor: COLORS.primary },
  refLabel: { fontSize: FONT.sizes.xs, color: COLORS.primary, fontWeight: FONT.weights.bold, textTransform: 'uppercase', marginBottom: SPACING.sm },
  refOk: { color: COLORS.success, fontSize: FONT.sizes.sm, marginTop: SPACING.sm, fontWeight: FONT.weights.semibold },
  refErr: { color: COLORS.danger, fontSize: FONT.sizes.sm, marginTop: SPACING.sm, fontWeight: FONT.weights.semibold },
  refHint: { color: COLORS.subtext, fontSize: FONT.sizes.xs, marginTop: SPACING.sm, fontStyle: 'italic' },
  resendText: { color: COLORS.primary, fontSize: FONT.sizes.sm, fontWeight: FONT.weights.semibold, textDecorationLine: 'underline' },
});

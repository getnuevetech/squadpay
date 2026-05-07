import { useRouter, useLocalSearchParams } from 'expo-router';
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
import { ArrowLeft } from 'lucide-react-native';
import { Button } from '../src/Button';
import { api } from '../src/api';
import { saveUser, loadUser } from '../src/session';
import { COLORS, FONT, RADIUS, SPACING } from '../src/theme';

type Step = 'name' | 'phone' | 'otp';

export default function AuthScreen() {
  const router = useRouter();
  // Phase H6.3 — when redirected from /home with `?mode=verify&user_id=...` we
  // skip the name step entirely and go straight to phone capture for the
  // existing (unverified) account.
  const params = useLocalSearchParams<{ mode?: string; user_id?: string }>();
  const verifyMode = params.mode === 'verify' && !!params.user_id;
  const [step, setStep] = useState<Step>(verifyMode ? 'phone' : 'name');
  const [name, setName] = useState('');
  const [phone, setPhone] = useState('');
  const [otp, setOtp] = useState('');
  const [userId, setUserId] = useState<string | null>(verifyMode ? (params.user_id as string) : null);
  const [loading, setLoading] = useState(false);
  // C1: optional referral code at signup
  const [showRefCode, setShowRefCode] = useState(false);
  const [refCode, setRefCode] = useState('');
  const [refValidated, setRefValidated] = useState<{ name: string; bonus: number } | null>(null);
  const [refError, setRefError] = useState<string | null>(null);

  // Phase H6.3 — when starting in verify mode, prefill the existing user's name
  // so it can be shown above the phone input ("Verifying for: Alex").
  useEffect(() => {
    if (verifyMode && params.user_id) {
      (async () => {
        try {
          const u = await loadUser();
          if (u && u.id === params.user_id) setName(u.name);
        } catch {}
      })();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [verifyMode, params.user_id]);
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
      // Phase H2 — pre-flight: detect "phone already registered to another account"
      // BEFORE we hand over the OTP, so we can ask the user before merging.
      let confirmExisting = false;
      try {
        const lookup = await api.lookupPhone(phone.trim(), userId);
        if (lookup?.exists && !lookup.blocked && lookup.name) {
          // Lookup already excludes the current placeholder, so any hit means
          // a different verified account owns this phone.
          const proceed = await new Promise<boolean>((resolve) => {
            Alert.alert(
              'Phone already registered',
              `An account with this number is already registered as "${lookup.name}".\n\nDo you want to sign in to that account? Your current name "${name}" will be replaced with "${lookup.name}", and any group you started will stay yours under the registered name.`,
              [
                { text: 'Cancel', style: 'cancel', onPress: () => resolve(false) },
                { text: `Use ${lookup.name}`, onPress: () => resolve(true) },
              ],
              { cancelable: false },
            );
          });
          if (!proceed) {
            setLoading(false);
            return;
          }
          confirmExisting = true;
        } else if (lookup?.blocked) {
          Alert.alert('Account blocked', 'This phone number is associated with a blocked account. Please contact support.');
          setLoading(false);
          return;
        }
      } catch (e) {
        // lookup is best-effort; if it fails we continue and rely on the
        // server's 409 fallback.
      }

      try {
        const verified = await api.verifyOtp(userId, phone.trim(), otp, confirmExisting);
        await saveUser(verified);
        router.replace('/');
      } catch (e: any) {
        // Server fallback: if lookup didn't run (e.g. offline) and the server
        // returned 409 phone_already_registered, surface the same prompt here.
        const msg = String(e?.message || '');
        if (msg.includes('phone_already_registered') || msg.includes('already registered')) {
          const proceed = await new Promise<boolean>((resolve) => {
            Alert.alert(
              'Phone already registered',
              'An account with this number is already registered. Do you want to sign in to that account?',
              [
                { text: 'Cancel', style: 'cancel', onPress: () => resolve(false) },
                { text: 'Use existing', onPress: () => resolve(true) },
              ],
              { cancelable: false },
            );
          });
          if (proceed) {
            const verified = await api.verifyOtp(userId, phone.trim(), otp, true);
            await saveUser(verified);
            router.replace('/');
          }
        } else {
          throw e;
        }
      }
    } catch (e: any) {
      Alert.alert('Invalid code', e.message || 'Verification failed');
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
      {/* Phase H6.3 — back button. Visible on every step:
            • step=name  → routes to / (home/welcome)
            • step=phone → if verifyMode, routes to /; else step=name
            • step=otp   → step=phone (re-enter number) */}
      <View style={styles.topBar}>
        <TouchableOpacity
          onPress={() => {
            if (step === 'otp') { setOtp(''); setStep('phone'); return; }
            if (step === 'phone' && !verifyMode) { setStep('name'); return; }
            router.replace('/');
          }}
          style={styles.backBtn}
          hitSlop={12}
          testID="auth-back-btn"
          activeOpacity={0.7}
        >
          <ArrowLeft size={20} color={COLORS.text} />
          <Text style={styles.backText}>Home</Text>
        </TouchableOpacity>
      </View>
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
  topBar: {
    paddingTop: Platform.OS === 'ios' ? 56 : 16,
    paddingHorizontal: SPACING.lg,
    paddingBottom: SPACING.sm,
  },
  backBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    alignSelf: 'flex-start',
    paddingHorizontal: 8,
    paddingVertical: 6,
    borderRadius: RADIUS.md,
  },
  backText: {
    fontSize: FONT.sizes.md,
    color: COLORS.text,
    fontWeight: FONT.weights.semibold,
  },
  content: { padding: SPACING.lg, paddingTop: SPACING.md },
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

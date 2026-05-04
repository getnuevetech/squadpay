import { useRouter } from 'expo-router';
import { useState } from 'react';
import {
  Alert,
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
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

  const submitName = async () => {
    if (!name.trim()) {
      Alert.alert('Name required');
      return;
    }
    setLoading(true);
    try {
      const u = await api.register(name.trim());
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
});

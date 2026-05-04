import { useLocalSearchParams, useRouter } from 'expo-router';
import { useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  KeyboardAvoidingView,
  Platform,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { QrCode } from 'lucide-react-native';
import { Button } from '../../src/Button';
import { api } from '../../src/api';
import { loadUser } from '../../src/session';
import { COLORS, FONT, RADIUS, SPACING } from '../../src/theme';

export default function JoinScreen() {
  const { code } = useLocalSearchParams<{ code: string }>();
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [inputCode, setInputCode] = useState('');
  const [joining, setJoining] = useState(false);

  const tryJoin = async (joinCode: string) => {
    const u = await loadUser();
    if (!u) {
      router.replace('/auth');
      return;
    }
    setJoining(true);
    try {
      const group = await api.getGroupByCode(joinCode);
      await api.joinGroup(group.id, u.id);
      router.replace(`/group/${group.id}`);
    } catch (e: any) {
      Alert.alert('Join failed', e.message);
      setLoading(false);
    } finally {
      setJoining(false);
    }
  };

  useEffect(() => {
    if (code && code !== 'code' && code.length >= 4) {
      tryJoin(code);
    } else {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [code]);

  if (loading || joining) {
    return (
      <SafeAreaView style={styles.center}>
        <ActivityIndicator color={COLORS.primary} />
        <Text style={styles.loadingText}>Joining bill...</Text>
      </SafeAreaView>
    );
  }

  return (
    <KeyboardAvoidingView
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      style={{ flex: 1, backgroundColor: COLORS.bg }}
    >
      <SafeAreaView style={styles.container}>
        <View style={styles.iconWrap}>
          <QrCode size={40} color={COLORS.primary} />
        </View>
        <Text style={styles.title}>Join a bill</Text>
        <Text style={styles.sub}>Enter the 8-character code from the lead.</Text>
        <TextInput
          testID="join-code-input"
          value={inputCode}
          onChangeText={(t) => setInputCode(t.trim())}
          placeholder="e.g. 8f3kL2pQ"
          placeholderTextColor={COLORS.disabledText}
          style={styles.input}
          autoCapitalize="none"
          autoCorrect={false}
        />
        <Button
          title="Join"
          testID="join-submit-btn"
          onPress={() => tryJoin(inputCode)}
          disabled={!inputCode}
          style={{ marginTop: SPACING.md }}
        />
      </SafeAreaView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: SPACING.lg, paddingTop: SPACING.xxl, alignItems: 'stretch' },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: SPACING.md, backgroundColor: COLORS.bg },
  loadingText: { color: COLORS.subtext, fontSize: FONT.sizes.sm },
  iconWrap: {
    width: 72,
    height: 72,
    borderRadius: 18,
    backgroundColor: COLORS.primaryLight,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: SPACING.lg,
  },
  title: {
    fontSize: FONT.sizes.xxl,
    fontWeight: FONT.weights.bold,
    color: COLORS.text,
    letterSpacing: -0.5,
  },
  sub: { fontSize: FONT.sizes.md, color: COLORS.subtext, marginTop: SPACING.sm, marginBottom: SPACING.lg },
  input: {
    height: 56,
    borderRadius: RADIUS.md,
    borderWidth: 1.5,
    borderColor: COLORS.border,
    backgroundColor: COLORS.surface,
    paddingHorizontal: SPACING.md,
    fontSize: FONT.sizes.lg,
    color: COLORS.text,
    letterSpacing: 2,
  },
});

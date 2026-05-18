import { useLocalSearchParams, useRouter } from 'expo-router';
import { useEffect, useState } from 'react';
import {
  KeyboardAvoidingView,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { QrCode, Camera as CameraIcon } from 'lucide-react-native';
import { Button } from '../../src/Button';
import { api } from '../../src/api';
import { loadUser } from '../../src/session';
import { COLORS, FONT, RADIUS, SPACING } from '../../src/theme';
import { toast } from '../../src/components/Toast';
import { friendlyError } from '../../src/errors';
import { Skeleton } from '../../src/components/Skeleton';
import { QRScannerModal } from '../../src/QRScannerModal';

/** Pull a SquadPay invite code out of either a raw code or a join URL.
 *  We expect codes to be 4-12 alphanumeric chars; URLs look like
 *  `https://www.getsquadpay.com/join/ABC12345`. We also handle the deep link
 *  scheme `squadpay://join/ABC12345`. */
function extractCode(raw: string): string {
  const s = (raw || '').trim();
  // URL or deep-link form → grab the last non-empty segment.
  const m = s.match(/(?:join\/)([A-Za-z0-9]{4,12})/i);
  if (m) return m[1];
  // Otherwise treat the entire string as the code (after stripping whitespace).
  return s;
}

export default function JoinScreen() {
  const { code } = useLocalSearchParams<{ code: string }>();
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [inputCode, setInputCode] = useState('');
  const [joining, setJoining] = useState(false);
  const [scannerOpen, setScannerOpen] = useState(false);

  const tryJoin = async (joinCode: string, source: 'code' | 'qr' | 'link' = 'code') => {
    const u = await loadUser();
    if (!u) {
      router.replace('/auth');
      return;
    }
    setJoining(true);
    try {
      const group = await api.getGroupByCode(joinCode);
      // Pass `source` so the backend logs how the member joined (Item 6).
      await api.joinGroup(group.id, u.id, source);
      // June 2025 — after a successful join, send the user STRAIGHT to their
      // squad dashboard (User Dashboard) instead of the invite/lobby page.
      // If the joiner happens to be the lead (rare — they'd already be in
      // the squad), the dashboard route auto-redirects to the Lead Dashboard.
      router.replace(`/group/${group.id}/summary`);
    } catch (e: any) {
      toast.error(friendlyError(e, "We couldn't add you to that Squad. Check the code and try again."));
      setLoading(false);
    } finally {
      setJoining(false);
    }
  };

  useEffect(() => {
    if (code && code !== 'code' && code.length >= 4) {
      // Joined via a Universal Link / deep link.
      tryJoin(code, 'link');
    } else {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [code]);

  const handleScanned = (data: string) => {
    setScannerOpen(false);
    const extracted = extractCode(data);
    if (!extracted) {
      toast.error('No SquadPay code found in that QR.');
      return;
    }
    setInputCode(extracted);
    // Auto-join after a successful scan — saves a tap.
    tryJoin(extracted, 'qr');
  };

  if (loading || joining) {
    return (
      <SafeAreaView style={styles.center} testID="join-loading">
        <View style={{ alignItems: 'center', gap: 16 }}>
          <Skeleton width={56} height={56} radius={28} />
          <Skeleton width={180} height={18} />
          <Skeleton width={120} height={12} />
        </View>
        <Text style={[styles.loadingText, { marginTop: 16 }]}>Joining bill…</Text>
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
        <Text style={styles.sub}>Scan the QR or enter the 8-character code from the lead.</Text>

        {/* NEW (Item 4) — scan a QR code with the phone camera */}
        <Pressable
          onPress={() => setScannerOpen(true)}
          style={styles.scanCta}
          testID="join-scan-qr-btn"
          android_ripple={{ color: 'rgba(255,255,255,0.15)' }}
        >
          <CameraIcon size={20} color="#fff" />
          <Text style={styles.scanCtaText}>Scan QR code</Text>
        </Pressable>

        <View style={styles.dividerRow}>
          <View style={styles.divider} />
          <Text style={styles.dividerText}>or enter code</Text>
          <View style={styles.divider} />
        </View>

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
          onPress={() => tryJoin(inputCode, 'code')}
          disabled={!inputCode}
          style={{ marginTop: SPACING.md }}
        />
      </SafeAreaView>

      <QRScannerModal
        visible={scannerOpen}
        onClose={() => setScannerOpen(false)}
        onScanned={handleScanned}
        prompt="Scan the SquadPay QR code"
      />
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
  scanCta: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    backgroundColor: COLORS.primary,
    paddingVertical: 14,
    borderRadius: RADIUS.md,
  },
  scanCtaText: { color: '#fff', fontWeight: FONT.weights.bold, fontSize: FONT.sizes.md },
  dividerRow: { flexDirection: 'row', alignItems: 'center', gap: SPACING.sm, marginVertical: SPACING.lg },
  divider: { flex: 1, height: 1, backgroundColor: COLORS.border },
  dividerText: { color: COLORS.subtext, fontSize: FONT.sizes.xs, textTransform: 'uppercase', letterSpacing: 1 },
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

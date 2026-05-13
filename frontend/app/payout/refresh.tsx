/**
 * Stripe Connect Express REFRESH handler.
 *
 * Stripe redirects here when an onboarding AccountLink expires (they
 * have a short TTL, ~5 min). Our job is to mint a fresh AccountLink
 * and either deep-link the user back into Stripe's flow, or — on web —
 * bounce them back into the cash-out screen so it can request a new
 * link itself.
 *
 * We keep the page deliberately thin: no card resync, no eligibility
 * polling. Those happen on the `return` route and inside cash-out.tsx.
 */
import { useEffect } from 'react';
import { ActivityIndicator, StyleSheet, Text, View } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { RefreshCw } from 'lucide-react-native';
import { COLORS, FONT, SPACING } from '../../src/theme';

export default function PayoutRefreshScreen() {
  const router = useRouter();
  const { group_id } = useLocalSearchParams<{ group_id?: string }>();

  useEffect(() => {
    const t = setTimeout(() => {
      const dest = group_id ? `/payout/cash-out?group_id=${group_id}` : '/payout/cash-out';
      router.replace(dest);
    }, 600);
    return () => clearTimeout(t);
  }, [group_id, router]);

  return (
    <SafeAreaView style={styles.root} edges={['top', 'bottom']}>
      <View style={styles.body}>
        <RefreshCw size={48} color={COLORS.primary} />
        <Text style={styles.title}>Refreshing your session…</Text>
        <Text style={styles.sub}>One moment — re-opening Stripe onboarding.</Text>
        <ActivityIndicator color={COLORS.primary} style={{ marginTop: SPACING.lg }} />
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: COLORS.bg },
  body: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: SPACING.xl,
  },
  title: {
    marginTop: SPACING.md,
    fontSize: FONT.sizes.xl,
    fontWeight: FONT.weights.heavy,
    color: COLORS.text,
    textAlign: 'center',
  },
  sub: {
    marginTop: SPACING.sm,
    fontSize: FONT.sizes.md,
    color: COLORS.subtext,
    textAlign: 'center',
  },
});

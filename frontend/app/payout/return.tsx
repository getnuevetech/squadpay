/**
 * Stripe Connect Express RETURN handler.
 *
 * Stripe redirects the lead here after completing (or skipping) onboarding.
 * The page itself does no UX heavy-lifting — its job is to bridge from the
 * browser tab (Stripe's hosted onboarding page) back into the SquadPay
 * app/web session, then forward the user into the Pay Out screen so the
 * cash-out flow can re-sync `payouts_enabled` against Stripe and show
 * either the amount form or a "still pending verification" notice.
 *
 * Notes
 * -----
 * • This route is registered in app.json's iOS associatedDomains +
 *   Android intent filters so on mobile, the redirect deep-links straight
 *   into the app (skipping the browser). On web it lands here normally.
 * • We forward `group_id` if Stripe preserved it as a query param so the
 *   user returns to the same squad's pay-out flow they started.
 * • We use router.replace (not push) so the back button doesn't take the
 *   user back to Stripe's onboarding page.
 */
import { useEffect } from 'react';
import { ActivityIndicator, StyleSheet, Text, View } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { CheckCircle2 } from 'lucide-react-native';
import { COLORS, FONT, SPACING } from '../../src/theme';

export default function PayoutReturnScreen() {
  const router = useRouter();
  // Stripe doesn't echo query params by default, but if our onboarding
  // helper bundled `group_id` into the return URL we forward it.
  const { group_id } = useLocalSearchParams<{ group_id?: string }>();

  useEffect(() => {
    // Tiny delay so the user sees the success affordance for ~600ms
    // before we whisk them back to the cash-out screen.
    const t = setTimeout(() => {
      const dest = group_id ? `/payout/cash-out?group_id=${group_id}` : '/payout/cash-out';
      router.replace(dest);
    }, 700);
    return () => clearTimeout(t);
  }, [group_id, router]);

  return (
    <SafeAreaView style={styles.root} edges={['top', 'bottom']}>
      <View style={styles.body}>
        <View style={styles.iconWrap}>
          <CheckCircle2 size={56} color={COLORS.primary} />
        </View>
        <Text style={styles.title}>Verification submitted</Text>
        <Text style={styles.sub}>
          Stripe is reviewing your details. Hang tight — taking you back to Pay Out…
        </Text>
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
  iconWrap: { marginBottom: SPACING.md },
  title: {
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
    lineHeight: 22,
  },
});

import { useLocalSearchParams, useRouter } from 'expo-router';
import { useEffect, useState } from 'react';
import { Linking, Pressable, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { CheckCircle2, Coins, ExternalLink } from 'lucide-react-native';
import { Button } from '../../../src/Button';
import { COLORS, FONT, RADIUS, SPACING } from '../../../src/theme';

export default function SuccessScreen() {
  const { id, amount, kind, via } = useLocalSearchParams<{
    id: string;
    amount?: string;
    kind?: string;
    via?: string;
  }>();
  const router = useRouter();

  const amt = parseFloat(amount || '0').toFixed(2);
  const isLeadPay = kind === 'lead';
  const isContribute = kind === 'contribute';
  const viaStripe = via === 'stripe';

  // Credit awards passed through global cache (set by the contribute flow
  // when it observes `awarded_credits` in the API response). We read from
  // a global so the success screen can render the badge without re-fetching.
  const [credits, setCredits] = useState<any[]>(() => {
    try {
      const g: any = globalThis as any;
      const arr = g.__SQUADPAY_AWARDED_CREDITS__ || [];
      g.__SQUADPAY_AWARDED_CREDITS__ = [];
      return Array.isArray(arr) ? arr : [];
    } catch { return []; }
  });
  useEffect(() => () => setCredits([]), []);
  const totalCredit = credits.reduce((s, c) => s + (Number(c.amount) || 0), 0);

  return (
    <SafeAreaView edges={['top', 'bottom']} style={{ flex: 1, backgroundColor: COLORS.bg }}>
      <View style={styles.container}>
        <View style={styles.icon}>
          <CheckCircle2 color={COLORS.success} size={96} strokeWidth={2.2} />
        </View>
        <Text style={styles.title} testID="success-title">
          {isLeadPay ? 'Bill paid!' : isContribute ? 'Contributed!' : 'Payment sent!'}
        </Text>
        <Text style={styles.amount}>${amt}</Text>
        {viaStripe ? (
          <View style={styles.stripeChip} testID="success-via-stripe">
            <Text style={styles.stripeChipText}>✓ Paid via Stripe</Text>
          </View>
        ) : null}
        <Text style={styles.sub} testID="success-subtitle">
          {isLeadPay
            ? viaStripe
              ? "Stripe charged the bill in full. We'll continue tracking repayments from your group."
              : "You paid the restaurant. We'll track repayments from your group."
            : isContribute
            ? "Your contribution is now in the Squad Wallet, the Squad Lead will pay the Merchant."
            : 'Your repayment has been recorded.'}
        </Text>

        {credits.length > 0 ? (
          <View style={styles.creditCard} testID="success-credit-badge">
            <View style={styles.creditHeader}>
              <Coins size={20} color="#fff" />
              <Text style={styles.creditHeaderText}>You earned a credit!</Text>
            </View>
            <Text style={styles.creditAmount} testID="success-credit-amount">
              +${totalCredit.toFixed(2)}
            </Text>
            {credits.map((c, idx) => (
              <Text key={idx} style={styles.creditMessage}>{c.message || c.rule_name}</Text>
            ))}
            <Pressable
              onPress={() => Linking.openURL('/legal/terms?section=credits' as any).catch(() => router.push('/legal/terms?section=credits' as any))}
              style={styles.tcRow}
              testID="success-credit-tc-link"
            >
              <ExternalLink size={12} color="rgba(255,255,255,0.9)" />
              <Text style={styles.tcText}>Terms & Conditions Applied \u2014 view credits clause</Text>
            </Pressable>
          </View>
        ) : null}
        <View style={styles.actions}>
          {isLeadPay ? (
            <Button
              title="Track repayments"
              onPress={() => router.replace(`/group/${id}/dashboard`)}
              testID="success-dashboard-btn"
            />
          ) : (
            <Button
              title="Done"
              onPress={() => router.replace(`/group/${id}/summary`)}
              testID="success-done-btn"
            />
          )}
          <Button
            title="Back to Home"
            variant="ghost"
            onPress={() => router.replace('/')}
            testID="success-home-btn"
            style={{ marginTop: SPACING.sm }}
          />
        </View>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: SPACING.xl,
  },
  icon: {
    width: 140,
    height: 140,
    borderRadius: 70,
    backgroundColor: COLORS.successLight,
    alignItems: 'center',
    justifyContent: 'center',
  },
  title: {
    marginTop: SPACING.lg,
    fontSize: FONT.sizes.xxl,
    fontWeight: FONT.weights.bold,
    color: COLORS.text,
    letterSpacing: -0.5,
  },
  amount: {
    fontSize: 56,
    fontWeight: FONT.weights.heavy,
    color: COLORS.success,
    letterSpacing: -1,
    marginTop: SPACING.sm,
  },
  sub: {
    textAlign: 'center',
    fontSize: FONT.sizes.md,
    color: COLORS.subtext,
    marginTop: SPACING.md,
    lineHeight: 22,
    maxWidth: 320,
  },
  actions: { alignSelf: 'stretch', marginTop: SPACING.xxl },
  stripeChip: { marginTop: SPACING.sm, paddingHorizontal: 12, paddingVertical: 4, borderRadius: 999, backgroundColor: '#635BFF' + '22', borderWidth: 1, borderColor: '#635BFF' },
  stripeChipText: { color: '#635BFF', fontSize: FONT.sizes.xs, fontWeight: FONT.weights.bold, letterSpacing: 0.5 },
  // Credit-earned celebratory card. The amount is BIG so the user can't miss it.
  creditCard: {
    alignSelf: 'stretch',
    marginTop: SPACING.lg,
    borderRadius: RADIUS.lg,
    backgroundColor: '#7c3aed',
    paddingVertical: SPACING.md,
    paddingHorizontal: SPACING.lg,
    alignItems: 'center',
    shadowColor: '#7c3aed',
    shadowOffset: { width: 0, height: 6 },
    shadowOpacity: 0.35,
    shadowRadius: 16,
    elevation: 6,
  },
  creditHeader: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  creditHeaderText: { color: '#fff', fontSize: FONT.sizes.md, fontWeight: FONT.weights.bold, letterSpacing: 0.3 },
  creditAmount: { color: '#fff', fontSize: 48, fontWeight: FONT.weights.heavy, letterSpacing: -1, marginTop: 4 },
  creditMessage: { color: 'rgba(255,255,255,0.95)', fontSize: FONT.sizes.sm, textAlign: 'center', marginTop: 4 },
  tcRow: { flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: SPACING.sm },
  tcText: { color: 'rgba(255,255,255,0.9)', fontSize: 11, fontWeight: FONT.weights.semibold, textDecorationLine: 'underline' },
});

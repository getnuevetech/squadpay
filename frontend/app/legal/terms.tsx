/**
 * Terms & Conditions (with Credits clause anchor).
 *
 * The credits portion is reachable via /legal/terms#credits and is
 * linked from the contribution success page and credit-earned SMS
 * messages so users always know how the program works.
 */
import { useEffect, useRef } from 'react';
import { ScrollView, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { ArrowLeft } from 'lucide-react-native';
import { COLORS, FONT, RADIUS, SPACING } from '../../src/theme';

export default function TermsScreen() {
  const router = useRouter();
  const params = useLocalSearchParams<{ section?: string }>();
  const scrollRef = useRef<ScrollView>(null);
  const creditsRef = useRef<View>(null);

  useEffect(() => {
    // Allow ?section=credits to deep-link to the credits clause.
    if (params.section === 'credits') {
      setTimeout(() => {
        creditsRef.current?.measureLayout?.(
          (scrollRef.current as any)?.getInnerViewNode?.() ?? (scrollRef.current as any),
          (_x, y) => { scrollRef.current?.scrollTo({ y, animated: true }); },
          () => {},
        );
      }, 250);
    }
  }, [params.section]);

  return (
    <SafeAreaView edges={['top', 'bottom']} style={{ flex: 1, backgroundColor: COLORS.bg }}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.canGoBack() ? router.back() : router.replace('/')} style={styles.backBtn} activeOpacity={0.7}>
          <ArrowLeft size={20} color={COLORS.text} />
        </TouchableOpacity>
        <Text style={styles.title}>Terms & Conditions</Text>
        <View style={{ width: 40 }} />
      </View>
      <ScrollView ref={scrollRef} contentContainerStyle={{ padding: SPACING.lg }}>
        <Text style={styles.h1}>SquadPay Terms of Service</Text>
        <Text style={styles.p}>
          By using SquadPay you agree to the terms below. SquadPay is a
          platform that helps groups split bills and contribute toward a
          shared payment. SquadPay is not a bank and does not custody
          funds outside of the payment flows described in these terms.
        </Text>
        <Text style={styles.h2}>Accounts & Identity</Text>
        <Text style={styles.p}>
          You agree to provide accurate contact information and a phone
          number you control. Misuse, fraud, or harassment may result in
          your account being suspended.
        </Text>
        <Text style={styles.h2}>Payments</Text>
        <Text style={styles.p}>
          All card payments are processed by Stripe. The merchant receives
          a single charge from the Squad Wallet (a Stripe-issued virtual
          card) after the Squad has been fully funded. SquadPay applies
          platform and transaction fees as configured by the SquadPay team
          and disclosed at checkout.
        </Text>

        {/* ==================== Credits Clause ==================== */}
        <View ref={creditsRef} style={styles.anchor} testID="terms-credits-anchor">
          <Text style={styles.h2}>Credits Program</Text>
          <Text style={styles.p}>
            SquadPay may, at its discretion, grant credits to users that
            qualify for active promotional rules. The full terms governing
            credits are below.
          </Text>
          <Text style={styles.h3}>How credits are earned</Text>
          <Text style={styles.p}>
            Credits are earned automatically when your contribution
            matches the criteria of an active promotion (for example, a
            first-time-user reward, a recurring milestone, an Nth-user-
            of-the-day reward, or a user-/Squad-specific promotion). The
            promotion text shown on your contribution confirmation page
            describes the rule that granted you the credit.
          </Text>
          <Text style={styles.h3}>Pending vs. Available</Text>
          <Text style={styles.p}>
            Credits start as "pending" and become "available" once the
            Squad that produced the credit is fully funded and the merchant
            charge has settled. Pending balances are visible in Settings →
            Credits but cannot be spent.
          </Text>
          <Text style={styles.h3}>Auto-application</Text>
          <Text style={styles.p}>
            Available credits are automatically applied to reduce your
            cash contribution on your next transaction. The applied
            amount appears on the contribution receipt and in your
            credit ledger.
          </Text>
          <Text style={styles.h3}>Refunds & forfeiture</Text>
          <Text style={styles.p}>
            If you request a refund of an overpayment on a Squad whose
            contribution earned a credit, any unused credit from that
            Squad is forfeited, and any credit that was previously
            applied to a refunded contribution is also forfeited.
            Credits have no cash value and cannot be added to refunds.
          </Text>
          <Text style={styles.h3}>Expiry & stacking</Text>
          <Text style={styles.p}>
            Each rule sets its own expiry window (or never expires). Two
            promotions may stack on a single contribution only when each
            rule explicitly allows stacking with the other; otherwise the
            first matching rule grants the credit.
          </Text>
          <Text style={styles.h3}>Discretion</Text>
          <Text style={styles.p}>
            SquadPay reserves the right to modify, pause, or revoke any
            credit rule at any time. Credits granted in error or as a
            result of abusive activity may be revoked without notice.
          </Text>
        </View>
        {/* ================== /Credits Clause ==================== */}

        <Text style={styles.h2}>Disputes & Refunds</Text>
        <Text style={styles.p}>
          Refunds are processed back to the original payment method
          (minus any non-recoverable processor fees and minus any
          credits forfeited under the Credits Program clause).
        </Text>
        <Text style={styles.h2}>Contact</Text>
        <Text style={styles.p}>
          For questions, please contact SquadPay support.
        </Text>
        <View style={{ height: 32 }} />
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  header: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    paddingHorizontal: SPACING.md, paddingVertical: SPACING.sm,
    borderBottomWidth: 1, borderBottomColor: COLORS.border, backgroundColor: COLORS.surface,
  },
  backBtn: {
    width: 40, height: 40, borderRadius: 20, backgroundColor: COLORS.bg,
    alignItems: 'center', justifyContent: 'center', borderWidth: 1, borderColor: COLORS.border,
  },
  title: { fontSize: FONT.sizes.lg, fontWeight: FONT.weights.bold, color: COLORS.text },
  h1: { fontSize: 22, fontWeight: FONT.weights.heavy, color: COLORS.text, marginBottom: SPACING.md },
  h2: { fontSize: 17, fontWeight: FONT.weights.bold, color: COLORS.text, marginTop: SPACING.lg, marginBottom: 6 },
  h3: { fontSize: 14, fontWeight: FONT.weights.bold, color: COLORS.text, marginTop: SPACING.md, marginBottom: 4 },
  p: { fontSize: 14, color: COLORS.subtext, lineHeight: 22 },
  anchor: { paddingTop: 4 },
});

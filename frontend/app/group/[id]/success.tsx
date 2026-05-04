import { useLocalSearchParams, useRouter } from 'expo-router';
import { StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { CheckCircle2 } from 'lucide-react-native';
import { Button } from '../../../src/Button';
import { COLORS, FONT, SPACING } from '../../../src/theme';

export default function SuccessScreen() {
  const { id, amount, kind } = useLocalSearchParams<{
    id: string;
    amount?: string;
    kind?: string;
  }>();
  const router = useRouter();

  const amt = parseFloat(amount || '0').toFixed(2);
  const isLeadPay = kind === 'lead';
  const isContribute = kind === 'contribute';

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
        <Text style={styles.sub} testID="success-subtitle">
          {isLeadPay
            ? "You paid the restaurant. We'll track repayments from your group."
            : isContribute
            ? "Your share is now in the group wallet. The lead will pay the merchant."
            : 'Your repayment has been recorded.'}
        </Text>
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
});

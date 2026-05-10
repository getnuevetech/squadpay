// SquadPay — Support / Help Center.
// Linked from the home footer. Provides contact options + a small FAQ section.
import { Linking, ScrollView, StyleSheet, Text, View } from 'react-native';
import { Stack, useRouter } from 'expo-router';
import { ChevronLeft, LifeBuoy, Mail, MessageCircle } from 'lucide-react-native';
import { COLORS, FONT, RADIUS, SPACING } from '../../src/theme';
import { PressableScale } from '../../src/components/PressableScale';

const SUPPORT_EMAIL = 'support@squadpay.us';
const LAST_UPDATED = 'June 2026';

export default function SupportScreen() {
  const router = useRouter();

  const openMail = () => {
    Linking.openURL(
      `mailto:${SUPPORT_EMAIL}?subject=${encodeURIComponent('SquadPay Support Request')}`
    ).catch(() => {});
  };

  return (
    <View style={{ flex: 1, backgroundColor: COLORS.bg }}>
      <Stack.Screen options={{ headerShown: false }} />
      <ScrollView contentContainerStyle={styles.wrap}>
        <View style={styles.headerRow}>
          <PressableScale onPress={() => router.back()} style={styles.backBtn} scaleTo={0.95}>
            <ChevronLeft color={COLORS.text} size={20} />
            <Text style={styles.backText}>Back</Text>
          </PressableScale>
        </View>

        <View style={styles.heroIcon}>
          <LifeBuoy color={COLORS.primary} size={28} strokeWidth={2.4} />
        </View>
        <Text style={styles.title}>Support</Text>
        <Text style={styles.updated}>We typically respond within 24 hours · {LAST_UPDATED}</Text>

        <Text style={styles.body}>
          Need help with a bill, payment, or your account? We're here for you. Pick a contact method
          below or browse the quick answers.
        </Text>

        {/* Primary contact CTAs */}
        <View style={styles.ctaCol}>
          <PressableScale style={styles.ctaCard} onPress={openMail} scaleTo={0.97}>
            <View style={styles.ctaIcon}>
              <Mail color={COLORS.primary} size={22} strokeWidth={2.2} />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.ctaTitle}>Email us</Text>
              <Text style={styles.ctaSub}>{SUPPORT_EMAIL}</Text>
            </View>
          </PressableScale>
        </View>

        {/* FAQ */}
        <Section title="Frequently Asked Questions">
          <FAQ q="I didn't receive my OTP code">
            Codes can take up to 60 seconds. Check that your phone has signal and the country code is
            correct. If it still doesn't arrive, tap “Resend” on the OTP screen or email us.
          </FAQ>
          <FAQ q="My contribution failed">
            Stripe processes all payments. If a card is declined, double-check the card details, ZIP
            code, and that there are sufficient funds. Bank-side fraud rules can also block first
            attempts — try once more or contact your bank.
          </FAQ>
          <FAQ q="How do I leave a group?">
            Open the group, tap the menu in the top right, and choose “Leave group.” Your unpaid items
            will be redistributed among remaining members.
          </FAQ>
          <FAQ q="Is my data secure?">
            We never store full card numbers — only Stripe tokens. Phone numbers and personal info are
            encrypted at rest. Read more in our{' '}
            <Text style={styles.link} onPress={() => router.push('/legal/privacy')}>
              Privacy Policy
            </Text>
            .
          </FAQ>
          <FAQ q="How do I delete my account?">
            Email{' '}
            <Text style={styles.link} onPress={openMail}>
              {SUPPORT_EMAIL}
            </Text>{' '}
            from the address tied to your account. We'll process the deletion within 30 days as
            required by law.
          </FAQ>
        </Section>

        <View style={styles.section}>
          <View style={styles.contactBox}>
            <MessageCircle color={COLORS.primary} size={22} />
            <View style={{ flex: 1 }}>
              <Text style={styles.contactTitle}>Still need help?</Text>
              <Text style={styles.body}>
                Email{' '}
                <Text style={styles.link} onPress={openMail}>
                  {SUPPORT_EMAIL}
                </Text>{' '}
                with as much detail as possible (group ID, phone number, screenshots) and we'll get
                back to you fast.
              </Text>
            </View>
          </View>
        </View>

        <Text style={styles.footer}>© SquadPay · Built for splitting fairly</Text>
      </ScrollView>
    </View>
  );
}

// ───── Helpers ─────

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <View style={styles.section}>
      <Text style={styles.sectionTitle}>{title}</Text>
      {children}
    </View>
  );
}

function FAQ({ q, children }: { q: string; children: React.ReactNode }) {
  return (
    <View style={styles.faqRow}>
      <Text style={styles.faqQ}>{q}</Text>
      <Text style={styles.body}>{children}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    padding: SPACING.lg,
    paddingBottom: SPACING.xxl,
    maxWidth: 760,
    alignSelf: 'center',
    width: '100%',
  },
  headerRow: { flexDirection: 'row', alignItems: 'center', marginBottom: SPACING.md },
  backBtn: { flexDirection: 'row', alignItems: 'center', gap: 4, paddingVertical: 6 },
  backText: { color: COLORS.text, fontSize: FONT.sizes.md, fontWeight: FONT.weights.medium },
  heroIcon: {
    width: 56,
    height: 56,
    borderRadius: 18,
    backgroundColor: COLORS.primaryLight,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: SPACING.sm,
  },
  title: { fontSize: 30, fontWeight: FONT.weights.heavy, color: COLORS.text, letterSpacing: -0.8 },
  updated: { fontSize: FONT.sizes.sm, color: COLORS.subtext, marginTop: 4, marginBottom: SPACING.lg },
  body: { fontSize: FONT.sizes.md, color: COLORS.text, lineHeight: 22 },
  ctaCol: { gap: SPACING.sm, marginTop: SPACING.md },
  ctaCard: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: SPACING.md,
    backgroundColor: COLORS.surface,
    padding: SPACING.md,
    borderRadius: RADIUS.lg,
    borderWidth: 1,
    borderColor: COLORS.border,
  },
  ctaIcon: {
    width: 44,
    height: 44,
    borderRadius: 14,
    backgroundColor: COLORS.primaryLight,
    alignItems: 'center',
    justifyContent: 'center',
  },
  ctaTitle: { fontSize: FONT.sizes.md, fontWeight: FONT.weights.bold, color: COLORS.text },
  ctaSub: { fontSize: FONT.sizes.sm, color: COLORS.subtext, marginTop: 2 },
  section: { marginTop: SPACING.xl },
  sectionTitle: {
    fontSize: FONT.sizes.lg,
    fontWeight: FONT.weights.bold,
    color: COLORS.text,
    marginBottom: SPACING.md,
  },
  faqRow: {
    backgroundColor: COLORS.surface,
    padding: SPACING.md,
    borderRadius: RADIUS.md,
    borderWidth: 1,
    borderColor: COLORS.border,
    marginBottom: SPACING.sm,
  },
  faqQ: {
    fontSize: FONT.sizes.md,
    fontWeight: FONT.weights.bold,
    color: COLORS.text,
    marginBottom: 6,
  },
  contactBox: {
    flexDirection: 'row',
    gap: SPACING.md,
    backgroundColor: COLORS.primaryLight,
    padding: SPACING.md,
    borderRadius: RADIUS.lg,
    alignItems: 'flex-start',
  },
  contactTitle: {
    fontSize: FONT.sizes.md,
    fontWeight: FONT.weights.bold,
    color: COLORS.text,
    marginBottom: 4,
  },
  link: { color: COLORS.primary, fontWeight: FONT.weights.semibold },
  footer: {
    textAlign: 'center',
    color: COLORS.subtext,
    marginTop: SPACING.xl,
    fontSize: FONT.sizes.xs,
  },
});

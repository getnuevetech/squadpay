// SquadPay — Privacy Policy. Mirror this content on the marketing site at
// https://www.squadpay.us/legal/privacy. Required by Apple App Store (Guideline 5.1.1)
// and Google Play (Data Safety section). Keep in sync with the actual data
// collection in the backend.
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { Stack, useRouter } from 'expo-router';
import { ChevronLeft, ShieldCheck } from 'lucide-react-native';
import { COLORS, FONT, RADIUS, SPACING } from '../../src/theme';
import { PressableScale } from '../../src/components/PressableScale';

const LAST_UPDATED = 'May 7, 2026';

export default function PrivacyPolicyScreen() {
  const router = useRouter();
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
          <ShieldCheck color={COLORS.primary} size={28} strokeWidth={2.4} />
        </View>
        <Text style={styles.title}>Privacy Policy</Text>
        <Text style={styles.updated}>Last updated: {LAST_UPDATED}</Text>

        <Text style={styles.body}>
          SquadPay (“we”, “our”, or “us”) helps groups split bills, contribute funds, and share a
          group payment card. Your privacy is important to us. This policy describes the
          information we collect, how we use it, and the choices you have.
        </Text>

        <Section title="1. Information We Collect">
          <Bullet>
            <B>Account information:</B> phone number, name, email (optional), and a verification
            code we text to you to confirm ownership of the phone.
          </Bullet>
          <Bullet>
            <B>Group activity:</B> the bills you create or join, items you assign, contributions you
            make, and group membership.
          </Bullet>
          <Bullet>
            <B>Payment data:</B> processed by Stripe. We never store full card numbers — only the
            last four digits and a Stripe token.
          </Bullet>
          <Bullet>
            <B>Receipt photos:</B> when you scan a receipt, the image is sent to OpenAI for
            line-item extraction. The image is not retained beyond the parse.
          </Bullet>
          <Bullet>
            <B>Device & usage data:</B> IP address, device type, OS version, crash reports, and
            anonymous usage analytics to keep the service reliable.
          </Bullet>
        </Section>

        <Section title="2. How We Use Information">
          <Bullet>To provide, maintain, and improve SquadPay.</Bullet>
          <Bullet>To process payments and issue group cards via Stripe.</Bullet>
          <Bullet>To send service notifications (verification codes, receipts, reminders).</Bullet>
          <Bullet>To prevent fraud and enforce our terms.</Bullet>
          <Bullet>
            We do <B>not</B> sell your personal information. We do not show ads.
          </Bullet>
        </Section>

        <Section title="3. Sharing With Third Parties">
          <Bullet>
            <B>Stripe</B> — payment processing and virtual card issuance.
          </Bullet>
          <Bullet>
            <B>Twilio / SignalWire</B> — SMS verification and reminders.
          </Bullet>
          <Bullet>
            <B>OpenAI</B> — receipt OCR and item parsing (image is not retained).
          </Bullet>
          <Bullet>
            <B>Google Workspace</B> — sending transactional email (password resets etc).
          </Bullet>
          <Bullet>
            We share data with these vendors only as needed to provide the service. We never sell
            your data.
          </Bullet>
        </Section>

        <Section title="4. Data Retention">
          <Text style={styles.body}>
            We retain account data for as long as your account is active. Receipt images are not
            stored. Group transaction history is retained for at least 7 years to comply with
            financial regulations. You can delete your account at any time from the app — within 30
            days we permanently delete personal data, retaining only what's required by law.
          </Text>
        </Section>

        <Section title="5. Your Choices & Rights">
          <Bullet>
            <B>Access & Export:</B> request a copy of your data by emailing privacy@squadpay.us.
          </Bullet>
          <Bullet>
            <B>Delete:</B> use the “Delete account” option in app or email us. We honor CCPA / GDPR
            deletion requests within 30 days.
          </Bullet>
          <Bullet>
            <B>Opt out of SMS:</B> reply STOP to any SquadPay SMS to disable non-transactional
            messages. Verification codes are required to use the service.
          </Bullet>
        </Section>

        <Section title="6. Children's Privacy">
          <Text style={styles.body}>
            SquadPay is not directed to children under 13. We do not knowingly collect data from
            them. If you believe we have, contact privacy@squadpay.us and we will delete it.
          </Text>
        </Section>

        <Section title="7. Changes To This Policy">
          <Text style={styles.body}>
            We may update this policy from time to time. Material changes will be announced in the
            app at least 7 days before they take effect.
          </Text>
        </Section>

        <Section title="8. Contact Us">
          <Text style={styles.body}>
            Questions or requests:{' '}
            <Text style={styles.link}>privacy@squadpay.us</Text>
            {'\n'}
            Mailing: SquadPay, [Your registered business address]
          </Text>
        </Section>

        <Text style={styles.footer}>© {new Date().getFullYear()} SquadPay. All rights reserved.</Text>
      </ScrollView>
    </View>
  );
}

// ───── Tiny presentational helpers (kept inline so the page is self-contained) ─────

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <View style={styles.section}>
      <Text style={styles.sectionTitle}>{title}</Text>
      {children}
    </View>
  );
}

function Bullet({ children }: { children: React.ReactNode }) {
  return (
    <View style={styles.bulletRow}>
      <Text style={styles.bulletDot}>•</Text>
      <Text style={[styles.body, { flex: 1 }]}>{children}</Text>
    </View>
  );
}

function B({ children }: { children: React.ReactNode }) {
  return <Text style={{ fontWeight: FONT.weights.bold }}>{children}</Text>;
}

const styles = StyleSheet.create({
  wrap: { padding: SPACING.lg, paddingBottom: SPACING.xxl, maxWidth: 760, alignSelf: 'center', width: '100%' },
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
  section: { marginTop: SPACING.lg },
  sectionTitle: {
    fontSize: FONT.sizes.lg,
    fontWeight: FONT.weights.bold,
    color: COLORS.text,
    marginBottom: SPACING.sm,
  },
  body: { fontSize: FONT.sizes.md, color: COLORS.text, lineHeight: 22 },
  bulletRow: { flexDirection: 'row', gap: 8, marginVertical: 4 },
  bulletDot: { color: COLORS.primary, fontSize: FONT.sizes.md, fontWeight: FONT.weights.heavy, lineHeight: 22 },
  link: { color: COLORS.primary, fontWeight: FONT.weights.semibold },
  footer: { textAlign: 'center', color: COLORS.subtext, marginTop: SPACING.xl, fontSize: FONT.sizes.xs },
});

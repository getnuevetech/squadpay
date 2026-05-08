// SquadPay — Terms of Service. Mirror at https://www.squadpay.us/legal/terms.
// Required by Apple App Store (Guideline 3.1.1 & 5.1.1) and Google Play.
// Keep in sync with the Stripe Connect / Issuing flow before going live.
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { Stack, useRouter } from 'expo-router';
import { ChevronLeft, FileText } from 'lucide-react-native';
import { COLORS, FONT, RADIUS, SPACING } from '../../src/theme';
import { PressableScale } from '../../src/components/PressableScale';

const LAST_UPDATED = 'May 7, 2026';

export default function TermsOfServiceScreen() {
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
          <FileText color={COLORS.primary} size={28} strokeWidth={2.4} />
        </View>
        <Text style={styles.title}>Terms of Service</Text>
        <Text style={styles.updated}>Last updated: {LAST_UPDATED}</Text>

        <Text style={styles.body}>
          These Terms of Service (“Terms”) govern your use of the SquadPay mobile and web
          applications (the “Service”) provided by SquadPay (“we”, “our”, or “us”). By creating an
          account or using the Service, you agree to these Terms.
        </Text>

        <Section title="1. Eligibility">
          <Text style={styles.body}>
            You must be at least 18 years old and a U.S. resident to use SquadPay. You must
            provide accurate registration information and keep it up to date.
          </Text>
        </Section>

        <Section title="2. The Service">
          <Bullet>SquadPay lets groups split bills, contribute funds, and share a virtual card.</Bullet>
          <Bullet>Payments are processed by Stripe; cards are issued via Stripe Issuing.</Bullet>
          <Bullet>SquadPay is not a bank. Funds held are not deposits and are not FDIC insured.</Bullet>
        </Section>

        <Section title="3. Your Account">
          <Text style={styles.body}>
            You are responsible for safeguarding your account, your phone, and any verification
            codes sent to you. Notify us at help@squadpay.us if you suspect unauthorized access.
          </Text>
        </Section>

        <Section title="4. Payments & Fees">
          <Bullet>Currently SquadPay does not charge a per-transaction fee. We may add fees in the future with at least 30 days' notice.</Bullet>
          <Bullet>Stripe fees apply to all payments and are disclosed before you confirm.</Bullet>
          <Bullet>Refunds for overpayments are processed via Stripe and may take 5–10 business days to appear on your card.</Bullet>
          <Bullet>Disputes (chargebacks) initiated through your card issuer are handled per Stripe's chargeback procedures.</Bullet>
        </Section>

        <Section title="5. Acceptable Use">
          <Bullet>Don't use SquadPay for illegal activity, fraud, money laundering, or to fund prohibited goods/services.</Bullet>
          <Bullet>Don't attempt to circumvent rate limits, tamper with the app, or scrape data without our written consent.</Bullet>
          <Bullet>Don't impersonate another person or share your verification codes with anyone.</Bullet>
          <Bullet>We may suspend or terminate accounts that violate these Terms or applicable laws.</Bullet>
        </Section>

        <Section title="6. Group Lead Responsibilities">
          <Text style={styles.body}>
            If you create a group bill, you are the “Lead.” As the Lead, you are responsible for
            the accuracy of the bill total and split. SquadPay is a tool to facilitate the split —
            we do not adjudicate disputes between members. Contributions made are at the discretion
            of each member.
          </Text>
        </Section>

        <Section title="7. Intellectual Property">
          <Text style={styles.body}>
            The SquadPay name, logo, and all software are owned by SquadPay or our licensors. You
            may use the Service only as permitted by these Terms.
          </Text>
        </Section>

        <Section title="8. Disclaimers">
          <Text style={styles.body}>
            THE SERVICE IS PROVIDED “AS IS” WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR
            IMPLIED. WE DO NOT WARRANT THAT THE SERVICE WILL BE UNINTERRUPTED OR ERROR-FREE. SOME
            JURISDICTIONS DO NOT ALLOW THESE EXCLUSIONS, IN WHICH CASE THEY APPLY TO THE EXTENT
            PERMITTED BY LAW.
          </Text>
        </Section>

        <Section title="9. Limitation of Liability">
          <Text style={styles.body}>
            TO THE MAXIMUM EXTENT PERMITTED BY LAW, SQUADPAY WILL NOT BE LIABLE FOR INDIRECT,
            INCIDENTAL, SPECIAL, CONSEQUENTIAL, OR PUNITIVE DAMAGES, OR ANY LOSS OF PROFITS OR
            REVENUES. OUR TOTAL LIABILITY FOR ANY CLAIM ARISING FROM OR RELATED TO THE SERVICE WILL
            NOT EXCEED $100 OR THE FEES YOU HAVE PAID US IN THE PRIOR 12 MONTHS, WHICHEVER IS
            GREATER.
          </Text>
        </Section>

        <Section title="10. Changes To These Terms">
          <Text style={styles.body}>
            We may update these Terms from time to time. Material changes will be announced in the
            app at least 7 days before they take effect. Your continued use of the Service after
            the effective date constitutes acceptance.
          </Text>
        </Section>

        <Section title="11. Governing Law">
          <Text style={styles.body}>
            These Terms are governed by the laws of the State of Delaware, USA, without regard to
            conflict-of-law principles. Disputes will be resolved in state or federal courts
            located in Delaware, except where prohibited by applicable consumer protection laws.
          </Text>
        </Section>

        <Section title="12. Contact">
          <Text style={styles.body}>
            Questions: <Text style={styles.link}>help@squadpay.us</Text>
            {'\n'}
            Mailing: SquadPay, [Your registered business address]
          </Text>
        </Section>

        <Text style={styles.footer}>© {new Date().getFullYear()} SquadPay. All rights reserved.</Text>
      </ScrollView>
    </View>
  );
}

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

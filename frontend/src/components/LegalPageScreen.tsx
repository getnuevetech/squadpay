/**
 * Shared legal page screen — used by /legal/support, /legal/privacy, /legal/terms.
 * Fetches the latest admin-managed content from /api/legal/pages/{slug} and
 * renders it with the LegalHtml component. Falls back to a friendly error
 * state if the API is unreachable.
 */
import { useEffect, useState } from 'react';
import {
  ActivityIndicator,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { Stack, useRouter } from 'expo-router';
import { ChevronLeft, LifeBuoy, ScrollText, ShieldCheck } from 'lucide-react-native';
import { COLORS, FONT, RADIUS, SPACING } from '../theme';
import { PressableScale } from './PressableScale';
import { LegalHtml } from './LegalHtml';
import { api } from '../api';

type Slug = 'support' | 'privacy' | 'terms';

const ICONS: Record<Slug, React.ComponentType<any>> = {
  support: LifeBuoy,
  privacy: ShieldCheck,
  terms: ScrollText,
};

export function LegalPageScreen({ slug }: { slug: Slug }) {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState<{ title: string; content_html: string; updated_at: string | null } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .getLegalPage(slug)
      .then((res) => {
        if (cancelled) return;
        setData({ title: res.title, content_html: res.content_html, updated_at: res.updated_at });
      })
      .catch((e) => {
        if (cancelled) return;
        setError(e?.message || 'Could not load this page');
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [slug]);

  const Icon = ICONS[slug];

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
          <Icon color={COLORS.primary} size={28} strokeWidth={2.4} />
        </View>
        <Text style={styles.title}>{data?.title || (slug === 'support' ? 'Support' : slug === 'privacy' ? 'Privacy Policy' : 'Terms & Conditions')}</Text>
        {data?.updated_at && (
          <Text style={styles.updated}>
            Last updated: {new Date(data.updated_at).toLocaleDateString()}
          </Text>
        )}

        {loading && (
          <View style={styles.center}>
            <ActivityIndicator color={COLORS.primary} />
          </View>
        )}

        {!loading && error && (
          <View style={styles.errorBox}>
            <Text style={styles.errorTitle}>Couldn't load this page</Text>
            <Text style={styles.errorBody}>
              Please check your connection and try again. If the issue persists, contact{' '}
              <Text style={styles.link} onPress={() => router.push('/legal/support')}>
                support
              </Text>
              .
            </Text>
          </View>
        )}

        {!loading && !error && data && <LegalHtml html={data.content_html} />}

        <Text style={styles.footer}>© 2026 — SquadPay by NueveTech</Text>
      </ScrollView>
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
  title: {
    fontSize: 30,
    fontWeight: FONT.weights.heavy,
    color: COLORS.text,
    letterSpacing: -0.8,
  },
  updated: { fontSize: FONT.sizes.sm, color: COLORS.subtext, marginTop: 4, marginBottom: SPACING.lg },
  center: { paddingVertical: SPACING.xl, alignItems: 'center' },
  errorBox: {
    marginTop: SPACING.lg,
    padding: SPACING.md,
    borderRadius: RADIUS.md,
    backgroundColor: '#FEF2F2',
    borderWidth: 1,
    borderColor: '#FEE2E2',
  },
  errorTitle: { fontWeight: FONT.weights.bold, color: '#991B1B', marginBottom: 4 },
  errorBody: { color: '#7F1D1D', fontSize: FONT.sizes.sm, lineHeight: 20 },
  link: { color: COLORS.primary, fontWeight: FONT.weights.semibold },
  footer: {
    textAlign: 'center',
    color: COLORS.subtext,
    marginTop: SPACING.xl,
    fontSize: FONT.sizes.xs,
  },
});

export default LegalPageScreen;

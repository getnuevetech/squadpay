import { useEffect, useState } from 'react';
import { View, Text, ScrollView, StyleSheet, ActivityIndicator } from 'react-native';
import { useLocalSearchParams, Stack } from 'expo-router';
import { publicCmsApi, CmsPage } from '../../src/adminApi';
import { COLORS, FONT, RADIUS, SPACING } from '../../src/theme';
import { SafeAreaView } from 'react-native-safe-area-context';

/**
 * Public CMS page renderer.
 *
 * Mounted at /p/[slug] (e.g. /p/about-us). The leading /p prefix keeps the
 * URL space cleanly separated from app routes (group/, admin/, etc.) and
 * lets us add many CMS pages without risk of collisions.
 */
export default function CmsPublicPage() {
  const { slug } = useLocalSearchParams<{ slug?: string }>();
  const [page, setPage] = useState<CmsPage | null>(null);
  const [busy, setBusy] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setBusy(true); setErr(null);
      try {
        if (!slug) throw new Error('No slug');
        const p = await publicCmsApi.get(String(slug));
        if (!cancelled) setPage(p);
      } catch (e: any) {
        if (!cancelled) setErr(e?.message || 'Page not found');
      } finally {
        if (!cancelled) setBusy(false);
      }
    })();
    return () => { cancelled = true; };
  }, [slug]);

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: COLORS.bg }} edges={['top']}>
      <Stack.Screen options={{ title: page?.title || 'Page', headerShown: true }} />
      <ScrollView contentContainerStyle={styles.container}>
        {busy && <ActivityIndicator color={COLORS.primary} style={{ marginTop: 40 }} />}
        {err && !busy ? (
          <View style={styles.errBox}>
            <Text style={styles.errTitle}>Page not found</Text>
            <Text style={styles.errSub}>The page you're looking for doesn't exist or has been unpublished.</Text>
          </View>
        ) : null}
        {page && !busy ? (
          <View>
            <Text style={styles.title}>{page.title}</Text>
            {page.meta_description ? <Text style={styles.meta}>{page.meta_description}</Text> : null}
            <View style={styles.divider} />
            <MarkdownLike text={page.body} />
          </View>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

/**
 * Very-light Markdown renderer — supports headings (#, ##, ###), unordered
 * lists (- ), and paragraph breaks. Avoids pulling in a Markdown lib so the
 * web bundle stays small.
 */
function MarkdownLike({ text }: { text: string }) {
  const blocks = text.split(/\n\n+/);
  return (
    <View style={{ gap: 12 }}>
      {blocks.map((b, idx) => {
        const trimmed = b.trim();
        if (trimmed.startsWith('### ')) return <Text key={idx} style={styles.h3}>{trimmed.slice(4)}</Text>;
        if (trimmed.startsWith('## ')) return <Text key={idx} style={styles.h2}>{trimmed.slice(3)}</Text>;
        if (trimmed.startsWith('# ')) return <Text key={idx} style={styles.h1}>{trimmed.slice(2)}</Text>;
        if (trimmed.split('\n').every((l) => l.trim().startsWith('- '))) {
          return (
            <View key={idx} style={{ gap: 6 }}>
              {trimmed.split('\n').map((l, i) => (
                <Text key={i} style={styles.li}>• {l.replace(/^-\s*/, '')}</Text>
              ))}
            </View>
          );
        }
        return <Text key={idx} style={styles.p}>{trimmed}</Text>;
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { padding: SPACING.lg, maxWidth: 760, alignSelf: 'center', width: '100%' },
  title: { fontSize: 32, fontWeight: FONT.weights.bold, color: COLORS.text, marginBottom: 6 },
  meta: { fontSize: FONT.sizes.sm, color: COLORS.subtext, fontStyle: 'italic' },
  divider: { height: 1, backgroundColor: COLORS.border, marginVertical: SPACING.md },
  h1: { fontSize: 26, fontWeight: FONT.weights.bold, color: COLORS.text, marginTop: 6 },
  h2: { fontSize: 22, fontWeight: FONT.weights.bold, color: COLORS.text, marginTop: 4 },
  h3: { fontSize: 18, fontWeight: FONT.weights.bold, color: COLORS.text },
  p: { fontSize: FONT.sizes.md, color: COLORS.text, lineHeight: 24 },
  li: { fontSize: FONT.sizes.md, color: COLORS.text, lineHeight: 22 },
  errBox: { padding: SPACING.lg, backgroundColor: COLORS.surface, borderRadius: RADIUS.md, borderWidth: 1, borderColor: COLORS.border, marginTop: 40, alignItems: 'center' },
  errTitle: { fontSize: FONT.sizes.lg, fontWeight: FONT.weights.bold, color: COLORS.text },
  errSub: { fontSize: FONT.sizes.sm, color: COLORS.subtext, marginTop: 6, textAlign: 'center' },
});

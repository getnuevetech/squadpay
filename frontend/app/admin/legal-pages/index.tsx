/**
 * Admin — Legal pages index.
 * Lists Support / Privacy / Terms with last-edited info and a quick edit link.
 * Backed by GET /api/admin/legal/pages.
 */
import { useEffect, useState, useCallback } from 'react';
import {
  ActivityIndicator,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import { useRouter } from 'expo-router';
import {
  FileText,
  ShieldCheck,
  HelpCircle,
  ChevronRight,
  Pencil,
  AlertTriangle,
} from 'lucide-react-native';
import { adminApi, LegalPage } from '../../../src/adminApi';
import { COLORS, FONT, RADIUS, SPACING } from '../../../src/theme';

const SLUG_META: Record<
  LegalPage['slug'],
  { title: string; subtitle: string; Icon: React.ComponentType<{ size: number; color: string }> }
> = {
  support: {
    title: 'Support',
    subtitle: 'FAQ + contact info shown at /legal/support',
    Icon: HelpCircle,
  },
  privacy: {
    title: 'Privacy Policy',
    subtitle: 'Linked from sign-up + landing page footer',
    Icon: ShieldCheck,
  },
  terms: {
    title: 'Terms & Conditions',
    subtitle: 'Required to accept on sign-up',
    Icon: FileText,
  },
};

export default function AdminLegalPagesIndex() {
  const router = useRouter();
  const [pages, setPages] = useState<LegalPage[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await adminApi.listLegalPages();
      setPages(res.pages);
    } catch (e: any) {
      setError(e?.message || 'Failed to load legal pages');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (loading) {
    return (
      <View style={styles.center} testID="admin-legal-loading">
        <ActivityIndicator color={COLORS.primary} />
      </View>
    );
  }

  return (
    <ScrollView contentContainerStyle={{ paddingBottom: 80 }} testID="admin-legal-index">
      <Text style={styles.heading}>Legal pages</Text>
      <Text style={styles.subheading}>
        Manage Support, Privacy and Terms content shown to users on the web and in-app.
      </Text>

      {error ? (
        <View style={styles.errorBox} testID="admin-legal-error">
          <AlertTriangle size={14} color={COLORS.danger} />
          <Text style={styles.errorText}>{error}</Text>
          <TouchableOpacity onPress={load} style={styles.retryBtn} activeOpacity={0.85}>
            <Text style={styles.retryText}>Retry</Text>
          </TouchableOpacity>
        </View>
      ) : null}

      <View style={{ gap: SPACING.sm }}>
        {pages.map((p) => {
          const meta = SLUG_META[p.slug] || {
            title: p.title,
            subtitle: '',
            Icon: FileText,
          };
          const Icon = meta.Icon;
          return (
            <TouchableOpacity
              key={p.slug}
              testID={`admin-legal-row-${p.slug}`}
              activeOpacity={0.85}
              onPress={() => router.push(`/admin/legal-pages/${p.slug}` as any)}
              style={styles.row}
            >
              <View style={styles.icon}>
                <Icon size={18} color={COLORS.primary} />
              </View>
              <View style={{ flex: 1 }}>
                <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                  <Text style={styles.title} numberOfLines={1}>
                    {meta.title}
                  </Text>
                  {p.is_default ? (
                    <View style={styles.defaultPill}>
                      <Text style={styles.defaultPillText}>Default</Text>
                    </View>
                  ) : (
                    <View style={styles.editedPill}>
                      <Text style={styles.editedPillText}>Customized</Text>
                    </View>
                  )}
                </View>
                <Text style={styles.subtitle} numberOfLines={1}>{meta.subtitle}</Text>
                <Text style={styles.meta}>
                  {p.updated_at
                    ? `Last edited ${new Date(p.updated_at).toLocaleString()}${p.updated_by ? ` by ${p.updated_by}` : ''}`
                    : 'Showing built-in default copy'}
                </Text>
              </View>
              <View style={styles.editBtn}>
                <Pencil size={14} color={COLORS.primary} />
                <Text style={styles.editBtnText}>Edit</Text>
                <ChevronRight size={14} color={COLORS.primary} />
              </View>
            </TouchableOpacity>
          );
        })}
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: SPACING.lg },
  heading: { fontSize: FONT.sizes.xl, fontWeight: FONT.weights.bold, color: COLORS.text },
  subheading: {
    fontSize: FONT.sizes.sm,
    color: COLORS.subtext,
    marginTop: 4,
    marginBottom: SPACING.lg,
  },
  errorBox: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    paddingHorizontal: SPACING.md,
    paddingVertical: 10,
    borderRadius: RADIUS.md,
    backgroundColor: COLORS.dangerLight,
    borderWidth: 1,
    borderColor: COLORS.danger,
    marginBottom: SPACING.md,
  },
  errorText: { flex: 1, color: COLORS.danger, fontSize: FONT.sizes.sm },
  retryBtn: {
    paddingHorizontal: 10,
    paddingVertical: 4,
    backgroundColor: COLORS.danger,
    borderRadius: RADIUS.pill,
  },
  retryText: { color: '#fff', fontSize: 11, fontWeight: FONT.weights.bold },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: SPACING.md,
    padding: SPACING.md,
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.md,
    borderWidth: 1,
    borderColor: COLORS.border,
  },
  icon: {
    width: 40,
    height: 40,
    borderRadius: 12,
    backgroundColor: COLORS.primaryLight,
    alignItems: 'center',
    justifyContent: 'center',
  },
  title: { fontSize: FONT.sizes.md, fontWeight: FONT.weights.bold, color: COLORS.text },
  subtitle: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: 2 },
  meta: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: 4, opacity: 0.8 },
  defaultPill: {
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: RADIUS.pill,
    backgroundColor: COLORS.warningLight,
    borderWidth: 1,
    borderColor: COLORS.warning,
  },
  defaultPillText: {
    fontSize: 10,
    color: COLORS.warning,
    fontWeight: FONT.weights.bold,
    textTransform: 'uppercase',
  },
  editedPill: {
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: RADIUS.pill,
    backgroundColor: COLORS.successLight,
    borderWidth: 1,
    borderColor: COLORS.success,
  },
  editedPillText: {
    fontSize: 10,
    color: COLORS.success,
    fontWeight: FONT.weights.bold,
    textTransform: 'uppercase',
  },
  editBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: RADIUS.pill,
    backgroundColor: COLORS.primaryLight,
  },
  editBtnText: { color: COLORS.primary, fontSize: FONT.sizes.xs, fontWeight: FONT.weights.bold },
});

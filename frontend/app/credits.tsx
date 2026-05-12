/**
 * User-side Credits screen (June 2025).
 *
 * Surfaces:
 *   - Available balance (auto-applied on the next contribution)
 *   - Pending balance (waiting for the source Squad to settle)
 *   - Ledger (last 50 entries)
 *
 * Linked from Settings -> Credits.
 */
import { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  FlatList,
  RefreshControl,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useRouter } from 'expo-router';
import { ArrowLeft, Coins, Clock, CheckCircle2, XCircle } from 'lucide-react-native';
import { api } from '../src/api';
import { loadUser } from '../src/session';
import { COLORS, FONT, RADIUS, SPACING } from '../src/theme';
import { formatSid } from '../src/ids';
import { friendlyError } from '../src/errors';
import { toast } from '../src/components/Toast';

export default function CreditsScreen() {
  const router = useRouter();
  const [summary, setSummary] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    const u = await loadUser();
    if (!u) { router.replace('/auth'); return; }
    try {
      const r = await api.getCreditsSummary(u.id);
      setSummary(r);
    } catch (e: any) {
      toast.error(friendlyError(e, "We couldn't load your credits."));
    } finally {
      setLoading(false);
    }
  }, [router]);

  useEffect(() => { load(); }, [load]);

  const onRefresh = async () => { setRefreshing(true); await load(); setRefreshing(false); };

  const statusBadge = (status: string) => {
    if (status === 'active') return { label: 'Available', color: COLORS.success, bg: COLORS.successLight, icon: CheckCircle2 };
    if (status === 'pending') return { label: 'Pending', color: COLORS.warning, bg: COLORS.warningLight, icon: Clock };
    if (status === 'consumed') return { label: 'Used', color: COLORS.subtext, bg: COLORS.disabledBg, icon: CheckCircle2 };
    if (status === 'forfeited') return { label: 'Forfeited', color: COLORS.danger, bg: COLORS.dangerLight, icon: XCircle };
    if (status === 'expired') return { label: 'Expired', color: COLORS.subtext, bg: COLORS.disabledBg, icon: XCircle };
    return { label: status, color: COLORS.subtext, bg: COLORS.disabledBg, icon: Clock };
  };

  return (
    <SafeAreaView edges={['top', 'bottom']} style={{ flex: 1, backgroundColor: COLORS.bg }}>
      <View style={styles.header}>
        <TouchableOpacity
          onPress={() => router.canGoBack() ? router.back() : router.replace('/settings')}
          style={styles.backBtn}
          activeOpacity={0.7}
          testID="credits-back-btn"
        >
          <ArrowLeft size={20} color={COLORS.text} />
        </TouchableOpacity>
        <Text style={styles.title}>Credits</Text>
        <View style={{ width: 40 }} />
      </View>

      {loading ? (
        <View style={styles.center}><ActivityIndicator color={COLORS.primary} /></View>
      ) : (
        <FlatList
          data={summary?.items || []}
          keyExtractor={(it) => it.id}
          contentContainerStyle={{ padding: SPACING.md, gap: SPACING.sm }}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={COLORS.primary} />
          }
          ListHeaderComponent={
            <View>
              <View style={styles.summaryRow}>
                <View style={[styles.summaryTile, { backgroundColor: COLORS.successLight }]}>
                  <Coins size={18} color={COLORS.success} />
                  <Text style={styles.summaryLabel}>Available</Text>
                  <Text style={[styles.summaryAmt, { color: COLORS.success }]} testID="credits-available">
                    ${(summary?.available || 0).toFixed(2)}
                  </Text>
                </View>
                <View style={[styles.summaryTile, { backgroundColor: COLORS.warningLight }]}>
                  <Clock size={18} color={COLORS.warning} />
                  <Text style={styles.summaryLabel}>Pending</Text>
                  <Text style={[styles.summaryAmt, { color: COLORS.warning }]} testID="credits-pending">
                    ${(summary?.pending || 0).toFixed(2)}
                  </Text>
                </View>
              </View>
              <Text style={styles.subtitle}>
                Available credits are auto-applied to your next contribution.
                Pending credits unlock once their source Squad is paid off.
              </Text>
              <Text style={styles.sectionTitle}>Ledger</Text>
            </View>
          }
          ListEmptyComponent={
            <View style={styles.empty}>
              <Coins size={48} color={COLORS.border} />
              <Text style={styles.emptyTitle}>No credits yet</Text>
              <Text style={styles.emptySub}>
                You'll earn credits when SquadPay promotions trigger on your contributions.
              </Text>
            </View>
          }
          renderItem={({ item }) => {
            const remaining = Math.max(0, (item.amount || 0) - (item.consumed_amount || 0));
            const b = statusBadge(item.status);
            const Icon = b.icon;
            return (
              <View style={styles.entry} testID={`credit-entry-${item.id}`}>
                <View style={[styles.statusPill, { backgroundColor: b.bg }]}>
                  <Icon size={12} color={b.color} />
                  <Text style={[styles.statusPillText, { color: b.color }]}>{b.label}</Text>
                </View>
                <Text style={styles.entryTitle}>{item.rule_name || 'Credit'}</Text>
                {item.rule_message ? (
                  <Text style={styles.entryMsg} numberOfLines={2}>{item.rule_message}</Text>
                ) : null}
                <View style={styles.entryFoot}>
                  <Text style={styles.entryDate}>
                    {new Date(item.created_at).toLocaleDateString()}
                    {item.source_group_id ? " \u00b7 " + formatSid(item.source_group_id) : ''}
                  </Text>
                  <Text style={styles.entryAmt}>${remaining.toFixed(2)}</Text>
                </View>
              </View>
            );
          }}
        />
      )}
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
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  summaryRow: { flexDirection: 'row', gap: SPACING.sm, marginBottom: SPACING.md },
  summaryTile: {
    flex: 1, borderRadius: RADIUS.lg, padding: SPACING.md, gap: 4,
  },
  summaryLabel: { color: COLORS.subtext, fontSize: FONT.sizes.xs, fontWeight: FONT.weights.semibold, textTransform: 'uppercase', letterSpacing: 1 },
  summaryAmt: { fontSize: 22, fontWeight: FONT.weights.heavy, letterSpacing: -0.5 },
  subtitle: { color: COLORS.subtext, fontSize: FONT.sizes.sm, lineHeight: 20, marginBottom: SPACING.md },
  sectionTitle: { fontSize: FONT.sizes.xs, color: COLORS.subtext, fontWeight: FONT.weights.semibold, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 8 },
  empty: { alignItems: 'center', padding: SPACING.lg, gap: SPACING.sm },
  emptyTitle: { fontSize: FONT.sizes.lg, fontWeight: FONT.weights.bold, color: COLORS.text },
  emptySub: { color: COLORS.subtext, fontSize: FONT.sizes.sm, textAlign: 'center' },
  entry: {
    backgroundColor: COLORS.surface, borderRadius: RADIUS.md, borderWidth: 1,
    borderColor: COLORS.border, padding: SPACING.md, gap: 4,
  },
  statusPill: { flexDirection: 'row', alignSelf: 'flex-start', alignItems: 'center', gap: 4, paddingHorizontal: 8, paddingVertical: 2, borderRadius: RADIUS.pill },
  statusPillText: { fontSize: 10, fontWeight: FONT.weights.bold, textTransform: 'uppercase', letterSpacing: 0.5 },
  entryTitle: { fontSize: FONT.sizes.md, fontWeight: FONT.weights.bold, color: COLORS.text, marginTop: 4 },
  entryMsg: { fontSize: FONT.sizes.sm, color: COLORS.subtext },
  entryFoot: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginTop: 4 },
  entryDate: { fontSize: FONT.sizes.xs, color: COLORS.subtext },
  entryAmt: { fontSize: 16, fontWeight: FONT.weights.heavy, color: COLORS.text },
});

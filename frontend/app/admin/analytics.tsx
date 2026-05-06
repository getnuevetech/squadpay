import { useEffect, useState, useCallback } from 'react';
import { View, Text, ScrollView, TouchableOpacity, StyleSheet, ActivityIndicator, Alert } from 'react-native';
import { BarChart3, Users, CreditCard, Wallet, TrendingUp, RefreshCw, Receipt } from 'lucide-react-native';
import { adminApi, AnalyticsPayload } from '../../src/adminApi';
import { COLORS, FONT, RADIUS, SPACING } from '../../src/theme';

type Range = '7d' | '30d' | '90d';

function money(n: number) { return `$${(Number(n) || 0).toFixed(2)}`; }
function compactMoney(n: number) {
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `$${(n / 1_000).toFixed(1)}k`;
  return `$${(Number(n) || 0).toFixed(0)}`;
}
function formatShort(d: string) {
  try { const dt = new Date(d); return `${dt.getMonth() + 1}/${dt.getDate()}`; } catch { return d; }
}

// Simple bar chart using flexbox + heights (no external deps)
function BarChart({
  data,
  max,
  color,
  formatter,
  testID,
  height = 130,
}: {
  data: { date: string; value: number }[];
  max?: number;
  color: string;
  formatter?: (v: number) => string;
  testID?: string;
  height?: number;
}) {
  const calcMax = max ?? Math.max(1, ...data.map((d) => d.value));
  // Show ~12 x-axis labels max
  const everyN = Math.max(1, Math.ceil(data.length / 8));
  return (
    <View style={{ height: height + 32 }} testID={testID}>
      <View style={[styles.barRow, { height }]}>
        {data.map((d, i) => {
          const h = calcMax > 0 ? Math.max(2, (d.value / calcMax) * (height - 6)) : 2;
          return (
            <View key={d.date + i} style={styles.barCol}>
              <View
                style={[styles.bar, { height: h, backgroundColor: color }]}
                testID={`bar-${i}`}
              />
            </View>
          );
        })}
      </View>
      <View style={styles.xAxis}>
        {data.map((d, i) => (
          <View key={d.date + 'x' + i} style={styles.barCol}>
            <Text style={styles.xLabel}>{i % everyN === 0 ? formatShort(d.date) : ''}</Text>
          </View>
        ))}
      </View>
    </View>
  );
}

function FunnelStep({ label, value, total, color }: { label: string; value: number; total: number; color: string }) {
  const pct = total > 0 ? Math.round((value / total) * 100) : 0;
  return (
    <View style={styles.funnelRow}>
      <View style={styles.funnelLeft}>
        <Text style={styles.funnelLabel}>{label}</Text>
        <Text style={styles.funnelValue}>{value.toLocaleString()} <Text style={styles.funnelPct}>({pct}%)</Text></Text>
      </View>
      <View style={styles.funnelBarBg}>
        <View style={[styles.funnelBar, { width: `${pct}%`, backgroundColor: color }]} />
      </View>
    </View>
  );
}

export default function AdminAnalytics() {
  const [data, setData] = useState<AnalyticsPayload | null>(null);
  const [busy, setBusy] = useState(true);
  const [range, setRange] = useState<Range>('30d');

  const load = useCallback(async (r: Range) => {
    setBusy(true);
    try {
      const d = await adminApi.getAnalytics(r);
      setData(d);
    } catch (e: any) { Alert.alert('Error', e?.message || 'Failed to load analytics'); }
    finally { setBusy(false); }
  }, []);
  useEffect(() => { load(range); }, [load, range]);

  if (busy && !data) return <View style={styles.center}><ActivityIndicator color={COLORS.primary} /></View>;
  if (!data) return null;

  const t = data.totals;
  const f = data.funnel;
  const c = data.card_metrics;
  const m = data.master_account;

  return (
    <ScrollView contentContainerStyle={{ paddingBottom: 80 }}>
      {/* Header + range toggle */}
      <View style={styles.headerRow}>
        <View style={{ flex: 1 }}>
          <Text style={styles.heading} testID="admin-analytics-heading">Analytics</Text>
          <Text style={styles.subheading}>{data.start_date} → {data.end_date}</Text>
        </View>
        <TouchableOpacity onPress={() => load(range)} style={styles.refreshBtn} activeOpacity={0.85} testID="analytics-refresh">
          <RefreshCw size={14} color="#fff" />
          <Text style={styles.refreshBtnText}>Refresh</Text>
        </TouchableOpacity>
      </View>

      <View style={styles.rangeRow}>
        {(['7d', '30d', '90d'] as Range[]).map((r) => (
          <TouchableOpacity
            key={r}
            onPress={() => setRange(r)}
            style={[styles.chip, range === r && styles.chipActive]}
            activeOpacity={0.85}
            testID={`range-${r}`}
          >
            <Text style={[styles.chipText, range === r && { color: '#fff' }]}>
              Last {r === '7d' ? '7 days' : r === '30d' ? '30 days' : '90 days'}
            </Text>
          </TouchableOpacity>
        ))}
      </View>

      {/* KPI Cards */}
      <View style={styles.kpiGrid}>
        <View style={styles.kpiCard}>
          <View style={[styles.kpiIcon, { backgroundColor: '#EEF2FF' }]}><Users size={18} color="#4F46E5" /></View>
          <Text style={styles.kpiLabel}>New signups</Text>
          <Text style={styles.kpiValue} testID="kpi-signups">{t.signups_in_range}</Text>
          <Text style={styles.kpiSub}>{t.verified_in_range} verified ({t.signups_in_range > 0 ? Math.round(t.verified_in_range / t.signups_in_range * 100) : 0}%)</Text>
        </View>
        <View style={styles.kpiCard}>
          <View style={[styles.kpiIcon, { backgroundColor: '#ECFDF5' }]}><Receipt size={18} color="#059669" /></View>
          <Text style={styles.kpiLabel}>Bills created</Text>
          <Text style={styles.kpiValue} testID="kpi-groups">{t.groups_in_range}</Text>
          <Text style={styles.kpiSub}>{t.groups} all time</Text>
        </View>
        <View style={styles.kpiCard}>
          <View style={[styles.kpiIcon, { backgroundColor: '#FEF3C7' }]}><TrendingUp size={18} color="#D97706" /></View>
          <Text style={styles.kpiLabel}>GMV</Text>
          <Text style={styles.kpiValue} testID="kpi-gmv">{compactMoney(t.gmv_in_range)}</Text>
          <Text style={styles.kpiSub}>{compactMoney(t.gmv)} all time</Text>
        </View>
        <View style={styles.kpiCard}>
          <View style={[styles.kpiIcon, { backgroundColor: '#FEE2E2' }]}><CreditCard size={18} color="#DC2626" /></View>
          <Text style={styles.kpiLabel}>Cards issued</Text>
          <Text style={styles.kpiValue} testID="kpi-cards">{c.total_issued}</Text>
          <Text style={styles.kpiSub}>{c.active} active · {c.inactive} inactive · {compactMoney(c.total_spent)} spent</Text>
        </View>
      </View>

      {/* Daily charts */}
      <View style={styles.card}>
        <Text style={styles.cardTitle}>Bills created per day</Text>
        <Text style={styles.cardSub}>{t.groups_in_range} bills in {data.range_days} days · avg {(t.groups_in_range / data.range_days).toFixed(1)}/day</Text>
        <BarChart
          data={data.groups_per_day.map((d) => ({ date: d.date, value: d.count }))}
          color="#4F46E5"
          testID="chart-groups"
        />
      </View>

      <View style={styles.card}>
        <Text style={styles.cardTitle}>GMV per day</Text>
        <Text style={styles.cardSub}>Total bill amounts created · avg {compactMoney(t.gmv_in_range / data.range_days)}/day</Text>
        <BarChart
          data={data.gmv_per_day.map((d) => ({ date: d.date, value: d.amount }))}
          color="#059669"
          testID="chart-gmv"
        />
      </View>

      <View style={styles.card}>
        <Text style={styles.cardTitle}>Contributions processed per day</Text>
        <Text style={styles.cardSub}>Total {compactMoney(t.gross_processed_in_range)} processed in {data.range_days} days</Text>
        <BarChart
          data={data.contributions_per_day.map((d) => ({ date: d.date, value: d.amount }))}
          color="#D97706"
          testID="chart-contributions"
        />
      </View>

      <View style={styles.card}>
        <Text style={styles.cardTitle}>New signups per day</Text>
        <Text style={styles.cardSub}>{t.signups_in_range} total · {t.verified_in_range} verified</Text>
        <BarChart
          data={data.signups_per_day.map((d) => ({ date: d.date, value: d.count }))}
          color="#0EA5E9"
          testID="chart-signups"
        />
      </View>

      {/* Funnel */}
      <View style={styles.card}>
        <Text style={styles.cardTitle}>Conversion funnel (all-time)</Text>
        <Text style={styles.cardSub}>From signup to settled bill</Text>
        <FunnelStep label="Signed up" value={f.signups} total={f.signups || 1} color="#4F46E5" />
        <FunnelStep label="Verified phone" value={f.verified} total={f.signups || 1} color="#0EA5E9" />
        <FunnelStep label="Joined a bill" value={f.joined_group} total={f.signups || 1} color="#10B981" />
        <FunnelStep label="Contributed" value={f.contributed} total={f.signups || 1} color="#D97706" />
        <FunnelStep label="Settled bills" value={f.settled_groups} total={f.signups || 1} color="#DC2626" />
      </View>

      {/* Top referrers */}
      <View style={styles.card}>
        <Text style={styles.cardTitle}>Top referrers (all-time)</Text>
        <Text style={styles.cardSub}>By number of users they referred</Text>
        {data.top_referrers.length > 0 ? data.top_referrers.map((r, i) => (
          <View key={r.user_id} style={styles.refRow} testID={`top-ref-${i}`}>
            <Text style={styles.refRank}>#{i + 1}</Text>
            <View style={{ flex: 1 }}>
              <Text style={styles.refName} numberOfLines={1}>{r.name}</Text>
              <Text style={styles.refMeta}>Code: {r.referral_code || '—'}</Text>
            </View>
            <View style={{ alignItems: 'flex-end' }}>
              <Text style={styles.refValue}>{r.signups}</Text>
              <Text style={styles.refMeta}>{r.verified_signups} verified</Text>
            </View>
          </View>
        )) : (
          <Text style={[styles.cardSub, { textAlign: 'center', marginTop: 16 }]}>No referrals yet.</Text>
        )}
      </View>

      {/* Card + Master Account summary */}
      <View style={[styles.card, { paddingVertical: SPACING.lg }]}>
        <Text style={styles.cardTitle}>Stripe Issuing summary (all-time)</Text>
        <View style={styles.summaryGrid}>
          <View style={styles.summaryCell}>
            <Text style={styles.summaryLabel}>Total cards issued</Text>
            <Text style={styles.summaryVal}>{c.total_issued}</Text>
          </View>
          <View style={styles.summaryCell}>
            <Text style={styles.summaryLabel}>Active</Text>
            <Text style={[styles.summaryVal, { color: COLORS.success }]}>{c.active}</Text>
          </View>
          <View style={styles.summaryCell}>
            <Text style={styles.summaryLabel}>Inactive</Text>
            <Text style={styles.summaryVal}>{c.inactive}</Text>
          </View>
          <View style={styles.summaryCell}>
            <Text style={styles.summaryLabel}>Total card spend</Text>
            <Text style={[styles.summaryVal, { color: COLORS.warning }]}>{money(c.total_spent)}</Text>
          </View>
          <View style={styles.summaryCell}>
            <Text style={styles.summaryLabel}>Master Account balance</Text>
            <Text style={[styles.summaryVal, { color: COLORS.primary }]}>{money(m.balance)}</Text>
          </View>
          <View style={styles.summaryCell}>
            <Text style={styles.summaryLabel}>Master ledger entries</Text>
            <Text style={styles.summaryVal}>{m.entries}</Text>
          </View>
        </View>
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  headerRow: { flexDirection: 'row', alignItems: 'center', gap: SPACING.md, marginBottom: SPACING.md },
  heading: { fontSize: FONT.sizes.xl, fontWeight: FONT.weights.bold, color: COLORS.text },
  subheading: { fontSize: FONT.sizes.sm, color: COLORS.subtext, marginTop: 2 },
  refreshBtn: { flexDirection: 'row', alignItems: 'center', gap: 6, height: 36, paddingHorizontal: SPACING.md, borderRadius: RADIUS.md, backgroundColor: COLORS.primary },
  refreshBtnText: { color: '#fff', fontWeight: FONT.weights.bold, fontSize: FONT.sizes.xs },
  rangeRow: { flexDirection: 'row', gap: 6, marginBottom: SPACING.md, flexWrap: 'wrap' },
  chip: { paddingHorizontal: SPACING.md, paddingVertical: 8, borderRadius: RADIUS.pill, backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border },
  chipActive: { backgroundColor: COLORS.primary, borderColor: COLORS.primary },
  chipText: { fontSize: FONT.sizes.sm, color: COLORS.text, fontWeight: FONT.weights.semibold },
  kpiGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: SPACING.md, marginBottom: SPACING.md },
  kpiCard: { flexBasis: '23%', flexGrow: 1, minWidth: 160, padding: SPACING.md, borderRadius: RADIUS.md, backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border },
  kpiIcon: { width: 36, height: 36, borderRadius: 18, alignItems: 'center', justifyContent: 'center', marginBottom: 8 },
  kpiLabel: { fontSize: FONT.sizes.xs, color: COLORS.subtext, fontWeight: FONT.weights.semibold, textTransform: 'uppercase' },
  kpiValue: { fontSize: 22, fontWeight: FONT.weights.bold, color: COLORS.text, marginTop: 2 },
  kpiSub: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: 4 },
  card: { backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border, borderRadius: RADIUS.md, padding: SPACING.md, marginBottom: SPACING.md },
  cardTitle: { fontSize: FONT.sizes.md, fontWeight: FONT.weights.bold, color: COLORS.text },
  cardSub: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: 2, marginBottom: SPACING.md },
  // Bar chart
  barRow: { flexDirection: 'row', alignItems: 'flex-end', gap: 1.5, paddingHorizontal: 2 },
  barCol: { flex: 1, alignItems: 'center' },
  bar: { width: '85%', borderTopLeftRadius: 3, borderTopRightRadius: 3, minHeight: 2 },
  xAxis: { flexDirection: 'row', gap: 1.5, marginTop: 6, paddingHorizontal: 2 },
  xLabel: { fontSize: 9, color: COLORS.subtext, textAlign: 'center' },
  // Funnel
  funnelRow: { paddingVertical: 8 },
  funnelLeft: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 },
  funnelLabel: { fontSize: FONT.sizes.sm, color: COLORS.text, fontWeight: FONT.weights.semibold },
  funnelValue: { fontSize: FONT.sizes.sm, color: COLORS.text, fontWeight: FONT.weights.bold },
  funnelPct: { color: COLORS.subtext, fontWeight: FONT.weights.regular },
  funnelBarBg: { height: 8, borderRadius: 4, backgroundColor: COLORS.disabledBg, overflow: 'hidden' },
  funnelBar: { height: '100%', borderRadius: 4 },
  // Top referrers
  refRow: { flexDirection: 'row', alignItems: 'center', gap: SPACING.md, paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: COLORS.border },
  refRank: { fontSize: FONT.sizes.md, fontWeight: FONT.weights.bold, color: COLORS.subtext, width: 32 },
  refName: { fontSize: FONT.sizes.sm, fontWeight: FONT.weights.semibold, color: COLORS.text },
  refMeta: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: 2 },
  refValue: { fontSize: FONT.sizes.md, fontWeight: FONT.weights.bold, color: COLORS.text },
  // Summary grid
  summaryGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: SPACING.md },
  summaryCell: { flex: 1, minWidth: 140, padding: SPACING.md, backgroundColor: COLORS.bg, borderRadius: RADIUS.md, borderWidth: 1, borderColor: COLORS.border },
  summaryLabel: { fontSize: FONT.sizes.xs, color: COLORS.subtext, fontWeight: FONT.weights.semibold, textTransform: 'uppercase' },
  summaryVal: { fontSize: FONT.sizes.lg, fontWeight: FONT.weights.bold, color: COLORS.text, marginTop: 4 },
});

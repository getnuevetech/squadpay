/**
 * Admin → Income & Fees ledger.
 *
 * Each group is a top-level row; tap to expand and see the per-contribution
 * fee-slice drill-down. All amounts are platform-RETAINED (fees the
 * platform keeps — Items/Tax/Tip go to the group's virtual card and are
 * NOT shown here).
 */
import { useEffect, useState } from 'react';
import {
  ActivityIndicator,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import { useRouter } from 'expo-router';
import { ArrowLeft, ChevronDown, Receipt, TrendingUp, Download, FileDown } from 'lucide-react-native';
import { adminApi, IncomeFeesResponse, incomeFeesApi } from '../../src/adminApi';
import { COLORS, FONT, RADIUS, SPACING } from '../../src/theme';
import { toast } from '../../src/components/Toast';
import { Alert } from 'react-native';

export default function AdminIncomeFees() {
  const router = useRouter();
  const [data, setData] = useState<IncomeFeesResponse | null>(null);
  const [busy, setBusy] = useState(true);
  const [open, setOpen] = useState<Record<string, boolean>>({});

  useEffect(() => {
    (async () => {
      try {
        const res = await adminApi.getIncomeFees();
        setData(res);
      } catch (e: any) {
        // Surface to user
        console.error('income-fees load failed', e);
      } finally {
        setBusy(false);
      }
    })();
  }, []);

  if (busy) {
    return (
      <View style={styles.center}>
        <ActivityIndicator color={COLORS.primary} />
      </View>
    );
  }
  if (!data) {
    return (
      <View style={styles.center}>
        <Text style={{ color: COLORS.subtext }}>Could not load income data.</Text>
      </View>
    );
  }

  const t = data.totals;

  return (
    <ScrollView style={{ flex: 1, backgroundColor: COLORS.bg }} contentContainerStyle={{ padding: SPACING.md, paddingBottom: 80 }}>
      <View style={styles.headerRow}>
        <TouchableOpacity onPress={() => router.back()} hitSlop={10}>
          <ArrowLeft size={22} color={COLORS.text} />
        </TouchableOpacity>
        <Text style={styles.heading}>Income & Fees</Text>
        <View style={{ flex: 1 }} />
        {/* Export buttons — CSV is fast, PDF is a one-page landscape ledger */}
        <TouchableOpacity
          onPress={async () => {
            try { const r = await incomeFeesApi.downloadCsv({}); toast.success(`Downloaded ${r.filename}`); }
            catch (e: any) { Alert.alert('Export failed', e?.message || 'CSV download failed'); }
          }}
          style={[styles.exportBtn, { backgroundColor: COLORS.primary }]}
          testID="income-fees-export-csv"
        >
          <Download size={13} color="#fff" />
          <Text style={styles.exportBtnText}>CSV</Text>
        </TouchableOpacity>
        <TouchableOpacity
          onPress={async () => {
            try { const r = await incomeFeesApi.downloadPdf({}); toast.success(`Downloaded ${r.filename}`); }
            catch (e: any) { Alert.alert('Export failed', e?.message || 'PDF download failed'); }
          }}
          style={[styles.exportBtn, { backgroundColor: COLORS.success }]}
          testID="income-fees-export-pdf"
        >
          <FileDown size={13} color="#fff" />
          <Text style={styles.exportBtnText}>PDF</Text>
        </TouchableOpacity>
      </View>
      <Text style={styles.subhead}>
        Total platform-retained fees. Items / Tax / Tip flow to the group's
        virtual card and are NOT shown here.
      </Text>

      {/* Aggregate cards */}
      <View style={styles.cardsRow}>
        <SummaryCard label="All-time retained" amount={t.total_retained} accent />
        <SummaryCard label="Last 30 days" amount={data.window_totals.month} />
      </View>
      <View style={styles.cardsRow}>
        <SummaryCard label="Last 7 days" amount={data.window_totals.week} small />
        <SummaryCard label="Bills counted" amount={t.groups_counted} count small />
        <SummaryCard label="Contributions" amount={t.contributions_counted} count small />
      </View>

      {/* Fee category breakdown */}
      <View style={styles.breakdownCard}>
        <Text style={styles.sectionTitle}>By fee category</Text>
        <BdRow label="Transaction fees" amount={t.transaction_fees} />
        <BdRow label="Platform fees" amount={t.platform_fees} />
        <BdRow label="Extra fee 1" amount={t.extra_1} />
        <BdRow label="Extra fee 2" amount={t.extra_2} />
        {t.extra_other > 0 ? <BdRow label="Other extras" amount={t.extra_other} /> : null}
        <View style={styles.bdTotalRow}>
          <Text style={styles.bdTotalLabel}>Total retained</Text>
          <Text style={styles.bdTotalValue}>${t.total_retained.toFixed(2)}</Text>
        </View>
      </View>

      {/* Per-group table */}
      <Text style={[styles.sectionTitle, { marginTop: SPACING.lg, marginBottom: SPACING.sm }]}>
        Per-group ledger
      </Text>

      {data.groups.length === 0 ? (
        <Text style={{ color: COLORS.subtext }}>No bills yet.</Text>
      ) : (
        data.groups.map((g) => {
          const isOpen = !!open[g.id];
          return (
            <View key={g.id} style={styles.groupCard}>
              <TouchableOpacity
                style={styles.groupRow}
                onPress={() => setOpen((p) => ({ ...p, [g.id]: !p[g.id] }))}
                activeOpacity={0.7}
              >
                <View style={{ flex: 1 }}>
                  <Text style={styles.groupTitle} numberOfLines={1}>{g.title}</Text>
                  <Text style={styles.groupMeta}>
                    {g.status} · {g.members_count} members · ${g.gross_contributed.toFixed(2)} contributed
                    {g.virtual_card_last4 ? ` · card ••${g.virtual_card_last4}` : ''}
                  </Text>
                </View>
                <View style={{ alignItems: 'flex-end' }}>
                  <Text style={styles.groupAmount}>${g.fees.total_retained.toFixed(2)}</Text>
                  <Text style={styles.groupAmountLabel}>retained</Text>
                </View>
                <View style={[{ marginLeft: 8 }, isOpen && { transform: [{ rotate: '180deg' }] }]}>
                  <ChevronDown size={18} color={COLORS.subtext} />
                </View>
              </TouchableOpacity>

              {isOpen && (
                <View style={styles.expandPane}>
                  <View style={styles.bdMini}>
                    <BdRow small label="Transaction" amount={g.fees.transaction_fees} />
                    <BdRow small label="Platform" amount={g.fees.platform_fees} />
                    <BdRow small label="Extra 1" amount={g.fees.extra_1} />
                    <BdRow small label="Extra 2" amount={g.fees.extra_2} />
                  </View>
                  <Text style={styles.contribHeading}>Contributions ({g.contributions.length})</Text>
                  {g.contributions.length === 0 ? (
                    <Text style={styles.empty}>No contributions yet.</Text>
                  ) : (
                    g.contributions.map((c, i) => (
                      <View key={i} style={styles.contribRow}>
                        <View style={{ flex: 1 }}>
                          <Text style={styles.contribName}>{c.user_name}</Text>
                          <Text style={styles.contribMeta}>
                            {c.ts ? new Date(c.ts).toLocaleString() : '—'} · ${c.amount.toFixed(2)} paid
                          </Text>
                        </View>
                        <View style={{ alignItems: 'flex-end' }}>
                          <Text style={styles.contribAmount}>${c.fee_slice_total.toFixed(2)}</Text>
                          <Text style={styles.contribMetaSmall}>
                            Tx ${c.transaction_fee.toFixed(2)} · Pl ${c.platform_fee.toFixed(2)}
                            {c.extra_1 > 0 ? ` · E1 $${c.extra_1.toFixed(2)}` : ''}
                            {c.extra_2 > 0 ? ` · E2 $${c.extra_2.toFixed(2)}` : ''}
                          </Text>
                        </View>
                      </View>
                    ))
                  )}
                </View>
              )}
            </View>
          );
        })
      )}
    </ScrollView>
  );
}

function SummaryCard({
  label, amount, accent, small, count,
}: { label: string; amount: number; accent?: boolean; small?: boolean; count?: boolean }) {
  return (
    <View style={[styles.summaryCard, accent && styles.summaryCardAccent, small && { paddingVertical: 12 }]}>
      <Text style={[styles.summaryLabel, accent && { color: '#D7C7FB' }]}>{label}</Text>
      <Text style={[styles.summaryAmount, accent && { color: '#fff' }, small && { fontSize: 22 }]}>
        {count ? amount : `$${amount.toFixed(2)}`}
      </Text>
    </View>
  );
}

function BdRow({ label, amount, small }: { label: string; amount: number; small?: boolean }) {
  return (
    <View style={styles.bdRow}>
      <Text style={[styles.bdLabel, small && { fontSize: 12 }]}>{label}</Text>
      <Text style={[styles.bdValue, small && { fontSize: 12 }]}>${amount.toFixed(2)}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: COLORS.bg },
  headerRow: { flexDirection: 'row', alignItems: 'center', gap: SPACING.md, marginBottom: 4 },
  exportBtn: { flexDirection: 'row', alignItems: 'center', gap: 4, paddingHorizontal: 12, height: 32, borderRadius: RADIUS.md },
  exportBtnText: { color: '#fff', fontWeight: FONT.weights.bold, fontSize: FONT.sizes.xs },
  heading: { flex: 1, fontSize: FONT.sizes.lg, fontWeight: FONT.weights.heavy, color: COLORS.text },
  subhead: { color: COLORS.subtext, fontSize: 12, marginBottom: SPACING.md, lineHeight: 17 },
  cardsRow: { flexDirection: 'row', gap: SPACING.sm, marginBottom: SPACING.sm },
  summaryCard: { flex: 1, backgroundColor: COLORS.surface, borderRadius: RADIUS.lg, padding: SPACING.md, borderWidth: 1, borderColor: COLORS.border },
  summaryCardAccent: { backgroundColor: COLORS.primary, borderColor: COLORS.primary },
  summaryLabel: { color: COLORS.subtext, fontSize: 11, textTransform: 'uppercase', letterSpacing: 0.5, fontWeight: FONT.weights.semibold, marginBottom: 4 },
  summaryAmount: { color: COLORS.text, fontSize: 28, fontWeight: FONT.weights.heavy, letterSpacing: -0.5 },
  breakdownCard: { backgroundColor: COLORS.surface, borderRadius: RADIUS.lg, padding: SPACING.md, borderWidth: 1, borderColor: COLORS.border, marginTop: SPACING.sm },
  sectionTitle: { color: COLORS.text, fontSize: FONT.sizes.md, fontWeight: FONT.weights.bold, marginBottom: SPACING.sm },
  bdRow: { flexDirection: 'row', justifyContent: 'space-between', paddingVertical: 5 },
  bdLabel: { color: COLORS.subtext, fontSize: FONT.sizes.sm },
  bdValue: { color: COLORS.text, fontSize: FONT.sizes.sm, fontWeight: FONT.weights.semibold },
  bdTotalRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', borderTopWidth: 1, borderTopColor: COLORS.border, marginTop: 6, paddingTop: 8 },
  bdTotalLabel: { color: COLORS.text, fontSize: FONT.sizes.sm, fontWeight: FONT.weights.bold },
  bdTotalValue: { color: COLORS.primary, fontSize: FONT.sizes.lg, fontWeight: FONT.weights.heavy },
  groupCard: { backgroundColor: COLORS.surface, borderRadius: RADIUS.md, marginBottom: SPACING.sm, borderWidth: 1, borderColor: COLORS.border, overflow: 'hidden' },
  groupRow: { flexDirection: 'row', alignItems: 'center', padding: SPACING.md, gap: SPACING.sm },
  groupTitle: { color: COLORS.text, fontWeight: FONT.weights.bold, fontSize: FONT.sizes.sm },
  groupMeta: { color: COLORS.subtext, fontSize: 11, marginTop: 2 },
  groupAmount: { color: COLORS.text, fontWeight: FONT.weights.heavy, fontSize: FONT.sizes.md },
  groupAmountLabel: { color: COLORS.subtext, fontSize: 10, textTransform: 'uppercase', letterSpacing: 0.5 },
  expandPane: { paddingHorizontal: SPACING.md, paddingBottom: SPACING.md, borderTopWidth: 1, borderTopColor: COLORS.border, backgroundColor: COLORS.bg },
  bdMini: { paddingVertical: SPACING.sm },
  contribHeading: { color: COLORS.subtext, fontSize: 11, textTransform: 'uppercase', letterSpacing: 0.5, fontWeight: FONT.weights.semibold, marginTop: SPACING.sm, marginBottom: 6 },
  contribRow: { flexDirection: 'row', alignItems: 'center', paddingVertical: 6, gap: SPACING.sm, borderTopWidth: 1, borderTopColor: COLORS.border },
  contribName: { color: COLORS.text, fontSize: FONT.sizes.sm, fontWeight: FONT.weights.semibold },
  contribMeta: { color: COLORS.subtext, fontSize: 11, marginTop: 2 },
  contribAmount: { color: COLORS.success, fontWeight: FONT.weights.bold, fontSize: FONT.sizes.sm },
  contribMetaSmall: { color: COLORS.subtext, fontSize: 10, marginTop: 2 },
  empty: { color: COLORS.subtext, fontSize: 12, textAlign: 'center', paddingVertical: SPACING.sm },
});

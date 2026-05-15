/**
 * /admin/reconciliation-drift — Phase 1 of Real-Time Ledger Reconciliation.
 *
 * Surfaces drift rows produced by the backend `admin_reconciliation_drift`
 * scanner. Admin can:
 *   • See unresolved drift summarised by kind
 *   • Trigger a fresh scan on-demand (vs the 15-min background loop)
 *   • Mark a drift row resolved (acknowledgement / manual fix completed)
 *   • View the last 20 scan run summaries
 *
 * Scope: PURE OBSERVATION. No mutations to groups, contributions, or
 * Stripe from this screen. Future phases will add auto-recovery actions.
 */
import { useEffect, useState, useCallback } from 'react';
import {
  ActivityIndicator,
  Alert,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import { useRouter } from 'expo-router';
import { RefreshCw, CheckCircle2, AlertTriangle, ChevronRight } from 'lucide-react-native';
import { reconciliationApi } from '../../src/adminApi';
import { COLORS, FONT, RADIUS, SPACING } from '../../src/theme';

type DriftRow = {
  id: string;
  group_id: string;
  group_title: string;
  group_status: string;
  kind: string;
  expected: number;
  observed: number;
  delta: number;
  detected_at: string;
  resolved: boolean;
  resolved_at?: string;
  resolved_by?: string;
  resolution_note?: string;
  notes?: string;
};
type RunRow = {
  id: string;
  ran_at: string;
  elapsed_ms: number;
  kinds_scanned: string[];
  drifts_found: number;
  rows_inserted: number;
  rows_refreshed: number;
};

function money(n: number) {
  return `$${(Number(n) || 0).toFixed(2)}`;
}
function fmtDate(s?: string) {
  if (!s) return '—';
  try {
    return new Date(s).toLocaleString();
  } catch {
    return s;
  }
}
function kindLabel(k: string) {
  if (k === 'db_internal') return 'DB Denorm';
  if (k === 'settlement_imbalance') return 'Settlement Imbalance';
  return k;
}
function kindColor(k: string): { bg: string; fg: string } {
  if (k === 'db_internal') return { bg: '#FEF3C7', fg: '#92400E' };
  if (k === 'settlement_imbalance') return { bg: '#FEE2E2', fg: '#991B1B' };
  return { bg: COLORS.disabledBg, fg: COLORS.subtext };
}

export default function AdminReconciliationDrift() {
  const router = useRouter();
  const [items, setItems] = useState<DriftRow[]>([]);
  const [runs, setRuns] = useState<RunRow[]>([]);
  const [total, setTotal] = useState(0);
  const [busy, setBusy] = useState(true);
  const [scanning, setScanning] = useState(false);
  const [showResolved, setShowResolved] = useState(false);

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const [list, runsRes] = await Promise.all([
        reconciliationApi.driftList({ resolved: showResolved ? undefined : false, limit: 200 }),
        reconciliationApi.driftRuns(),
      ]);
      setItems(list.items);
      setTotal(list.total);
      setRuns(runsRes.items);
    } catch (e: any) {
      Alert.alert('Load failed', e?.message || 'Could not load drift data');
    } finally {
      setBusy(false);
    }
  }, [showResolved]);

  useEffect(() => {
    load();
  }, [load]);

  const scanNow = async () => {
    setScanning(true);
    try {
      const summary = await reconciliationApi.driftScanNow();
      await load();
      Alert.alert(
        'Scan complete',
        `Found ${summary.drifts_found} drift row${summary.drifts_found === 1 ? '' : 's'} ` +
          `(${summary.rows_inserted} new, ${summary.rows_refreshed} refreshed) in ${summary.elapsed_ms}ms.`,
      );
    } catch (e: any) {
      Alert.alert('Scan failed', e?.message || 'Could not run scan');
    } finally {
      setScanning(false);
    }
  };

  const resolveOne = async (row: DriftRow) => {
    Alert.alert(
      'Mark resolved?',
      `Acknowledge drift on "${row.group_title}" (${kindLabel(row.kind)})?\n\nThis is an audit acknowledgement — it does NOT fix the underlying data.`,
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Resolve',
          style: 'destructive',
          onPress: async () => {
            try {
              await reconciliationApi.driftResolve(row.id, 'Acknowledged by admin');
              await load();
            } catch (e: any) {
              Alert.alert('Failed', e?.message || 'Could not resolve');
            }
          },
        },
      ],
    );
  };

  const lastRun = runs[0];
  const unresolvedCount = items.filter((d) => !d.resolved).length;
  const dbDenormCount = items.filter((d) => d.kind === 'db_internal' && !d.resolved).length;
  const imbalanceCount = items.filter((d) => d.kind === 'settlement_imbalance' && !d.resolved).length;

  return (
    <ScrollView style={styles.root} contentContainerStyle={styles.content}>
      <View style={styles.headerRow}>
        <Text style={styles.title}>Reconciliation Drift</Text>
        <TouchableOpacity
          style={[styles.scanBtn, scanning && styles.scanBtnBusy]}
          onPress={scanNow}
          disabled={scanning}
          testID="drift-scan-now"
        >
          {scanning ? (
            <ActivityIndicator size="small" color="#FFF" />
          ) : (
            <>
              <RefreshCw size={14} color="#FFF" />
              <Text style={styles.scanBtnText}>Scan now</Text>
            </>
          )}
        </TouchableOpacity>
      </View>
      <Text style={styles.subtitle}>
        Phase 1 of Real-Time Ledger Reconciliation. Detects denormalization rot and
        settlement imbalances. Pure observation — never mutates groups.
      </Text>

      {/* Status header */}
      {lastRun && (
        <View style={styles.statusCard}>
          <Text style={styles.statusLabel}>Last scan</Text>
          <Text style={styles.statusValue}>{fmtDate(lastRun.ran_at)}</Text>
          <Text style={styles.statusSub}>
            {lastRun.drifts_found} drift{lastRun.drifts_found === 1 ? '' : 's'} found · {lastRun.elapsed_ms}ms ·{' '}
            {lastRun.kinds_scanned.join(', ')}
          </Text>
        </View>
      )}

      {/* KPI tiles */}
      <View style={styles.kpiRow}>
        <View style={styles.kpiTile}>
          <Text style={styles.kpiNumber}>{unresolvedCount}</Text>
          <Text style={styles.kpiLabel}>Unresolved</Text>
        </View>
        <View style={styles.kpiTile}>
          <Text style={[styles.kpiNumber, { color: '#92400E' }]}>{dbDenormCount}</Text>
          <Text style={styles.kpiLabel}>DB Denorm</Text>
        </View>
        <View style={styles.kpiTile}>
          <Text style={[styles.kpiNumber, { color: '#991B1B' }]}>{imbalanceCount}</Text>
          <Text style={styles.kpiLabel}>Imbalance</Text>
        </View>
      </View>

      <TouchableOpacity
        style={styles.toggleRow}
        onPress={() => setShowResolved((v) => !v)}
        testID="drift-toggle-resolved"
      >
        <Text style={styles.toggleText}>
          {showResolved ? 'Showing all (resolved + unresolved)' : 'Showing unresolved only'}
        </Text>
        <Text style={styles.toggleAction}>{showResolved ? 'Hide resolved' : 'Show resolved'}</Text>
      </TouchableOpacity>

      {busy ? (
        <View style={styles.center}>
          <ActivityIndicator color={COLORS.primary} />
        </View>
      ) : items.length === 0 ? (
        <View style={styles.center}>
          <CheckCircle2 size={48} color={COLORS.success} />
          <Text style={styles.emptyTitle}>No drift detected</Text>
          <Text style={styles.emptySub}>
            All groups' funding aggregates match their contributions. The
            ledger is in balance.
          </Text>
        </View>
      ) : (
        <View>
          {items.map((d) => {
            const c = kindColor(d.kind);
            return (
              <View
                key={d.id}
                style={[styles.driftRow, d.resolved && styles.driftRowResolved]}
                testID={`drift-row-${d.id}`}
              >
                <View style={styles.driftHeaderRow}>
                  <View style={[styles.kindPill, { backgroundColor: c.bg }]}>
                    <Text style={[styles.kindPillText, { color: c.fg }]}>
                      {kindLabel(d.kind)}
                    </Text>
                  </View>
                  {d.resolved ? (
                    <View style={styles.resolvedBadge}>
                      <CheckCircle2 size={12} color={COLORS.success} />
                      <Text style={styles.resolvedText}>Resolved</Text>
                    </View>
                  ) : (
                    <AlertTriangle size={16} color="#DC2626" />
                  )}
                </View>
                <TouchableOpacity
                  onPress={() => router.push(`/admin/groups/${d.group_id}`)}
                  activeOpacity={0.7}
                >
                  <Text style={styles.groupTitle}>{d.group_title}</Text>
                  <Text style={styles.groupSub}>
                    {d.group_id} · {d.group_status}
                  </Text>
                </TouchableOpacity>
                <View style={styles.numbersRow}>
                  <View style={styles.numberCell}>
                    <Text style={styles.numberLabel}>Expected</Text>
                    <Text style={styles.numberValue}>{money(d.expected)}</Text>
                  </View>
                  <View style={styles.numberCell}>
                    <Text style={styles.numberLabel}>Observed</Text>
                    <Text style={styles.numberValue}>{money(d.observed)}</Text>
                  </View>
                  <View style={styles.numberCell}>
                    <Text style={styles.numberLabel}>Delta</Text>
                    <Text
                      style={[
                        styles.numberValue,
                        { color: Math.abs(d.delta) > 0.01 ? '#DC2626' : COLORS.text },
                      ]}
                    >
                      {d.delta > 0 ? '+' : ''}
                      {money(d.delta).replace('$', '$')}
                    </Text>
                  </View>
                </View>
                {d.notes && <Text style={styles.notes}>{d.notes}</Text>}
                {d.resolution_note && (
                  <Text style={styles.resolutionNote}>
                    Resolved {fmtDate(d.resolved_at)} by {d.resolved_by}:{' '}
                    {d.resolution_note}
                  </Text>
                )}
                {!d.resolved && (
                  <TouchableOpacity
                    style={styles.resolveBtn}
                    onPress={() => resolveOne(d)}
                    testID={`drift-resolve-${d.id}`}
                  >
                    <Text style={styles.resolveBtnText}>Mark resolved</Text>
                  </TouchableOpacity>
                )}
              </View>
            );
          })}
          {total > items.length && (
            <Text style={styles.footnote}>
              Showing {items.length} of {total} rows
            </Text>
          )}
        </View>
      )}

      {/* Scan history */}
      <View style={styles.section}>
        <Text style={styles.sectionTitle}>Scan history (last 20)</Text>
        {runs.length === 0 ? (
          <Text style={styles.footnote}>No scans recorded yet.</Text>
        ) : (
          runs.map((rn) => (
            <View key={rn.id} style={styles.runRow}>
              <Text style={styles.runDate}>{fmtDate(rn.ran_at)}</Text>
              <Text style={styles.runDetail}>
                {rn.drifts_found} found · {rn.rows_inserted} new · {rn.rows_refreshed} refreshed · {rn.elapsed_ms}ms
              </Text>
            </View>
          ))
        )}
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: COLORS.bg },
  content: { padding: SPACING.md, paddingBottom: SPACING.xl },
  headerRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  title: { fontSize: FONT.sizes.xl, fontWeight: FONT.weights.bold, color: COLORS.text },
  subtitle: { fontSize: FONT.sizes.sm, color: COLORS.subtext, marginTop: 4, marginBottom: SPACING.md },
  scanBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    backgroundColor: COLORS.primary,
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: RADIUS.md,
  },
  scanBtnBusy: { opacity: 0.7 },
  scanBtnText: { color: '#FFF', fontWeight: FONT.weights.semibold, fontSize: FONT.sizes.sm },
  statusCard: {
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.md,
    padding: SPACING.md,
    borderWidth: 1,
    borderColor: COLORS.border,
    marginBottom: SPACING.md,
  },
  statusLabel: { fontSize: FONT.sizes.xs, color: COLORS.subtext, textTransform: 'uppercase' },
  statusValue: { fontSize: FONT.sizes.md, color: COLORS.text, fontWeight: FONT.weights.semibold, marginTop: 2 },
  statusSub: { fontSize: FONT.sizes.sm, color: COLORS.subtext, marginTop: 4 },
  kpiRow: { flexDirection: 'row', gap: SPACING.sm, marginBottom: SPACING.md },
  kpiTile: {
    flex: 1,
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.md,
    padding: SPACING.md,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: COLORS.border,
  },
  kpiNumber: { fontSize: 24, fontWeight: FONT.weights.bold, color: COLORS.text },
  kpiLabel: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: 2 },
  toggleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: SPACING.sm,
  },
  toggleText: { fontSize: FONT.sizes.sm, color: COLORS.subtext },
  toggleAction: { fontSize: FONT.sizes.sm, color: COLORS.primary, fontWeight: FONT.weights.semibold },
  center: { alignItems: 'center', justifyContent: 'center', padding: SPACING.lg, gap: SPACING.sm },
  emptyTitle: { fontSize: FONT.sizes.md, fontWeight: FONT.weights.semibold, color: COLORS.text, marginTop: 8 },
  emptySub: { fontSize: FONT.sizes.sm, color: COLORS.subtext, textAlign: 'center', maxWidth: 320 },
  driftRow: {
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.md,
    padding: SPACING.md,
    marginBottom: SPACING.sm,
    borderWidth: 1,
    borderColor: COLORS.border,
  },
  driftRowResolved: { opacity: 0.55 },
  driftHeaderRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  kindPill: { paddingHorizontal: 8, paddingVertical: 2, borderRadius: 999 },
  kindPillText: { fontSize: 11, fontWeight: FONT.weights.semibold },
  resolvedBadge: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  resolvedText: { fontSize: 11, color: COLORS.success, fontWeight: FONT.weights.semibold },
  groupTitle: { fontSize: FONT.sizes.md, fontWeight: FONT.weights.semibold, color: COLORS.text, marginTop: 8 },
  groupSub: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: 2 },
  numbersRow: { flexDirection: 'row', gap: SPACING.md, marginTop: SPACING.sm },
  numberCell: { flex: 1 },
  numberLabel: { fontSize: FONT.sizes.xs, color: COLORS.subtext, textTransform: 'uppercase' },
  numberValue: { fontSize: FONT.sizes.md, color: COLORS.text, fontWeight: FONT.weights.semibold, marginTop: 2 },
  notes: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: SPACING.sm, lineHeight: 16 },
  resolutionNote: {
    fontSize: FONT.sizes.xs,
    color: COLORS.success,
    marginTop: SPACING.sm,
    fontStyle: 'italic',
  },
  resolveBtn: {
    marginTop: SPACING.sm,
    alignSelf: 'flex-start',
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: RADIUS.sm,
    borderWidth: 1,
    borderColor: COLORS.border,
  },
  resolveBtnText: { color: COLORS.text, fontSize: FONT.sizes.xs, fontWeight: FONT.weights.semibold },
  footnote: { fontSize: FONT.sizes.xs, color: COLORS.subtext, textAlign: 'center', marginTop: SPACING.md },
  section: { marginTop: SPACING.lg },
  sectionTitle: {
    fontSize: FONT.sizes.md,
    fontWeight: FONT.weights.semibold,
    color: COLORS.text,
    marginBottom: SPACING.sm,
  },
  runRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingVertical: 6,
    borderBottomWidth: 1,
    borderBottomColor: COLORS.border,
  },
  runDate: { fontSize: FONT.sizes.sm, color: COLORS.text },
  runDetail: { fontSize: FONT.sizes.xs, color: COLORS.subtext },
});

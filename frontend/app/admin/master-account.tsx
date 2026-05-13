import { useEffect, useState, useCallback } from 'react';
import { View, Text, ScrollView, TouchableOpacity, StyleSheet, ActivityIndicator, Alert } from 'react-native';
import { Wallet, RefreshCw, AlertCircle, Download } from 'lucide-react-native';
import { adminApi, MasterAccountEntry } from '../../src/adminApi';
import { COLORS, FONT, RADIUS, SPACING } from '../../src/theme';
import { toast } from '../../src/components/Toast';

function money(n: number) { return `$${(Number(n) || 0).toFixed(2)}`; }
function fmtDate(s?: string) { if (!s) return '—'; try { return new Date(s).toLocaleString(); } catch { return s; } }

export default function AdminMasterAccount() {
  const [items, setItems] = useState<MasterAccountEntry[] | null>(null);
  const [balance, setBalance] = useState(0);
  const [total, setTotal] = useState(0);
  const [busy, setBusy] = useState(true);

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const r = await adminApi.getMasterAccount({ limit: 200 });
      setItems(r.items);
      setBalance(r.balance);
      setTotal(r.total);
    } catch (e: any) { Alert.alert('Error', e?.message || 'Failed to load'); }
    finally { setBusy(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  // Export to CSV — uses native browser anchor download on web; mobile gets a toast.
  const onExportCsv = () => {
    if (!items || items.length === 0) {
      Alert.alert('Nothing to export', 'No ledger entries to download.');
      return;
    }
    const rows: (string | number)[][] = [
      ['Created at', 'Created by', 'Group title', 'Lead', 'Source card', 'Amount', 'Balance after', 'Note'],
    ];
    for (const e of items) {
      rows.push([
        e.created_at || '',
        e.created_by || '',
        e.group_title || '',
        e.lead_name || '',
        e.card_id || '',
        Number(e.amount || 0).toFixed(2),
        Number(e.balance_after || 0).toFixed(2),
        (e.note || '').replace(/[\r\n]+/g, ' '),
      ]);
    }
    const csv = rows.map((r) => r.map((c) => {
      const s = String(c ?? '');
      // Escape commas, quotes and newlines per RFC4180
      return /[,"\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
    }).join(',')).join('\n');
    const filename = `master_account_${new Date().toISOString().replace(/[:.]/g, '-')}.csv`;
    if (typeof window !== 'undefined' && typeof document !== 'undefined') {
      const blob = new Blob([csv], { type: 'text/csv' });
      const href = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = href;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(href);
      toast.success(`Downloaded ${filename}`);
    } else {
      Alert.alert('CSV ready', `${filename} (${csv.length} bytes). Please export from the admin web console.`);
    }
  };

  if (busy && !items) return <View style={styles.center}><ActivityIndicator color={COLORS.primary} /></View>;

  return (
    <ScrollView contentContainerStyle={{ paddingBottom: 80 }} horizontal={false}>
      <Text style={styles.heading} testID="admin-master-heading">Master Account</Text>
      <Text style={styles.subheading}>
        Ledger of all leftover funds collected after group payments settle.
        Each entry traces back to the originating squad.
      </Text>

      <View style={styles.balanceCard}>
        <View style={styles.balanceIcon}><Wallet size={24} color="#fff" /></View>
        <View style={{ flex: 1 }}>
          <Text style={styles.balanceLabel}>Master account balance</Text>
          <Text style={styles.balanceVal} testID="master-balance">{money(balance)}</Text>
          <Text style={styles.balanceSub}>{total} ledger entries</Text>
        </View>
        <View style={{ gap: 8 }}>
          <TouchableOpacity onPress={load} style={styles.refreshBtn} activeOpacity={0.85} testID="master-refresh">
            <RefreshCw size={14} color="#fff" />
            <Text style={styles.refreshBtnText}>Refresh</Text>
          </TouchableOpacity>
          <TouchableOpacity onPress={onExportCsv} style={[styles.refreshBtn, { backgroundColor: 'rgba(255,255,255,0.25)' }]} activeOpacity={0.85} testID="master-export-csv">
            <Download size={14} color="#fff" />
            <Text style={styles.refreshBtnText}>CSV</Text>
          </TouchableOpacity>
        </View>
      </View>

      {/* Proper data table — header row plus one data row per ledger entry.
          Horizontal scroll on small screens so columns don't squish. */}
      <ScrollView horizontal showsHorizontalScrollIndicator>
        <View style={styles.tableWrap}>
          <View style={[styles.tableRow, styles.tableHeaderRow]}>
            <Text style={[styles.th, styles.colDate]}>Date</Text>
            <Text style={[styles.th, styles.colGroup]}>Group</Text>
            <Text style={[styles.th, styles.colLead]}>Lead</Text>
            <Text style={[styles.th, styles.colCard]}>Source ref</Text>
            <Text style={[styles.th, styles.colAmount, styles.right]}>Amount</Text>
            <Text style={[styles.th, styles.colAmount, styles.right]}>Balance after</Text>
            <Text style={[styles.th, styles.colNote]}>Note</Text>
            <Text style={[styles.th, styles.colBy]}>By</Text>
          </View>

          {items && items.length > 0 ? items.map((it, idx) => (
            <View
              key={it.id}
              style={[styles.tableRow, idx % 2 === 0 ? styles.rowEven : styles.rowOdd]}
              testID={`master-row-${it.id}`}
            >
              <Text style={[styles.td, styles.colDate]} numberOfLines={1}>{fmtDate(it.created_at)}</Text>
              <Text style={[styles.td, styles.colGroup, styles.strong]} numberOfLines={1}>{it.group_title || '—'}</Text>
              <Text style={[styles.td, styles.colLead]} numberOfLines={1}>{it.lead_name || '—'}</Text>
              <Text style={[styles.td, styles.colCard, styles.mono]} numberOfLines={1}>{it.card_id?.slice(-12) || '—'}</Text>
              <Text style={[styles.td, styles.colAmount, styles.right, { color: COLORS.success, fontWeight: FONT.weights.bold }]}>+{money(it.amount)}</Text>
              <Text style={[styles.td, styles.colAmount, styles.right, styles.strong]}>{money(it.balance_after)}</Text>
              <Text style={[styles.td, styles.colNote]} numberOfLines={2}>{it.note || '—'}</Text>
              <Text style={[styles.td, styles.colBy]} numberOfLines={1}>{it.created_by || '—'}</Text>
            </View>
          )) : !busy ? (
            <View style={styles.emptyState}>
              <AlertCircle size={20} color={COLORS.subtext} />
              <Text style={styles.emptyText}>
                No master account entries yet. Entries are created automatically when a squad
                settles and "credit contributors" is off.
              </Text>
            </View>
          ) : null}
        </View>
      </ScrollView>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  heading: { fontSize: FONT.sizes.xl, fontWeight: FONT.weights.bold, color: COLORS.text },
  subheading: { fontSize: FONT.sizes.sm, color: COLORS.subtext, marginBottom: SPACING.lg },
  balanceCard: { flexDirection: 'row', alignItems: 'center', gap: SPACING.md, padding: SPACING.lg, marginBottom: SPACING.lg, backgroundColor: COLORS.primary, borderRadius: RADIUS.md },
  balanceIcon: { width: 48, height: 48, borderRadius: 24, backgroundColor: 'rgba(255,255,255,0.2)', alignItems: 'center', justifyContent: 'center' },
  balanceLabel: { fontSize: FONT.sizes.xs, color: 'rgba(255,255,255,0.85)', fontWeight: FONT.weights.semibold, textTransform: 'uppercase' },
  balanceVal: { fontSize: 28, fontWeight: FONT.weights.bold, color: '#fff', marginTop: 4 },
  balanceSub: { fontSize: FONT.sizes.xs, color: 'rgba(255,255,255,0.85)', marginTop: 2 },
  refreshBtn: { flexDirection: 'row', alignItems: 'center', gap: 6, height: 32, paddingHorizontal: SPACING.md, borderRadius: RADIUS.md, backgroundColor: 'rgba(0,0,0,0.18)' },
  refreshBtnText: { color: '#fff', fontWeight: FONT.weights.bold, fontSize: FONT.sizes.xs },
  // Table
  tableWrap: { minWidth: 1024, backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border, borderRadius: RADIUS.md, overflow: 'hidden' },
  tableRow: { flexDirection: 'row', alignItems: 'center', borderBottomWidth: 1, borderBottomColor: COLORS.border, paddingHorizontal: SPACING.sm },
  tableHeaderRow: { backgroundColor: COLORS.bg, borderBottomWidth: 2 },
  rowEven: { backgroundColor: COLORS.surface },
  rowOdd: { backgroundColor: COLORS.bg },
  th: { fontSize: 11, color: COLORS.subtext, fontWeight: FONT.weights.bold, textTransform: 'uppercase', letterSpacing: 0.4, paddingVertical: 10, paddingHorizontal: 6 },
  td: { fontSize: FONT.sizes.sm, color: COLORS.text, paddingVertical: 10, paddingHorizontal: 6 },
  strong: { fontWeight: FONT.weights.semibold },
  mono: { fontFamily: 'monospace', letterSpacing: 0.4 },
  right: { textAlign: 'right' },
  colDate: { width: 160 },
  colGroup: { width: 200 },
  colLead: { width: 140 },
  colCard: { width: 140 },
  colAmount: { width: 110 },
  colNote: { width: 200 },
  colBy: { width: 140 },
  emptyState: { padding: SPACING.xl, alignItems: 'center', justifyContent: 'center', gap: 8 },
  emptyText: { fontSize: FONT.sizes.xs, color: COLORS.subtext, fontStyle: 'italic', textAlign: 'center', maxWidth: 480 },
});

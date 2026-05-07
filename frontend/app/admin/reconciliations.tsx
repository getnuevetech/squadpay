import { useEffect, useState, useCallback } from 'react';
import { View, Text, ScrollView, TextInput, TouchableOpacity, StyleSheet, ActivityIndicator, Alert, Switch } from 'react-native';
import { RefreshCw, Search, Filter, ChevronRight, Save, AlertCircle } from 'lucide-react-native';
import { adminApi, ReconciliationRow, ReconciliationSettings } from '../../src/adminApi';
import { COLORS, FONT, RADIUS, SPACING } from '../../src/theme';

function money(n: number) { return `$${(Number(n) || 0).toFixed(2)}`; }
function fmtDate(s?: string) { if (!s) return '—'; try { return new Date(s).toLocaleString(); } catch { return s; } }

function ActionPill({ action }: { action: string | null }) {
  let bg = COLORS.disabledBg, fg = COLORS.subtext, label = action || '—';
  if (action === 'credit_contributors') { bg = '#ECFDF5'; fg = '#059669'; label = 'Credited'; }
  else if (action === 'moved_to_master') { bg = '#EEF2FF'; fg = '#4F46E5'; label = 'Moved to Master'; }
  else if (action === 'no_leftover') { bg = COLORS.disabledBg; fg = COLORS.subtext; label = 'No leftover'; }
  return (
    <View style={[styles.pill, { backgroundColor: bg }]}>
      <Text style={[styles.pillText, { color: fg }]}>{label}</Text>
    </View>
  );
}

export default function AdminReconciliations() {
  const [items, setItems] = useState<ReconciliationRow[] | null>(null);
  const [total, setTotal] = useState(0);
  const [busy, setBusy] = useState(true);
  const [q, setQ] = useState('');
  const [actionFilter, setActionFilter] = useState<string>('');
  const [settings, setSettings] = useState<ReconciliationSettings | null>(null);
  const [savingSet, setSavingSet] = useState(false);
  const [detail, setDetail] = useState<ReconciliationRow | null>(null);

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const [list, s] = await Promise.all([
        adminApi.listReconciliations({ q: q || undefined, action: actionFilter || undefined, limit: 50 }),
        adminApi.getReconciliationSettings(),
      ]);
      setItems(list.items);
      setTotal(list.total);
      setSettings(s);
    } catch (e: any) { Alert.alert('Error', e?.message || 'Failed to load'); }
    finally { setBusy(false); }
  }, [q, actionFilter]);
  useEffect(() => { load(); }, [load]);

  const toggleCreditContributors = async (next: boolean) => {
    if (!settings) return;
    setSavingSet(true);
    try {
      const updated = await adminApi.setReconciliationSettings({ credit_contributors_enabled: next });
      setSettings(updated);
    } catch (e: any) { Alert.alert('Error', e?.message || 'Failed'); }
    finally { setSavingSet(false); }
  };

  const toggleAutoDisable = async (next: boolean) => {
    if (!settings) return;
    setSavingSet(true);
    try {
      const updated = await adminApi.setReconciliationSettings({ auto_disable_card: next });
      setSettings(updated);
    } catch (e: any) { Alert.alert('Error', e?.message || 'Failed'); }
    finally { setSavingSet(false); }
  };

  if (busy && !items) return <View style={styles.center}><ActivityIndicator color={COLORS.primary} /></View>;

  return (
    <ScrollView contentContainerStyle={{ paddingBottom: 80 }}>
      <Text style={styles.heading} testID="admin-reconciliations-heading">Reconciliations</Text>
      <Text style={styles.subheading}>
        Real-time tracking of merchant spend vs. funds collected. When a card is settled and leftover
        funds remain, they are either credited back to contributors or moved to the Master Account
        depending on the toggle below.
      </Text>

      {/* Settings card */}
      {settings ? (
        <View style={styles.card}>
          <View style={styles.toggleRow}>
            <View style={{ flex: 1 }}>
              <Text style={styles.label}>Credit contributors on leftover</Text>
              <Text style={styles.helper}>
                When ON — leftover funds are refunded to each contributor's SquadPay wallet, proportional to what they contributed.
                When OFF — leftover funds are moved to the Master Account.
              </Text>
            </View>
            <Switch
              value={!!settings.credit_contributors_enabled}
              onValueChange={toggleCreditContributors}
              disabled={savingSet}
              trackColor={{ false: COLORS.disabledBg, true: COLORS.primary }}
              thumbColor="#fff"
              testID="rcn-toggle-credit-contributors"
            />
          </View>
          <View style={styles.divider} />
          <View style={styles.toggleRow}>
            <View style={{ flex: 1 }}>
              <Text style={styles.label}>Auto-disable card after settlement</Text>
              <Text style={styles.helper}>
                When ON — the Stripe Issuing card is automatically cancelled after reconciliation completes.
                When OFF — admin must manually disable from the Groups page.
              </Text>
            </View>
            <Switch
              value={settings.auto_disable_card !== false}
              onValueChange={toggleAutoDisable}
              disabled={savingSet}
              trackColor={{ false: COLORS.disabledBg, true: COLORS.primary }}
              thumbColor="#fff"
              testID="rcn-toggle-auto-disable"
            />
          </View>
          {settings.updated_at ? (
            <Text style={styles.metaSmall}>Last updated {fmtDate(settings.updated_at)} by {settings.updated_by}</Text>
          ) : null}
        </View>
      ) : null}

      {/* Search + filter */}
      <View style={[styles.card, { paddingVertical: SPACING.sm }]}>
        <View style={styles.searchRow}>
          <Search size={14} color={COLORS.subtext} />
          <TextInput
            style={styles.searchInput}
            value={q}
            onChangeText={setQ}
            onSubmitEditing={load}
            placeholder="Search group, lead, card id"
            placeholderTextColor={COLORS.disabledText}
            testID="rcn-search"
          />
          <TouchableOpacity onPress={load} style={styles.refreshBtn} activeOpacity={0.85} testID="rcn-refresh">
            <RefreshCw size={14} color="#fff" />
            <Text style={styles.refreshBtnText}>Refresh</Text>
          </TouchableOpacity>
        </View>
        <View style={styles.filterRow}>
          <Filter size={12} color={COLORS.subtext} />
          {[
            { v: '', label: 'All' },
            { v: 'credit_contributors', label: 'Credited' },
            { v: 'moved_to_master', label: 'Master' },
            { v: 'no_leftover', label: 'No leftover' },
          ].map(({ v, label }) => (
            <TouchableOpacity
              key={v || 'all'}
              onPress={() => setActionFilter(v)}
              style={[styles.chip, actionFilter === v && styles.chipActive]}
              activeOpacity={0.85}
              testID={`rcn-filter-${v || 'all'}`}
            >
              <Text style={[styles.chipText, actionFilter === v && { color: '#fff' }]}>{label}</Text>
            </TouchableOpacity>
          ))}
        </View>
      </View>

      <Text style={styles.metaSmall}>{total} reconciliation event{total === 1 ? '' : 's'}</Text>

      {items && items.length > 0 ? items.map((it) => (
        <TouchableOpacity
          key={it.id}
          style={styles.row}
          activeOpacity={0.85}
          onPress={() => setDetail(it)}
          testID={`rcn-row-${it.id}`}
        >
          <View style={{ flex: 1 }}>
            <View style={styles.rowTop}>
              <Text style={styles.rowTitle} numberOfLines={1}>{it.group_title}</Text>
              <ActionPill action={it.action} />
            </View>
            <Text style={styles.rowMeta} numberOfLines={1}>
              Lead: {it.lead_name || '—'}  •  Card: {it.card_id?.slice(-8) || '—'}  •  {it.source}
            </Text>
            <View style={styles.amountRow}>
              <Text style={styles.amountSm}>Collected <Text style={{ color: COLORS.text, fontWeight: '700' }}>{money(it.amount_collected)}</Text></Text>
              <Text style={styles.amountSm}>Spent <Text style={{ color: COLORS.text, fontWeight: '700' }}>{money(it.amount_spent)}</Text></Text>
              <Text style={[styles.amountSm, { color: it.leftover > 0.005 ? COLORS.warning : COLORS.success, fontWeight: '700' }]}>
                Leftover {money(it.leftover)}
              </Text>
            </View>
            <Text style={styles.metaSmall}>{fmtDate(it.created_at)}</Text>
          </View>
          <ChevronRight size={16} color={COLORS.subtext} />
        </TouchableOpacity>
      )) : !busy ? (
        <View style={[styles.card, styles.center, { paddingVertical: 32 }]}>
          <AlertCircle size={20} color={COLORS.subtext} />
          <Text style={[styles.helper, { textAlign: 'center', marginTop: 8 }]}>
            No reconciliation events yet. Events are auto-created after the merchant charges a virtual card.
          </Text>
        </View>
      ) : null}

      {/* Detail modal-like overlay (web-friendly) */}
      {detail ? (
        <View style={styles.overlay}>
          <View style={styles.modal}>
            <View style={styles.modalHeader}>
              <Text style={styles.modalTitle}>{detail.group_title}</Text>
              <TouchableOpacity onPress={() => setDetail(null)} testID="rcn-detail-close"><Text style={styles.closeX}>✕</Text></TouchableOpacity>
            </View>
            <ActionPill action={detail.action} />
            <Text style={styles.kv}><Text style={styles.k}>Group ID:</Text> {detail.group_id}</Text>
            <Text style={styles.kv}><Text style={styles.k}>Lead:</Text> {detail.lead_name || '—'} ({detail.lead_phone || '—'})</Text>
            <Text style={styles.kv}><Text style={styles.k}>Card:</Text> {detail.card_id}</Text>
            <Text style={styles.kv}><Text style={styles.k}>Source:</Text> {detail.source}</Text>
            <Text style={styles.kv}><Text style={styles.k}>Created:</Text> {fmtDate(detail.created_at)} by {detail.created_by || '—'}</Text>
            <View style={styles.divider} />
            <View style={styles.amountGrid}>
              <View style={styles.amountCell}><Text style={styles.amountCellLabel}>Collected</Text><Text style={styles.amountCellVal}>{money(detail.amount_collected)}</Text></View>
              <View style={styles.amountCell}><Text style={styles.amountCellLabel}>Spent</Text><Text style={styles.amountCellVal}>{money(detail.amount_spent)}</Text></View>
              <View style={styles.amountCell}><Text style={styles.amountCellLabel}>Leftover</Text><Text style={[styles.amountCellVal, { color: detail.leftover > 0.005 ? COLORS.warning : COLORS.success }]}>{money(detail.leftover)}</Text></View>
            </View>
            {detail.merchant_summary?.name ? (
              <Text style={styles.kv}><Text style={styles.k}>Merchant:</Text> {detail.merchant_summary.name} — {detail.merchant_summary.city || '—'} ({detail.merchant_summary.category || '—'})</Text>
            ) : null}
            <Text style={styles.kv}><Text style={styles.k}>Transactions:</Text> {detail.transactions_count}</Text>
            {detail.action === 'credit_contributors' && detail.contributor_credits && detail.contributor_credits.length > 0 ? (
              <>
                <View style={styles.divider} />
                <Text style={[styles.label, { marginTop: 0 }]}>Contributor refunds</Text>
                {detail.contributor_credits.map((c) => (
                  <Text key={c.credit_id} style={styles.kv}>{c.name || c.user_id} — {money(c.amount)} (credit_id: {c.credit_id})</Text>
                ))}
              </>
            ) : null}
            {detail.action === 'moved_to_master' ? (
              <Text style={styles.kv}><Text style={styles.k}>Master ledger entry:</Text> {detail.master_account_entry_id} — balance after: {money(detail.master_balance_after || 0)}</Text>
            ) : null}
          </View>
        </View>
      ) : null}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  heading: { fontSize: FONT.sizes.xl, fontWeight: FONT.weights.bold, color: COLORS.text },
  subheading: { fontSize: FONT.sizes.sm, color: COLORS.subtext, marginBottom: SPACING.lg },
  card: { backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border, borderRadius: RADIUS.md, padding: SPACING.md, marginBottom: SPACING.md },
  toggleRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: SPACING.md, paddingVertical: SPACING.sm },
  label: { fontSize: FONT.sizes.sm, color: COLORS.text, fontWeight: FONT.weights.semibold, marginTop: SPACING.sm },
  helper: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: 4, fontStyle: 'italic' },
  divider: { height: 1, backgroundColor: COLORS.border, marginVertical: SPACING.md },
  searchRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  searchInput: { flex: 1, height: 36, borderRadius: RADIUS.md, borderWidth: 1, borderColor: COLORS.border, paddingHorizontal: SPACING.md, color: COLORS.text, backgroundColor: COLORS.bg, outlineStyle: 'none' as any },
  refreshBtn: { flexDirection: 'row', alignItems: 'center', gap: 6, height: 36, paddingHorizontal: SPACING.md, borderRadius: RADIUS.md, backgroundColor: COLORS.primary },
  refreshBtnText: { color: '#fff', fontWeight: FONT.weights.bold, fontSize: FONT.sizes.xs },
  filterRow: { flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: SPACING.sm, flexWrap: 'wrap' },
  chip: { paddingHorizontal: SPACING.md, paddingVertical: 6, borderRadius: RADIUS.pill, backgroundColor: COLORS.bg, borderWidth: 1, borderColor: COLORS.border },
  chipActive: { backgroundColor: COLORS.primary, borderColor: COLORS.primary },
  chipText: { fontSize: FONT.sizes.xs, color: COLORS.text, fontWeight: FONT.weights.semibold },
  pill: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: RADIUS.pill, alignSelf: 'flex-start' },
  pillText: { fontSize: 10, fontWeight: FONT.weights.bold, textTransform: 'uppercase' },
  row: { flexDirection: 'row', alignItems: 'center', gap: SPACING.sm, padding: SPACING.md, marginBottom: SPACING.sm, backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border, borderRadius: RADIUS.md },
  rowTop: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: SPACING.sm },
  rowTitle: { fontSize: FONT.sizes.md, fontWeight: FONT.weights.bold, color: COLORS.text, flex: 1 },
  rowMeta: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: 4 },
  amountRow: { flexDirection: 'row', gap: SPACING.md, marginTop: 6, flexWrap: 'wrap' },
  amountSm: { fontSize: FONT.sizes.xs, color: COLORS.subtext },
  metaSmall: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: SPACING.sm, fontStyle: 'italic' },
  overlay: { position: 'absolute', top: 0, bottom: 0, left: 0, right: 0, backgroundColor: 'rgba(15, 23, 42, 0.55)', alignItems: 'center', justifyContent: 'center', padding: SPACING.lg },
  modal: { backgroundColor: COLORS.surface, borderRadius: RADIUS.md, padding: SPACING.lg, width: '100%', maxWidth: 560, gap: 6 },
  modalHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  modalTitle: { fontSize: FONT.sizes.lg, fontWeight: FONT.weights.bold, color: COLORS.text, flex: 1 },
  closeX: { fontSize: 20, color: COLORS.subtext, paddingHorizontal: 6 },
  kv: { fontSize: FONT.sizes.sm, color: COLORS.text, marginTop: 4 },
  k: { color: COLORS.subtext, fontWeight: FONT.weights.semibold },
  amountGrid: { flexDirection: 'row', gap: SPACING.md, flexWrap: 'wrap' },
  amountCell: { flex: 1, minWidth: 120, padding: SPACING.md, borderRadius: RADIUS.md, backgroundColor: COLORS.bg, borderWidth: 1, borderColor: COLORS.border },
  amountCellLabel: { fontSize: FONT.sizes.xs, color: COLORS.subtext, fontWeight: FONT.weights.semibold, textTransform: 'uppercase' },
  amountCellVal: { fontSize: FONT.sizes.lg, fontWeight: FONT.weights.bold, color: COLORS.text, marginTop: 4 },
});

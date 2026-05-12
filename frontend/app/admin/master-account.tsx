import { useEffect, useState, useCallback } from 'react';
import { View, Text, ScrollView, TouchableOpacity, StyleSheet, ActivityIndicator, Alert } from 'react-native';
import { Wallet, RefreshCw, AlertCircle, CreditCard, Info } from 'lucide-react-native';
import { adminApi, MasterAccountEntry, MasterCard } from '../../src/adminApi';
import { COLORS, FONT, RADIUS, SPACING } from '../../src/theme';
import { toast } from '../../src/components/Toast';

function money(n: number) { return `$${(Number(n) || 0).toFixed(2)}`; }
function fmtDate(s?: string) { if (!s) return '—'; try { return new Date(s).toLocaleString(); } catch { return s; } }

export default function AdminMasterAccount() {
  const [items, setItems] = useState<MasterAccountEntry[] | null>(null);
  const [balance, setBalance] = useState(0);
  const [total, setTotal] = useState(0);
  const [busy, setBusy] = useState(true);
  // Master Virtual Card state (Batch C addition).
  const [masterCard, setMasterCard] = useState<MasterCard | null>(null);
  const [issuingCard, setIssuingCard] = useState(false);

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const r = await adminApi.getMasterAccount({ limit: 100 });
      setItems(r.items);
      setBalance(r.balance);
      setTotal(r.total);
      // Fetch master-card status in parallel — separate endpoint so we don't
      // bloat the existing ledger response shape.
      try {
        const mc = await adminApi.getMasterCard();
        setMasterCard(mc.card);
      } catch { /* non-fatal — card section just shows "not issued" */ }
    } catch (e: any) { Alert.alert('Error', e?.message || 'Failed to load'); }
    finally { setBusy(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const onIssueMasterCard = async () => {
    setIssuingCard(true);
    try {
      const res = await adminApi.issueMasterCard();
      setMasterCard(res.card);
      toast.success(res.created ? 'Master card scaffolded' : 'Master card already exists');
    } catch (e: any) {
      Alert.alert('Issue failed', e?.message || 'Could not issue master card');
    } finally { setIssuingCard(false); }
  };

  if (busy && !items) return <View style={styles.center}><ActivityIndicator color={COLORS.primary} /></View>;

  return (
    <ScrollView contentContainerStyle={{ paddingBottom: 80 }}>
      <Text style={styles.heading} testID="admin-master-heading">Master Account</Text>
      <Text style={styles.subheading}>
        Virtual ledger of all leftover funds collected after group cards have settled. Each entry traces
        back to a specific group and card.
      </Text>

      <View style={styles.balanceCard}>
        <View style={styles.balanceIcon}><Wallet size={24} color="#fff" /></View>
        <View style={{ flex: 1 }}>
          <Text style={styles.balanceLabel}>Master account balance</Text>
          <Text style={styles.balanceVal} testID="master-balance">{money(balance)}</Text>
          <Text style={styles.balanceSub}>{total} ledger entries</Text>
        </View>
        <TouchableOpacity onPress={load} style={styles.refreshBtn} activeOpacity={0.85} testID="master-refresh">
          <RefreshCw size={14} color="#fff" />
          <Text style={styles.refreshBtnText}>Refresh</Text>
        </TouchableOpacity>
      </View>

      {/* ─── Master Virtual Card (Batch C) ─────────────────────────────────
          Stripe Issuing doesn't allow card-to-card balance transfers — but
          all our Issuing cards draw against the same Stripe Platform
          Balance. So the Master Card is a real card the platform spends
          retained fees + residuals from. Today it's scaffolded; flip the
          Stripe call in /app/backend/routes/admin_master_account.py once
          a platform cardholder is configured. */}
      <View style={styles.masterCard} testID="master-card-section">
        <View style={styles.masterCardHeader}>
          <CreditCard size={18} color={COLORS.primary} />
          <Text style={styles.masterCardTitle}>Master Virtual Card</Text>
        </View>
        <View style={styles.noteRow}>
          <Info size={12} color={COLORS.subtext} />
          <Text style={styles.noteText}>
            Stripe Issuing cards don't have balances — they share the Platform Balance.
            The Master Card lets the platform spend retained fees + residuals from this pool.
          </Text>
        </View>
        {masterCard?.stripe_card_id ? (
          <View style={styles.masterCardBody}>
            <Text style={styles.masterCardLast4}>•••• {masterCard.last4 || '----'}</Text>
            <Text style={styles.masterCardMeta}>Status: {masterCard.status}</Text>
            <Text style={styles.masterCardMetaSmall}>Stripe card id: {masterCard.stripe_card_id}</Text>
          </View>
        ) : masterCard?.status === 'pending_stripe_setup' ? (
          <View style={styles.masterCardBody}>
            <Text style={styles.masterCardLast4}>Scaffolded</Text>
            <Text style={styles.masterCardMeta}>Stripe Issuing call not yet wired.</Text>
            {masterCard?.note ? <Text style={styles.masterCardMetaSmall}>{masterCard.note}</Text> : null}
          </View>
        ) : (
          <View style={styles.masterCardBody}>
            <Text style={styles.masterCardLast4}>Not yet issued</Text>
            <TouchableOpacity
              onPress={onIssueMasterCard}
              disabled={issuingCard}
              style={[styles.issueBtn, issuingCard && { opacity: 0.5 }]}
              testID="issue-master-card-btn"
            >
              <Text style={styles.issueBtnText}>{issuingCard ? 'Working…' : 'Issue Master Virtual Card'}</Text>
            </TouchableOpacity>
          </View>
        )}
      </View>

      {items && items.length > 0 ? items.map((it) => (
        <View key={it.id} style={styles.row} testID={`master-row-${it.id}`}>
          <View style={{ flex: 1 }}>
            <View style={styles.rowTop}>
              <Text style={styles.rowTitle} numberOfLines={1}>{it.group_title}</Text>
              <Text style={styles.amount}>+{money(it.amount)}</Text>
            </View>
            <Text style={styles.rowMeta} numberOfLines={1}>
              Lead: {it.lead_name || '—'}  •  Card: {it.card_id?.slice(-8) || '—'}
            </Text>
            <Text style={styles.rowMeta}>
              Balance after: <Text style={{ color: COLORS.text, fontWeight: '700' }}>{money(it.balance_after)}</Text>
            </Text>
            {it.note ? <Text style={styles.note}>{it.note}</Text> : null}
            <Text style={styles.metaSmall}>{fmtDate(it.created_at)} by {it.created_by || '—'}</Text>
          </View>
        </View>
      )) : !busy ? (
        <View style={[styles.card, styles.center, { paddingVertical: 32 }]}>
          <AlertCircle size={20} color={COLORS.subtext} />
          <Text style={[styles.helper, { textAlign: 'center', marginTop: 8 }]}>
            No master account entries yet. Entries are created automatically when a group card settles
            and "credit contributors" is OFF.
          </Text>
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
  balanceCard: { flexDirection: 'row', alignItems: 'center', gap: SPACING.md, padding: SPACING.lg, marginBottom: SPACING.lg, backgroundColor: COLORS.primary, borderRadius: RADIUS.md },
  balanceIcon: { width: 48, height: 48, borderRadius: 24, backgroundColor: 'rgba(255,255,255,0.2)', alignItems: 'center', justifyContent: 'center' },
  balanceLabel: { fontSize: FONT.sizes.xs, color: 'rgba(255,255,255,0.85)', fontWeight: FONT.weights.semibold, textTransform: 'uppercase' },
  balanceVal: { fontSize: 28, fontWeight: FONT.weights.bold, color: '#fff', marginTop: 4 },
  balanceSub: { fontSize: FONT.sizes.xs, color: 'rgba(255,255,255,0.85)', marginTop: 2 },
  refreshBtn: { flexDirection: 'row', alignItems: 'center', gap: 6, height: 36, paddingHorizontal: SPACING.md, borderRadius: RADIUS.md, backgroundColor: 'rgba(0,0,0,0.18)' },
  refreshBtnText: { color: '#fff', fontWeight: FONT.weights.bold, fontSize: FONT.sizes.xs },
  row: { padding: SPACING.md, marginBottom: SPACING.sm, backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border, borderRadius: RADIUS.md },
  rowTop: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: SPACING.sm },
  rowTitle: { fontSize: FONT.sizes.md, fontWeight: FONT.weights.bold, color: COLORS.text, flex: 1 },
  amount: { fontSize: FONT.sizes.md, fontWeight: FONT.weights.bold, color: COLORS.success },
  rowMeta: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: 4 },
  note: { fontSize: FONT.sizes.xs, color: COLORS.text, marginTop: 4, fontStyle: 'italic' },
  helper: { fontSize: FONT.sizes.xs, color: COLORS.subtext, fontStyle: 'italic' },
  metaSmall: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: 4, fontStyle: 'italic' },
  // Master Virtual Card section (Batch C)
  masterCard: { backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border, borderRadius: RADIUS.md, padding: SPACING.md, marginBottom: SPACING.lg },
  masterCardHeader: { flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: SPACING.sm },
  masterCardTitle: { fontSize: FONT.sizes.md, fontWeight: FONT.weights.bold, color: COLORS.text },
  noteRow: { flexDirection: 'row', alignItems: 'flex-start', gap: 6, marginBottom: SPACING.sm },
  noteText: { color: COLORS.subtext, fontSize: 11, lineHeight: 16, flex: 1 },
  masterCardBody: { gap: 6 },
  masterCardLast4: { fontSize: FONT.sizes.lg, fontWeight: FONT.weights.heavy, color: COLORS.text, letterSpacing: 1 },
  masterCardMeta: { color: COLORS.subtext, fontSize: FONT.sizes.xs },
  masterCardMetaSmall: { color: COLORS.subtext, fontSize: 11, fontStyle: 'italic' },
  issueBtn: { backgroundColor: COLORS.primary, paddingVertical: 10, paddingHorizontal: SPACING.md, borderRadius: RADIUS.md, alignItems: 'center', marginTop: 6, alignSelf: 'flex-start' },
  issueBtnText: { color: '#fff', fontWeight: FONT.weights.bold, fontSize: FONT.sizes.sm },
});

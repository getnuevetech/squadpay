import { useEffect, useState, useCallback } from 'react';
import { View, Text, ScrollView, TouchableOpacity, StyleSheet, ActivityIndicator } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useRouter } from 'expo-router';
import { ArrowLeft, Wallet, Gift, ShieldOff, CheckCircle2, Crown } from 'lucide-react-native';
import { api } from '../src/api';
import { loadUser } from '../src/session';
import { COLORS, FONT, RADIUS, SPACING } from '../src/theme';

type CreditRow = {
  id: string;
  amount: number;
  consumed_amount: number;
  remaining: number;
  kind: string;
  status: string;
  note?: string | null;
  created_at: string;
  last_consumed_at?: string;
};

type CreditWallet = {
  user_id: string;
  balance: number;
  items: CreditRow[];
  lead_auto_discount?: { type: 'flat' | 'percent'; value: number; note?: string | null } | null;
};

const KIND_LABEL: Record<string, string> = {
  admin_grant: 'Admin grant',
  referral_referrer: 'Referral reward',
  referral_referee: 'Welcome bonus',
};

function StatusIcon({ status }: { status: string }) {
  if (status === 'active') return <CheckCircle2 size={12} color={COLORS.success} />;
  if (status === 'consumed') return <Wallet size={12} color={COLORS.subtext} />;
  if (status === 'revoked') return <ShieldOff size={12} color={COLORS.danger} />;
  return <Wallet size={12} color={COLORS.subtext} />;
}

export default function CreditsScreen() {
  const router = useRouter();
  const [user, setUser] = useState<Awaited<ReturnType<typeof loadUser>>>(null);
  const [wallet, setWallet] = useState<CreditWallet | null>(null);
  const [busy, setBusy] = useState(true);

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const u = await loadUser();
      setUser(u);
      if (u) {
        const r = await fetch(`${process.env.EXPO_PUBLIC_BACKEND_URL}/api/users/${u.id}/credits`).then((x) => x.json());
        setWallet(r);
      }
    } catch (e) { /* swallow */ }
    finally { setBusy(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  if (busy || !user) return <SafeAreaView style={styles.center}><ActivityIndicator color={COLORS.primary} /></SafeAreaView>;

  const items = wallet?.items || [];
  const active = items.filter((c) => c.status === 'active');
  const consumed = items.filter((c) => c.status === 'consumed');
  const revoked = items.filter((c) => c.status === 'revoked');

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <ScrollView contentContainerStyle={{ padding: SPACING.md, paddingBottom: SPACING.xxl }}>
        <TouchableOpacity onPress={() => router.back()} style={styles.backBtn} activeOpacity={0.7} testID="credits-back">
          <ArrowLeft size={18} color={COLORS.text} />
          <Text style={styles.backText}>Back</Text>
        </TouchableOpacity>

        <View style={styles.heroCard}>
          <View style={styles.heroIcon}><Wallet size={26} color="#fff" /></View>
          <Text style={styles.heroLabel}>YOUR CREDIT BALANCE</Text>
          <Text style={styles.heroBalance} testID="credits-balance">${(wallet?.balance ?? 0).toFixed(2)}</Text>
          <Text style={styles.heroSub}>Auto-applied to your share when you contribute to a bill.</Text>
        </View>

        {wallet?.lead_auto_discount ? (
          <View style={styles.leadCard}>
            <Crown size={14} color={COLORS.warning} />
            <View style={{ flex: 1 }}>
              <Text style={styles.leadTitle}>Lead VIP discount</Text>
              <Text style={styles.leadSub}>
                Every group you create gets {wallet.lead_auto_discount.type === 'percent' ? `${wallet.lead_auto_discount.value}%` : `$${wallet.lead_auto_discount.value.toFixed(2)}`} off automatically.
              </Text>
            </View>
          </View>
        ) : null}

        <View style={styles.statsRow}>
          <View style={styles.statBox}><Text style={[styles.statValue, { color: COLORS.success }]}>{active.length}</Text><Text style={styles.statLabel}>Active</Text></View>
          <View style={styles.statBox}><Text style={styles.statValue}>{consumed.length}</Text><Text style={styles.statLabel}>Used</Text></View>
          <View style={styles.statBox}><Text style={[styles.statValue, { color: COLORS.danger }]}>{revoked.length}</Text><Text style={styles.statLabel}>Revoked</Text></View>
        </View>

        <Text style={styles.sectionTitle}>Credit history ({items.length})</Text>
        {items.length === 0 ? (
          <View style={styles.empty}>
            <Gift size={28} color={COLORS.subtext} />
            <Text style={styles.emptyTxt}>No credits yet</Text>
            <Text style={styles.emptySub}>Earn credits by inviting friends or wait for a promo.</Text>
          </View>
        ) : (
          items.map((c) => (
            <View key={c.id} style={[styles.row, c.status === 'revoked' && { opacity: 0.55 }]} testID={`credits-row-${c.id}`}>
              <View style={styles.rowLeft}>
                <Text style={styles.rowAmt}>${Number(c.amount || 0).toFixed(2)}</Text>
                <Text style={styles.rowKind}>{KIND_LABEL[c.kind] || c.kind}</Text>
              </View>
              <View style={{ flex: 1 }}>
                <View style={{ flexDirection: 'row', alignItems: 'center', gap: 4, flexWrap: 'wrap' }}>
                  <StatusIcon status={c.status} />
                  <Text style={[styles.rowStatus,
                    c.status === 'active' && { color: COLORS.success },
                    c.status === 'consumed' && { color: COLORS.subtext },
                    c.status === 'revoked' && { color: COLORS.danger },
                  ]}>{c.status}</Text>
                  {c.consumed_amount > 0 && c.status === 'consumed' ? <Text style={styles.metaSmall}>fully used</Text> : null}
                  {c.consumed_amount > 0 && c.status === 'active' ? <Text style={styles.metaSmall}>${Number(c.amount - c.consumed_amount).toFixed(2)} remaining</Text> : null}
                </View>
                {c.note ? <Text style={styles.rowNote} numberOfLines={2}>{c.note}</Text> : null}
                <Text style={styles.metaSmall}>{new Date(c.created_at).toLocaleDateString()}</Text>
              </View>
            </View>
          ))
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: COLORS.bg },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: COLORS.bg },
  backBtn: { flexDirection: 'row', alignItems: 'center', gap: 4, marginBottom: SPACING.md },
  backText: { color: COLORS.text, fontSize: FONT.sizes.sm, fontWeight: FONT.weights.semibold },
  heroCard: { padding: SPACING.lg, backgroundColor: COLORS.primary, borderRadius: RADIUS.lg, alignItems: 'center', marginBottom: SPACING.md },
  heroIcon: { width: 56, height: 56, borderRadius: 28, backgroundColor: 'rgba(255,255,255,0.18)', alignItems: 'center', justifyContent: 'center', marginBottom: SPACING.sm },
  heroLabel: { fontSize: 11, color: 'rgba(255,255,255,0.7)', fontWeight: FONT.weights.bold, letterSpacing: 1 },
  heroBalance: { fontSize: 44, fontWeight: FONT.weights.heavy, color: '#fff', marginVertical: 6 },
  heroSub: { fontSize: FONT.sizes.xs, color: 'rgba(255,255,255,0.85)', textAlign: 'center' },
  leadCard: { flexDirection: 'row', alignItems: 'center', gap: SPACING.sm, padding: SPACING.md, backgroundColor: COLORS.warningLight, borderRadius: RADIUS.md, borderWidth: 1, borderColor: COLORS.warning, marginBottom: SPACING.md },
  leadTitle: { fontSize: FONT.sizes.sm, fontWeight: FONT.weights.bold, color: COLORS.warning },
  leadSub: { fontSize: FONT.sizes.xs, color: COLORS.text, marginTop: 2 },
  statsRow: { flexDirection: 'row', gap: SPACING.sm, marginBottom: SPACING.lg },
  statBox: { flex: 1, padding: SPACING.md, backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border, borderRadius: RADIUS.md, alignItems: 'center' },
  statValue: { fontSize: FONT.sizes.xl, fontWeight: FONT.weights.bold, color: COLORS.text },
  statLabel: { fontSize: 11, color: COLORS.subtext, marginTop: 2 },
  sectionTitle: { fontSize: FONT.sizes.md, fontWeight: FONT.weights.bold, color: COLORS.text, marginBottom: SPACING.sm },
  empty: { padding: SPACING.lg, alignItems: 'center' },
  emptyTxt: { fontSize: FONT.sizes.sm, color: COLORS.subtext, fontWeight: FONT.weights.semibold, marginTop: 8 },
  emptySub: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: 4, textAlign: 'center' },
  row: { flexDirection: 'row', alignItems: 'flex-start', gap: SPACING.md, padding: SPACING.md, backgroundColor: COLORS.surface, borderRadius: RADIUS.md, borderWidth: 1, borderColor: COLORS.border, marginBottom: 8 },
  rowLeft: { width: 80, alignItems: 'flex-start' },
  rowAmt: { fontSize: FONT.sizes.lg, fontWeight: FONT.weights.bold, color: COLORS.text },
  rowKind: { fontSize: 10, color: COLORS.subtext, fontWeight: FONT.weights.semibold, textTransform: 'uppercase', marginTop: 2 },
  rowStatus: { fontSize: 11, fontWeight: FONT.weights.bold, textTransform: 'uppercase' },
  rowNote: { fontSize: FONT.sizes.xs, color: COLORS.text, marginTop: 4, fontStyle: 'italic' },
  metaSmall: { fontSize: 11, color: COLORS.subtext, marginTop: 2 },
});

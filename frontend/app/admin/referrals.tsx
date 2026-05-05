import { useEffect, useState, useCallback } from 'react';
import { View, Text, ScrollView, TextInput, TouchableOpacity, StyleSheet, ActivityIndicator, Alert, Switch } from 'react-native';
import { Gift, TrendingUp, Users as UsersIcon, Wallet, Save, ChevronRight } from 'lucide-react-native';
import { adminApi, ReferralSettings, ReferrerRow, ReferralStats } from '../../src/adminApi';
import { COLORS, FONT, RADIUS, SPACING } from '../../src/theme';

function StatCard({ icon, label, value, color = COLORS.primary }: any) {
  return (
    <View style={styles.statCard}>
      <View style={[styles.statIcon, { backgroundColor: color + '22' }]}>{icon}</View>
      <View style={{ flex: 1 }}>
        <Text style={styles.statLabel}>{label}</Text>
        <Text style={styles.statValue}>{value}</Text>
      </View>
    </View>
  );
}

export default function AdminReferrals() {
  const [settings, setSettings] = useState<ReferralSettings | null>(null);
  const [referrers, setReferrers] = useState<ReferrerRow[]>([]);
  const [stats, setStats] = useState<ReferralStats | null>(null);
  const [busy, setBusy] = useState(true);
  const [saving, setSaving] = useState(false);
  const [enabled, setEnabled] = useState(false);
  const [referrerCredit, setReferrerCredit] = useState('0');
  const [refereeCredit, setRefereeCredit] = useState('0');
  const [q, setQ] = useState('');

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const [s, r] = await Promise.all([
        adminApi.getReferralSettings(),
        adminApi.listReferrers({ limit: 100, q: q || undefined }),
      ]);
      setSettings(s);
      setEnabled(s.enabled);
      setReferrerCredit(String(s.referrer_credit ?? 0));
      setRefereeCredit(String(s.referee_credit ?? 0));
      setReferrers(r.items);
      setStats(r.stats);
    } catch (e: any) {
      Alert.alert('Error', e?.message || 'Failed to load');
    } finally { setBusy(false); }
  }, [q]);

  useEffect(() => { load(); }, []);

  const saveSettings = async () => {
    const rA = parseFloat(referrerCredit) || 0;
    const rB = parseFloat(refereeCredit) || 0;
    if (rA < 0 || rB < 0) { Alert.alert('Invalid', 'Credit amounts must be ≥ 0'); return; }
    setSaving(true);
    try {
      const out = await adminApi.setReferralSettings({ enabled, referrer_credit: rA, referee_credit: rB });
      setSettings(out);
      Alert.alert('Saved', `Referral system ${out.enabled ? 'ENABLED' : 'disabled'}.`);
    } catch (e: any) {
      Alert.alert('Error', e?.message || 'Failed to save');
    } finally { setSaving(false); }
  };

  if (busy) return <View style={styles.center}><ActivityIndicator color={COLORS.primary} /></View>;

  return (
    <ScrollView contentContainerStyle={{ paddingBottom: 80 }}>
      <Text style={styles.heading} testID="admin-referrals-heading">Referrals</Text>
      <Text style={styles.subheading}>Track referrers and configure rewards. Rewards land as pending credits redeemable in Phase C2.</Text>

      <View style={styles.grid}>
        <StatCard icon={<UsersIcon size={18} color={COLORS.primary} />} label="Total referred" value={stats?.total_referred ?? 0} />
        <StatCard icon={<TrendingUp size={18} color={COLORS.success} />} label="Verified" value={stats?.verified_referred ?? 0} color={COLORS.success} />
        <StatCard icon={<Gift size={18} color={'#8B5CF6'} />} label="Conversion" value={`${stats?.conversion_rate ?? 0}%`} color={'#8B5CF6'} />
        <StatCard icon={<Wallet size={18} color={COLORS.warning} />} label="Pending credits" value={stats?.pending_credits ?? 0} color={COLORS.warning} />
      </View>

      <View style={styles.card}>
        <Text style={styles.cardTitle}>Reward settings</Text>
        <Text style={styles.cardSub}>When enabled, rewards are auto-granted as pending credits the first time a referee verifies their phone.</Text>

        <View style={styles.toggleRow}>
          <View style={{ flex: 1 }}>
            <Text style={styles.label}>Enable referral system</Text>
            <Text style={styles.helper}>{enabled ? 'New referrals grant pending credits.' : 'Codes are tracked but no credits are issued.'}</Text>
          </View>
          <Switch
            value={enabled}
            onValueChange={setEnabled}
            trackColor={{ false: COLORS.disabledBg, true: COLORS.primary }}
            thumbColor={'#fff'}
            testID="admin-referrals-enable"
          />
        </View>

        <View style={styles.formRow}>
          <View style={{ flex: 1 }}>
            <Text style={styles.label}>Referrer credit ($)</Text>
            <TextInput
              style={styles.input}
              keyboardType="decimal-pad"
              value={referrerCredit}
              onChangeText={setReferrerCredit}
              placeholder="0.00"
              placeholderTextColor={COLORS.disabledText}
              testID="admin-referrals-referrer-credit"
            />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.label}>Referee credit ($)</Text>
            <TextInput
              style={styles.input}
              keyboardType="decimal-pad"
              value={refereeCredit}
              onChangeText={setRefereeCredit}
              placeholder="0.00"
              placeholderTextColor={COLORS.disabledText}
              testID="admin-referrals-referee-credit"
            />
          </View>
        </View>

        <TouchableOpacity onPress={saveSettings} disabled={saving} style={[styles.saveBtn, saving && { opacity: 0.6 }]} activeOpacity={0.85} testID="admin-referrals-save">
          <Save size={14} color="#fff" />
          <Text style={styles.saveBtnText}>{saving ? 'Saving…' : 'Save settings'}</Text>
        </TouchableOpacity>
        {settings?.updated_at ? (
          <Text style={styles.metaSmall}>Last updated {new Date(settings.updated_at).toLocaleString()}</Text>
        ) : null}
      </View>

      <View style={styles.card}>
        <View style={styles.headerRow}>
          <Text style={styles.cardTitle}>Top referrers</Text>
          <TextInput
            style={[styles.input, { height: 36, marginTop: 0, width: 240 }]}
            value={q}
            onChangeText={setQ}
            onSubmitEditing={load}
            placeholder="Search name / phone / code"
            placeholderTextColor={COLORS.disabledText}
            returnKeyType="search"
            testID="admin-referrals-search"
          />
        </View>

        {referrers.length === 0 ? (
          <Text style={styles.empty}>No referrers yet.</Text>
        ) : referrers.map((r) => (
          <View key={r.user_id} style={styles.row} testID={`admin-referrer-row-${r.user_id}`}>
            <View style={[styles.avatar, r.is_blocked && { backgroundColor: COLORS.dangerLight }]}>
              <Text style={[styles.avatarText, r.is_blocked && { color: COLORS.danger }]}>{(r.name || '?').slice(0, 1).toUpperCase()}</Text>
            </View>
            <View style={{ flex: 1 }}>
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                <Text style={styles.name}>{r.name || '—'}</Text>
                <View style={styles.codePill}><Text style={styles.codePillText}>{r.referral_code || '—'}</Text></View>
              </View>
              <Text style={styles.meta}>{r.phone || 'no phone'}</Text>
            </View>
            <View style={{ alignItems: 'flex-end' }}>
              <Text style={styles.bigStat}>{r.total_referrals}</Text>
              <Text style={styles.bigStatLabel}>{r.verified_referrals} verified</Text>
            </View>
          </View>
        ))}
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  heading: { fontSize: FONT.sizes.xl, fontWeight: FONT.weights.bold, color: COLORS.text },
  subheading: { fontSize: FONT.sizes.sm, color: COLORS.subtext, marginBottom: SPACING.lg },
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: SPACING.sm, marginBottom: SPACING.md },
  statCard: { flex: 1, minWidth: 200, flexDirection: 'row', alignItems: 'center', gap: SPACING.sm, padding: SPACING.md, backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border, borderRadius: RADIUS.md },
  statIcon: { width: 36, height: 36, borderRadius: 18, alignItems: 'center', justifyContent: 'center' },
  statLabel: { fontSize: FONT.sizes.xs, color: COLORS.subtext, textTransform: 'uppercase', fontWeight: FONT.weights.medium },
  statValue: { fontSize: FONT.sizes.xl, fontWeight: FONT.weights.bold, color: COLORS.text, marginTop: 2 },
  card: { backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border, borderRadius: RADIUS.md, padding: SPACING.md, marginBottom: SPACING.md },
  cardTitle: { fontSize: FONT.sizes.md, fontWeight: FONT.weights.bold, color: COLORS.text },
  cardSub: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: 4 },
  headerRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12, marginBottom: SPACING.sm },
  toggleRow: { flexDirection: 'row', alignItems: 'center', gap: SPACING.md, paddingVertical: SPACING.md, borderBottomWidth: 1, borderBottomColor: COLORS.border },
  label: { fontSize: FONT.sizes.sm, color: COLORS.text, fontWeight: FONT.weights.semibold },
  helper: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: 2 },
  formRow: { flexDirection: 'row', gap: SPACING.md, marginTop: SPACING.md },
  input: { height: 40, borderRadius: RADIUS.md, borderWidth: 1, borderColor: COLORS.border, paddingHorizontal: SPACING.md, color: COLORS.text, backgroundColor: COLORS.bg, marginTop: 6, outlineStyle: 'none' as any },
  saveBtn: { marginTop: SPACING.md, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6, height: 42, backgroundColor: COLORS.primary, borderRadius: RADIUS.md },
  saveBtnText: { color: '#fff', fontWeight: FONT.weights.bold, fontSize: FONT.sizes.sm },
  metaSmall: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: SPACING.sm, fontStyle: 'italic' },
  empty: { fontSize: FONT.sizes.sm, color: COLORS.subtext, fontStyle: 'italic' },
  row: { flexDirection: 'row', alignItems: 'center', gap: SPACING.md, paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: COLORS.border },
  avatar: { width: 36, height: 36, borderRadius: 18, backgroundColor: COLORS.primaryLight, alignItems: 'center', justifyContent: 'center' },
  avatarText: { color: COLORS.primary, fontWeight: FONT.weights.bold },
  name: { fontSize: FONT.sizes.md, fontWeight: FONT.weights.semibold, color: COLORS.text },
  meta: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: 2 },
  codePill: { backgroundColor: COLORS.primaryLight, paddingHorizontal: 8, paddingVertical: 2, borderRadius: RADIUS.pill },
  codePillText: { color: COLORS.primary, fontSize: 11, fontWeight: FONT.weights.bold, letterSpacing: 0.5 },
  bigStat: { fontSize: FONT.sizes.xl, fontWeight: FONT.weights.bold, color: COLORS.text },
  bigStatLabel: { fontSize: 10, color: COLORS.subtext, fontWeight: FONT.weights.medium },
});

import { useEffect, useState, useCallback } from 'react';
import { View, Text, TouchableOpacity, ScrollView, StyleSheet, ActivityIndicator, Alert, Switch } from 'react-native';
import { Apple, Smartphone, Save, Wallet } from 'lucide-react-native';
import { _aRequest } from '../../src/adminApi';
import { COLORS, FONT, RADIUS, SPACING } from '../../src/theme';
import { toast } from '../../src/components/Toast';

/**
 * Admin → Wallets — turn Apple Pay / Google Pay buttons on or off.
 *
 * When OFF the member checkout hides the native PaymentSheet button and
 * falls back to Stripe Checkout WebView (which still surfaces wallet
 * buttons natively in browsers — but the per-transaction fee is higher).
 * Useful for cost-tuning during slow periods.
 */
type WalletConfig = {
  apple_pay_enabled: boolean;
  google_pay_enabled: boolean;
  updated_at?: string | null;
  updated_by?: string | null;
};

const walletApi = {
  get: () => _aRequest<WalletConfig>('/admin/wallet-config'),
  set: (apple: boolean, google: boolean) =>
    _aRequest<WalletConfig & { ok: boolean }>('/admin/wallet-config', {
      method: 'PUT',
      body: JSON.stringify({ apple_pay_enabled: apple, google_pay_enabled: google }),
    }),
};

export default function AdminWalletConfig() {
  const [cfg, setCfg] = useState<WalletConfig | null>(null);
  const [apple, setApple] = useState(true);
  const [google, setGoogle] = useState(true);
  const [busy, setBusy] = useState(true);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const r = await walletApi.get();
      setCfg(r);
      setApple(r.apple_pay_enabled);
      setGoogle(r.google_pay_enabled);
    } catch (e: any) {
      Alert.alert('Error', e?.message || 'Failed to load wallet config');
    } finally {
      setBusy(false);
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  const save = async () => {
    setSaving(true);
    try {
      const r = await walletApi.set(apple, google);
      setCfg(r);
      toast.success('Wallet config saved');
    } catch (e: any) {
      Alert.alert('Save failed', e?.message || 'Could not save');
    } finally {
      setSaving(false);
    }
  };

  if (busy) return <View style={styles.center}><ActivityIndicator color={COLORS.primary} /></View>;

  return (
    <ScrollView contentContainerStyle={{ paddingBottom: 80 }}>
      <Text style={styles.heading} testID="wallet-heading">Wallets — Apple Pay & Google Pay</Text>
      <Text style={styles.subheading}>
        Control whether the in-app native PaymentSheet (Apple Pay / Google Pay)
        appears on member checkout. When disabled, the Stripe Checkout WebView
        is used instead — which still surfaces wallet buttons in supported
        browsers, but at a higher per-transaction fee. Toggle these to A/B
        test cost vs. conversion.
      </Text>

      <View style={styles.card}>
        <View style={styles.row}>
          <View style={[styles.iconBox, { backgroundColor: '#000' }]}>
            <Apple size={22} color="#fff" fill="#fff" />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.rowTitle}>Apple Pay (iOS)</Text>
            <Text style={styles.rowSub}>Shown to iOS users in the in-app contribute flow.</Text>
          </View>
          <Switch
            value={apple}
            onValueChange={setApple}
            trackColor={{ true: COLORS.primary, false: COLORS.border }}
            thumbColor="#fff"
            testID="wallet-apple-switch"
          />
        </View>

        <View style={styles.divider} />

        <View style={styles.row}>
          <View style={[styles.iconBox, { backgroundColor: '#4285F4' }]}>
            <Smartphone size={22} color="#fff" />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.rowTitle}>Google Pay (Android)</Text>
            <Text style={styles.rowSub}>Shown to Android users in the in-app contribute flow.</Text>
          </View>
          <Switch
            value={google}
            onValueChange={setGoogle}
            trackColor={{ true: COLORS.primary, false: COLORS.border }}
            thumbColor="#fff"
            testID="wallet-google-switch"
          />
        </View>
      </View>

      <View style={styles.actions}>
        {cfg?.updated_at ? (
          <Text style={styles.metaText}>
            Last updated: {new Date(cfg.updated_at).toLocaleString()}
            {cfg.updated_by ? ` by ${cfg.updated_by}` : ''}
          </Text>
        ) : <View />}
        <TouchableOpacity
          onPress={save}
          disabled={saving}
          style={[styles.saveBtn, saving && { opacity: 0.7 }]}
          testID="wallet-save"
        >
          {saving ? <ActivityIndicator color="#fff" size="small" /> : <Save size={14} color="#fff" />}
          <Text style={styles.saveBtnText}>{saving ? 'Saving…' : 'Save'}</Text>
        </TouchableOpacity>
      </View>

      <View style={styles.note}>
        <Wallet size={14} color={COLORS.subtext} />
        <Text style={styles.noteText}>
          If you keep BOTH off, all member checkouts go through Stripe Checkout
          WebView. Stripe still shows Apple Pay / Google Pay buttons inside
          the WebView when supported.
        </Text>
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  heading: { fontSize: FONT.sizes.xl, fontWeight: FONT.weights.bold, color: COLORS.text },
  subheading: { fontSize: FONT.sizes.sm, color: COLORS.subtext, marginTop: 4, marginBottom: SPACING.lg, maxWidth: 720 },
  card: { padding: SPACING.md, backgroundColor: COLORS.surface, borderRadius: RADIUS.md, borderWidth: 1, borderColor: COLORS.border },
  row: { flexDirection: 'row', alignItems: 'center', gap: SPACING.md, paddingVertical: SPACING.md },
  iconBox: { width: 44, height: 44, borderRadius: RADIUS.md, alignItems: 'center', justifyContent: 'center' },
  rowTitle: { fontSize: FONT.sizes.md, color: COLORS.text, fontWeight: FONT.weights.bold },
  rowSub: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: 2 },
  divider: { height: 1, backgroundColor: COLORS.border },
  actions: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginTop: SPACING.md, gap: SPACING.md },
  metaText: { fontSize: 11, color: COLORS.subtext, fontStyle: 'italic' },
  saveBtn: { flexDirection: 'row', alignItems: 'center', gap: 6, paddingHorizontal: SPACING.lg, height: 38, borderRadius: RADIUS.md, backgroundColor: COLORS.primary },
  saveBtnText: { color: '#fff', fontWeight: FONT.weights.bold, fontSize: FONT.sizes.sm },
  note: { flexDirection: 'row', alignItems: 'flex-start', gap: 8, marginTop: SPACING.lg, padding: SPACING.md, backgroundColor: COLORS.bg, borderRadius: RADIUS.md, borderLeftWidth: 3, borderLeftColor: COLORS.subtext },
  noteText: { flex: 1, fontSize: FONT.sizes.xs, color: COLORS.subtext, lineHeight: 18 },
});

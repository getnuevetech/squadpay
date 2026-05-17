/**
 * IssuerGatewaysTab — The "Virtual Card Issuer" tab inside /admin/gateways.
 *
 * Shows all integrated issuer adapters (Stripe / Lithic / Highnote / Unit)
 * as cards. Exactly one is ACTIVE at any time — the active issuer owns the
 * full lifecycle for every new squad: card issuance, funding, tokenization,
 * webhooks. Switching providers is a one-click admin action; no code deploy
 * needed.
 *
 * Each card surfaces:
 *   • Live health (auth-validating ping)
 *   • Capabilities (Apple/Google Wallet, single-use, multi-use)
 *   • Configure credentials (per-provider .env keys)
 *   • Enable/Disable toggle
 *   • Make Active (mutex — demotes whichever was active before)
 *
 * Compliance note: this tab does NOT show or manage bank accounts /
 * deposit balances. SquadPay never holds money — active issuer auto-funds
 * from the platform's connected bank at auth-time.
 */
import { useCallback, useEffect, useState } from 'react';
import {
  View, Text, ScrollView, StyleSheet, ActivityIndicator,
  TouchableOpacity, Alert, TextInput, Switch,
} from 'react-native';
import {
  CheckCircle2, AlertTriangle, ChevronDown, Save, RefreshCw,
  CreditCard, Smartphone, ShieldCheck, ShieldAlert,
} from 'lucide-react-native';
import { paymentGatewaysApi, IssuerProvider, IssuerListResp } from '../../adminApi/paymentGateways';
import { COLORS, FONT, RADIUS, SPACING } from '../../theme';

export default function IssuerGatewaysTab({ purpose = 'issuer' }: { purpose?: 'issuer' | 'payout' }) {
  const [data, setData] = useState<IssuerListResp | null>(null);
  const [loading, setLoading] = useState(true);
  const [busySlug, setBusySlug] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  // Per-provider credential form state, keyed by slug.
  const [creds, setCreds] = useState<Record<string, Record<string, string>>>({});

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await paymentGatewaysApi.list();
      setData(r);
    } catch (e: any) {
      Alert.alert('Failed to load issuers', e?.message || '');
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  // Filter providers by tab purpose. Adapter.purpose tells us where each one
  // belongs ("issuer", "payout", or "both"). Lithic / Stripe / Highnote =
  // issuer; Unit.co = payout (founder repurposed June 2025).
  const filteredProviders = (data?.providers || []).filter((p) =>
    purpose === 'issuer'
      ? p.purpose === 'issuer' || p.purpose === 'both'
      : p.purpose === 'payout' || p.purpose === 'both',
  );

  const onToggle = async (p: IssuerProvider, on: boolean) => {
    if (p.active && !on) {
      Alert.alert(
        'Cannot disable the active issuer',
        `${p.display_name} is currently the active issuer. Activate another provider first, then disable this one.`,
      );
      return;
    }
    setBusySlug(p.slug);
    try {
      await paymentGatewaysApi.toggle(p.slug, on);
      await load();
    } catch (e: any) {
      Alert.alert('Toggle failed', e?.message || '');
    } finally {
      setBusySlug(null);
    }
  };

  const onActivate = async (p: IssuerProvider) => {
    if (!p.configured) {
      Alert.alert('Configure first', `${p.display_name} has no credentials yet. Configure and save credentials, then activate.`);
      return;
    }
    if (!p.health.ok) {
      Alert.alert('Health check failed', p.health.message || 'Provider is not reachable.');
      return;
    }
    setBusySlug(p.slug);
    try {
      await paymentGatewaysApi.activate(p.slug);
      await load();
      Alert.alert('Activated', `${p.display_name} is now the live virtual-card issuer for all new squads.`);
    } catch (e: any) {
      Alert.alert('Activate failed', e?.message || '');
    } finally {
      setBusySlug(null);
    }
  };

  const onSaveCreds = async (p: IssuerProvider) => {
    const filled = creds[p.slug] || {};
    const nonEmpty = Object.fromEntries(
      Object.entries(filled).filter(([_, v]) => String(v).trim().length > 0),
    );
    if (Object.keys(nonEmpty).length === 0) {
      Alert.alert('Nothing to save', 'Fill at least one credential field first.');
      return;
    }
    setBusySlug(p.slug);
    try {
      const r = await paymentGatewaysApi.configure(p.slug, nonEmpty);
      Alert.alert(
        r.health.ok ? 'Saved' : 'Saved (with warning)',
        r.health.ok
          ? `${p.display_name} credentials saved and verified.`
          : `Credentials saved but health check failed: ${r.health.message}`,
      );
      setCreds((prev) => ({ ...prev, [p.slug]: {} }));
      await load();
    } catch (e: any) {
      Alert.alert('Save failed', e?.message || '');
    } finally {
      setBusySlug(null);
    }
  };

  if (loading) {
    return (
      <View style={styles.loading}>
        <ActivityIndicator />
        <Text style={styles.loadingText}>Loading virtual card issuers…</Text>
      </View>
    );
  }

  if (!data) {
    return (
      <View style={styles.loading}>
        <Text style={styles.loadingText}>No data.</Text>
      </View>
    );
  }

  return (
    <ScrollView style={{ flex: 1 }} contentContainerStyle={{ padding: SPACING.md, gap: SPACING.md }} testID="issuer-gateways-tab">
      {/* Header strip */}
      <View style={styles.headerCard}>
        <View style={{ flex: 1 }}>
          <Text style={styles.headerTitle}>
            {purpose === 'issuer' ? 'Virtual Card Issuer' : 'New Adapter-Based Payout Providers'}
          </Text>
          <Text style={styles.headerSub}>
            {purpose === 'issuer'
              ? "One active issuer at a time. The active provider owns every new squad's card lifecycle: issuance, funding, tokenization, webhooks. Switching is instant — no code deploy."
              : "Adapter-based providers usable for pushing money out (merchant payouts, lead bank deposits). Configure credentials and enable each one independently. Existing legacy payout providers are listed above this section."}
          </Text>
          {purpose === 'issuer' ? (
            <Text style={styles.headerActive}>
              Active: <Text style={styles.headerActiveSlug}>{data.active_issuer}</Text>
              {data.active_changed_by ? <Text style={styles.headerActiveBy}>  •  changed by {data.active_changed_by}</Text> : null}
            </Text>
          ) : null}
        </View>
        <TouchableOpacity onPress={load} style={styles.refreshBtn} testID="issuer-refresh">
          <RefreshCw size={16} color={COLORS.primary} />
          <Text style={styles.refreshText}>Refresh</Text>
        </TouchableOpacity>
      </View>

      {filteredProviders.length === 0 ? (
        <View style={styles.empty}>
          <Text style={styles.emptyText}>
            No {purpose === 'issuer' ? 'card-issuance' : 'payout-capable'} adapters available.
          </Text>
        </View>
      ) : null}

      {/* Provider cards */}
      {filteredProviders.map((p) => {
        const isExpanded = expanded === p.slug;
        const busy = busySlug === p.slug;
        return (
          <View key={p.slug} style={[styles.card, p.active && styles.cardActive]} testID={`issuer-card-${p.slug}`}>
            <TouchableOpacity
              activeOpacity={0.85}
              onPress={() => setExpanded(isExpanded ? null : p.slug)}
              style={styles.cardHeader}
            >
              <View style={styles.cardHeaderLeft}>
                <CreditCard size={20} color={p.active ? COLORS.primary : COLORS.subtext} />
                <View style={{ flex: 1 }}>
                  <View style={styles.cardTitleRow}>
                    <Text style={styles.cardTitle}>{p.display_name}</Text>
                    {p.active ? (
                      <View style={styles.activeBadge}>
                        <CheckCircle2 size={11} color={COLORS.success} />
                        <Text style={styles.activeBadgeText}>ACTIVE</Text>
                      </View>
                    ) : null}
                    {!p.configured ? (
                      <View style={styles.warnBadge}>
                        <Text style={styles.warnBadgeText}>NEEDS CREDENTIALS</Text>
                      </View>
                    ) : null}
                  </View>
                  <Text style={styles.cardMeta}>
                    {p.health.ok ? (
                      <Text style={{ color: COLORS.success }}>● Healthy</Text>
                    ) : (
                      <Text style={{ color: COLORS.danger }}>● {p.health.message.slice(0, 80)}</Text>
                    )}
                    {p.health.env ? <Text style={{ color: COLORS.subtext }}>  •  env: {p.health.env}</Text> : null}
                    {p.health.latency_ms ? <Text style={{ color: COLORS.subtext }}>  •  {p.health.latency_ms}ms</Text> : null}
                  </Text>
                  <View style={styles.capRow}>
                    {p.capabilities.apple_wallet ? <CapChip icon="🍎" label="Apple Pay" /> : null}
                    {p.capabilities.google_wallet ? <CapChip icon="💭" label="Google Pay" /> : null}
                    {p.capabilities.single_use ? <CapChip icon="🔂" label="Single-use" /> : null}
                  </View>
                </View>
              </View>
              <ChevronDown
                size={18}
                color={COLORS.subtext}
                style={{ transform: [{ rotate: isExpanded ? '180deg' : '0deg' }] }}
              />
            </TouchableOpacity>

            {isExpanded ? (
              <View style={styles.cardBody}>
                {/* Enable / Disable */}
                <View style={styles.row}>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.rowLabel}>Enabled</Text>
                    <Text style={styles.rowSub}>
                      Disabled providers cannot be activated. The currently-active provider cannot be disabled.
                    </Text>
                  </View>
                  <Switch
                    value={p.enabled}
                    onValueChange={(v) => onToggle(p, v)}
                    disabled={busy}
                    trackColor={{ true: COLORS.primary, false: COLORS.disabledBg }}
                    thumbColor="#fff"
                  />
                </View>

                {/* Credentials */}
                <Text style={styles.sectionHeader}>Credentials</Text>
                {p.env_keys.length === 0 ? (
                  <Text style={styles.helpText}>This provider has no credential fields.</Text>
                ) : (
                  p.env_keys.map((key) => (
                    <View key={key} style={styles.field}>
                      <Text style={styles.fieldLabel}>{key}</Text>
                      <TextInput
                        value={creds[p.slug]?.[key] || ''}
                        onChangeText={(t) =>
                          setCreds((prev) => ({
                            ...prev,
                            [p.slug]: { ...(prev[p.slug] || {}), [key]: t },
                          }))
                        }
                        placeholder={p.configured ? '•••••• (already set, type to overwrite)' : 'Paste credential value'}
                        placeholderTextColor={COLORS.subtext}
                        secureTextEntry={!key.endsWith('_ENV')}
                        autoCapitalize="none"
                        autoCorrect={false}
                        style={styles.input}
                        testID={`issuer-${p.slug}-${key}`}
                      />
                    </View>
                  ))
                )}

                {/* Action row */}
                <View style={styles.actionRow}>
                  <TouchableOpacity
                    onPress={() => onSaveCreds(p)}
                    disabled={busy}
                    style={[styles.btn, styles.btnSecondary, busy && { opacity: 0.5 }]}
                    testID={`issuer-save-${p.slug}`}
                  >
                    <Save size={14} color={COLORS.primary} />
                    <Text style={styles.btnSecondaryText}>Save credentials</Text>
                  </TouchableOpacity>
                  {/* "Make Active" only meaningful for issuer-purpose providers.
                      Payout-purpose providers don't have a single-active mutex \u2014
                      multiple payout rails can run in parallel. */}
                  {purpose === 'issuer' ? (
                    <TouchableOpacity
                      onPress={() => onActivate(p)}
                      disabled={busy || p.active}
                      style={[
                        styles.btn,
                        styles.btnPrimary,
                        (busy || p.active) && { opacity: 0.5 },
                      ]}
                      testID={`issuer-activate-${p.slug}`}
                    >
                      {p.active ? <CheckCircle2 size={14} color="#fff" /> : <Smartphone size={14} color="#fff" />}
                      <Text style={styles.btnPrimaryText}>
                        {p.active ? 'Currently Active' : 'Make Active'}
                      </Text>
                    </TouchableOpacity>
                  ) : null}
                </View>

                {/* Compliance footer */}
                <View style={styles.compliance}>
                  <ShieldCheck size={14} color={COLORS.success} />
                  <Text style={styles.complianceText}>
                    SquadPay never holds money. Activated issuer auto-funds from the platform bank at
                    auth-time. No squad balance is ever stored.
                  </Text>
                </View>
              </View>
            ) : null}
          </View>
        );
      })}
    </ScrollView>
  );
}

function CapChip({ icon, label }: { icon: string; label: string }) {
  return (
    <View style={styles.capChip}>
      <Text style={styles.capChipText}>{icon}  {label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  loading: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: SPACING.xl, gap: 8 },
  loadingText: { color: COLORS.subtext },
  headerCard: {
    flexDirection: 'row', alignItems: 'flex-start',
    backgroundColor: COLORS.surfaceMuted, padding: SPACING.md,
    borderRadius: RADIUS.lg, gap: SPACING.md,
  },
  headerTitle: { fontSize: 16, fontWeight: FONT.weights.heavy, color: COLORS.text },
  headerSub: { fontSize: 12, color: COLORS.subtext, marginTop: 4, lineHeight: 18 },
  headerActive: { fontSize: 12, marginTop: 8, color: COLORS.text },
  headerActiveSlug: { fontWeight: FONT.weights.heavy, color: COLORS.primary, textTransform: 'uppercase' },
  headerActiveBy: { color: COLORS.subtext },
  refreshBtn: {
    flexDirection: 'row', alignItems: 'center', gap: 6,
    paddingVertical: 6, paddingHorizontal: 10, borderRadius: RADIUS.md,
    backgroundColor: 'rgba(108,71,255,0.10)',
  },
  refreshText: { color: COLORS.primary, fontSize: 12, fontWeight: FONT.weights.semibold },
  empty: {
    padding: SPACING.lg, alignItems: 'center', justifyContent: 'center',
    backgroundColor: COLORS.surfaceMuted, borderRadius: RADIUS.md,
  },
  emptyText: { color: COLORS.subtext, fontSize: 13, fontStyle: 'italic' },
  card: {
    borderWidth: 1, borderColor: COLORS.border, borderRadius: RADIUS.lg,
    backgroundColor: COLORS.surface,
  },
  cardActive: { borderColor: COLORS.primary, backgroundColor: 'rgba(108,71,255,0.04)' },
  cardHeader: { flexDirection: 'row', alignItems: 'center', padding: SPACING.md, gap: SPACING.sm },
  cardHeaderLeft: { flex: 1, flexDirection: 'row', alignItems: 'flex-start', gap: SPACING.sm },
  cardTitleRow: { flexDirection: 'row', alignItems: 'center', gap: 6, flexWrap: 'wrap' },
  cardTitle: { fontSize: 15, fontWeight: FONT.weights.heavy, color: COLORS.text },
  activeBadge: {
    flexDirection: 'row', alignItems: 'center', gap: 3,
    paddingHorizontal: 6, paddingVertical: 2, borderRadius: 999,
    backgroundColor: 'rgba(46,204,113,0.15)',
  },
  activeBadgeText: { fontSize: 9, fontWeight: FONT.weights.heavy, color: COLORS.success, letterSpacing: 0.5 },
  warnBadge: {
    paddingHorizontal: 6, paddingVertical: 2, borderRadius: 999,
    backgroundColor: 'rgba(243,156,18,0.15)',
  },
  warnBadgeText: { fontSize: 9, fontWeight: FONT.weights.heavy, color: '#c98a16', letterSpacing: 0.5 },
  cardMeta: { fontSize: 11, color: COLORS.subtext, marginTop: 4 },
  capRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 4, marginTop: 6 },
  capChip: {
    paddingHorizontal: 6, paddingVertical: 2, borderRadius: 999,
    backgroundColor: 'rgba(108,71,255,0.08)',
  },
  capChipText: { fontSize: 10, color: COLORS.primary, fontWeight: FONT.weights.semibold },
  cardBody: {
    paddingHorizontal: SPACING.md, paddingBottom: SPACING.md,
    borderTopWidth: 1, borderTopColor: COLORS.border, gap: SPACING.md,
  },
  row: { flexDirection: 'row', alignItems: 'center', gap: SPACING.md, marginTop: SPACING.sm },
  rowLabel: { fontSize: 13, fontWeight: FONT.weights.semibold, color: COLORS.text },
  rowSub: { fontSize: 11, color: COLORS.subtext, marginTop: 2, lineHeight: 16 },
  sectionHeader: {
    fontSize: 11, fontWeight: FONT.weights.heavy, color: COLORS.subtext,
    textTransform: 'uppercase', letterSpacing: 1, marginTop: 4,
  },
  helpText: { fontSize: 12, color: COLORS.subtext, fontStyle: 'italic' },
  field: { gap: 4 },
  fieldLabel: { fontSize: 11, fontWeight: FONT.weights.semibold, color: COLORS.subtext, letterSpacing: 0.5 },
  input: {
    borderWidth: 1, borderColor: COLORS.border, borderRadius: RADIUS.md,
    paddingHorizontal: 10, paddingVertical: 8, fontSize: 13, color: COLORS.text,
    backgroundColor: COLORS.surface,
  },
  actionRow: { flexDirection: 'row', gap: SPACING.sm, marginTop: SPACING.sm },
  btn: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6,
    paddingVertical: 10, paddingHorizontal: 14, borderRadius: RADIUS.md, flex: 1,
  },
  btnPrimary: { backgroundColor: COLORS.primary },
  btnPrimaryText: { color: '#fff', fontWeight: FONT.weights.heavy, fontSize: 13 },
  btnSecondary: { backgroundColor: 'rgba(108,71,255,0.10)' },
  btnSecondaryText: { color: COLORS.primary, fontWeight: FONT.weights.heavy, fontSize: 13 },
  compliance: {
    flexDirection: 'row', alignItems: 'flex-start', gap: 6, padding: 10,
    backgroundColor: 'rgba(46,204,113,0.08)', borderRadius: RADIUS.md,
  },
  complianceText: { flex: 1, fontSize: 11, color: COLORS.text, lineHeight: 16 },
});

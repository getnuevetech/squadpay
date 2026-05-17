/**
 * /admin/gateways — Payment Gateway Configuration (Phase 2).
 *
 * Two tabs: CHARGE / PAYOUT. Each tab lists supported providers as cards.
 * Tap a card → expand to edit credentials. "Make active" promotes the
 * provider; backend ensures only one is active per group.
 *
 * The provider catalog (slug, fields, fee labels) comes from the backend
 * (/api/admin/gateways/catalog). API keys are masked once stored.
 */
import { useEffect, useMemo, useState, useCallback } from 'react';
import {
  View, Text, ScrollView, StyleSheet, ActivityIndicator,
  TouchableOpacity, Alert, TextInput, Platform,
} from 'react-native';
import { CheckCircle2, ShieldAlert, Plug, ChevronDown, Save, Eye, EyeOff, Zap } from 'lucide-react-native';
import { adminApi } from '../../src/adminApi';
import { COLORS, FONT, RADIUS, SPACING } from '../../src/theme';
import IssuerGatewaysTab from '../../src/components/admin/IssuerGatewaysTab';

// Top-level tab union: original 2 (charge/payout) + new "issuer" for virtual
// card adapters (Stripe / Lithic / Highnote / Unit). Per user spec all
// payment gateway configuration lives on this single page.
type TopTab = 'charge' | 'payout' | 'issuer';

type ProviderField = {
  key: string;
  label: string;
  kind: 'secret' | 'public' | 'select';
  required?: boolean;
  help_text?: string;
  options?: string[];
};
type Provider = {
  slug: string;
  display_name: string;
  group: 'charge' | 'payout';
  icon_hint?: string;
  default_fee_label: string;
  regions: string[];
  fields: ProviderField[];
  status: 'production' | 'scaffold';
};
type StoredConfig = {
  id: string;
  group: 'charge' | 'payout';
  provider_slug: string;
  is_active: boolean;
  settings: Record<string, any>;
  credentials: Record<string, { kind: string; set?: boolean; masked?: string | null; value?: string | null }>;
  updated_at: string;
};

export default function GatewaysPage() {
  const [tab, setTab] = useState<TopTab>('charge');
  const [catalog, setCatalog] = useState<{ charge: Provider[]; payout: Provider[] } | null>(null);
  const [active, setActive] = useState<{ charge: string | null; payout: string | null }>({ charge: null, payout: null });
  const [configs, setConfigs] = useState<Record<string, StoredConfig>>({}); // key: `${group}:${slug}`
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [savingKey, setSavingKey] = useState<string | null>(null);

  // Edit-form local state, keyed by `${group}:${slug}`.
  const [formInputs, setFormInputs] = useState<Record<string, Record<string, string>>>({});
  const [shownSecret, setShownSecret] = useState<Record<string, boolean>>({});

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [cat, state] = await Promise.all([
        adminApi.gatewayCatalog(),
        adminApi.gatewayState(),
      ]);
      setCatalog({ charge: cat.charge_providers, payout: cat.payout_providers });
      setActive(cat.active);
      const map: Record<string, StoredConfig> = {};
      for (const c of state.items) map[`${c.group}:${c.provider_slug}`] = c;
      setConfigs(map);
    } catch (e: any) {
      Alert.alert('Failed to load', e?.message || '');
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  const formKey = (p: Provider) => `${p.group}:${p.slug}`;

  const onChangeField = (p: Provider, k: string, v: string) => {
    const fk = formKey(p);
    setFormInputs((prev) => ({ ...prev, [fk]: { ...(prev[fk] || {}), [k]: v } }));
  };

  const saveProvider = async (p: Provider) => {
    const fk = formKey(p);
    const credentials = formInputs[fk] || {};
    if (Object.keys(credentials).length === 0) {
      Alert.alert('Nothing to save', 'Update at least one field first.');
      return;
    }
    setSavingKey(fk);
    try {
      const updated = await adminApi.saveGatewayCredentials(p.group, p.slug, credentials);
      setConfigs((prev) => ({ ...prev, [fk]: updated }));
      setFormInputs((prev) => ({ ...prev, [fk]: {} })); // clear typed values
      Alert.alert('Saved', `${p.display_name} credentials updated.`);
    } catch (e: any) {
      Alert.alert('Save failed', e?.message || '');
    } finally {
      setSavingKey(null);
    }
  };

  const activateProvider = async (p: Provider) => {
    const doActivate = async () => {
      try {
        await adminApi.activateGateway(p.group, p.slug);
        await load();
        Alert.alert('Activated', `${p.display_name} is now the active ${p.group} provider.`);
      } catch (e: any) {
        Alert.alert('Activation failed', e?.message || '');
      }
    };
    if (Platform.OS === 'web') {
      // eslint-disable-next-line no-alert
      if (window.confirm(`Set ${p.display_name} as the active ${p.group} provider?`)) doActivate();
    } else {
      Alert.alert('Activate provider', `Set ${p.display_name} as active?`, [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Activate', onPress: doActivate },
      ]);
    }
  };

  const tabProviders = useMemo(() => {
    if (!catalog) return [] as Provider[];
    return tab === 'charge' ? catalog.charge : catalog.payout;
  }, [catalog, tab]);

  if (loading || !catalog) {
    return <View style={styles.center}><ActivityIndicator color={COLORS.primary} /></View>;
  }

  return (
    <ScrollView style={styles.root} contentContainerStyle={styles.container}>
      <View style={styles.headerRow}>
        <Plug size={20} color={COLORS.primary} />
        <Text style={styles.h1}>Payment Gateways</Text>
      </View>
      <Text style={styles.sub}>
        SquadPay supports two independent provider groups: <Text style={styles.bold}>Charge</Text> (collect contributions
        from members) and <Text style={styles.bold}>Payout</Text> (push funds to a debit card via iframe). Configure each provider's
        API keys, then activate exactly one provider per group.
      </Text>

      {/* Tabs */}
      <View style={styles.tabRow}>
        {(['charge', 'payout', 'issuer'] as const).map((t) => {
          const isOn = t === tab;
          const activeSlug = t === 'issuer' ? null : active[t as 'charge' | 'payout'];
          return (
            <TouchableOpacity
              key={t}
              onPress={() => setTab(t)}
              activeOpacity={0.8}
              style={[styles.tab, isOn && styles.tabActive]}
              testID={`gateways-tab-${t}`}
            >
              <Text style={[styles.tabText, isOn && { color: '#fff' }]}>
                {t === 'charge' ? 'Charge / Collection' : t === 'payout' ? 'Payout / Withdrawal' : 'Virtual Card Issuer'}
              </Text>
              {t === 'issuer' ? (
                <Text style={[styles.tabSub, isOn && { color: '#fff', opacity: 0.85 }]}>
                  Stripe / Lithic / Highnote / Unit
                </Text>
              ) : activeSlug ? (
                <Text style={[styles.tabSub, isOn && { color: '#fff', opacity: 0.85 }]}>
                  Active: {activeSlug}
                </Text>
              ) : (
                <Text style={[styles.tabSub, isOn && { color: '#fff', opacity: 0.85 }, { color: COLORS.danger }]}>
                  No provider active
                </Text>
              )}
            </TouchableOpacity>
          );
        })}
      </View>

      {tab === 'issuer' ? (
        <IssuerGatewaysTab purpose="issuer" />
      ) : (
        <>
          {tabProviders.map((p) => {
        const fk = formKey(p);
        const cfg = configs[fk];
        const isActive = active[p.group] === p.slug;
        const isExpanded = expanded === fk;
        const isScaffold = p.status === 'scaffold';

        return (
          <View key={fk} style={[styles.card, isActive && styles.cardActive]} testID={`gw-card-${p.slug}`}>
            <TouchableOpacity
              activeOpacity={0.85}
              onPress={() => setExpanded(isExpanded ? null : fk)}
              style={styles.cardHeader}
            >
              <View style={{ flex: 1 }}>
                <View style={styles.cardHeaderTitle}>
                  <Text style={styles.cardName}>{p.display_name}</Text>
                  {isActive ? (
                    <View style={styles.activeBadge}>
                      <CheckCircle2 size={11} color={COLORS.success} />
                      <Text style={styles.activeBadgeText}>ACTIVE</Text>
                    </View>
                  ) : null}
                  {isScaffold ? (
                    <View style={styles.scaffoldBadge}>
                      <Text style={styles.scaffoldText}>SCAFFOLD</Text>
                    </View>
                  ) : null}
                </View>
                <Text style={styles.cardMeta}>
                  Fee: <Text style={styles.feeText}>{p.default_fee_label}</Text>
                  {'  •  '}
                  Regions: {p.regions.join(', ')}
                </Text>
                {isScaffold ? (
                  <Text style={styles.scaffoldHint}>
                    Adapter not yet implemented. Credentials saved here will be live once we ship the {p.display_name} adapter in a future release.
                  </Text>
                ) : null}
              </View>
              <ChevronDown
                size={18}
                color={COLORS.subtext}
                style={{ transform: [{ rotate: isExpanded ? '180deg' : '0deg' }] }}
              />
            </TouchableOpacity>

            {isExpanded ? (
              <View style={styles.cardBody}>
                {p.fields.map((f) => {
                  const stored = cfg?.credentials[f.key];
                  const typed = formInputs[fk]?.[f.key];
                  const placeholder =
                    stored && stored.kind === 'secret' && stored.set
                      ? `Stored: ${stored.masked}`
                      : stored && stored.kind !== 'secret' && stored.value
                      ? String(stored.value)
                      : '';
                  const secretShown = !!shownSecret[`${fk}:${f.key}`];

                  return (
                    <View key={f.key} style={styles.field}>
                      <Text style={styles.fieldLabel}>
                        {f.label}
                        {f.required ? <Text style={{ color: COLORS.danger }}> *</Text> : null}
                      </Text>
                      {f.kind === 'select' ? (
                        <View style={styles.optionRow}>
                          {(f.options || []).map((opt) => {
                            const current = typed ?? (stored?.value as string | undefined) ?? '';
                            const isSel = current === opt;
                            return (
                              <TouchableOpacity
                                key={opt}
                                onPress={() => onChangeField(p, f.key, opt)}
                                activeOpacity={0.7}
                                style={[styles.optionChip, isSel && styles.optionChipActive]}
                              >
                                <Text style={[styles.optionChipText, isSel && { color: '#fff' }]}>{opt}</Text>
                              </TouchableOpacity>
                            );
                          })}
                        </View>
                      ) : (
                        <View style={styles.inputRow}>
                          <TextInput
                            value={typed ?? ''}
                            onChangeText={(t) => onChangeField(p, f.key, t)}
                            placeholder={placeholder || `Enter ${f.label.toLowerCase()}`}
                            placeholderTextColor={COLORS.subtext}
                            secureTextEntry={f.kind === 'secret' && !secretShown}
                            autoCapitalize="none"
                            autoCorrect={false}
                            style={styles.input}
                            testID={`gw-input-${p.slug}-${f.key}`}
                          />
                          {f.kind === 'secret' ? (
                            <TouchableOpacity
                              onPress={() => setShownSecret((s) => ({ ...s, [`${fk}:${f.key}`]: !secretShown }))}
                              style={styles.eyeBtn}
                              activeOpacity={0.7}
                            >
                              {secretShown ? <EyeOff size={14} color={COLORS.subtext} /> : <Eye size={14} color={COLORS.subtext} />}
                            </TouchableOpacity>
                          ) : null}
                        </View>
                      )}
                      {f.help_text ? <Text style={styles.helpText}>{f.help_text}</Text> : null}
                    </View>
                  );
                })}

                <View style={styles.actionRow}>
                  <TouchableOpacity
                    onPress={() => saveProvider(p)}
                    style={[styles.btn, styles.btnPrimary]}
                    activeOpacity={0.8}
                    disabled={savingKey === fk}
                    testID={`gw-save-${p.slug}`}
                  >
                    {savingKey === fk ? <ActivityIndicator color="#fff" /> : <Save size={14} color="#fff" />}
                    <Text style={styles.btnPrimaryText}>Save credentials</Text>
                  </TouchableOpacity>

                  {!isActive ? (
                    <TouchableOpacity
                      onPress={() => activateProvider(p)}
                      style={[styles.btn, styles.btnSuccess]}
                      activeOpacity={0.8}
                      testID={`gw-activate-${p.slug}`}
                    >
                      <Zap size={14} color="#fff" />
                      <Text style={styles.btnPrimaryText}>Make active for {p.group}</Text>
                    </TouchableOpacity>
                  ) : (
                    <View style={[styles.btn, styles.btnGhost]}>
                      <CheckCircle2 size={14} color={COLORS.success} />
                      <Text style={styles.btnGhostText}>Currently active</Text>
                    </View>
                  )}
                </View>

                <View style={styles.reminderBox}>
                  <ShieldAlert size={12} color={COLORS.warning} />
                  <Text style={styles.reminderText}>
                    After switching providers, update <Text style={styles.bold}>Platform Fees</Text> to reflect this provider's fee:{' '}
                    <Text style={styles.bold}>{p.default_fee_label}</Text>.
                  </Text>
                </View>
              </View>
            ) : null}
          </View>
        );
        })}
        {/* Adapter-based payout providers (Lithic / Highnote / Unit / Stripe).
            Founder spec: "add all new gateways to also be in group for payout".
            Renders ONLY providers whose adapter.purpose includes "payout"
            (currently Unit.co \u2014 repurposed for merchant payouts). */}
        {tab === 'payout' && <IssuerGatewaysTab purpose="payout" />}
        </>
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: COLORS.bg },
  container: { padding: SPACING.lg, gap: SPACING.md, maxWidth: 1100, alignSelf: 'stretch', width: '100%' },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: SPACING.xl },
  headerRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  h1: { fontSize: FONT.sizes.xl, fontWeight: FONT.weights.bold, color: COLORS.text },
  sub: { fontSize: FONT.sizes.sm, color: COLORS.subtext, lineHeight: 19 },
  bold: { fontWeight: FONT.weights.bold, color: COLORS.text },
  tabRow: { flexDirection: 'row', gap: 8, marginVertical: SPACING.sm },
  tab: {
    flex: 1, paddingVertical: 12, paddingHorizontal: SPACING.md, borderRadius: RADIUS.md,
    backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border,
  },
  tabActive: { backgroundColor: COLORS.primary, borderColor: COLORS.primary },
  tabText: { color: COLORS.text, fontWeight: FONT.weights.bold, fontSize: FONT.sizes.sm },
  tabSub: { color: COLORS.subtext, fontSize: 11, marginTop: 2 },

  card: {
    backgroundColor: COLORS.surface, borderRadius: RADIUS.lg,
    borderWidth: 1, borderColor: COLORS.border, overflow: 'hidden',
  },
  cardActive: { borderColor: COLORS.success, borderWidth: 2 },
  cardHeader: { flexDirection: 'row', alignItems: 'center', gap: 12, padding: SPACING.md },
  cardHeaderTitle: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  cardName: { fontSize: FONT.sizes.md, color: COLORS.text, fontWeight: FONT.weights.bold },
  cardMeta: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: 4 },
  feeText: { color: COLORS.text, fontWeight: FONT.weights.semibold },
  scaffoldHint: { fontSize: 11, color: COLORS.warning, marginTop: 4, fontStyle: 'italic' },

  activeBadge: { flexDirection: 'row', alignItems: 'center', gap: 4, paddingHorizontal: 6, paddingVertical: 2, borderRadius: 999, backgroundColor: COLORS.successLight || '#DCFCE7' },
  activeBadgeText: { fontSize: 9, color: COLORS.success, fontWeight: FONT.weights.bold },
  scaffoldBadge: { paddingHorizontal: 6, paddingVertical: 2, borderRadius: 999, backgroundColor: COLORS.warningLight || '#FEF3C7' },
  scaffoldText: { fontSize: 9, color: COLORS.warning, fontWeight: FONT.weights.bold },

  cardBody: { padding: SPACING.md, gap: SPACING.md, borderTopWidth: 1, borderTopColor: COLORS.border, backgroundColor: COLORS.bg },
  field: {},
  fieldLabel: { fontSize: FONT.sizes.xs, color: COLORS.subtext, fontWeight: FONT.weights.semibold, marginBottom: 4 },
  inputRow: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  input: {
    flex: 1, borderWidth: 1, borderColor: COLORS.border, borderRadius: RADIUS.md,
    paddingHorizontal: 12, paddingVertical: 10, color: COLORS.text, fontSize: FONT.sizes.md,
    backgroundColor: COLORS.surface, fontFamily: 'monospace',
  },
  eyeBtn: { padding: 8, borderRadius: RADIUS.md, backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border },
  helpText: { fontSize: 11, color: COLORS.subtext, marginTop: 4 },
  optionRow: { flexDirection: 'row', gap: 6 },
  optionChip: { paddingHorizontal: 12, paddingVertical: 6, borderRadius: 999, borderWidth: 1, borderColor: COLORS.border, backgroundColor: COLORS.surface },
  optionChipActive: { backgroundColor: COLORS.primary, borderColor: COLORS.primary },
  optionChipText: { fontSize: FONT.sizes.xs, color: COLORS.text, fontWeight: FONT.weights.semibold },

  actionRow: { flexDirection: 'row', gap: 8, marginTop: SPACING.sm },
  btn: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6, paddingHorizontal: 18, paddingVertical: 10, borderRadius: RADIUS.md, minHeight: 40 },
  btnPrimary: { backgroundColor: COLORS.primary, flex: 1 },
  btnSuccess: { backgroundColor: COLORS.success, flex: 1 },
  btnGhost: { backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.success, flex: 1 },
  btnPrimaryText: { color: '#fff', fontWeight: FONT.weights.bold, fontSize: FONT.sizes.sm },
  btnGhostText: { color: COLORS.success, fontWeight: FONT.weights.bold, fontSize: FONT.sizes.sm },

  reminderBox: {
    flexDirection: 'row', alignItems: 'flex-start', gap: 6,
    padding: SPACING.sm, borderRadius: RADIUS.md,
    backgroundColor: COLORS.warningLight || '#FEF3C7',
  },
  reminderText: { flex: 1, fontSize: 11, color: COLORS.warning, lineHeight: 16 },
});

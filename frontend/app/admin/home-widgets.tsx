/**
 * Admin → Home Widgets
 *
 * Configures the two admin-controlled cards rendered on the user home
 * screen below the FeaturedBillCard:
 *
 *   • "What's Next" — ordered, per-rule editable suggestion card. Each
 *     rule has a fixed trigger condition (key) but its title/subtitle/
 *     icon/route are admin-editable. Rules can be toggled on/off.
 *
 *   • "Promo Banner" — single evergreen card with title/body/icon/route
 *     + dismiss settings.
 *
 * UI uses the existing admin chrome and styling primitives.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import { Stack } from 'expo-router';
import { request } from '../../src/adminApi/_core';
import { COLORS, FONT, RADIUS, SPACING } from '../../src/theme';
import { toast } from '../../src/components/Toast';

type Rule = {
  key: string;
  enabled: boolean;
  title: string;
  subtitle: string;
  icon: string;
  route: string;
};
type Promo = {
  enabled: boolean;
  title: string;
  body: string;
  icon: string;
  route: string;
  dismissible: boolean;
  dismiss_days: number;
};
type Config = {
  whats_next_card: { enabled: boolean; rules: Rule[] };
  promo_banner: Promo;
  allowed_icons: string[];
  known_rule_keys: string[];
  updated_at?: string;
};

const RULE_LABELS: Record<string, string> = {
  verify_phone: 'When the user has NOT verified their phone',
  outstanding_owed: 'When the user owes money on 1+ squads',
  no_squads: 'When the user has no squads yet',
  invite_friends: 'When invite-friends is enabled (fallback)',
};

export default function AdminHomeWidgetsScreen() {
  const [cfg, setCfg] = useState<Config | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await request<Config>('/home-widgets');
      setCfg(data);
    } catch (e: any) {
      Alert.alert('Failed to load', e?.message || 'Could not fetch widgets config');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const save = useCallback(async () => {
    if (!cfg) return;
    setSaving(true);
    try {
      await request('/home-widgets', {
        method: 'PUT',
        body: JSON.stringify({
          whats_next_card: cfg.whats_next_card,
          promo_banner: cfg.promo_banner,
        }),
      });
      toast.success('Saved');
      await load();
    } catch (e: any) {
      Alert.alert('Save failed', e?.message || 'Try again');
    } finally {
      setSaving(false);
    }
  }, [cfg, load]);

  const updateRule = (idx: number, patch: Partial<Rule>) => {
    if (!cfg) return;
    const next = { ...cfg };
    next.whats_next_card.rules = next.whats_next_card.rules.map((r, i) =>
      i === idx ? { ...r, ...patch } : r,
    );
    setCfg(next);
  };

  if (loading || !cfg) {
    return (
      <View style={styles.center}>
        <ActivityIndicator color={COLORS.primary} />
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <Stack.Screen options={{ title: 'Home Widgets' }} />
      <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
        <Text style={styles.pageTitle}>Home Widgets</Text>
        <Text style={styles.pageSub}>
          Configure the cards shown on the user home page below the featured bill.
          Changes apply immediately for new home loads.
        </Text>

        {/* ─── What's Next ─── */}
        <View style={styles.section}>
          <View style={styles.sectionHeader}>
            <Text style={styles.sectionTitle}>"What's Next" Card</Text>
            <Switch
              value={cfg.whats_next_card.enabled}
              onValueChange={(v) =>
                setCfg({ ...cfg, whats_next_card: { ...cfg.whats_next_card, enabled: v } })
              }
              testID="whats-next-enabled"
            />
          </View>
          <Text style={styles.sectionSub}>
            The user sees the FIRST enabled rule whose trigger matches their state.
            If none match, the card hides.
          </Text>

          {cfg.whats_next_card.rules.map((rule, idx) => (
            <View key={rule.key} style={styles.ruleCard} testID={`rule-${rule.key}`}>
              <View style={styles.ruleHeader}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.ruleKey}>{rule.key}</Text>
                  <Text style={styles.ruleTrigger}>{RULE_LABELS[rule.key] || rule.key}</Text>
                </View>
                <Switch
                  value={rule.enabled}
                  onValueChange={(v) => updateRule(idx, { enabled: v })}
                  testID={`rule-${rule.key}-enabled`}
                />
              </View>

              <FieldLabel>Title</FieldLabel>
              <TextInput
                style={styles.input}
                value={rule.title}
                onChangeText={(t) => updateRule(idx, { title: t })}
                placeholder="Card title"
                placeholderTextColor={COLORS.disabledText}
                testID={`rule-${rule.key}-title`}
              />
              {rule.key === 'outstanding_owed' ? (
                <Text style={styles.hint}>
                  Tokens available: {'{amount}'} (e.g. $24.50), {'{count}'}, {'{plural}'} (s or empty).
                </Text>
              ) : null}

              <FieldLabel>Subtitle</FieldLabel>
              <TextInput
                style={styles.input}
                value={rule.subtitle}
                onChangeText={(t) => updateRule(idx, { subtitle: t })}
                placeholder="Card subtitle"
                placeholderTextColor={COLORS.disabledText}
                testID={`rule-${rule.key}-subtitle`}
              />

              <FieldLabel>Route</FieldLabel>
              <TextInput
                style={styles.input}
                value={rule.route}
                onChangeText={(t) => updateRule(idx, { route: t })}
                placeholder="/example-route"
                placeholderTextColor={COLORS.disabledText}
                autoCapitalize="none"
                testID={`rule-${rule.key}-route`}
              />

              <FieldLabel>Icon</FieldLabel>
              <IconPicker
                allowed={cfg.allowed_icons}
                value={rule.icon}
                onChange={(v) => updateRule(idx, { icon: v })}
                testIDPrefix={`rule-${rule.key}-icon`}
              />
            </View>
          ))}
        </View>

        {/* ─── Promo Banner ─── */}
        <View style={styles.section}>
          <View style={styles.sectionHeader}>
            <Text style={styles.sectionTitle}>Promo Banner</Text>
            <Switch
              value={cfg.promo_banner.enabled}
              onValueChange={(v) =>
                setCfg({ ...cfg, promo_banner: { ...cfg.promo_banner, enabled: v } })
              }
              testID="promo-enabled"
            />
          </View>
          <Text style={styles.sectionSub}>
            Evergreen message shown to all users. Optionally dismissible.
          </Text>

          <FieldLabel>Title</FieldLabel>
          <TextInput
            style={styles.input}
            value={cfg.promo_banner.title}
            onChangeText={(t) => setCfg({ ...cfg, promo_banner: { ...cfg.promo_banner, title: t } })}
            placeholder="Promo title"
            placeholderTextColor={COLORS.disabledText}
            testID="promo-title"
          />

          <FieldLabel>Body</FieldLabel>
          <TextInput
            style={[styles.input, { minHeight: 60 }]}
            value={cfg.promo_banner.body}
            onChangeText={(t) => setCfg({ ...cfg, promo_banner: { ...cfg.promo_banner, body: t } })}
            placeholder="Short marketing message"
            placeholderTextColor={COLORS.disabledText}
            multiline
            testID="promo-body"
          />

          <FieldLabel>Route</FieldLabel>
          <TextInput
            style={styles.input}
            value={cfg.promo_banner.route}
            onChangeText={(t) => setCfg({ ...cfg, promo_banner: { ...cfg.promo_banner, route: t } })}
            placeholder="/example-route"
            placeholderTextColor={COLORS.disabledText}
            autoCapitalize="none"
            testID="promo-route"
          />

          <FieldLabel>Icon</FieldLabel>
          <IconPicker
            allowed={cfg.allowed_icons}
            value={cfg.promo_banner.icon}
            onChange={(v) =>
              setCfg({ ...cfg, promo_banner: { ...cfg.promo_banner, icon: v } })
            }
            testIDPrefix="promo-icon"
          />

          <View style={styles.row}>
            <Text style={styles.toggleLabel}>Dismissible (× button)</Text>
            <Switch
              value={cfg.promo_banner.dismissible}
              onValueChange={(v) =>
                setCfg({ ...cfg, promo_banner: { ...cfg.promo_banner, dismissible: v } })
              }
              testID="promo-dismissible"
            />
          </View>

          {cfg.promo_banner.dismissible && (
            <>
              <FieldLabel>Re-surface after dismiss (days)</FieldLabel>
              <TextInput
                style={styles.input}
                value={String(cfg.promo_banner.dismiss_days)}
                onChangeText={(t) =>
                  setCfg({
                    ...cfg,
                    promo_banner: {
                      ...cfg.promo_banner,
                      dismiss_days: Math.max(0, Math.min(365, parseInt(t.replace(/\D/g, ''), 10) || 0)),
                    },
                  })
                }
                keyboardType="number-pad"
                placeholder="7"
                placeholderTextColor={COLORS.disabledText}
                testID="promo-dismiss-days"
              />
            </>
          )}
        </View>

        <View style={{ height: SPACING.xl }} />
        <TouchableOpacity
          style={[styles.saveBtn, saving ? styles.saveBtnSaving : null]}
          onPress={save}
          disabled={saving}
          testID="save-btn"
        >
          <Text style={styles.saveBtnText}>{saving ? 'Saving…' : 'Save changes'}</Text>
        </TouchableOpacity>

        {cfg.updated_at ? (
          <Text style={styles.metaText}>
            Last updated: {new Date(cfg.updated_at).toLocaleString()}
          </Text>
        ) : null}

        <View style={{ height: 80 }} />
      </ScrollView>
    </View>
  );
}

// ─── helpers ──────────────────────────────────────────────────────────────
function FieldLabel({ children }: { children: React.ReactNode }) {
  return <Text style={styles.fieldLabel}>{children}</Text>;
}

function IconPicker({
  allowed,
  value,
  onChange,
  testIDPrefix,
}: {
  allowed: string[];
  value: string;
  onChange: (v: string) => void;
  testIDPrefix?: string;
}) {
  return (
    <View style={styles.iconGrid}>
      {allowed.map((name) => {
        const selected = name === value;
        return (
          <Pressable
            key={name}
            onPress={() => onChange(name)}
            style={[styles.iconChip, selected && styles.iconChipOn]}
            testID={testIDPrefix ? `${testIDPrefix}-${name}` : undefined}
          >
            <Text style={[styles.iconChipText, selected && styles.iconChipTextOn]}>
              {name}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: COLORS.bg },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  scroll: { padding: SPACING.lg },
  pageTitle: { fontSize: FONT.h2, fontWeight: '800', color: COLORS.text },
  pageSub: { fontSize: FONT.small, color: COLORS.subtext, marginTop: 4, marginBottom: SPACING.lg },
  section: {
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.lg,
    borderWidth: 1,
    borderColor: COLORS.border,
    padding: SPACING.lg,
    marginBottom: SPACING.lg,
  },
  sectionHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  sectionTitle: { fontSize: FONT.h4, fontWeight: '700', color: COLORS.text },
  sectionSub: { fontSize: FONT.small, color: COLORS.subtext, marginTop: 4, marginBottom: SPACING.md },
  ruleCard: {
    backgroundColor: COLORS.bg,
    borderRadius: RADIUS.md,
    borderWidth: 1,
    borderColor: COLORS.border,
    padding: SPACING.md,
    marginTop: SPACING.md,
  },
  ruleHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: SPACING.md,
    marginBottom: SPACING.sm,
  },
  ruleKey: { fontSize: FONT.body, fontWeight: '700', color: COLORS.text },
  ruleTrigger: { fontSize: FONT.small, color: COLORS.subtext, marginTop: 2 },
  fieldLabel: { fontSize: FONT.small, color: COLORS.textMuted, marginTop: SPACING.md, marginBottom: 6, fontWeight: '600' },
  input: {
    borderWidth: 1, borderColor: COLORS.border, borderRadius: RADIUS.md,
    paddingHorizontal: SPACING.md, paddingVertical: Platform.OS === 'ios' ? 12 : 10,
    fontSize: FONT.body, color: COLORS.text, backgroundColor: COLORS.surface,
  },
  hint: { fontSize: 11, color: COLORS.subtext, marginTop: 4, fontStyle: 'italic' },
  row: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    marginTop: SPACING.md,
  },
  toggleLabel: { fontSize: FONT.body, color: COLORS.text },
  iconGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  iconChip: {
    paddingHorizontal: 10, paddingVertical: 6,
    borderRadius: 14, borderWidth: 1, borderColor: COLORS.border, backgroundColor: COLORS.surface,
  },
  iconChipOn: { backgroundColor: COLORS.primary, borderColor: COLORS.primary },
  iconChipText: { fontSize: 11, color: COLORS.textMuted },
  iconChipTextOn: { color: '#fff', fontWeight: '700' },
  saveBtn: {
    backgroundColor: COLORS.primary,
    borderRadius: RADIUS.md, paddingVertical: 14, alignItems: 'center',
  },
  saveBtnSaving: { opacity: 0.6 },
  saveBtnText: { color: '#fff', fontWeight: '700', fontSize: FONT.body },
  metaText: { textAlign: 'center', color: COLORS.subtext, fontSize: FONT.small, marginTop: SPACING.md },
});

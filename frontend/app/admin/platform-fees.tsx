/**
 * Admin → App Config (rendered at the legacy /admin/platform-fees route
 * so existing links keep working).
 *
 * Single page that lets a super-admin tune every runtime setting:
 *   • Core fees       — transaction fee % + platform fee $
 *   • Extra fees      — the two extra-slot fees (% or flat)
 *   • Wallet          — Apple/Google push-provisioning toggles
 *   • Limits          — min members, min/max bill, max items
 *   • OTP             — code length, expiry, attempts/hour
 *   • Card            — spend-cap buffer %, auto-disable hours
 *   • Reminders       — cadence + bill expiry
 *   • OCR             — provider + model
 *   • Brand           — sms sender, support email, tip suggestions
 *   • Ops             — maintenance mode
 */
import { useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import { useRouter } from 'expo-router';
import {
  ArrowLeft,
  DollarSign,
  Percent,
  Save,
  Wallet as WalletIcon,
  Shield,
  Smartphone,
  CreditCard,
  Bell,
  Scan,
  Tag,
  AlertTriangle,
} from 'lucide-react-native';
import { adminApi, AppConfig, AdminPlatformFee } from '../../src/adminApi';
import { COLORS, FONT, RADIUS, SPACING } from '../../src/theme';
import { toast } from '../../src/components/Toast';

export default function AdminAppConfig() {
  const router = useRouter();
  const [cfg, setCfg] = useState<AppConfig | null>(null);
  const [busy, setBusy] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const res = await adminApi.getAppConfig();
        setCfg(res);
      } catch (e: any) {
        Alert.alert('Error', e?.message || 'Failed to load app config');
      } finally {
        setBusy(false);
      }
    })();
  }, []);

  const patch = <K extends keyof AppConfig>(section: K, value: AppConfig[K]) => {
    setCfg((prev) => (prev ? { ...prev, [section]: value } : prev));
  };

  const updateExtraFee = (id: string, p: Partial<AdminPlatformFee>) => {
    if (!cfg) return;
    patch('extra_fees', cfg.extra_fees.map((f) => (f.id === id ? { ...f, ...p } : f)));
  };

  const save = async () => {
    if (!cfg) return;
    setSaving(true);
    try {
      const updated = await adminApi.updateAppConfig(cfg);
      setCfg(updated);
      toast.success('App config saved');
    } catch (e: any) {
      Alert.alert('Save failed', e?.message || 'Could not save app config');
    } finally {
      setSaving(false);
    }
  };

  if (busy || !cfg) {
    return (
      <View style={styles.center}>
        <ActivityIndicator color={COLORS.primary} />
      </View>
    );
  }

  return (
    <ScrollView
      style={{ flex: 1, backgroundColor: COLORS.bg }}
      contentContainerStyle={{ padding: SPACING.md, paddingBottom: 80 }}
      testID="admin-app-config-page"
    >
      <View style={styles.headerRow}>
        <TouchableOpacity onPress={() => router.back()} hitSlop={10}>
          <ArrowLeft size={22} color={COLORS.text} />
        </TouchableOpacity>
        <Text style={styles.heading}>App Config & Fees</Text>
        <TouchableOpacity
          onPress={save}
          disabled={saving}
          style={[styles.saveBtn, saving && { opacity: 0.5 }]}
          testID="save-app-config"
        >
          <Save size={16} color="#fff" />
          <Text style={styles.saveText}>{saving ? 'Saving…' : 'Save'}</Text>
        </TouchableOpacity>
      </View>

      <Text style={styles.helpText}>
        Changes apply to all NEW bills created after save. Existing bills keep the
        fee schedule from the moment they were created.
      </Text>

      {/* ═══════════════════════════════════ Core Fees ═══════════════════════════════════ */}
      <Section icon={<DollarSign size={18} color={COLORS.primary} />} title="Core Fees">
        <Field
          label="Transaction Fee — Display Label"
          help="Shown as the row name in every Bill Breakdown card."
          value={cfg.core_fees.transaction_fee_label}
          onChangeText={(t) =>
            patch('core_fees', { ...cfg.core_fees, transaction_fee_label: t.slice(0, 40) })
          }
          testID="config-transaction-fee-label"
        />
        {/* June 2025 — Enable/disable toggle for Transaction Fee. */}
        <View style={styles.switchRow}>
          <Text style={styles.switchLabel}>Transaction Fee Enabled</Text>
          <Switch
            value={cfg.core_fees.transaction_fee_enabled !== false}
            onValueChange={(v) => patch('core_fees', { ...cfg.core_fees, transaction_fee_enabled: v })}
            testID="config-transaction-fee-enabled"
          />
        </View>
        <Field
          label="Transaction Fee (%)"
          help="Applied to each member's merchant share. Default 3.0%."
          value={String(cfg.core_fees.transaction_fee_pct)}
          keyboardType="decimal-pad"
          onChangeText={(t) =>
            patch('core_fees', { ...cfg.core_fees, transaction_fee_pct: parseFloat(t) || 0 })
          }
          suffix="%"
          testID="config-transaction-fee"
        />
        {/* June 2025 — Optional cap (max $) per member. 0 = no cap. */}
        <Field
          label="Transaction Fee Cap ($)"
          help="Optional maximum $ per member. Set 0 for no cap."
          value={String(cfg.core_fees.transaction_fee_cap ?? 0)}
          keyboardType="decimal-pad"
          onChangeText={(t) =>
            patch('core_fees', { ...cfg.core_fees, transaction_fee_cap: parseFloat(t) || 0 })
          }
          prefix="$"
          testID="config-transaction-fee-cap"
        />
        <Field
          label="Platform Fee — Display Label"
          help="Shown as the row name in every Bill Breakdown card."
          value={cfg.core_fees.platform_fee_label}
          onChangeText={(t) =>
            patch('core_fees', { ...cfg.core_fees, platform_fee_label: t.slice(0, 40) })
          }
          testID="config-platform-fee-label"
        />
        {/* June 2025 — Enable/disable toggle for Platform Fee. */}
        <View style={styles.switchRow}>
          <Text style={styles.switchLabel}>Platform Fee Enabled</Text>
          <Switch
            value={cfg.core_fees.platform_fee_enabled !== false}
            onValueChange={(v) => patch('core_fees', { ...cfg.core_fees, platform_fee_enabled: v })}
            testID="config-platform-fee-enabled"
          />
        </View>
        {/* June 2025 — Platform fee can be FIXED $ or PERCENT. */}
        <View style={styles.toggleRow}>
          <Text style={styles.toggleLabel}>Platform Fee Type</Text>
          <View style={styles.toggleGroup}>
            <TouchableOpacity
              style={[styles.toggleBtn, (cfg.core_fees.platform_fee_type || 'fixed') === 'fixed' && styles.toggleBtnActive]}
              onPress={() => patch('core_fees', { ...cfg.core_fees, platform_fee_type: 'fixed' })}
              testID="config-platform-fee-type-fixed"
            >
              <Text style={[styles.toggleBtnText, (cfg.core_fees.platform_fee_type || 'fixed') === 'fixed' && styles.toggleBtnTextActive]}>$ Fixed</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[styles.toggleBtn, cfg.core_fees.platform_fee_type === 'percent' && styles.toggleBtnActive]}
              onPress={() => patch('core_fees', { ...cfg.core_fees, platform_fee_type: 'percent' })}
              testID="config-platform-fee-type-percent"
            >
              <Text style={[styles.toggleBtnText, cfg.core_fees.platform_fee_type === 'percent' && styles.toggleBtnTextActive]}>% Percent</Text>
            </TouchableOpacity>
          </View>
        </View>
        <Field
          label={
            (cfg.core_fees.platform_fee_type || 'fixed') === 'percent'
              ? 'Platform Fee (%)'
              : 'Platform Fee ($)'
          }
          help={
            (cfg.core_fees.platform_fee_type || 'fixed') === 'percent'
              ? 'Percent of Share per Squad (Equal) or Total Bill / N (Itemized). Each member pays their own — not divided.'
              : 'Flat dollars charged per member (each pays full, NOT divided). Default $0.50.'
          }
          value={String(cfg.core_fees.platform_fee_value ?? cfg.core_fees.platform_fee_flat ?? 0.5)}
          keyboardType="decimal-pad"
          onChangeText={(t) =>
            patch('core_fees', {
              ...cfg.core_fees,
              platform_fee_value: parseFloat(t) || 0,
              // Keep legacy field mirrored for old consumers when fixed.
              platform_fee_flat: (cfg.core_fees.platform_fee_type || 'fixed') === 'fixed' ? (parseFloat(t) || 0) : (cfg.core_fees.platform_fee_flat || 0),
            })
          }
          prefix={(cfg.core_fees.platform_fee_type || 'fixed') === 'fixed' ? '$' : undefined}
          suffix={(cfg.core_fees.platform_fee_type || 'fixed') === 'percent' ? '%' : undefined}
          testID="config-platform-fee"
        />
        {/* June 2025 — Optional cap (max $) per member. */}
        <Field
          label="Platform Fee Cap ($)"
          help="Optional maximum $ per member (mostly useful when type=Percent). 0 = no cap."
          value={String(cfg.core_fees.platform_fee_cap ?? 0)}
          keyboardType="decimal-pad"
          onChangeText={(t) =>
            patch('core_fees', { ...cfg.core_fees, platform_fee_cap: parseFloat(t) || 0 })
          }
          prefix="$"
          testID="config-platform-fee-cap"
        />

        {/* June 2025 — Insurance: always percent, layered on top of
            (Share + Platform + Extras), before Transaction Fee. */}
        <Field
          label="Insurance — Display Label"
          help="Shown as the row name in every Bill Breakdown card."
          value={cfg.core_fees.insurance_label || 'Insurance'}
          onChangeText={(t) =>
            patch('core_fees', { ...cfg.core_fees, insurance_label: t.slice(0, 40) })
          }
          testID="config-insurance-label"
        />
        {/* June 2025 — Enable/disable toggle for Insurance. */}
        <View style={styles.switchRow}>
          <Text style={styles.switchLabel}>Insurance Enabled</Text>
          <Switch
            value={cfg.core_fees.insurance_enabled !== false}
            onValueChange={(v) => patch('core_fees', { ...cfg.core_fees, insurance_enabled: v })}
            testID="config-insurance-enabled"
          />
        </View>
        <Field
          label="Insurance (%)"
          help="Always percent — applied to (Share + Platform + Extras). Default 1.0%. Each member pays their own."
          value={String(cfg.core_fees.insurance_pct ?? 1.0)}
          keyboardType="decimal-pad"
          onChangeText={(t) =>
            patch('core_fees', { ...cfg.core_fees, insurance_pct: parseFloat(t) || 0 })
          }
          suffix="%"
          testID="config-insurance-pct"
        />
        {/* June 2025 — Insurance cap (max $) per member. */}
        <Field
          label="Insurance Cap ($)"
          help="Optional maximum $ per member. 0 = no cap."
          value={String(cfg.core_fees.insurance_cap ?? 0)}
          keyboardType="decimal-pad"
          onChangeText={(t) =>
            patch('core_fees', { ...cfg.core_fees, insurance_cap: parseFloat(t) || 0 })
          }
          prefix="$"
          testID="config-insurance-cap"
        />
      </Section>

      {/* ═══════════════════════════════════ Extra Fees ═══════════════════════════════════ */}
      <Section icon={<Tag size={18} color={COLORS.primary} />} title="Extra Fees (up to 2)">
        {cfg.extra_fees.map((fee) => (
          <View key={fee.id} style={styles.feeCard}>
            <View style={styles.feeHeader}>
              <TextInput
                value={fee.name}
                onChangeText={(t) => updateExtraFee(fee.id, { name: t })}
                style={styles.feeName}
                placeholder="Fee name"
                placeholderTextColor={COLORS.subtext}
              />
              <Switch
                value={fee.enabled}
                onValueChange={(v) => updateExtraFee(fee.id, { enabled: v })}
              />
            </View>
            <View style={styles.feeBody}>
              <View style={styles.typeRow}>
                {(['percent', 'flat'] as const).map((t) => (
                  <TouchableOpacity
                    key={t}
                    onPress={() => updateExtraFee(fee.id, { type: t })}
                    style={[styles.typeBtn, fee.type === t && styles.typeBtnActive]}
                  >
                    {t === 'percent' ? (
                      <Percent size={14} color={fee.type === t ? '#fff' : COLORS.subtext} />
                    ) : (
                      <DollarSign size={14} color={fee.type === t ? '#fff' : COLORS.subtext} />
                    )}
                    <Text style={[styles.typeText, fee.type === t && { color: '#fff' }]}>
                      {t === 'percent' ? 'Percent' : 'Flat'}
                    </Text>
                  </TouchableOpacity>
                ))}
              </View>
              <TextInput
                value={String(fee.value)}
                onChangeText={(t) => updateExtraFee(fee.id, { value: parseFloat(t) || 0 })}
                style={styles.feeValue}
                keyboardType="decimal-pad"
                placeholder="0"
                placeholderTextColor={COLORS.subtext}
              />
              {/* June 2025 — Optional per-extra cap (max $ per member). */}
              <View style={styles.extraCapRow}>
                <Text style={styles.extraCapLabel}>Cap ($)</Text>
                <TextInput
                  value={String((fee as any).cap ?? 0)}
                  onChangeText={(t) => updateExtraFee(fee.id, { cap: parseFloat(t) || 0 } as any)}
                  style={styles.extraCapInput}
                  keyboardType="decimal-pad"
                  placeholder="0 = no cap"
                  placeholderTextColor={COLORS.subtext}
                  testID={`config-extra-${fee.id}-cap`}
                />
              </View>
            </View>
          </View>
        ))}
      </Section>

      {/* ═══════════════════════════════════ Wallet ═══════════════════════════════════
          REMOVED — Apple/Google Pay enrollment toggles already exist on the
          /admin/integrations page (Phase G4). We deliberately do NOT duplicate
          them here. The backend wallet_routes.py reads the enrollment flags
          from the issuing-settings doc (managed by /admin/integrations). */}

      {/* ═══════════════════════════════════ Limits ═══════════════════════════════════ */}
      <Section icon={<Shield size={18} color={COLORS.primary} />} title="Limits & Guardrails">
        <Field
          label="Min members per bill"
          value={String(cfg.limits.min_members_per_bill)}
          keyboardType="number-pad"
          onChangeText={(t) =>
            patch('limits', { ...cfg.limits, min_members_per_bill: parseInt(t) || 2 })
          }
        />
        <Field
          label="Min bill amount ($)"
          value={String(cfg.limits.min_bill_amount)}
          keyboardType="decimal-pad"
          onChangeText={(t) =>
            patch('limits', { ...cfg.limits, min_bill_amount: parseFloat(t) || 0 })
          }
          prefix="$"
        />
        <Field
          label="Max bill amount ($)"
          value={String(cfg.limits.max_bill_amount)}
          keyboardType="decimal-pad"
          onChangeText={(t) =>
            patch('limits', { ...cfg.limits, max_bill_amount: parseFloat(t) || 0 })
          }
          prefix="$"
        />
        <Field
          label="Max items per bill"
          value={String(cfg.limits.max_items_per_bill)}
          keyboardType="number-pad"
          onChangeText={(t) =>
            patch('limits', { ...cfg.limits, max_items_per_bill: parseInt(t) || 200 })
          }
        />
      </Section>

      {/* ═══════════════════════════════════ OTP ═══════════════════════════════════ */}
      <Section icon={<Smartphone size={18} color={COLORS.primary} />} title="OTP / Phone Auth">
        <Field
          label="Code length"
          value={String(cfg.otp.code_length)}
          keyboardType="number-pad"
          onChangeText={(t) =>
            patch('otp', { ...cfg.otp, code_length: parseInt(t) || 6 })
          }
        />
        <Field
          label="Expiry (seconds)"
          value={String(cfg.otp.expiry_seconds)}
          keyboardType="number-pad"
          onChangeText={(t) =>
            patch('otp', { ...cfg.otp, expiry_seconds: parseInt(t) || 300 })
          }
          suffix="s"
        />
        <Field
          label="Max attempts / hour"
          value={String(cfg.otp.max_attempts_per_hour)}
          keyboardType="number-pad"
          onChangeText={(t) =>
            patch('otp', { ...cfg.otp, max_attempts_per_hour: parseInt(t) || 5 })
          }
        />
      </Section>

      {/* ═══════════════════════════════════ Card ═══════════════════════════════════ */}
      <Section icon={<CreditCard size={18} color={COLORS.primary} />} title="Virtual Card">
        <Field
          label="Spend cap buffer (%)"
          help="Adds this % headroom to the card's spend limit so a small tax adjustment at POS doesn't decline."
          value={String(cfg.card.spend_cap_buffer_pct)}
          keyboardType="decimal-pad"
          onChangeText={(t) =>
            patch('card', { ...cfg.card, spend_cap_buffer_pct: parseFloat(t) || 0 })
          }
          suffix="%"
        />
        <Field
          label="Auto-disable card after (hours)"
          value={String(cfg.card.auto_disable_hours)}
          keyboardType="number-pad"
          onChangeText={(t) =>
            patch('card', { ...cfg.card, auto_disable_hours: parseInt(t) || 24 })
          }
          suffix="h"
        />
      </Section>

      {/* ═══════════════════════════════════ Reminders ═══════════════════════════════════ */}
      <Section icon={<Bell size={18} color={COLORS.primary} />} title="Reminders">
        <Field
          label="Cadence (hours)"
          help="How often we nudge un-paid members."
          value={String(cfg.reminders.cadence_hours)}
          keyboardType="number-pad"
          onChangeText={(t) =>
            patch('reminders', { ...cfg.reminders, cadence_hours: parseInt(t) || 24 })
          }
          suffix="h"
        />
        <Field
          label="Bill expiry (hours)"
          help="Bills inactive for this long are auto-closed."
          value={String(cfg.reminders.bill_expiry_hours)}
          keyboardType="number-pad"
          onChangeText={(t) =>
            patch('reminders', { ...cfg.reminders, bill_expiry_hours: parseInt(t) || 168 })
          }
          suffix="h"
        />
      </Section>

      {/* ═══════════════════════════════════ OCR ═══════════════════════════════════ */}
      <Section icon={<Scan size={18} color={COLORS.primary} />} title="Receipt OCR">
        <View style={{ gap: 8 }}>
          <Text style={styles.fieldLabel}>Provider</Text>
          <View style={styles.typeRow}>
            {(['openai', 'anthropic', 'gemini'] as const).map((p) => (
              <TouchableOpacity
                key={p}
                onPress={() => patch('ocr', { ...cfg.ocr, provider: p })}
                style={[styles.typeBtn, cfg.ocr.provider === p && styles.typeBtnActive]}
              >
                <Text style={[styles.typeText, cfg.ocr.provider === p && { color: '#fff' }]}>
                  {p}
                </Text>
              </TouchableOpacity>
            ))}
          </View>
        </View>
        <Field
          label="Model"
          help="e.g. gpt-4o, claude-sonnet-4.5, gemini-2.5-pro"
          value={cfg.ocr.model}
          onChangeText={(t) => patch('ocr', { ...cfg.ocr, model: t })}
        />
      </Section>

      {/* ═══════════════════════════════════ Brand ═══════════════════════════════════ */}
      <Section icon={<Tag size={18} color={COLORS.primary} />} title="Brand & Defaults">
        <Field
          label="SMS sender ID"
          help="Shown as the SMS 'from'. Max 11 chars."
          value={cfg.brand.sms_sender_id}
          onChangeText={(t) => patch('brand', { ...cfg.brand, sms_sender_id: t.slice(0, 11) })}
        />
        <Field
          label="Support email"
          value={cfg.brand.support_email}
          autoCapitalize="none"
          keyboardType="email-address"
          onChangeText={(t) => patch('brand', { ...cfg.brand, support_email: t })}
        />
        <Field
          label="Default tip suggestions (comma-separated %)"
          value={cfg.brand.default_tip_suggestions.join(', ')}
          onChangeText={(t) =>
            patch('brand', {
              ...cfg.brand,
              default_tip_suggestions: t
                .split(',')
                .map((s) => parseFloat(s.trim()))
                .filter((n) => !isNaN(n)),
            })
          }
        />
      </Section>

      {/* ═══════════════════════════════════ Ops ═══════════════════════════════════ */}
      <Section icon={<AlertTriangle size={18} color={COLORS.danger} />} title="Operations">
        <Toggle
          label="Maintenance mode (pauses new bills)"
          value={cfg.ops.maintenance_mode}
          onChange={(v) => patch('ops', { ...cfg.ops, maintenance_mode: v })}
        />
        <Field
          label="Maintenance message"
          value={cfg.ops.maintenance_message}
          onChangeText={(t) => patch('ops', { ...cfg.ops, maintenance_message: t })}
          multiline
        />
      </Section>

      <TouchableOpacity
        onPress={save}
        disabled={saving}
        style={[styles.saveBtnLarge, saving && { opacity: 0.5 }]}
      >
        <Save size={18} color="#fff" />
        <Text style={styles.saveTextLarge}>{saving ? 'Saving…' : 'Save All Changes'}</Text>
      </TouchableOpacity>
    </ScrollView>
  );
}

// ──────────────────────────────────────────────────────────────────────────
// Small helpers
// ──────────────────────────────────────────────────────────────────────────

function Section({
  icon,
  title,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <View style={styles.section}>
      <View style={styles.sectionHeader}>
        {icon}
        <Text style={styles.sectionTitle}>{title}</Text>
      </View>
      <View style={{ gap: SPACING.md }}>{children}</View>
    </View>
  );
}

function Field({
  label,
  help,
  value,
  onChangeText,
  keyboardType,
  prefix,
  suffix,
  autoCapitalize,
  multiline,
  testID,
}: {
  label: string;
  help?: string;
  value: string;
  onChangeText: (t: string) => void;
  keyboardType?: any;
  prefix?: string;
  suffix?: string;
  autoCapitalize?: 'none' | 'words' | 'sentences' | 'characters';
  multiline?: boolean;
  testID?: string;
}) {
  return (
    <View style={{ gap: 4 }}>
      <Text style={styles.fieldLabel}>{label}</Text>
      <View style={styles.fieldRow}>
        {prefix ? <Text style={styles.fieldAffix}>{prefix}</Text> : null}
        <TextInput
          value={value}
          onChangeText={onChangeText}
          keyboardType={keyboardType}
          autoCapitalize={autoCapitalize}
          multiline={multiline}
          style={[styles.fieldInput, multiline && { minHeight: 60 }]}
          placeholderTextColor={COLORS.subtext}
          testID={testID}
        />
        {suffix ? <Text style={styles.fieldAffix}>{suffix}</Text> : null}
      </View>
      {help ? <Text style={styles.fieldHelp}>{help}</Text> : null}
    </View>
  );
}

function Toggle({
  label,
  value,
  onChange,
  disabled,
  testID,
}: {
  label: string;
  value: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
  testID?: string;
}) {
  return (
    <View style={[styles.toggleRow, disabled && { opacity: 0.45 }]}>
      <Text style={styles.toggleLabel}>{label}</Text>
      <Switch value={value} onValueChange={onChange} disabled={disabled} testID={testID} />
    </View>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: COLORS.bg },
  headerRow: { flexDirection: 'row', alignItems: 'center', gap: SPACING.md, marginBottom: SPACING.sm },
  heading: { flex: 1, fontSize: FONT.sizes.lg, fontWeight: FONT.weights.heavy, color: COLORS.text },
  helpText: { color: COLORS.subtext, fontSize: FONT.sizes.xs, marginBottom: SPACING.md, lineHeight: 18 },
  saveBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    backgroundColor: COLORS.primary,
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: RADIUS.md,
  },
  saveText: { color: '#fff', fontWeight: FONT.weights.bold, fontSize: FONT.sizes.sm },
  saveBtnLarge: {
    marginTop: SPACING.lg,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    backgroundColor: COLORS.primary,
    paddingVertical: 14,
    borderRadius: RADIUS.lg,
  },
  saveTextLarge: { color: '#fff', fontWeight: FONT.weights.bold, fontSize: FONT.sizes.md },
  section: {
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.lg,
    padding: SPACING.md,
    marginBottom: SPACING.md,
    borderWidth: 1,
    borderColor: COLORS.border,
  },
  sectionHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginBottom: SPACING.md,
  },
  sectionTitle: { fontSize: FONT.sizes.md, fontWeight: FONT.weights.bold, color: COLORS.text },
  sectionHelp: { color: COLORS.subtext, fontSize: FONT.sizes.xs, marginBottom: SPACING.sm, lineHeight: 16 },
  fieldLabel: { color: COLORS.subtext, fontSize: FONT.sizes.xs, fontWeight: FONT.weights.semibold, textTransform: 'uppercase', letterSpacing: 0.5 },
  fieldRow: { flexDirection: 'row', alignItems: 'center', borderWidth: 1, borderColor: COLORS.border, borderRadius: RADIUS.md, paddingHorizontal: 10, backgroundColor: COLORS.bg },
  fieldInput: { flex: 1, paddingVertical: 10, color: COLORS.text, fontSize: FONT.sizes.sm },
  fieldAffix: { color: COLORS.subtext, fontSize: FONT.sizes.sm, fontWeight: FONT.weights.semibold, paddingHorizontal: 4 },
  fieldHelp: { color: COLORS.subtext, fontSize: 11, lineHeight: 14 },
  toggleRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  toggleLabel: { color: COLORS.text, fontSize: FONT.sizes.sm, flex: 1, paddingRight: SPACING.md },
  feeCard: { borderWidth: 1, borderColor: COLORS.border, borderRadius: RADIUS.md, padding: SPACING.sm, gap: SPACING.sm },
  // June 2025 — Platform Fee type toggle ($ Fixed vs % Percent)
  toggleRow: { gap: SPACING.xs, marginBottom: SPACING.sm },
  toggleLabel: { fontSize: FONT.sizes.sm, fontWeight: FONT.weights.semibold, color: COLORS.text },
  toggleGroup: { flexDirection: 'row', gap: SPACING.xs, marginTop: SPACING.xs },
  toggleBtn: { flex: 1, paddingVertical: SPACING.sm, paddingHorizontal: SPACING.md, borderRadius: RADIUS.md, borderWidth: 1, borderColor: COLORS.border, alignItems: 'center', backgroundColor: COLORS.surface },
  toggleBtnActive: { backgroundColor: COLORS.primary, borderColor: COLORS.primary },
  toggleBtnText: { fontSize: FONT.sizes.sm, fontWeight: FONT.weights.semibold, color: COLORS.text },
  toggleBtnTextActive: { color: '#fff' },
  // June 2025 — Enable/disable Switch row used for each fee toggle.
  switchRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: SPACING.sm,
    borderTopWidth: 1,
    borderTopColor: COLORS.border,
  },
  switchLabel: { fontSize: FONT.sizes.sm, fontWeight: FONT.weights.semibold, color: COLORS.text },
  // June 2025 — Inline cap input row inside each Extra Fee card.
  extraCapRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: SPACING.sm,
    marginTop: SPACING.xs,
  },
  extraCapLabel: { fontSize: FONT.sizes.xs, color: COLORS.subtext, fontWeight: FONT.weights.semibold },
  extraCapInput: {
    flex: 1,
    fontSize: FONT.sizes.sm,
    color: COLORS.text,
    paddingVertical: SPACING.xs,
    paddingHorizontal: SPACING.sm,
    borderRadius: RADIUS.sm,
    borderWidth: 1,
    borderColor: COLORS.border,
    backgroundColor: COLORS.bg,
  },
  feeHeader: { flexDirection: 'row', alignItems: 'center', gap: SPACING.sm },
  feeName: { flex: 1, fontWeight: FONT.weights.bold, color: COLORS.text, paddingVertical: 6, fontSize: FONT.sizes.sm },
  feeBody: { flexDirection: 'row', alignItems: 'center', gap: SPACING.sm },
  typeRow: { flexDirection: 'row', gap: 6 },
  typeBtn: { flexDirection: 'row', alignItems: 'center', gap: 4, borderWidth: 1, borderColor: COLORS.border, paddingHorizontal: 10, paddingVertical: 6, borderRadius: 999 },
  typeBtnActive: { backgroundColor: COLORS.primary, borderColor: COLORS.primary },
  typeText: { fontSize: FONT.sizes.xs, color: COLORS.subtext, fontWeight: FONT.weights.semibold, textTransform: 'capitalize' },
  feeValue: { flex: 1, borderWidth: 1, borderColor: COLORS.border, borderRadius: RADIUS.md, paddingHorizontal: 10, paddingVertical: 8, color: COLORS.text, backgroundColor: COLORS.bg, textAlign: 'right' },
});

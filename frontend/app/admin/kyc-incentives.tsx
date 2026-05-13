/**
 * Admin · KYC Incentive Config (June 2025).
 *
 * Two-tab config page for Stripe Connect onboarding rewards:
 *   • Lead   — default $10, larger upsell messages
 *   • Member — default $5, member-tailored messages for covering members
 *
 * Reward modes:
 *   • credit_off_next_bill         — dollar-credit applied to next squad
 *   • waive_platform_fees_next_bill — waive SquadPay platform fees on next squad
 *
 * Rewards are queued in users.pending_rewards and consumed by core.py
 * when the next bill computes — never stored as a balance.
 */
import { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { ShieldCheck, AlertCircle, CheckCircle2, Crown, Users } from 'lucide-react-native';
import { kycIncentiveApi, type KycIncentiveConfig } from '../../src/adminApi';
import { COLORS, FONT, RADIUS, SPACING } from '../../src/theme';

type Role = 'lead' | 'member';

export default function AdminKycIncentivesScreen() {
  const [role, setRole] = useState<Role>('lead');
  const [leadCfg, setLeadCfg] = useState<KycIncentiveConfig | null>(null);
  const [memberCfg, setMemberCfg] = useState<KycIncentiveConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [l, m] = await Promise.all([kycIncentiveApi.getLead(), kycIncentiveApi.getMember()]);
      setLeadCfg(l);
      setMemberCfg(m);
    } catch (e: any) {
      setError(e?.message || 'Failed to load KYC incentive configs');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const cfg = role === 'lead' ? leadCfg : memberCfg;
  const setCfg = (next: KycIncentiveConfig) => {
    if (role === 'lead') setLeadCfg(next);
    else setMemberCfg(next);
  };

  const updateField = <K extends keyof KycIncentiveConfig>(k: K, v: KycIncentiveConfig[K]) => {
    if (!cfg) return;
    setCfg({ ...cfg, [k]: v });
  };

  const save = async () => {
    if (!cfg) return;
    setSaving(true);
    setError(null);
    setSavedAt(null);
    try {
      const body = {
        enabled: cfg.enabled,
        reward_mode: cfg.reward_mode,
        credit_amount: Number(cfg.credit_amount) || 0,
        messages: cfg.messages.filter((m) => m.trim()),
      };
      const next = role === 'lead'
        ? await kycIncentiveApi.setLead(body)
        : await kycIncentiveApi.setMember(body);
      setCfg(next);
      setSavedAt(new Date().toLocaleTimeString());
    } catch (e: any) {
      setError(e?.message || 'Failed to save');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <SafeAreaView style={s.safe}>
        <View style={s.center}>
          <ActivityIndicator color={COLORS.primary} />
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={s.safe} edges={['top']}>
      <ScrollView contentContainerStyle={s.scroll}>
        <View style={s.header}>
          <ShieldCheck size={24} color={COLORS.primary} />
          <Text style={s.h1}>KYC Incentive</Text>
        </View>
        <Text style={s.sub}>
          One-shot reward queued when a user completes Stripe Connect onboarding for
          the first time. Applied to their next squad as a credit/fee-waiver —
          never stored as a balance.
        </Text>

        {/* Role tabs */}
        <View style={s.tabRow}>
          <TouchableOpacity
            style={[s.tab, role === 'lead' && s.tabActive]}
            onPress={() => setRole('lead')}
          >
            <Crown size={14} color={role === 'lead' ? '#fff' : COLORS.text} />
            <Text style={[s.tabText, role === 'lead' && s.tabTextActive]}>Lead ($10 default)</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[s.tab, role === 'member' && s.tabActive]}
            onPress={() => setRole('member')}
          >
            <Users size={14} color={role === 'member' ? '#fff' : COLORS.text} />
            <Text style={[s.tabText, role === 'member' && s.tabTextActive]}>Member ($5 default)</Text>
          </TouchableOpacity>
        </View>

        {error ? (
          <View style={s.error}>
            <AlertCircle size={16} color={COLORS.danger} />
            <Text style={s.errorText}>{error}</Text>
          </View>
        ) : null}
        {savedAt ? (
          <View style={s.success}>
            <CheckCircle2 size={16} color={COLORS.success} />
            <Text style={s.successText}>Saved {role} config at {savedAt}</Text>
          </View>
        ) : null}

        {cfg && (
          <>
            {/* Enabled toggle */}
            <View style={s.row}>
              <Text style={s.rowLabel}>{role === 'lead' ? 'Lead' : 'Member'} KYC incentive enabled</Text>
              <TouchableOpacity
                style={[s.toggle, cfg.enabled && s.toggleOn]}
                onPress={() => updateField('enabled', !cfg.enabled)}
              >
                <View style={[s.knob, cfg.enabled && s.knobOn]} />
              </TouchableOpacity>
            </View>

            {/* Reward mode */}
            <View style={s.card}>
              <Text style={s.cardTitle}>Reward Mode</Text>
              <TouchableOpacity
                style={[s.modePill, cfg.reward_mode === 'credit_off_next_bill' && s.modePillActive]}
                onPress={() => updateField('reward_mode', 'credit_off_next_bill')}
              >
                <Text style={[s.modePillText, cfg.reward_mode === 'credit_off_next_bill' && s.modePillTextActive]}>
                  💵 Credit Off Next Bill
                </Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[s.modePill, cfg.reward_mode === 'waive_platform_fees_next_bill' && s.modePillActive]}
                onPress={() => updateField('reward_mode', 'waive_platform_fees_next_bill')}
              >
                <Text style={[s.modePillText, cfg.reward_mode === 'waive_platform_fees_next_bill' && s.modePillTextActive]}>
                  🪙 Waive Platform Fees on Next Bill
                </Text>
              </TouchableOpacity>
            </View>

            {/* Credit amount (only for credit mode) */}
            {cfg.reward_mode === 'credit_off_next_bill' && (
              <View style={s.card}>
                <Text style={s.cardTitle}>Credit Amount (USD)</Text>
                <View style={s.amountRow}>
                  <Text style={s.amountPrefix}>$</Text>
                  <TextInput
                    style={s.amountInput}
                    keyboardType="decimal-pad"
                    value={String(cfg.credit_amount)}
                    onChangeText={(v) =>
                      updateField('credit_amount', parseFloat(v.replace(/[^0-9.]/g, '')) || 0)
                    }
                  />
                </View>
              </View>
            )}

            {/* Messages */}
            <View style={s.card}>
              <Text style={s.cardTitle}>Upsell Messages (rotated randomly)</Text>
              <Text style={s.sub}>
                One shown to the user before Stripe redirect. Max 10 entries, 200 chars each.
              </Text>
              {cfg.messages.map((msg, i) => (
                <View key={i} style={s.msgRow}>
                  <TextInput
                    style={s.msgInput}
                    value={msg}
                    onChangeText={(v) => {
                      const next = [...cfg.messages];
                      next[i] = v.slice(0, 200);
                      updateField('messages', next);
                    }}
                    placeholder="Message text…"
                    placeholderTextColor={COLORS.muted}
                    multiline
                  />
                  <TouchableOpacity
                    onPress={() => {
                      const next = cfg.messages.filter((_, idx) => idx !== i);
                      updateField('messages', next);
                    }}
                  >
                    <Text style={s.removeText}>Remove</Text>
                  </TouchableOpacity>
                </View>
              ))}
              {cfg.messages.length < 10 && (
                <TouchableOpacity
                  style={s.addMsgBtn}
                  onPress={() => updateField('messages', [...cfg.messages, ''])}
                >
                  <Text style={s.addMsgText}>+ Add message</Text>
                </TouchableOpacity>
              )}
            </View>

            <TouchableOpacity
              style={[s.saveBtn, saving && { opacity: 0.5 }]}
              disabled={saving}
              onPress={save}
            >
              {saving ? (
                <ActivityIndicator color="#fff" />
              ) : (
                <Text style={s.saveText}>
                  Save {role === 'lead' ? 'Lead' : 'Member'} Config
                </Text>
              )}
            </TouchableOpacity>
          </>
        )}

        <View style={{ height: 60 }} />
      </ScrollView>
    </SafeAreaView>
  );
}

const s = StyleSheet.create({
  safe: { flex: 1, backgroundColor: COLORS.bg },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  scroll: { padding: SPACING.lg, gap: SPACING.md },
  header: { flexDirection: 'row', alignItems: 'center', gap: SPACING.sm },
  h1: { fontSize: FONT.sizes.xl, fontWeight: '700', color: COLORS.text },
  sub: { fontSize: FONT.sizes.sm, color: COLORS.muted, lineHeight: 18 },
  tabRow: { flexDirection: 'row', gap: SPACING.sm },
  tab: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: SPACING.xs,
    paddingVertical: SPACING.sm,
    paddingHorizontal: SPACING.md,
    borderRadius: RADIUS.md,
    backgroundColor: COLORS.surface,
    borderWidth: 1,
    borderColor: COLORS.border,
  },
  tabActive: { backgroundColor: COLORS.primary, borderColor: COLORS.primary },
  tabText: { fontSize: FONT.sizes.sm, fontWeight: '600', color: COLORS.text },
  tabTextActive: { color: '#fff' },
  error: {
    flexDirection: 'row', alignItems: 'center', gap: SPACING.xs,
    padding: SPACING.sm, backgroundColor: COLORS.dangerLight, borderRadius: RADIUS.md,
  },
  errorText: { color: COLORS.danger, fontSize: FONT.sizes.sm },
  success: {
    flexDirection: 'row', alignItems: 'center', gap: SPACING.xs,
    padding: SPACING.sm, backgroundColor: COLORS.successLight, borderRadius: RADIUS.md,
  },
  successText: { color: COLORS.success, fontSize: FONT.sizes.sm },
  row: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    padding: SPACING.md, backgroundColor: COLORS.surface, borderRadius: RADIUS.md,
  },
  rowLabel: { flex: 1, color: COLORS.text, fontSize: FONT.sizes.md, fontWeight: '600' },
  toggle: {
    width: 44, height: 24, borderRadius: 12,
    backgroundColor: COLORS.border, padding: 2, justifyContent: 'center',
  },
  toggleOn: { backgroundColor: COLORS.primary },
  knob: { width: 20, height: 20, borderRadius: 10, backgroundColor: '#fff' },
  knobOn: { alignSelf: 'flex-end' },
  card: {
    padding: SPACING.md, backgroundColor: COLORS.surface, borderRadius: RADIUS.md,
    gap: SPACING.sm,
  },
  cardTitle: { fontSize: FONT.sizes.md, fontWeight: '700', color: COLORS.text },
  modePill: {
    paddingVertical: SPACING.sm, paddingHorizontal: SPACING.md,
    borderRadius: RADIUS.sm, backgroundColor: COLORS.bg,
    borderWidth: 1, borderColor: COLORS.border,
  },
  modePillActive: { backgroundColor: COLORS.primary, borderColor: COLORS.primary },
  modePillText: { fontSize: FONT.sizes.sm, color: COLORS.text, fontWeight: '600' },
  modePillTextActive: { color: '#fff' },
  amountRow: { flexDirection: 'row', alignItems: 'center', gap: SPACING.xs },
  amountPrefix: { fontSize: FONT.sizes.lg, color: COLORS.text, fontWeight: '700' },
  amountInput: {
    flex: 1, paddingHorizontal: SPACING.sm, paddingVertical: SPACING.sm,
    backgroundColor: COLORS.bg, borderRadius: RADIUS.sm,
    borderWidth: 1, borderColor: COLORS.border,
    fontSize: FONT.sizes.lg, color: COLORS.text, fontWeight: '700',
  },
  msgRow: { gap: SPACING.xs, paddingTop: SPACING.sm, borderTopWidth: 1, borderTopColor: COLORS.border },
  msgInput: {
    paddingHorizontal: SPACING.sm, paddingVertical: SPACING.sm,
    backgroundColor: COLORS.bg, borderRadius: RADIUS.sm,
    borderWidth: 1, borderColor: COLORS.border,
    fontSize: FONT.sizes.sm, color: COLORS.text, minHeight: 60,
  },
  removeText: { color: COLORS.danger, fontSize: FONT.sizes.xs, alignSelf: 'flex-end' },
  addMsgBtn: { paddingVertical: SPACING.sm, alignItems: 'center', backgroundColor: COLORS.bg, borderRadius: RADIUS.sm },
  addMsgText: { color: COLORS.primary, fontWeight: '600', fontSize: FONT.sizes.sm },
  saveBtn: {
    backgroundColor: COLORS.primary, paddingVertical: SPACING.md,
    borderRadius: RADIUS.md, alignItems: 'center', marginTop: SPACING.sm,
  },
  saveText: { color: '#fff', fontSize: FONT.sizes.md, fontWeight: '700' },
});

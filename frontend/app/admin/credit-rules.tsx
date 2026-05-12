/**
 * Admin Credit Rules manager (June 2025).
 *
 * Compact CRUD: list rules + create/edit them via an inline form. Rules
 * are evaluated server-side at contribute time and award credits that
 * follow the lifecycle described in /legal/terms#credits.
 */
import { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Platform,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  TextInput,
  TouchableOpacity,
  View,
  Modal,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  Plus,
  Coins,
  Calendar,
  Tag,
  Trash2,
  Pencil,
  AlertCircle,
  CheckCircle2,
} from 'lucide-react-native';
import { adminApi } from '../../src/adminApi';
import { COLORS, FONT, RADIUS, SPACING } from '../../src/theme';

type CriteriaType =
  | 'first_time'
  | 'nth_contribution'
  | 'date'
  | 'nth_of_period'
  | 'specific_names'
  | 'specific_users'
  | 'specific_groups';

type RewardType = 'fixed' | 'pct_user_no_fees' | 'pct_group_no_fees';

const CRITERIA_OPTIONS: { value: CriteriaType; label: string }[] = [
  { value: 'first_time', label: 'First-time user' },
  { value: 'nth_contribution', label: 'Nth contribution by user' },
  { value: 'date', label: 'Specific date / range' },
  { value: 'nth_of_period', label: 'Nth user of day / month' },
  { value: 'specific_names', label: 'Specific user names' },
  { value: 'specific_users', label: 'Specific user IDs' },
  { value: 'specific_groups', label: 'Specific Squad IDs' },
];

const REWARD_OPTIONS: { value: RewardType; label: string }[] = [
  { value: 'fixed', label: 'Fixed $' },
  { value: 'pct_user_no_fees', label: '% of user contribution (no fees)' },
  { value: 'pct_group_no_fees', label: '% of Squad total (no fees)' },
];

export default function AdminCreditRulesScreen() {
  const [rules, setRules] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [editorVisible, setEditorVisible] = useState(false);
  const [editing, setEditing] = useState<any | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await adminApi.listCreditRules();
      setRules(r.items || []);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const openCreate = () => { setEditing(null); setEditorVisible(true); };
  const openEdit = (r: any) => { setEditing(r); setEditorVisible(true); };

  const toggleActive = async (r: any) => {
    try {
      await adminApi.patchCreditRule(r.id, { active: !r.active });
      await load();
    } catch {}
  };
  const remove = async (r: any) => {
    if (Platform.OS === 'web') {
      if (!confirm(`Delete "${r.name}"? This cannot be undone.`)) return;
    }
    try { await adminApi.deleteCreditRule(r.id); await load(); } catch {}
  };

  const criteriaSummary = (c: any): string => {
    if (!c) return '';
    switch (c.type) {
      case 'first_time': return 'First-time user';
      case 'nth_contribution': return `Contribution #${c.n}`;
      case 'date': return `Date ${c.date_from}${c.date_to ? ' → ' + c.date_to : ''}`;
      case 'nth_of_period': return `Nth = ${c.n} per ${c.period}`;
      case 'specific_names': return `Names: ${(c.names || []).join(', ')}`;
      case 'specific_users': return `User IDs: ${(c.user_ids || []).length}`;
      case 'specific_groups': return `Squad IDs: ${(c.group_ids || []).length}`;
      default: return c.type;
    }
  };
  const rewardSummary = (r: any): string => {
    if (!r) return '';
    if (r.type === 'fixed') return `$${Number(r.value).toFixed(2)}` + (r.cap ? ` (cap $${r.cap})` : '');
    return `${r.value}% ` + (r.type === 'pct_user_no_fees' ? 'of user' : 'of Squad') + (r.cap ? ` (cap $${r.cap})` : '');
  };

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: COLORS.bg }} edges={['bottom']}>
      <ScrollView contentContainerStyle={{ padding: SPACING.lg, gap: SPACING.md }}>
        <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }}>
          <Text style={styles.h1}>Credit Rules</Text>
          <TouchableOpacity style={styles.newBtn} onPress={openCreate} activeOpacity={0.85} testID="credit-rules-new">
            <Plus size={16} color="#fff" />
            <Text style={styles.newBtnText}>New rule</Text>
          </TouchableOpacity>
        </View>
        <Text style={styles.subtle}>
          Define when users earn credit and how much. Active rules are
          evaluated at every contribution. Pending credits unlock when
          the source Squad is settled.
        </Text>

        {loading ? (
          <ActivityIndicator color={COLORS.primary} />
        ) : rules.length === 0 ? (
          <View style={styles.empty}>
            <Coins size={42} color={COLORS.border} />
            <Text style={styles.emptyTitle}>No credit rules yet</Text>
            <Text style={styles.emptySub}>Tap “New rule” to set up your first promotion.</Text>
          </View>
        ) : (
          rules.map((r) => (
            <View key={r.id} style={styles.row} testID={`credit-rule-${r.id}`}>
              <View style={{ flex: 1, gap: 4 }}>
                <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
                  <Text style={styles.rowName}>{r.name}</Text>
                  {!r.active ? (
                    <View style={styles.pauseBadge}><Text style={styles.pauseBadgeText}>Paused</Text></View>
                  ) : null}
                </View>
                <Text style={styles.rowMeta}>{criteriaSummary(r.criteria)} · {rewardSummary(r.reward)}</Text>
                <Text style={styles.rowMeta}>“{r.message}”</Text>
                <Text style={styles.rowStats}>matches {r.match_count || 0} · paid ${(r.total_paid_out || 0).toFixed(2)}</Text>
              </View>
              <View style={{ gap: 6 }}>
                <Switch value={r.active} onValueChange={() => toggleActive(r)} testID={`credit-rule-toggle-${r.id}`} />
                <TouchableOpacity onPress={() => openEdit(r)} style={styles.iconBtn} activeOpacity={0.85}>
                  <Pencil size={14} color={COLORS.primary} />
                </TouchableOpacity>
                <TouchableOpacity onPress={() => remove(r)} style={styles.iconBtn} activeOpacity={0.85}>
                  <Trash2 size={14} color={COLORS.danger} />
                </TouchableOpacity>
              </View>
            </View>
          ))
        )}
      </ScrollView>

      <RuleEditorModal
        visible={editorVisible}
        initial={editing}
        existingRules={rules}
        onClose={() => setEditorVisible(false)}
        onSaved={async () => { setEditorVisible(false); await load(); }}
      />
    </SafeAreaView>
  );
}

function RuleEditorModal({ visible, initial, existingRules, onClose, onSaved }: any) {
  const [name, setName] = useState('');
  const [message, setMessage] = useState('');
  const [active, setActive] = useState(true);
  const [cType, setCType] = useState<CriteriaType>('first_time');
  const [cN, setCN] = useState('1');
  const [cPeriod, setCPeriod] = useState<'day' | 'month'>('day');
  const [cDateFrom, setCDateFrom] = useState('');
  const [cDateTo, setCDateTo] = useState('');
  const [cNames, setCNames] = useState('');
  const [cUserIds, setCUserIds] = useState('');
  const [cGroupIds, setCGroupIds] = useState('');
  const [rType, setRType] = useState<RewardType>('fixed');
  const [rValue, setRValue] = useState('5');
  const [rCap, setRCap] = useState('');
  const [expiryDays, setExpiryDays] = useState('');
  const [stackableWith, setStackableWith] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!visible) return;
    setErr(null);
    setName(initial?.name || '');
    setMessage(initial?.message || '');
    setActive(initial?.active ?? true);
    const c = initial?.criteria || {};
    setCType((c.type as CriteriaType) || 'first_time');
    setCN(String(c.n ?? 1));
    setCPeriod((c.period as any) || 'day');
    setCDateFrom(c.date_from || '');
    setCDateTo(c.date_to || '');
    setCNames((c.names || []).join(', '));
    setCUserIds((c.user_ids || []).join(', '));
    setCGroupIds((c.group_ids || []).join(', '));
    const r = initial?.reward || {};
    setRType((r.type as RewardType) || 'fixed');
    setRValue(String(r.value ?? 5));
    setRCap(r.cap != null ? String(r.cap) : '');
    setExpiryDays(initial?.expiry_days != null ? String(initial.expiry_days) : '');
    setStackableWith(initial?.stackable_with || []);
  }, [visible, initial]);

  const save = async () => {
    setErr(null);
    if (!name.trim()) { setErr('Name is required.'); return; }
    if (!message.trim()) { setErr('Message is required.'); return; }
    const criteria: any = { type: cType };
    if (cType === 'nth_contribution' || cType === 'nth_of_period') criteria.n = parseInt(cN, 10) || 1;
    if (cType === 'nth_of_period') criteria.period = cPeriod;
    if (cType === 'date') { criteria.date_from = cDateFrom; if (cDateTo) criteria.date_to = cDateTo; }
    if (cType === 'specific_names') criteria.names = cNames.split(/[,\n]+/).map(s => s.trim()).filter(Boolean);
    if (cType === 'specific_users') criteria.user_ids = cUserIds.split(/[\s,]+/).filter(Boolean);
    if (cType === 'specific_groups') criteria.group_ids = cGroupIds.split(/[\s,]+/).filter(Boolean);
    const reward: any = { type: rType, value: parseFloat(rValue) || 0 };
    if (rCap) reward.cap = parseFloat(rCap);
    const body = {
      name: name.trim(),
      message: message.trim(),
      active,
      criteria,
      reward,
      expiry_days: expiryDays ? parseInt(expiryDays, 10) : null,
      stackable_with: stackableWith,
    };
    setSaving(true);
    try {
      if (initial?.id) {
        await adminApi.patchCreditRule(initial.id, body);
      } else {
        await adminApi.createCreditRule(body);
      }
      await onSaved();
    } catch (e: any) {
      setErr(e?.message || 'Could not save the rule.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal visible={visible} animationType="slide" transparent onRequestClose={onClose}>
      <View style={editorStyles.backdrop}>
        <View style={editorStyles.sheet}>
          <ScrollView contentContainerStyle={{ padding: SPACING.lg, gap: SPACING.sm }}>
            <Text style={styles.h1}>{initial ? 'Edit credit rule' : 'New credit rule'}</Text>

            <Text style={editorStyles.label}>Rule name</Text>
            <TextInput value={name} onChangeText={setName} style={editorStyles.input} placeholder="e.g. First-time bonus" placeholderTextColor={COLORS.disabledText} />

            <Text style={editorStyles.label}>Message shown to user</Text>
            <TextInput value={message} onChangeText={setMessage} multiline style={[editorStyles.input, { minHeight: 76, textAlignVertical: 'top' }]} placeholder="You're our 10th user today — here's $5 on us!" placeholderTextColor={COLORS.disabledText} />

            <Text style={editorStyles.label}>Criteria</Text>
            <View style={editorStyles.chipRow}>
              {CRITERIA_OPTIONS.map(o => (
                <TouchableOpacity key={o.value} style={[editorStyles.chip, cType === o.value && editorStyles.chipActive]} onPress={() => setCType(o.value)} activeOpacity={0.85}>
                  <Text style={[editorStyles.chipText, cType === o.value && editorStyles.chipTextActive]}>{o.label}</Text>
                </TouchableOpacity>
              ))}
            </View>
            {cType === 'nth_contribution' && (
              <TextInput value={cN} onChangeText={setCN} keyboardType="number-pad" style={editorStyles.input} placeholder="N (e.g. 5, 10)" placeholderTextColor={COLORS.disabledText} />
            )}
            {cType === 'nth_of_period' && (
              <View style={{ flexDirection: 'row', gap: 8 }}>
                <TextInput value={cN} onChangeText={setCN} keyboardType="number-pad" style={[editorStyles.input, { flex: 1 }]} placeholder="N" placeholderTextColor={COLORS.disabledText} />
                <View style={[editorStyles.chipRow, { flex: 1 }]}>
                  {(['day', 'month'] as const).map(p => (
                    <TouchableOpacity key={p} style={[editorStyles.chip, cPeriod === p && editorStyles.chipActive]} onPress={() => setCPeriod(p)} activeOpacity={0.85}>
                      <Text style={[editorStyles.chipText, cPeriod === p && editorStyles.chipTextActive]}>per {p}</Text>
                    </TouchableOpacity>
                  ))}
                </View>
              </View>
            )}
            {cType === 'date' && (
              <View style={{ flexDirection: 'row', gap: 8 }}>
                <TextInput value={cDateFrom} onChangeText={setCDateFrom} style={[editorStyles.input, { flex: 1 }]} placeholder="From YYYY-MM-DD" placeholderTextColor={COLORS.disabledText} />
                <TextInput value={cDateTo} onChangeText={setCDateTo} style={[editorStyles.input, { flex: 1 }]} placeholder="To YYYY-MM-DD (opt)" placeholderTextColor={COLORS.disabledText} />
              </View>
            )}
            {cType === 'specific_names' && (
              <TextInput value={cNames} onChangeText={setCNames} style={editorStyles.input} placeholder="Alice, Bob, Chinwe…" placeholderTextColor={COLORS.disabledText} />
            )}
            {cType === 'specific_users' && (
              <TextInput value={cUserIds} onChangeText={setCUserIds} style={editorStyles.input} placeholder="u_xxx, u_yyy…" autoCapitalize="none" placeholderTextColor={COLORS.disabledText} />
            )}
            {cType === 'specific_groups' && (
              <TextInput value={cGroupIds} onChangeText={setCGroupIds} style={editorStyles.input} placeholder="g_xxx, g_yyy…" autoCapitalize="none" placeholderTextColor={COLORS.disabledText} />
            )}

            <Text style={editorStyles.label}>Reward</Text>
            <View style={editorStyles.chipRow}>
              {REWARD_OPTIONS.map(o => (
                <TouchableOpacity key={o.value} style={[editorStyles.chip, rType === o.value && editorStyles.chipActive]} onPress={() => setRType(o.value)} activeOpacity={0.85}>
                  <Text style={[editorStyles.chipText, rType === o.value && editorStyles.chipTextActive]}>{o.label}</Text>
                </TouchableOpacity>
              ))}
            </View>
            <View style={{ flexDirection: 'row', gap: 8 }}>
              <TextInput value={rValue} onChangeText={setRValue} keyboardType="decimal-pad" style={[editorStyles.input, { flex: 1 }]} placeholder={rType === 'fixed' ? 'Dollar amount' : 'Percentage'} placeholderTextColor={COLORS.disabledText} />
              <TextInput value={rCap} onChangeText={setRCap} keyboardType="decimal-pad" style={[editorStyles.input, { flex: 1 }]} placeholder="Max payout $ (opt)" placeholderTextColor={COLORS.disabledText} />
            </View>

            <Text style={editorStyles.label}>Expires after (days, blank = never)</Text>
            <TextInput value={expiryDays} onChangeText={setExpiryDays} keyboardType="number-pad" style={editorStyles.input} placeholder="e.g. 90" placeholderTextColor={COLORS.disabledText} />

            {existingRules?.length > 0 && (
              <>
                <Text style={editorStyles.label}>Stackable with</Text>
                <View style={editorStyles.chipRow}>
                  {existingRules.filter((x: any) => !initial || x.id !== initial.id).map((x: any) => {
                    const on = stackableWith.includes(x.id);
                    return (
                      <TouchableOpacity
                        key={x.id}
                        style={[editorStyles.chip, on && editorStyles.chipActive]}
                        onPress={() => setStackableWith(prev => on ? prev.filter(i => i !== x.id) : [...prev, x.id])}
                        activeOpacity={0.85}
                      >
                        <Text style={[editorStyles.chipText, on && editorStyles.chipTextActive]}>{x.name}</Text>
                      </TouchableOpacity>
                    );
                  })}
                </View>
              </>
            )}

            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8, marginTop: SPACING.sm }}>
              <Text style={editorStyles.label}>Active</Text>
              <Switch value={active} onValueChange={setActive} />
            </View>

            {err ? (
              <View style={editorStyles.errBanner}>
                <AlertCircle size={14} color={COLORS.danger} />
                <Text style={editorStyles.errText}>{err}</Text>
              </View>
            ) : null}

            <View style={{ flexDirection: 'row', gap: 8, marginTop: SPACING.md }}>
              <TouchableOpacity onPress={onClose} style={[editorStyles.cancelBtn, { flex: 1 }]} activeOpacity={0.85}>
                <Text style={editorStyles.cancelBtnText}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity onPress={save} disabled={saving} style={[editorStyles.saveBtn, { flex: 1 }, saving && { opacity: 0.7 }]} activeOpacity={0.85}>
                {saving ? <ActivityIndicator color="#fff" /> : (
                  <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
                    <CheckCircle2 size={16} color="#fff" />
                    <Text style={editorStyles.saveBtnText}>{initial ? 'Save' : 'Create'}</Text>
                  </View>
                )}
              </TouchableOpacity>
            </View>
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  h1: { fontSize: 22, fontWeight: FONT.weights.heavy, color: COLORS.text },
  subtle: { color: COLORS.subtext, fontSize: FONT.sizes.sm, lineHeight: 20 },
  newBtn: { flexDirection: 'row', alignItems: 'center', gap: 6, paddingHorizontal: 12, paddingVertical: 8, backgroundColor: COLORS.primary, borderRadius: RADIUS.md },
  newBtnText: { color: '#fff', fontWeight: FONT.weights.bold, fontSize: FONT.sizes.sm },
  empty: { alignItems: 'center', padding: SPACING.lg, gap: SPACING.sm },
  emptyTitle: { fontSize: FONT.sizes.lg, fontWeight: FONT.weights.bold, color: COLORS.text },
  emptySub: { color: COLORS.subtext, fontSize: FONT.sizes.sm, textAlign: 'center' },
  row: { flexDirection: 'row', alignItems: 'flex-start', gap: SPACING.md, padding: SPACING.md, backgroundColor: COLORS.surface, borderRadius: RADIUS.md, borderWidth: 1, borderColor: COLORS.border },
  rowName: { fontWeight: FONT.weights.bold, fontSize: FONT.sizes.md, color: COLORS.text },
  rowMeta: { fontSize: FONT.sizes.xs, color: COLORS.subtext },
  rowStats: { fontSize: 11, color: COLORS.subtext, marginTop: 2 },
  pauseBadge: { paddingHorizontal: 6, paddingVertical: 2, borderRadius: RADIUS.pill, backgroundColor: COLORS.disabledBg },
  pauseBadgeText: { fontSize: 10, color: COLORS.subtext, fontWeight: FONT.weights.bold, textTransform: 'uppercase', letterSpacing: 0.5 },
  iconBtn: { width: 28, height: 28, borderRadius: 14, backgroundColor: COLORS.bg, alignItems: 'center', justifyContent: 'center', borderWidth: 1, borderColor: COLORS.border },
});

const editorStyles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: 'rgba(0,0,0,0.4)', justifyContent: 'flex-end' },
  sheet: { backgroundColor: COLORS.bg, borderTopLeftRadius: 20, borderTopRightRadius: 20, maxHeight: '92%' },
  label: { fontSize: FONT.sizes.xs, color: COLORS.subtext, fontWeight: FONT.weights.semibold, textTransform: 'uppercase', letterSpacing: 1, marginTop: SPACING.sm },
  input: { borderRadius: RADIUS.md, borderWidth: 1.5, borderColor: COLORS.border, backgroundColor: COLORS.surface, paddingHorizontal: SPACING.md, paddingVertical: Platform.OS === 'ios' ? 10 : 8, fontSize: FONT.sizes.md, color: COLORS.text },
  chipRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  chip: { paddingHorizontal: 10, paddingVertical: 6, borderRadius: RADIUS.pill, backgroundColor: COLORS.primaryLight, borderWidth: 1, borderColor: COLORS.primaryLight },
  chipActive: { backgroundColor: COLORS.primary, borderColor: COLORS.primary },
  chipText: { color: COLORS.primary, fontWeight: FONT.weights.semibold, fontSize: FONT.sizes.xs },
  chipTextActive: { color: '#fff' },
  errBanner: { flexDirection: 'row', alignItems: 'center', gap: 6, backgroundColor: COLORS.dangerLight, borderRadius: RADIUS.md, padding: 10 },
  errText: { color: COLORS.danger, fontSize: FONT.sizes.sm, flex: 1 },
  cancelBtn: { backgroundColor: COLORS.surface, borderRadius: RADIUS.md, height: 44, alignItems: 'center', justifyContent: 'center', borderWidth: 1, borderColor: COLORS.border },
  cancelBtnText: { color: COLORS.text, fontWeight: FONT.weights.semibold, fontSize: FONT.sizes.md },
  saveBtn: { backgroundColor: COLORS.primary, borderRadius: RADIUS.md, height: 44, alignItems: 'center', justifyContent: 'center' },
  saveBtnText: { color: '#fff', fontWeight: FONT.weights.bold, fontSize: FONT.sizes.md },
});

import { useEffect, useState, useCallback } from 'react';
import { View, Text, TextInput, TouchableOpacity, ScrollView, StyleSheet, ActivityIndicator, Alert, Platform } from 'react-native';
import { GripVertical, Trash2, Plus, Save, RefreshCw, CheckCircle2, XCircle } from 'lucide-react-native';
import { ocrApi, OcrConfig, OcrProviderEntry } from '../../src/adminApi';
import { COLORS, FONT, RADIUS, SPACING } from '../../src/theme';
import { toast } from '../../src/components/Toast';

/**
 * Admin → Receipt OCR — manage the provider failover chain.
 *
 * The chain is tried in order: first one wins. If it throws or returns
 * non-JSON, the backend transparently falls back to the next entry. The
 * recent-attempts table shows which provider actually answered each call
 * — invaluable when one of them is rate-limited or down.
 */
const KNOWN_PROVIDERS: Array<{ key: string; label: string; models: string[] }> = [
  { key: 'openai', label: 'OpenAI', models: ['gpt-4o', 'gpt-4.1', 'gpt-4o-mini'] },
  { key: 'anthropic', label: 'Anthropic', models: ['claude-sonnet-4-5-20250929', 'claude-opus-4-1-20250805', 'claude-haiku-4-5-20251001'] },
  { key: 'gemini', label: 'Google Gemini', models: ['gemini-2.5-flash', 'gemini-2.5-pro', 'gemini-2.5-flash-lite'] },
];

export default function AdminOcrConfig() {
  const [cfg, setCfg] = useState<OcrConfig | null>(null);
  const [busy, setBusy] = useState(true);
  const [saving, setSaving] = useState(false);
  const [chain, setChain] = useState<OcrProviderEntry[]>([]);

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const r = await ocrApi.get();
      setCfg(r);
      setChain(r.providers);
    } catch (e: any) {
      Alert.alert('Error', e?.message || 'Failed to load OCR config');
    } finally {
      setBusy(false);
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  const moveUp = (i: number) => {
    if (i === 0) return;
    const c = [...chain];
    [c[i - 1], c[i]] = [c[i], c[i - 1]];
    setChain(c);
  };
  const moveDown = (i: number) => {
    if (i === chain.length - 1) return;
    const c = [...chain];
    [c[i + 1], c[i]] = [c[i], c[i + 1]];
    setChain(c);
  };
  const remove = (i: number) => setChain(chain.filter((_, idx) => idx !== i));
  const add = () => setChain([...chain, { provider: 'openai', model: 'gpt-4o' }]);
  const editProvider = (i: number, provider: string) => {
    const p = KNOWN_PROVIDERS.find((x) => x.key === provider);
    const c = [...chain];
    c[i] = { provider, model: p?.models?.[0] || c[i].model };
    setChain(c);
  };
  const editModel = (i: number, model: string) => {
    const c = [...chain];
    c[i] = { ...c[i], model };
    setChain(c);
  };

  const onSave = async () => {
    if (chain.length === 0) {
      Alert.alert('At least one provider required', 'OCR cannot function with an empty chain.');
      return;
    }
    setSaving(true);
    try {
      await ocrApi.set(chain);
      toast.success('OCR chain saved');
      await load();
    } catch (e: any) {
      Alert.alert('Save failed', e?.message || 'Could not save');
    } finally {
      setSaving(false);
    }
  };

  if (busy) return <View style={styles.center}><ActivityIndicator color={COLORS.primary} /></View>;

  return (
    <ScrollView contentContainerStyle={{ paddingBottom: 80 }}>
      <Text style={styles.heading} testID="ocr-heading">Receipt OCR — provider chain</Text>
      <Text style={styles.subheading}>
        Providers are tried in order. When one fails, the next takes over
        automatically. Drag to reorder, edit the model name, or remove
        entries. Changes apply to all future receipt scans immediately.
      </Text>

      <View style={styles.card}>
        {chain.map((p, idx) => {
          const prov = KNOWN_PROVIDERS.find((x) => x.key === p.provider);
          const knownModel = prov?.models.includes(p.model);
          return (
            <View key={`${p.provider}-${idx}`} style={styles.providerRow} testID={`ocr-row-${idx}`}>
              <View style={styles.rankBubble}><Text style={styles.rankText}>{idx + 1}</Text></View>

              <View style={{ flex: 1, gap: 6 }}>
                <Text style={styles.fieldLabel}>Provider</Text>
                <View style={styles.chipsRow}>
                  {KNOWN_PROVIDERS.map((pp) => (
                    <TouchableOpacity
                      key={pp.key}
                      onPress={() => editProvider(idx, pp.key)}
                      style={[styles.chip, p.provider === pp.key && styles.chipActive]}
                      testID={`ocr-row-${idx}-prov-${pp.key}`}
                    >
                      <Text style={[styles.chipText, p.provider === pp.key && styles.chipTextActive]}>{pp.label}</Text>
                    </TouchableOpacity>
                  ))}
                </View>
                <Text style={[styles.fieldLabel, { marginTop: 8 }]}>Model</Text>
                <TextInput
                  style={styles.input}
                  value={p.model}
                  onChangeText={(v) => editModel(idx, v)}
                  autoCapitalize="none"
                  placeholder="e.g. gpt-4o"
                  placeholderTextColor={COLORS.disabledText}
                  testID={`ocr-row-${idx}-model`}
                />
                {prov && (
                  <View style={styles.chipsRow}>
                    {prov.models.map((m) => (
                      <TouchableOpacity
                        key={m}
                        onPress={() => editModel(idx, m)}
                        style={[styles.chipSm, p.model === m && styles.chipSmActive]}
                      >
                        <Text style={[styles.chipSmText, p.model === m && styles.chipSmTextActive]}>{m}</Text>
                      </TouchableOpacity>
                    ))}
                  </View>
                )}
                {!knownModel && (
                  <Text style={styles.hint}>Custom model name (not in the known list).</Text>
                )}
              </View>

              <View style={styles.rowActions}>
                <TouchableOpacity onPress={() => moveUp(idx)} disabled={idx === 0} style={[styles.actionBtn, idx === 0 && { opacity: 0.4 }]}><Text style={styles.actionBtnText}>▲</Text></TouchableOpacity>
                <TouchableOpacity onPress={() => moveDown(idx)} disabled={idx === chain.length - 1} style={[styles.actionBtn, idx === chain.length - 1 && { opacity: 0.4 }]}><Text style={styles.actionBtnText}>▼</Text></TouchableOpacity>
                <TouchableOpacity onPress={() => remove(idx)} style={[styles.actionBtn, { backgroundColor: COLORS.dangerLight }]}>
                  <Trash2 size={14} color={COLORS.danger} />
                </TouchableOpacity>
              </View>
            </View>
          );
        })}

        <View style={styles.footerRow}>
          <TouchableOpacity onPress={add} style={styles.addBtn} testID="ocr-add">
            <Plus size={14} color={COLORS.primary} />
            <Text style={styles.addBtnText}>Add provider</Text>
          </TouchableOpacity>
          <TouchableOpacity onPress={onSave} disabled={saving} style={[styles.saveBtn, saving && { opacity: 0.7 }]} testID="ocr-save">
            {saving ? <ActivityIndicator color="#fff" size="small" /> : <Save size={14} color="#fff" />}
            <Text style={styles.saveBtnText}>{saving ? 'Saving…' : 'Save chain'}</Text>
          </TouchableOpacity>
        </View>
      </View>

      <View style={styles.headerRow}>
        <Text style={styles.h2}>Recent attempts</Text>
        <TouchableOpacity onPress={load} style={styles.refreshChip}><RefreshCw size={12} color={COLORS.subtext} /><Text style={styles.refreshChipText}>Refresh</Text></TouchableOpacity>
      </View>
      {cfg?.recent_attempts?.length ? cfg.recent_attempts.map((a) => (
        <View key={a.id} style={styles.attemptRow}>
          <View style={styles.attemptIcon}>
            {a.succeeded ? <CheckCircle2 size={16} color={COLORS.success} /> : <XCircle size={16} color={COLORS.danger} />}
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.attemptTitle}>
              {a.succeeded ? `✓ ${a.provider_used || 'unknown'}` : '✗ all providers failed'} · {new Date(a.at).toLocaleString()}
            </Text>
            <Text style={styles.attemptSub}>
              tried {a.attempts.length}: {a.attempts.map((x) => `${x.provider}${x.ok ? '✓' : '✗'}`).join(' → ')}
            </Text>
          </View>
        </View>
      )) : <Text style={styles.empty}>No OCR scans logged yet.</Text>}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  heading: { fontSize: FONT.sizes.xl, fontWeight: FONT.weights.bold, color: COLORS.text },
  subheading: { fontSize: FONT.sizes.sm, color: COLORS.subtext, marginTop: 2, marginBottom: SPACING.md, maxWidth: 720 },
  card: { padding: SPACING.md, backgroundColor: COLORS.surface, borderRadius: RADIUS.md, borderWidth: 1, borderColor: COLORS.border, marginBottom: SPACING.lg },
  providerRow: { flexDirection: 'row', alignItems: 'flex-start', gap: SPACING.sm, paddingVertical: SPACING.md, borderTopWidth: 1, borderTopColor: COLORS.border },
  rankBubble: { width: 30, height: 30, borderRadius: 15, backgroundColor: COLORS.primary, alignItems: 'center', justifyContent: 'center' },
  rankText: { color: '#fff', fontWeight: FONT.weights.bold, fontSize: FONT.sizes.sm },
  fieldLabel: { fontSize: 10, color: COLORS.subtext, textTransform: 'uppercase', fontWeight: FONT.weights.bold, letterSpacing: 0.4 },
  chipsRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  chip: { paddingHorizontal: 10, height: 30, borderRadius: RADIUS.pill, borderWidth: 1, borderColor: COLORS.border, backgroundColor: COLORS.bg, alignItems: 'center', justifyContent: 'center' },
  chipActive: { backgroundColor: COLORS.primary, borderColor: COLORS.primary },
  chipText: { fontSize: FONT.sizes.xs, color: COLORS.text, fontWeight: FONT.weights.medium },
  chipTextActive: { color: '#fff' },
  chipSm: { paddingHorizontal: 8, height: 24, borderRadius: RADIUS.pill, borderWidth: 1, borderColor: COLORS.border, backgroundColor: COLORS.bg, alignItems: 'center', justifyContent: 'center' },
  chipSmActive: { backgroundColor: COLORS.primaryLight, borderColor: COLORS.primary },
  chipSmText: { fontSize: 10, color: COLORS.subtext },
  chipSmTextActive: { color: COLORS.primary, fontWeight: FONT.weights.semibold },
  input: { height: 38, borderRadius: RADIUS.md, borderWidth: 1, borderColor: COLORS.border, paddingHorizontal: SPACING.md, color: COLORS.text, backgroundColor: COLORS.bg, fontSize: FONT.sizes.sm },
  hint: { fontSize: 11, color: COLORS.warning, fontStyle: 'italic' },
  rowActions: { gap: 6 },
  actionBtn: { width: 30, height: 30, borderRadius: RADIUS.md, alignItems: 'center', justifyContent: 'center', backgroundColor: COLORS.bg, borderWidth: 1, borderColor: COLORS.border },
  actionBtnText: { fontSize: 12, color: COLORS.text },
  footerRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginTop: SPACING.md, paddingTop: SPACING.md, borderTopWidth: 1, borderTopColor: COLORS.border },
  addBtn: { flexDirection: 'row', alignItems: 'center', gap: 6, paddingHorizontal: 12, height: 36, borderRadius: RADIUS.md, borderWidth: 1, borderColor: COLORS.primary, backgroundColor: COLORS.primaryLight },
  addBtnText: { color: COLORS.primary, fontWeight: FONT.weights.bold, fontSize: FONT.sizes.xs },
  saveBtn: { flexDirection: 'row', alignItems: 'center', gap: 6, paddingHorizontal: 16, height: 36, borderRadius: RADIUS.md, backgroundColor: COLORS.primary },
  saveBtnText: { color: '#fff', fontWeight: FONT.weights.bold, fontSize: FONT.sizes.xs },
  headerRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: SPACING.sm },
  h2: { fontSize: FONT.sizes.lg, fontWeight: FONT.weights.bold, color: COLORS.text },
  refreshChip: { flexDirection: 'row', alignItems: 'center', gap: 4, paddingHorizontal: 10, height: 28, borderRadius: RADIUS.pill, backgroundColor: COLORS.bg, borderWidth: 1, borderColor: COLORS.border },
  refreshChipText: { fontSize: FONT.sizes.xs, color: COLORS.subtext, fontWeight: FONT.weights.semibold },
  empty: { fontSize: FONT.sizes.sm, color: COLORS.subtext, fontStyle: 'italic' },
  attemptRow: { flexDirection: 'row', gap: 10, paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: COLORS.border },
  attemptIcon: { width: 24, alignItems: 'center', paddingTop: 2 },
  attemptTitle: { fontSize: FONT.sizes.sm, color: COLORS.text, fontWeight: FONT.weights.semibold },
  attemptSub: { fontSize: 11, color: COLORS.subtext, marginTop: 2, fontFamily: Platform.select({ ios: 'Menlo', android: 'monospace', default: 'monospace' }) },
});

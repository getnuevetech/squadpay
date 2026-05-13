import { useEffect, useState, useCallback } from 'react';
import { View, Text, TouchableOpacity, ScrollView, StyleSheet, ActivityIndicator, Alert, TextInput } from 'react-native';
import { Hash, Save } from 'lucide-react-native';
import { _aRequest } from '../../src/adminApi';
import { COLORS, FONT, RADIUS, SPACING } from '../../src/theme';
import { toast } from '../../src/components/Toast';

/**
 * Admin → Join Codes (#5)
 *
 * Lets admins pick the charset + length for newly-generated squad codes.
 * Default is 6-digit numeric — easiest to share verbally and type into the
 * join field. Existing groups keep their old codes; this only affects
 * codes minted for new groups going forward.
 */
type JoinCfg = { charset: string; length: number; updated_at?: string | null; updated_by?: string | null };

const joinApi = {
  get: () => _aRequest<JoinCfg>('/admin/join-code-config'),
  set: (charset: string, length: number) =>
    _aRequest<JoinCfg & { ok: boolean }>('/admin/join-code-config', {
      method: 'PUT',
      body: JSON.stringify({ charset, length }),
    }),
};

export default function AdminJoinCodeConfig() {
  const [cfg, setCfg] = useState<JoinCfg | null>(null);
  const [charset, setCharset] = useState('numeric');
  const [length, setLength] = useState('6');
  const [busy, setBusy] = useState(true);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const r = await joinApi.get();
      setCfg(r);
      setCharset(r.charset);
      setLength(String(r.length));
    } catch (e: any) { Alert.alert('Error', e?.message || 'Failed to load join-code config'); }
    finally { setBusy(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const save = async () => {
    const n = Math.max(4, Math.min(12, parseInt(length, 10) || 6));
    setSaving(true);
    try {
      await joinApi.set(charset, n);
      toast.success('Join-code config saved');
      load();
    } catch (e: any) { Alert.alert('Save failed', e?.message || 'Could not save'); }
    finally { setSaving(false); }
  };

  if (busy) return <View style={styles.center}><ActivityIndicator color={COLORS.primary} /></View>;

  // Sample of what the next generated code will look like.
  const sample = (() => {
    const n = Math.max(4, Math.min(12, parseInt(length, 10) || 6));
    const pool = charset === 'numeric' ? '0123456789' : charset === 'alpha' ? 'ABCDEFGHIJKLMNOPQRSTUVWXYZ' : 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789';
    return Array.from({ length: n }, () => pool[Math.floor(Math.random() * pool.length)]).join('');
  })();

  return (
    <ScrollView contentContainerStyle={{ paddingBottom: 80 }}>
      <Text style={styles.heading} testID="joincode-heading">Squad Join Codes</Text>
      <Text style={styles.subheading}>
        Configure the charset and length of the join code shown when starting
        a new squad. Default: 6-digit numeric (easy to read aloud + type).
        Existing squads keep their codes; this only affects new ones.
      </Text>

      <View style={styles.card}>
        <Text style={styles.fieldLabel}>Charset</Text>
        <View style={styles.chipsRow}>
          {([
            { k: 'numeric', l: 'Numeric (0-9)' },
            { k: 'alpha', l: 'Letters (A-Z)' },
            { k: 'alphanumeric', l: 'Mixed (A-Z + 0-9)' },
          ]).map((c) => (
            <TouchableOpacity
              key={c.k}
              onPress={() => setCharset(c.k)}
              style={[styles.chip, charset === c.k && styles.chipActive]}
              testID={`joincode-charset-${c.k}`}
            >
              <Text style={[styles.chipText, charset === c.k && styles.chipTextActive]}>{c.l}</Text>
            </TouchableOpacity>
          ))}
        </View>

        <Text style={[styles.fieldLabel, { marginTop: SPACING.md }]}>Length (4 – 12)</Text>
        <TextInput
          style={styles.input}
          value={length}
          onChangeText={setLength}
          keyboardType="number-pad"
          maxLength={2}
          testID="joincode-length"
        />

        <View style={styles.preview}>
          <Hash size={18} color={COLORS.subtext} />
          <Text style={styles.previewLabel}>Sample code:</Text>
          <Text style={styles.previewValue} testID="joincode-sample">{sample}</Text>
        </View>

        <View style={styles.actions}>
          {cfg?.updated_at ? (
            <Text style={styles.metaText}>
              Last updated: {new Date(cfg.updated_at).toLocaleString()}
              {cfg.updated_by ? ` by ${cfg.updated_by}` : ''}
            </Text>
          ) : <View />}
          <TouchableOpacity onPress={save} disabled={saving} style={[styles.saveBtn, saving && { opacity: 0.7 }]} testID="joincode-save">
            {saving ? <ActivityIndicator color="#fff" size="small" /> : <Save size={14} color="#fff" />}
            <Text style={styles.saveBtnText}>{saving ? 'Saving…' : 'Save'}</Text>
          </TouchableOpacity>
        </View>
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  heading: { fontSize: FONT.sizes.xl, fontWeight: FONT.weights.bold, color: COLORS.text },
  subheading: { fontSize: FONT.sizes.sm, color: COLORS.subtext, marginTop: 4, marginBottom: SPACING.lg, maxWidth: 720 },
  card: { padding: SPACING.lg, backgroundColor: COLORS.surface, borderRadius: RADIUS.md, borderWidth: 1, borderColor: COLORS.border },
  fieldLabel: { fontSize: 10, color: COLORS.subtext, textTransform: 'uppercase', fontWeight: FONT.weights.bold, letterSpacing: 0.4, marginBottom: 8 },
  chipsRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  chip: { paddingHorizontal: 14, height: 36, borderRadius: RADIUS.pill, borderWidth: 1, borderColor: COLORS.border, backgroundColor: COLORS.bg, alignItems: 'center', justifyContent: 'center' },
  chipActive: { backgroundColor: COLORS.primary, borderColor: COLORS.primary },
  chipText: { fontSize: FONT.sizes.sm, color: COLORS.text, fontWeight: FONT.weights.medium },
  chipTextActive: { color: '#fff' },
  input: { height: 42, borderRadius: RADIUS.md, borderWidth: 1, borderColor: COLORS.border, paddingHorizontal: SPACING.md, color: COLORS.text, backgroundColor: COLORS.bg, fontSize: FONT.sizes.md, width: 100 },
  preview: { flexDirection: 'row', alignItems: 'center', gap: 8, marginTop: SPACING.md, padding: SPACING.md, backgroundColor: COLORS.bg, borderRadius: RADIUS.md },
  previewLabel: { fontSize: FONT.sizes.xs, color: COLORS.subtext },
  previewValue: { fontSize: FONT.sizes.lg, fontWeight: FONT.weights.bold, color: COLORS.primary, fontFamily: 'monospace', letterSpacing: 2 },
  actions: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginTop: SPACING.md, gap: SPACING.md },
  metaText: { fontSize: 11, color: COLORS.subtext, fontStyle: 'italic', flex: 1 },
  saveBtn: { flexDirection: 'row', alignItems: 'center', gap: 6, paddingHorizontal: SPACING.lg, height: 38, borderRadius: RADIUS.md, backgroundColor: COLORS.primary },
  saveBtnText: { color: '#fff', fontWeight: FONT.weights.bold, fontSize: FONT.sizes.sm },
});

/**
 * Admin · Landing Page dynamic visuals (June 2025).
 *
 * Lets admin manage rotating-random pools for the unauth landing screen:
 *   • Phone-frame colors    (1..10 hex)
 *   • Background shades     (1..10 hex)
 *   • Hashtags              (1..10 short strings)
 *   • Avatar slots × 3      (1..5 image URLs each)
 *
 * The frontend HeroPhoneFrame fetches the public `/runtime/landing-page`
 * snapshot on mount and picks a random value from each pool per visit.
 */
import { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Image,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Sparkles, Hash, Palette, Image as ImageIcon, AlertCircle, CheckCircle2, Trash2, Plus } from 'lucide-react-native';
import { landingPageConfigApi, type LandingPageConfig } from '../../src/adminApi';
import { COLORS, FONT, RADIUS, SPACING } from '../../src/theme';

const AVATAR_SLOTS: { key: keyof LandingPageConfig['avatars']; label: string }[] = [
  { key: 'slot_left', label: 'Slot 1 (top-left, overlaps dark hashtag chip)' },
  { key: 'slot_right_man', label: 'Slot 2 (bottom-right, left face)' },
  { key: 'slot_right_woman', label: 'Slot 3 (bottom-right, right face)' },
];

function HexInput({ value, onChange, onDelete }: { value: string; onChange: (v: string) => void; onDelete: () => void }) {
  return (
    <View style={s.hexRow}>
      <View style={[s.hexSwatch, { backgroundColor: value || '#fff' }]} />
      <TextInput
        style={s.hexInput}
        value={value}
        onChangeText={(t) => onChange(t.toUpperCase().slice(0, 7))}
        autoCapitalize="characters"
        placeholder="#7C3AED"
        placeholderTextColor={COLORS.muted}
      />
      <TouchableOpacity onPress={onDelete}>
        <Trash2 size={16} color={COLORS.danger} />
      </TouchableOpacity>
    </View>
  );
}

function StringInput({ value, onChange, onDelete }: { value: string; onChange: (v: string) => void; onDelete: () => void }) {
  return (
    <View style={s.strRow}>
      <TextInput
        style={s.strInput}
        value={value}
        onChangeText={(t) => onChange(t.slice(0, 32))}
        placeholder="# SplitBill"
        placeholderTextColor={COLORS.muted}
      />
      <TouchableOpacity onPress={onDelete}>
        <Trash2 size={16} color={COLORS.danger} />
      </TouchableOpacity>
    </View>
  );
}

function UrlInput({ value, onChange, onDelete }: { value: string; onChange: (v: string) => void; onDelete: () => void }) {
  const isValid = value.startsWith('http');
  return (
    <View style={s.urlRow}>
      {isValid ? (
        <Image source={{ uri: value }} style={s.urlPreview} />
      ) : (
        <View style={[s.urlPreview, { backgroundColor: COLORS.border, alignItems: 'center', justifyContent: 'center' }]}>
          <ImageIcon size={14} color={COLORS.muted} />
        </View>
      )}
      <TextInput
        style={s.urlInput}
        value={value}
        onChangeText={(t) => onChange(t.slice(0, 500))}
        placeholder="https://images.unsplash.com/..."
        placeholderTextColor={COLORS.muted}
        autoCapitalize="none"
        autoCorrect={false}
      />
      <TouchableOpacity onPress={onDelete}>
        <Trash2 size={16} color={COLORS.danger} />
      </TouchableOpacity>
    </View>
  );
}

export default function AdminLandingPageScreen() {
  const [cfg, setCfg] = useState<LandingPageConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setCfg(await landingPageConfigApi.get());
    } catch (e: any) {
      setError(e?.message || 'Failed to load landing page config');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const save = async () => {
    if (!cfg) return;
    setSaving(true);
    setError(null);
    setSavedAt(null);
    try {
      const cleaned = {
        phone_frame_colors: cfg.phone_frame_colors.filter((c) => /^#[0-9A-F]{6}$/.test(c)),
        bg_purple_shades: cfg.bg_purple_shades.filter((c) => /^#[0-9A-F]{6}$/.test(c)),
        hashtags: cfg.hashtags.filter((h) => h.trim()),
        avatars: {
          slot_left: cfg.avatars.slot_left.filter((u) => u.startsWith('http')),
          slot_right_man: cfg.avatars.slot_right_man.filter((u) => u.startsWith('http')),
          slot_right_woman: cfg.avatars.slot_right_woman.filter((u) => u.startsWith('http')),
        },
      };
      const next = await landingPageConfigApi.set(cleaned);
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
  if (!cfg) return null;

  const updateArray = <K extends keyof LandingPageConfig>(k: K, v: any) => setCfg({ ...cfg, [k]: v });
  const updateAvatar = (slot: keyof LandingPageConfig['avatars'], list: string[]) =>
    setCfg({ ...cfg, avatars: { ...cfg.avatars, [slot]: list } });

  return (
    <SafeAreaView style={s.safe} edges={['top']}>
      <ScrollView contentContainerStyle={s.scroll}>
        <View style={s.header}>
          <Sparkles size={24} color={COLORS.primary} />
          <Text style={s.h1}>Landing Page Visuals</Text>
        </View>
        <Text style={s.sub}>
          Random-rotating pools for the unauth landing screen. The hero illustration
          picks one value from each pool every time a visitor opens the app.
        </Text>

        {error ? (
          <View style={s.error}>
            <AlertCircle size={16} color={COLORS.danger} />
            <Text style={s.errorText}>{error}</Text>
          </View>
        ) : null}
        {savedAt ? (
          <View style={s.success}>
            <CheckCircle2 size={16} color={COLORS.success} />
            <Text style={s.successText}>Saved at {savedAt}</Text>
          </View>
        ) : null}

        {/* Phone-frame colors */}
        <View style={s.card}>
          <View style={s.cardHeader}>
            <Palette size={18} color={COLORS.primary} />
            <Text style={s.cardTitle}>Phone-frame color pool</Text>
          </View>
          <Text style={s.sub}>Phone frame border + "Split Now" button. 1–10 hex values.</Text>
          {cfg.phone_frame_colors.map((c, i) => (
            <HexInput
              key={i}
              value={c}
              onChange={(v) => {
                const next = [...cfg.phone_frame_colors];
                next[i] = v;
                updateArray('phone_frame_colors', next);
              }}
              onDelete={() => {
                const next = cfg.phone_frame_colors.filter((_, idx) => idx !== i);
                updateArray('phone_frame_colors', next);
              }}
            />
          ))}
          {cfg.phone_frame_colors.length < 10 && (
            <TouchableOpacity
              style={s.addBtn}
              onPress={() => updateArray('phone_frame_colors', [...cfg.phone_frame_colors, '#7C3AED'])}
            >
              <Plus size={14} color={COLORS.primary} />
              <Text style={s.addBtnText}>Add color</Text>
            </TouchableOpacity>
          )}
        </View>

        {/* Background purple shades */}
        <View style={s.card}>
          <View style={s.cardHeader}>
            <Palette size={18} color={COLORS.primary} />
            <Text style={s.cardTitle}>Background purple shade pool</Text>
          </View>
          <Text style={s.sub}>
            Landing page background. Keep these as LIGHT shades of purple
            (otherwise text contrast may break).
          </Text>
          {cfg.bg_purple_shades.map((c, i) => (
            <HexInput
              key={i}
              value={c}
              onChange={(v) => {
                const next = [...cfg.bg_purple_shades];
                next[i] = v;
                updateArray('bg_purple_shades', next);
              }}
              onDelete={() => {
                const next = cfg.bg_purple_shades.filter((_, idx) => idx !== i);
                updateArray('bg_purple_shades', next);
              }}
            />
          ))}
          {cfg.bg_purple_shades.length < 10 && (
            <TouchableOpacity
              style={s.addBtn}
              onPress={() => updateArray('bg_purple_shades', [...cfg.bg_purple_shades, '#F5F0FF'])}
            >
              <Plus size={14} color={COLORS.primary} />
              <Text style={s.addBtnText}>Add shade</Text>
            </TouchableOpacity>
          )}
        </View>

        {/* Hashtags */}
        <View style={s.card}>
          <View style={s.cardHeader}>
            <Hash size={18} color={COLORS.primary} />
            <Text style={s.cardTitle}>Hashtag pool</Text>
          </View>
          <Text style={s.sub}>
            3 chips render per visit (top-left dark, top-right accent, bottom-right light).
            Provide at least 3 entries; 1–10 allowed. Each ≤32 chars.
          </Text>
          {cfg.hashtags.map((h, i) => (
            <StringInput
              key={i}
              value={h}
              onChange={(v) => {
                const next = [...cfg.hashtags];
                next[i] = v;
                updateArray('hashtags', next);
              }}
              onDelete={() => {
                const next = cfg.hashtags.filter((_, idx) => idx !== i);
                updateArray('hashtags', next);
              }}
            />
          ))}
          {cfg.hashtags.length < 10 && (
            <TouchableOpacity
              style={s.addBtn}
              onPress={() => updateArray('hashtags', [...cfg.hashtags, '# NewTag'])}
            >
              <Plus size={14} color={COLORS.primary} />
              <Text style={s.addBtnText}>Add hashtag</Text>
            </TouchableOpacity>
          )}
        </View>

        {/* Avatars × 3 slots */}
        {AVATAR_SLOTS.map(({ key, label }) => (
          <View key={key} style={s.card}>
            <View style={s.cardHeader}>
              <ImageIcon size={18} color={COLORS.primary} />
              <Text style={s.cardTitle}>{label}</Text>
            </View>
            <Text style={s.sub}>1–5 image URLs. One is picked at random per landing visit.</Text>
            {cfg.avatars[key].map((u, i) => (
              <UrlInput
                key={i}
                value={u}
                onChange={(v) => {
                  const next = [...cfg.avatars[key]];
                  next[i] = v;
                  updateAvatar(key, next);
                }}
                onDelete={() => {
                  const next = cfg.avatars[key].filter((_, idx) => idx !== i);
                  updateAvatar(key, next);
                }}
              />
            ))}
            {cfg.avatars[key].length < 5 && (
              <TouchableOpacity
                style={s.addBtn}
                onPress={() => updateAvatar(key, [...cfg.avatars[key], ''])}
              >
                <Plus size={14} color={COLORS.primary} />
                <Text style={s.addBtnText}>Add image URL</Text>
              </TouchableOpacity>
            )}
          </View>
        ))}

        <TouchableOpacity
          style={[s.saveBtn, saving && { opacity: 0.5 }]}
          disabled={saving}
          onPress={save}
        >
          {saving ? (
            <ActivityIndicator color="#fff" />
          ) : (
            <Text style={s.saveText}>Save Landing Page Config</Text>
          )}
        </TouchableOpacity>

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
  card: {
    padding: SPACING.md, backgroundColor: COLORS.surface,
    borderRadius: RADIUS.md, gap: SPACING.sm,
  },
  cardHeader: { flexDirection: 'row', alignItems: 'center', gap: SPACING.xs },
  cardTitle: { fontSize: FONT.sizes.md, fontWeight: '700', color: COLORS.text },
  hexRow: { flexDirection: 'row', alignItems: 'center', gap: SPACING.sm },
  hexSwatch: {
    width: 28, height: 28, borderRadius: 6,
    borderWidth: 1, borderColor: COLORS.border,
  },
  hexInput: {
    flex: 1, paddingHorizontal: SPACING.sm, paddingVertical: SPACING.sm,
    backgroundColor: COLORS.bg, borderRadius: RADIUS.sm,
    borderWidth: 1, borderColor: COLORS.border,
    fontSize: FONT.sizes.sm, color: COLORS.text, fontWeight: '600',
  },
  strRow: { flexDirection: 'row', alignItems: 'center', gap: SPACING.sm },
  strInput: {
    flex: 1, paddingHorizontal: SPACING.sm, paddingVertical: SPACING.sm,
    backgroundColor: COLORS.bg, borderRadius: RADIUS.sm,
    borderWidth: 1, borderColor: COLORS.border,
    fontSize: FONT.sizes.sm, color: COLORS.text, fontWeight: '600',
  },
  urlRow: { flexDirection: 'row', alignItems: 'center', gap: SPACING.sm },
  urlPreview: { width: 36, height: 36, borderRadius: 18, overflow: 'hidden' },
  urlInput: {
    flex: 1, paddingHorizontal: SPACING.sm, paddingVertical: SPACING.sm,
    backgroundColor: COLORS.bg, borderRadius: RADIUS.sm,
    borderWidth: 1, borderColor: COLORS.border,
    fontSize: FONT.sizes.xs, color: COLORS.text,
  },
  addBtn: {
    flexDirection: 'row', alignItems: 'center', gap: 6,
    paddingVertical: SPACING.sm, paddingHorizontal: SPACING.md,
    backgroundColor: COLORS.primaryLight, borderRadius: RADIUS.sm,
    alignSelf: 'flex-start',
  },
  addBtnText: { color: COLORS.primary, fontWeight: '700', fontSize: FONT.sizes.sm },
  saveBtn: {
    backgroundColor: COLORS.primary, paddingVertical: SPACING.md,
    borderRadius: RADIUS.md, alignItems: 'center', marginTop: SPACING.sm,
  },
  saveText: { color: '#fff', fontSize: FONT.sizes.md, fontWeight: '700' },
});

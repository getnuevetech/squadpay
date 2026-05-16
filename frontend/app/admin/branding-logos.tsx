/**
 * Admin → Branding & Logos.
 *
 * Lets a super_admin/manager swap any of the SquadPay brand surfaces at
 * runtime. The backend auto-resizes every upload to the slot's required
 * dimensions (transparent padding for non-white-bg slots, white otherwise)
 * so the admin never has to crop on their end.
 *
 * Slots that map to native iOS/Android icons show a clear "Requires next
 * mobile build" note because installed devices keep the bundled icons until
 * a new binary is shipped via EAS.
 */
import React, { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Image,
  Platform,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import { useRouter } from 'expo-router';
import * as ImagePicker from 'expo-image-picker';
import { ChevronLeft, ImagePlus, Trash2, AlertTriangle, RotateCcw, Image as ImageIcon } from 'lucide-react-native';
import { brandingLogosApi, LogoSlot } from '../../src/adminApi/brandingLogos';
import { COLORS, FONT, RADIUS, SPACING } from '../../src/theme';

export default function BrandingLogosScreen() {
  const router = useRouter();
  const [slots, setSlots] = useState<LogoSlot[]>([]);
  const [busy, setBusy] = useState(true);
  const [uploading, setUploading] = useState<string | null>(null); // slot key currently being saved
  const [reloadKey, setReloadKey] = useState(0);

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const res = await brandingLogosApi.list();
      setSlots(res.slots);
    } catch (e: any) {
      Alert.alert('Could not load logo slots', e?.message || 'Network error');
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const pickAndUpload = useCallback(async (slot: LogoSlot) => {
    try {
      if (Platform.OS !== 'web') {
        const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
        if (!perm.granted) {
          Alert.alert('Permission needed', 'Allow photo library access to upload a logo.');
          return;
        }
      }
      const result = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ImagePicker.MediaTypeOptions.Images,
        allowsEditing: false,
        quality: 1,
        base64: true,
      });
      if (result.canceled) return;
      const asset = result.assets?.[0];
      if (!asset?.base64) {
        Alert.alert('Upload failed', 'Could not read the selected image.');
        return;
      }
      setUploading(slot.slot);
      await brandingLogosApi.upload(slot.slot, asset.base64);
      setReloadKey((k) => k + 1);
      await load();
      Alert.alert('Saved', `${slot.label} updated. The new ${slot.width}×${slot.height} version is live.`);
    } catch (e: any) {
      Alert.alert('Upload failed', e?.message || 'Unknown error');
    } finally {
      setUploading(null);
    }
  }, [load]);

  const reset = useCallback(async (slot: LogoSlot) => {
    Alert.alert(
      'Reset to default?',
      `Discards the custom upload for "${slot.label}" and restores the SquadPay default.`,
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Reset',
          style: 'destructive',
          onPress: async () => {
            try {
              setUploading(slot.slot);
              await brandingLogosApi.reset(slot.slot);
              setReloadKey((k) => k + 1);
              await load();
            } catch (e: any) {
              Alert.alert('Reset failed', e?.message || 'Unknown error');
            } finally {
              setUploading(null);
            }
          },
        },
      ],
    );
  }, [load]);

  return (
    <ScrollView
      style={styles.screen}
      contentContainerStyle={styles.content}
      refreshControl={<RefreshControl refreshing={busy} onRefresh={load} tintColor={COLORS.primary} />}
    >
      <View style={styles.headerRow}>
        <TouchableOpacity onPress={() => router.back()} style={styles.backBtn} testID="branding-back">
          <ChevronLeft size={22} color={COLORS.text} />
        </TouchableOpacity>
        <View style={{ flex: 1 }}>
          <Text style={styles.heading}>Branding & Logos</Text>
          <Text style={styles.subheading}>
            Replace any SquadPay logo. Uploads are auto-resized — drop in any
            square (or wide) PNG/JPG and we'll fit it to the slot.
          </Text>
        </View>
      </View>

      {busy && slots.length === 0 ? (
        <View style={styles.loading}>
          <ActivityIndicator color={COLORS.primary} />
        </View>
      ) : (
        slots.map((slot) => (
          <SlotCard
            key={slot.slot}
            slot={slot}
            reloadKey={reloadKey}
            uploading={uploading === slot.slot}
            onUpload={() => pickAndUpload(slot)}
            onReset={() => reset(slot)}
          />
        ))
      )}
    </ScrollView>
  );
}

function SlotCard({
  slot,
  reloadKey,
  uploading,
  onUpload,
  onReset,
}: {
  slot: LogoSlot;
  reloadKey: number;
  uploading: boolean;
  onUpload: () => void;
  onReset: () => void;
}) {
  // Cache-bust the preview by appending the reload counter so freshly
  // uploaded images replace the previous thumbnail immediately. The
  // backend returns a relative `current_url` (e.g. /api/runtime/logo/...);
  // when the frontend lives on a different origin than the API we need to
  // prepend the backend host so <Image/> can actually resolve it.
  const BACKEND = process.env.EXPO_PUBLIC_BACKEND_URL || '';
  const baseUrl = slot.current_url.startsWith('http')
    ? slot.current_url
    : `${BACKEND}${slot.current_url}`;
  const previewUri = `${baseUrl}${baseUrl.includes('?') ? '&' : '?'}r=${reloadKey}`;
  const bgLabel =
    slot.background === 'transparent' ? 'Transparent' :
    slot.background === 'white' ? 'White (opaque)' : 'Any';

  return (
    <View style={styles.card}>
      <View style={styles.cardLeft}>
        <View
          style={[
            styles.thumbWrap,
            // Show a checkerboard for transparent slots so the user sees
            // the alpha channel; white slots get a white tile to match.
            slot.background === 'transparent' ? styles.thumbAlpha : styles.thumbWhite,
          ]}
        >
          <Image source={{ uri: previewUri }} style={styles.thumb} resizeMode="contain" />
        </View>
      </View>
      <View style={styles.cardBody}>
        <View style={styles.cardTitleRow}>
          <ImageIcon size={16} color={COLORS.primary} />
          <Text style={styles.cardTitle}>{slot.label}</Text>
          {slot.has_override ? (
            <View style={styles.overrideChip}>
              <Text style={styles.overrideChipText}>Custom</Text>
            </View>
          ) : (
            <View style={styles.defaultChip}>
              <Text style={styles.defaultChipText}>Default</Text>
            </View>
          )}
        </View>
        <Text style={styles.cardWhere}>{slot.where}</Text>
        <View style={styles.specsRow}>
          <Spec label="Size" value={`${slot.width} × ${slot.height}`} />
          <Spec label="Background" value={bgLabel} />
        </View>
        {slot.requires_native_build ? (
          <View style={styles.warnRow}>
            <AlertTriangle size={14} color={COLORS.warning} />
            <Text style={styles.warnText}>
              Requires next mobile build (EAS) — installed iOS/Android devices keep
              the bundled icon until you ship a new binary.
            </Text>
          </View>
        ) : null}
        <View style={styles.actionRow}>
          <Pressable
            style={({ pressed }) => [
              styles.primaryBtn,
              uploading && { opacity: 0.6 },
              pressed && { opacity: 0.85 },
            ]}
            onPress={onUpload}
            disabled={uploading}
            testID={`logo-upload-${slot.slot}`}
          >
            {uploading ? (
              <ActivityIndicator size="small" color="#fff" />
            ) : (
              <ImagePlus size={16} color="#fff" />
            )}
            <Text style={styles.primaryBtnText}>
              {uploading ? 'Uploading…' : slot.has_override ? 'Replace' : 'Upload'}
            </Text>
          </Pressable>
          {slot.has_override ? (
            <Pressable
              style={({ pressed }) => [styles.secondaryBtn, pressed && { opacity: 0.7 }]}
              onPress={onReset}
              disabled={uploading}
              testID={`logo-reset-${slot.slot}`}
            >
              <RotateCcw size={14} color={COLORS.subtext} />
              <Text style={styles.secondaryBtnText}>Reset</Text>
            </Pressable>
          ) : null}
        </View>
      </View>
    </View>
  );
}

function Spec({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.spec}>
      <Text style={styles.specLabel}>{label}</Text>
      <Text style={styles.specValue}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: COLORS.bg },
  content: { padding: SPACING.md, paddingBottom: SPACING.xl },
  headerRow: { flexDirection: 'row', alignItems: 'flex-start', gap: SPACING.sm, marginBottom: SPACING.md },
  backBtn: { padding: 6, borderRadius: 999, backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border },
  heading: { fontSize: FONT.sizes.lg, fontWeight: FONT.weights.heavy, color: COLORS.text },
  subheading: { color: COLORS.subtext, fontSize: FONT.sizes.xs, marginTop: 2, lineHeight: 18 },
  loading: { paddingVertical: SPACING.xl, alignItems: 'center' },

  card: {
    flexDirection: 'row',
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.lg,
    padding: SPACING.md,
    marginBottom: SPACING.md,
    gap: SPACING.md,
    borderWidth: 1,
    borderColor: COLORS.border,
  },
  cardLeft: { width: 96, alignItems: 'center' },
  cardBody: { flex: 1, gap: 6 },
  thumbWrap: {
    width: 96,
    height: 96,
    borderRadius: RADIUS.md,
    borderWidth: 1,
    borderColor: COLORS.border,
    overflow: 'hidden',
    alignItems: 'center',
    justifyContent: 'center',
  },
  thumbWhite: { backgroundColor: '#FFFFFF' },
  // Simple "transparent" indicator — light checkerboard suggestion via
  // diagonal stripes painted by background color blend.
  thumbAlpha: { backgroundColor: '#F4F4F6' },
  thumb: { width: '100%', height: '100%' },

  cardTitleRow: { flexDirection: 'row', alignItems: 'center', gap: 8, flexWrap: 'wrap' },
  cardTitle: { fontSize: FONT.sizes.md, fontWeight: FONT.weights.bold, color: COLORS.text, flexShrink: 1 },
  cardWhere: { fontSize: FONT.sizes.xs, color: COLORS.subtext, lineHeight: 17 },

  overrideChip: {
    paddingHorizontal: 8, paddingVertical: 2, borderRadius: 999,
    backgroundColor: 'rgba(124, 58, 237, 0.12)',
  },
  overrideChipText: { color: COLORS.primary, fontSize: 10, fontWeight: FONT.weights.bold, textTransform: 'uppercase', letterSpacing: 0.5 },
  defaultChip: {
    paddingHorizontal: 8, paddingVertical: 2, borderRadius: 999,
    backgroundColor: 'rgba(0,0,0,0.05)',
  },
  defaultChipText: { color: COLORS.subtext, fontSize: 10, fontWeight: FONT.weights.bold, textTransform: 'uppercase', letterSpacing: 0.5 },

  specsRow: { flexDirection: 'row', gap: SPACING.md, marginTop: 2 },
  spec: { },
  specLabel: { fontSize: 10, color: COLORS.subtext, fontWeight: FONT.weights.semibold, textTransform: 'uppercase', letterSpacing: 0.5 },
  specValue: { fontSize: FONT.sizes.sm, color: COLORS.text, fontWeight: FONT.weights.semibold, marginTop: 2 },

  warnRow: {
    flexDirection: 'row', alignItems: 'flex-start', gap: 6,
    backgroundColor: 'rgba(245, 158, 11, 0.10)',
    borderRadius: RADIUS.sm,
    paddingHorizontal: 8, paddingVertical: 6,
    marginTop: 4,
  },
  warnText: { color: COLORS.warning, fontSize: FONT.sizes.xs, flex: 1, lineHeight: 17 },

  actionRow: { flexDirection: 'row', gap: SPACING.sm, marginTop: SPACING.sm, flexWrap: 'wrap' },
  primaryBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    backgroundColor: COLORS.primary,
    paddingHorizontal: 14,
    paddingVertical: 9,
    borderRadius: RADIUS.md,
  },
  primaryBtnText: { color: '#fff', fontWeight: FONT.weights.bold, fontSize: FONT.sizes.sm },
  secondaryBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    paddingHorizontal: 14,
    paddingVertical: 9,
    borderRadius: RADIUS.md,
    borderWidth: 1,
    borderColor: COLORS.border,
    backgroundColor: COLORS.bg,
  },
  secondaryBtnText: { color: COLORS.subtext, fontWeight: FONT.weights.semibold, fontSize: FONT.sizes.sm },
});

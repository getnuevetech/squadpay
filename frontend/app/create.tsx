import { useRouter } from 'expo-router';
import { useEffect, useState } from 'react';
import {
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
  ActivityIndicator,
  Alert,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import * as ImagePicker from 'expo-image-picker';
import { Camera, Edit3, Trash2, Plus, Zap, Target, Sparkles, Upload } from 'lucide-react-native';
import { Button } from '../src/Button';
import { GradientButton } from '../src/components/GradientButton';
import { api } from '../src/api';
import { loadUser } from '../src/session';
import { COLORS, FONT, RADIUS, SPACING } from '../src/theme';
import { toast } from '../src/components/Toast';
import { friendlyError } from '../src/errors';

type Mode = 'fast' | 'smart' | 'itemized';

type DraftItem = { name: string; price: string; quantity: string };

export default function CreateBillScreen() {
  const router = useRouter();
  const [title, setTitle] = useState('Group Bill');
  const [tax, setTax] = useState('');
  const [tip, setTip] = useState('');
  const [mode, setMode] = useState<Mode>('smart');
  const [items, setItems] = useState<DraftItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [userId, setUserId] = useState<string | null>(null);

  useEffect(() => {
    loadUser().then((u) => {
      if (!u) router.replace('/auth');
      else setUserId(u.id);
    });
  }, [router]);

  const addItem = () =>
    setItems((prev) => [...prev, { name: '', price: '', quantity: '1' }]);
  const updateItem = (idx: number, key: keyof DraftItem, val: string) =>
    setItems((prev) => prev.map((it, i) => (i === idx ? { ...it, [key]: val } : it)));
  const removeItem = (idx: number) =>
    setItems((prev) => prev.filter((_, i) => i !== idx));

  // Item 5 — receipt input has TWO buttons now:
  //   • Upload  → picks a photo from the gallery (renamed from old "Scan")
  //   • Scan    → opens the phone camera to take a picture of a receipt
  // Both feed into the same scanReceipt → api.scanReceipt(b64) pipeline.

  const handleParsedReceipt = async (base64: string) => {
    setScanning(true);
    try {
      const parsed = await api.scanReceipt(base64);
      setItems(
        parsed.items.map((it) => ({
          name: it.name,
          price: String(it.price),
          quantity: String(it.quantity || 1),
        })),
      );
      setTax(parsed.tax ? String(parsed.tax) : '');
      setTip(parsed.tip ? String(parsed.tip) : '');
      setMode('itemized');
    } catch (e: any) {
      toast.error(friendlyError(e, "We couldn't read that receipt. Try a clearer photo or add items manually."));
    } finally {
      setScanning(false);
    }
  };

  const uploadReceipt = async () => {
    try {
      const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
      if (!perm.granted) {
        Alert.alert('Permission needed', 'Allow photo access to upload receipts.');
        return;
      }
      const res = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ImagePicker.MediaTypeOptions.Images,
        base64: true,
        quality: 0.6,
      });
      if (res.canceled || !res.assets?.[0]?.base64) return;
      await handleParsedReceipt(res.assets[0].base64!);
    } catch (e: any) {
      toast.error(friendlyError(e, "We couldn't open your photo library. Please try again."));
    }
  };

  const captureReceipt = async () => {
    try {
      const perm = await ImagePicker.requestCameraPermissionsAsync();
      if (!perm.granted) {
        Alert.alert('Permission needed', 'Allow camera access to scan a receipt.');
        return;
      }
      const res = await ImagePicker.launchCameraAsync({
        mediaTypes: ImagePicker.MediaTypeOptions.Images,
        base64: true,
        quality: 0.6,
      });
      if (res.canceled || !res.assets?.[0]?.base64) return;
      await handleParsedReceipt(res.assets[0].base64!);
    } catch (e: any) {
      toast.error(friendlyError(e, "We couldn't open your camera. Please try again."));
    }
  };

  // Backwards-compat alias for any callers still using the old name.
  const scanReceipt = uploadReceipt;

  const computedSubtotal = () =>
    items.reduce(
      (s, it) => s + (parseFloat(it.price) || 0) * (parseInt(it.quantity || '1', 10) || 1),
      0,
    );

  const computedTotal = () =>
    computedSubtotal() + (parseFloat(tax) || 0) + (parseFloat(tip) || 0);

  const create = async () => {
    if (!userId) return;
    const subtotal = computedSubtotal();
    const total = computedTotal();
    if (subtotal <= 0) {
      toast.info('Add at least one item to start the bill');
      return;
    }
    if (mode === 'itemized' && items.length === 0) {
      toast.info('Itemized split needs at least one item');
      return;
    }
    setLoading(true);
    try {
      const payloadItems = items
        .filter((it) => it.name.trim() && parseFloat(it.price))
        .map((it) => ({
          name: it.name.trim(),
          price: parseFloat(it.price),
          quantity: parseInt(it.quantity || '1', 10) || 1,
        }));
      const group = await api.createGroup({
        lead_id: userId,
        title: title.trim() || 'Group Bill',
        total_amount: total,
        tax: parseFloat(tax) || 0,
        tip: parseFloat(tip) || 0,
        split_mode: mode,
        items: payloadItems,
      });
      router.replace(`/group/${group.id}`);
    } catch (e: any) {
      toast.error(e?.message || 'Could not create bill');
    } finally {
      setLoading(false);
    }
  };

  return (
    <KeyboardAvoidingView
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      style={{ flex: 1, backgroundColor: COLORS.bg }}
    >
      <SafeAreaView edges={['bottom']} style={{ flex: 1 }}>
        <ScrollView
          contentContainerStyle={{ padding: SPACING.md, paddingBottom: 120 }}
          keyboardShouldPersistTaps="handled"
        >
          <Text style={styles.label}>Bill name</Text>
          <TextInput
            testID="create-title-input"
            value={title}
            onChangeText={setTitle}
            placeholder="Dinner at Taste Kitchen"
            placeholderTextColor={COLORS.disabledText}
            style={styles.input}
          />

          <View style={styles.row2}>
            <View style={{ flex: 2 }}>
              <Text style={styles.label}>Subtotal (auto)</Text>
              <View
                testID="create-subtotal-readonly"
                style={[styles.input, styles.readonly]}
              >
                <Text style={styles.readonlyText}>
                  ${computedSubtotal().toFixed(2)}
                </Text>
                <Text style={styles.readonlyHint}>from items</Text>
              </View>
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.label}>Tax</Text>
              <TextInput
                testID="create-tax-input"
                value={tax}
                onChangeText={setTax}
                placeholder="0"
                placeholderTextColor={COLORS.disabledText}
                keyboardType="decimal-pad"
                style={styles.input}
              />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.label}>Tip</Text>
              <TextInput
                testID="create-tip-input"
                value={tip}
                onChangeText={setTip}
                placeholder="0"
                placeholderTextColor={COLORS.disabledText}
                keyboardType="decimal-pad"
                style={styles.input}
              />
            </View>
          </View>

          <Text style={[styles.label, { marginTop: SPACING.lg }]}>Split mode</Text>
          <View style={styles.modeRow}>
            {(
              [
                { k: 'fast', title: 'Fast', sub: 'Equal', icon: <Zap size={18} color={mode === 'fast' ? '#fff' : COLORS.primary} /> },
                { k: 'smart', title: 'Smart', sub: 'Balanced', icon: <Sparkles size={18} color={mode === 'smart' ? '#fff' : COLORS.primary} /> },
                { k: 'itemized', title: 'Itemized', sub: 'Per item', icon: <Target size={18} color={mode === 'itemized' ? '#fff' : COLORS.primary} /> },
              ] as const
            ).map((m) => (
              <TouchableOpacity
                key={m.k}
                testID={`create-mode-${m.k}`}
                onPress={() => setMode(m.k)}
                style={[styles.modeCard, mode === m.k && styles.modeCardActive]}
                activeOpacity={0.85}
              >
                <View>{m.icon}</View>
                <Text style={[styles.modeTitle, mode === m.k && { color: '#fff' }]}>{m.title}</Text>
                <Text style={[styles.modeSub, mode === m.k && { color: '#EDE9FE' }]}>{m.sub}</Text>
              </TouchableOpacity>
            ))}
          </View>

          {/* "Items" label removed per UX request. Action chips align right
              so the receipt-action row reads as a toolbar above the list. */}
          <View style={[styles.itemsHeader, { justifyContent: 'flex-end' }]}>
            <View style={{ flexDirection: 'row', gap: SPACING.sm }}>
              {/* Item 5 — Upload from gallery (renamed from old "Scan") */}
              <TouchableOpacity
                testID="create-upload-btn"
                onPress={uploadReceipt}
                style={styles.chip}
                disabled={scanning}
              >
                {scanning ? (
                  <ActivityIndicator size="small" color={COLORS.primary} />
                ) : (
                  <>
                    <Upload size={14} color={COLORS.primary} />
                    <Text style={styles.chipText}>Upload</Text>
                  </>
                )}
              </TouchableOpacity>
              {/* Item 5 — Scan via phone camera (NEW) */}
              <TouchableOpacity
                testID="create-scan-camera-btn"
                onPress={captureReceipt}
                style={styles.chip}
                disabled={scanning}
              >
                <Camera size={14} color={COLORS.primary} />
                <Text style={styles.chipText}>Scan</Text>
              </TouchableOpacity>
              <TouchableOpacity testID="create-add-item-btn" onPress={addItem} style={styles.chip}>
                <Plus size={14} color={COLORS.primary} />
                <Text style={styles.chipText}>Add</Text>
              </TouchableOpacity>
            </View>
          </View>

          {items.length === 0 ? (
            <View style={styles.emptyItems}>
              <Edit3 size={32} color={COLORS.border} />
              <Text style={styles.emptyItemsText}>
                Add items to start the bill. Subtotal updates automatically.
              </Text>
            </View>
          ) : (
            items.map((it, idx) => (
              <View key={idx} style={styles.itemRow}>
                <TextInput
                  testID={`create-item-name-${idx}`}
                  value={it.name}
                  onChangeText={(t) => updateItem(idx, 'name', t)}
                  placeholder="Item name"
                  placeholderTextColor={COLORS.disabledText}
                  style={[styles.input, { flex: 2, marginBottom: 0 }]}
                />
                <TextInput
                  testID={`create-item-price-${idx}`}
                  value={it.price}
                  onChangeText={(t) => updateItem(idx, 'price', t)}
                  placeholder="$"
                  placeholderTextColor={COLORS.disabledText}
                  keyboardType="decimal-pad"
                  style={[styles.input, { flex: 1, marginBottom: 0 }]}
                />
                <TextInput
                  testID={`create-item-qty-${idx}`}
                  value={it.quantity}
                  onChangeText={(t) => updateItem(idx, 'quantity', t)}
                  placeholder="x1"
                  placeholderTextColor={COLORS.disabledText}
                  keyboardType="number-pad"
                  style={[styles.input, { width: 56, marginBottom: 0 }]}
                />
                <TouchableOpacity
                  testID={`create-item-remove-${idx}`}
                  onPress={() => removeItem(idx)}
                  style={styles.removeBtn}
                >
                  <Trash2 size={16} color={COLORS.danger} />
                </TouchableOpacity>
              </View>
            ))
          )}

          <View style={{ height: SPACING.xl }} />
        </ScrollView>

        <View style={styles.bottomBar}>
          <View style={{ flex: 1 }}>
            <Text style={styles.bottomLabel}>Total</Text>
            <Text style={styles.bottomValue}>${computedTotal().toFixed(2)}</Text>
          </View>
          <GradientButton
            title="Create Bill"
            onPress={create}
            loading={loading}
            testID="create-submit-btn"
            style={{ minWidth: 180 }}
          />
        </View>
      </SafeAreaView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  label: {
    fontSize: FONT.sizes.xs,
    color: COLORS.subtext,
    textTransform: 'uppercase',
    letterSpacing: 1,
    marginBottom: 6,
    fontWeight: FONT.weights.semibold,
  },
  input: {
    height: 48,
    borderRadius: RADIUS.md,
    borderWidth: 1.5,
    borderColor: COLORS.border,
    backgroundColor: COLORS.surface,
    paddingHorizontal: SPACING.md,
    color: COLORS.text,
    fontSize: FONT.sizes.md,
    marginBottom: SPACING.md,
  },
  readonly: {
    backgroundColor: COLORS.disabledBg,
    borderColor: COLORS.border,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  readonlyText: {
    color: COLORS.text,
    fontSize: FONT.sizes.md,
    fontWeight: FONT.weights.semibold,
  },
  readonlyHint: {
    color: COLORS.subtext,
    fontSize: FONT.sizes.xs,
  },
  row2: { flexDirection: 'row', gap: SPACING.sm },
  modeRow: { flexDirection: 'row', gap: SPACING.sm },
  modeCard: {
    flex: 1,
    padding: SPACING.md,
    borderRadius: RADIUS.md,
    borderWidth: 1.5,
    borderColor: COLORS.border,
    backgroundColor: COLORS.surface,
    minHeight: 96,
    justifyContent: 'space-between',
  },
  modeCardActive: { backgroundColor: COLORS.primary, borderColor: COLORS.primary },
  modeTitle: { fontSize: FONT.sizes.md, fontWeight: FONT.weights.bold, color: COLORS.text },
  modeSub: { fontSize: FONT.sizes.xs, color: COLORS.subtext },
  itemsHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginTop: SPACING.lg,
    marginBottom: SPACING.md,
  },
  itemsTitle: { fontSize: FONT.sizes.lg, fontWeight: FONT.weights.bold, color: COLORS.text },
  chip: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 10,
    paddingVertical: 8,
    borderRadius: RADIUS.pill,
    backgroundColor: COLORS.primaryLight,
    gap: 4,
  },
  chipText: {
    color: COLORS.primary,
    fontSize: FONT.sizes.xs,
    fontWeight: FONT.weights.semibold,
  },
  emptyItems: {
    alignItems: 'center',
    padding: SPACING.lg,
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.md,
    borderWidth: 1,
    borderColor: COLORS.border,
    gap: SPACING.sm,
  },
  emptyItemsText: { color: COLORS.subtext, fontSize: FONT.sizes.sm, textAlign: 'center' },
  itemRow: {
    flexDirection: 'row',
    gap: 6,
    alignItems: 'center',
    marginBottom: SPACING.sm,
  },
  removeBtn: {
    width: 40,
    height: 40,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: RADIUS.md,
    backgroundColor: COLORS.dangerLight,
  },
  bottomBar: {
    position: 'absolute',
    bottom: 0,
    left: 0,
    right: 0,
    flexDirection: 'row',
    padding: SPACING.md,
    backgroundColor: COLORS.surface,
    borderTopWidth: 1,
    borderTopColor: COLORS.border,
    alignItems: 'center',
    gap: SPACING.md,
  },
  bottomLabel: { fontSize: FONT.sizes.xs, color: COLORS.subtext, textTransform: 'uppercase', letterSpacing: 1 },
  bottomValue: { fontSize: FONT.sizes.xxl, fontWeight: FONT.weights.bold, color: COLORS.text },
});

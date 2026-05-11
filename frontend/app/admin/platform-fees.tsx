/**
 * Admin → Platform Fees
 *
 * Lets a super-admin configure up to 2 extra fees that get applied
 * automatically to every new bill. Each fee has:
 *   - name  (e.g. "Service Fee")
 *   - type  (% of merchant subtotal | flat $ per bill, split equally)
 *   - value
 *   - enabled toggle
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
import { ArrowLeft, DollarSign, Percent, Save } from 'lucide-react-native';
import { adminApi, AdminPlatformFee } from '../../src/adminApi';
import { COLORS, FONT, RADIUS, SPACING } from '../../src/theme';
import { toast } from '../../src/components/Toast';

export default function AdminPlatformFees() {
  const router = useRouter();
  const [fees, setFees] = useState<AdminPlatformFee[]>([]);
  const [busy, setBusy] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const res = await adminApi.getPlatformFees();
        setFees(res.fees);
      } catch (e: any) {
        Alert.alert('Error', e?.message || 'Failed to load fees');
      } finally {
        setBusy(false);
      }
    })();
  }, []);

  const updateFee = (id: string, patch: Partial<AdminPlatformFee>) => {
    setFees((prev) => prev.map((f) => (f.id === id ? { ...f, ...patch } : f)));
  };

  const save = async () => {
    // Lightweight validation: a fee must have a name. The "value" can be
    // 0 — backend ignores zero-value fees, so we don't block the save.
    // Otherwise an enabled toggle with the default value=0 would silently
    // fail validation and never persist, making it look like the toggle
    // "doesn't stick".
    for (const f of fees) {
      if (!f.name?.trim()) {
        Alert.alert('Invalid fee', `"${f.id}" needs a name.`);
        return;
      }
    }
    setSaving(true);
    try {
      const res = await adminApi.updatePlatformFees(fees);
      setFees(res.fees);
      toast.success('Platform fees saved');
    } catch (e: any) {
      Alert.alert('Save failed', e?.message || 'Could not save fees');
    } finally {
      setSaving(false);
    }
  };

  if (busy) {
    return (
      <View style={styles.center}>
        <ActivityIndicator color={COLORS.primary} />
      </View>
    );
  }

  return (
    <ScrollView style={{ flex: 1, backgroundColor: COLORS.bg }} contentContainerStyle={{ padding: SPACING.md }}>
      <View style={styles.headerRow}>
        <TouchableOpacity onPress={() => router.back()} hitSlop={10}>
          <ArrowLeft size={22} color={COLORS.text} />
        </TouchableOpacity>
        <Text style={styles.heading}>Platform Fees</Text>
      </View>

      <Text style={styles.intro}>
        Configure up to 2 additional fees that apply to every new bill.
        Flat fees are split equally across all members; percent fees scale
        with each member's share of the merchant total.
      </Text>

      {fees.map((f) => (
        <View key={f.id} style={styles.card} testID={`fee-card-${f.id}`}>
          <View style={styles.cardHeader}>
            <Text style={styles.slotLabel}>Slot {f.id.replace('extra_', '')}</Text>
            <View style={styles.switchRow}>
              <Text style={styles.enabledText}>{f.enabled ? 'Enabled' : 'Disabled'}</Text>
              <Switch
                value={f.enabled}
                onValueChange={(v) => updateFee(f.id, { enabled: v })}
                trackColor={{ false: COLORS.border, true: COLORS.primary }}
                thumbColor="#fff"
                testID={`fee-toggle-${f.id}`}
              />
            </View>
          </View>

          <Text style={styles.fieldLabel}>Fee name</Text>
          <TextInput
            value={f.name}
            onChangeText={(v) => updateFee(f.id, { name: v })}
            placeholder="e.g. Service Fee"
            placeholderTextColor={COLORS.subtext}
            style={styles.input}
            testID={`fee-name-${f.id}`}
            maxLength={40}
          />

          <Text style={styles.fieldLabel}>Type</Text>
          <View style={styles.typeRow}>
            <TouchableOpacity
              style={[styles.typeBtn, f.type === 'percent' && styles.typeBtnActive]}
              onPress={() => updateFee(f.id, { type: 'percent' })}
              activeOpacity={0.7}
              testID={`fee-type-percent-${f.id}`}
            >
              <Percent size={14} color={f.type === 'percent' ? '#fff' : COLORS.text} />
              <Text style={[styles.typeText, f.type === 'percent' && { color: '#fff' }]}>Percent</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[styles.typeBtn, f.type === 'flat' && styles.typeBtnActive]}
              onPress={() => updateFee(f.id, { type: 'flat' })}
              activeOpacity={0.7}
              testID={`fee-type-flat-${f.id}`}
            >
              <DollarSign size={14} color={f.type === 'flat' ? '#fff' : COLORS.text} />
              <Text style={[styles.typeText, f.type === 'flat' && { color: '#fff' }]}>Flat $</Text>
            </TouchableOpacity>
          </View>

          <Text style={styles.fieldLabel}>
            {f.type === 'percent' ? 'Value (%)' : 'Value ($)'}
          </Text>
          <TextInput
            value={String(f.value)}
            onChangeText={(v) => {
              const n = Number(v.replace(/[^0-9.]/g, ''));
              updateFee(f.id, { value: isFinite(n) ? n : 0 });
            }}
            keyboardType="decimal-pad"
            style={styles.input}
            testID={`fee-value-${f.id}`}
          />

          <Text style={styles.helper}>
            {f.type === 'percent'
              ? `Charges ${f.value}% of each member's merchant share.`
              : `Charges $${Number(f.value).toFixed(2)} per bill, split equally across members.`}
          </Text>
        </View>
      ))}

      <TouchableOpacity
        style={[styles.saveBtn, saving && { opacity: 0.6 }]}
        onPress={save}
        disabled={saving}
        activeOpacity={0.85}
        testID="fee-save-btn"
      >
        {saving ? (
          <ActivityIndicator color="#fff" />
        ) : (
          <>
            <Save size={16} color="#fff" />
            <Text style={styles.saveText}>Save Fees</Text>
          </>
        )}
      </TouchableOpacity>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: COLORS.bg },
  headerRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: SPACING.md,
    marginBottom: SPACING.md,
  },
  heading: { fontSize: FONT.sizes.xl, fontWeight: FONT.weights.heavy, color: COLORS.text },
  intro: { color: COLORS.subtext, fontSize: FONT.sizes.sm, marginBottom: SPACING.md, lineHeight: 20 },
  card: {
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.md,
    padding: SPACING.md,
    borderWidth: 1,
    borderColor: COLORS.border,
    marginBottom: SPACING.md,
  },
  cardHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: SPACING.md },
  slotLabel: { color: COLORS.primary, fontWeight: FONT.weights.bold, fontSize: FONT.sizes.sm, letterSpacing: 1, textTransform: 'uppercase' },
  switchRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  enabledText: { color: COLORS.subtext, fontSize: FONT.sizes.xs, fontWeight: FONT.weights.semibold },
  fieldLabel: { color: COLORS.subtext, fontSize: FONT.sizes.xs, fontWeight: FONT.weights.semibold, marginTop: 8, marginBottom: 4, textTransform: 'uppercase', letterSpacing: 0.6 },
  input: {
    backgroundColor: COLORS.bg,
    borderRadius: RADIUS.sm,
    padding: 10,
    fontSize: FONT.sizes.md,
    color: COLORS.text,
    borderWidth: 1,
    borderColor: COLORS.border,
  },
  typeRow: { flexDirection: 'row', gap: 8 },
  typeBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    flex: 1,
    paddingVertical: 10,
    borderRadius: RADIUS.sm,
    borderWidth: 1,
    borderColor: COLORS.border,
    backgroundColor: COLORS.bg,
  },
  typeBtnActive: { backgroundColor: COLORS.primary, borderColor: COLORS.primary },
  typeText: { color: COLORS.text, fontWeight: FONT.weights.semibold, fontSize: FONT.sizes.sm },
  helper: { color: COLORS.subtext, fontSize: FONT.sizes.xs, marginTop: 8, fontStyle: 'italic' },
  saveBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    backgroundColor: COLORS.primary,
    borderRadius: RADIUS.md,
    paddingVertical: 14,
    marginTop: SPACING.md,
  },
  saveText: { color: '#fff', fontWeight: FONT.weights.bold, fontSize: FONT.sizes.md },
});

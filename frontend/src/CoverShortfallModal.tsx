import React, { useState } from 'react';
import {
  Modal,
  View,
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  KeyboardAvoidingView,
  Platform,
  Alert,
  ScrollView,
} from 'react-native';
import { X, AlertTriangle, HandCoins, Gift } from 'lucide-react-native';
import { Button } from './Button';
import { COLORS, FONT, RADIUS, SPACING } from './theme';
import { api, Group } from './api';

type Props = {
  visible: boolean;
  onClose: () => void;
  onSaved: (g: Group) => void;
  group: Group;
  userId: string;
  maxAmount: number;
};

export function CoverShortfallModal({ visible, onClose, onSaved, group, userId, maxAmount }: Props) {
  const [amountStr, setAmountStr] = useState(String(maxAmount.toFixed(2)));
  const [mode, setMode] = useState<'loan' | 'gift' | null>(null);
  const [step, setStep] = useState<'amount' | 'mode' | 'confirm'>('amount');
  const [saving, setSaving] = useState(false);

  React.useEffect(() => {
    if (visible) {
      setAmountStr(String(maxAmount.toFixed(2)));
      setMode(null);
      setStep('amount');
    }
  }, [visible, maxAmount]);

  const amount = Math.max(0, parseFloat(amountStr) || 0);
  const close = () => {
    if (saving) return;
    onClose();
  };

  const submit = async () => {
    if (!mode) return;
    if (amount <= 0 || amount > maxAmount + 0.01) {
      Alert.alert('Invalid amount', `Enter an amount between $0 and $${maxAmount.toFixed(2)}.`);
      return;
    }
    setSaving(true);
    try {
      const updated = await api.contribute(group.id, userId, amount, false, {
        cover_shortfall: true,
        is_loan: mode === 'loan',
      });
      onSaved(updated);
      onClose();
      Alert.alert(
        mode === 'loan' ? '💰 Loan recorded' : '🎁 Gift recorded',
        mode === 'loan'
          ? `You loaned $${amount.toFixed(2)} to the group. You can withdraw it any time from the summary screen.`
          : `You gifted $${amount.toFixed(2)} to the group. This won't be repaid.`,
      );
    } catch (e: any) {
      Alert.alert('Could not save', e?.message || 'Please try again.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal visible={visible} animationType="slide" transparent onRequestClose={close}>
      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        style={styles.backdrop}
      >
        <View style={styles.sheet}>
          <View style={styles.handle} />
          <View style={styles.headerRow}>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
              <AlertTriangle size={20} color={COLORS.warning} />
              <Text style={styles.title}>Cover the shortfall</Text>
            </View>
            <TouchableOpacity onPress={close} style={styles.closeBtn} testID="cover-shortfall-close">
              <X size={20} color={COLORS.subtext} />
            </TouchableOpacity>
          </View>

          <ScrollView style={{ maxHeight: 460 }} keyboardShouldPersistTaps="handled">
            {step === 'amount' && (
              <>
                <View style={styles.warnBox}>
                  <Text style={styles.warnTitle}>Heads up</Text>
                  <Text style={styles.warnBody}>
                    The lead has not yet covered the bill. By contributing extra, you keep the group moving — but please decide carefully whether this is a loan or a gift on the next step.
                  </Text>
                </View>
                <Text style={styles.label}>Amount you want to cover</Text>
                <TextInput
                  testID="cover-shortfall-amount"
                  style={styles.input}
                  value={amountStr}
                  onChangeText={setAmountStr}
                  placeholder={`Up to $${maxAmount.toFixed(2)}`}
                  placeholderTextColor={COLORS.disabledText}
                  keyboardType="decimal-pad"
                />
                <Text style={styles.hint}>
                  Maximum: ${maxAmount.toFixed(2)} (the current shortfall)
                </Text>
                <Button
                  title="Continue"
                  onPress={() => {
                    if (amount <= 0 || amount > maxAmount + 0.01) {
                      Alert.alert('Invalid amount', `Enter an amount between $0.01 and $${maxAmount.toFixed(2)}.`);
                      return;
                    }
                    setStep('mode');
                  }}
                  testID="cover-shortfall-amount-next"
                />
              </>
            )}

            {step === 'mode' && (
              <>
                <Text style={styles.label}>Choose carefully — this affects what you can recover</Text>
                <TouchableOpacity
                  testID="cover-shortfall-loan-card"
                  style={[styles.modeCard, mode === 'loan' && styles.modeCardActive]}
                  activeOpacity={0.85}
                  onPress={() => setMode('loan')}
                >
                  <HandCoins size={20} color={mode === 'loan' ? '#fff' : COLORS.primary} />
                  <View style={{ flex: 1 }}>
                    <Text style={[styles.modeTitle, mode === 'loan' && { color: '#fff' }]}>Loan — get it back</Text>
                    <Text style={[styles.modeBody, mode === 'loan' && { color: '#E0E7FF' }]}>
                      You can withdraw your ${amount.toFixed(2)} from the wallet at any time. Use this if you expect to be repaid.
                    </Text>
                  </View>
                  <View style={[styles.radio, mode === 'loan' && styles.radioActive]}>
                    {mode === 'loan' && <View style={styles.radioDot} />}
                  </View>
                </TouchableOpacity>
                <TouchableOpacity
                  testID="cover-shortfall-gift-card"
                  style={[styles.modeCard, mode === 'gift' && styles.modeCardGiftActive]}
                  activeOpacity={0.85}
                  onPress={() => setMode('gift')}
                >
                  <Gift size={20} color={mode === 'gift' ? '#fff' : COLORS.success} />
                  <View style={{ flex: 1 }}>
                    <Text style={[styles.modeTitle, mode === 'gift' && { color: '#fff' }]}>Gift — final, no return</Text>
                    <Text style={[styles.modeBody, mode === 'gift' && { color: '#D1FAE5' }]}>
                      Your ${amount.toFixed(2)} is donated to the group permanently. You will NOT be able to withdraw or be repaid.
                    </Text>
                  </View>
                  <View style={[styles.radio, mode === 'gift' && styles.radioActiveGift]}>
                    {mode === 'gift' && <View style={styles.radioDot} />}
                  </View>
                </TouchableOpacity>
                <Button
                  title="Continue"
                  onPress={() => {
                    if (!mode) {
                      Alert.alert('Choose one', 'Pick Loan or Gift to continue.');
                      return;
                    }
                    setStep('confirm');
                  }}
                  disabled={!mode}
                  testID="cover-shortfall-mode-next"
                />
              </>
            )}

            {step === 'confirm' && mode && (
              <>
                <View style={[styles.warnBox, mode === 'gift' && { backgroundColor: '#FEF3C7', borderColor: '#F59E0B' }]}>
                  <Text style={styles.warnTitle}>
                    {mode === 'loan' ? 'Confirm your loan' : '⚠️ One last check — this is a GIFT'}
                  </Text>
                  <Text style={styles.warnBody}>
                    {mode === 'loan'
                      ? `You're loaning $${amount.toFixed(2)} to cover the shortfall. You'll be able to withdraw it from the wallet whenever you want.`
                      : `You are about to GIFT $${amount.toFixed(2)} to the group. This is final — once submitted you cannot get this money back. Are you sure?`}
                  </Text>
                </View>
                <Button
                  title={saving ? 'Saving…' : mode === 'loan' ? `Loan $${amount.toFixed(2)}` : `Gift $${amount.toFixed(2)} (final)`}
                  onPress={submit}
                  disabled={saving}
                  testID="cover-shortfall-submit"
                  variant={mode === 'gift' ? 'secondary' : 'primary'}
                />
                <TouchableOpacity onPress={() => setStep('mode')} style={{ marginTop: 12, alignSelf: 'center' }}>
                  <Text style={{ color: COLORS.subtext, fontSize: FONT.sizes.sm }}>← Back to choose loan/gift</Text>
                </TouchableOpacity>
              </>
            )}
          </ScrollView>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: 'rgba(0,0,0,0.45)', justifyContent: 'flex-end' },
  sheet: {
    backgroundColor: COLORS.bg,
    borderTopLeftRadius: RADIUS.lg,
    borderTopRightRadius: RADIUS.lg,
    padding: SPACING.lg,
    paddingBottom: SPACING.xl + SPACING.lg,
    gap: SPACING.sm,
  },
  handle: {
    width: 36,
    height: 4,
    backgroundColor: COLORS.border,
    alignSelf: 'center',
    borderRadius: 2,
    marginBottom: SPACING.md,
  },
  headerRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: SPACING.sm },
  title: { fontSize: FONT.sizes.lg, fontWeight: FONT.weights.bold, color: COLORS.text },
  closeBtn: { padding: 4 },
  warnBox: {
    backgroundColor: COLORS.warningLight,
    padding: SPACING.md,
    borderRadius: RADIUS.md,
    borderWidth: 1,
    borderColor: COLORS.warning,
    marginBottom: SPACING.md,
  },
  warnTitle: { color: '#92400E', fontWeight: FONT.weights.bold, fontSize: FONT.sizes.sm, marginBottom: 4 },
  warnBody: { color: '#92400E', fontSize: FONT.sizes.sm, lineHeight: 20 },
  label: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginBottom: 6, marginTop: SPACING.sm },
  input: {
    height: 52,
    borderRadius: RADIUS.md,
    borderWidth: 1.5,
    borderColor: COLORS.border,
    backgroundColor: COLORS.surface,
    paddingHorizontal: SPACING.md,
    color: COLORS.text,
    fontSize: FONT.sizes.lg,
    fontWeight: FONT.weights.semibold,
    marginBottom: SPACING.sm,
  },
  hint: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginBottom: SPACING.md },
  modeCard: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: SPACING.sm,
    padding: SPACING.md,
    borderRadius: RADIUS.md,
    borderWidth: 1.5,
    borderColor: COLORS.border,
    backgroundColor: COLORS.surface,
    marginBottom: SPACING.sm,
  },
  modeCardActive: { borderColor: COLORS.primary, backgroundColor: COLORS.primary },
  modeCardGiftActive: { borderColor: COLORS.success, backgroundColor: COLORS.success },
  modeTitle: { color: COLORS.text, fontWeight: FONT.weights.bold, fontSize: FONT.sizes.md, marginBottom: 2 },
  modeBody: { color: COLORS.subtext, fontSize: FONT.sizes.sm, lineHeight: 18 },
  radio: { width: 18, height: 18, borderRadius: 9, borderWidth: 2, borderColor: COLORS.border, alignItems: 'center', justifyContent: 'center' },
  radioActive: { borderColor: '#fff' },
  radioActiveGift: { borderColor: '#fff' },
  radioDot: { width: 8, height: 8, borderRadius: 4, backgroundColor: '#fff' },
});

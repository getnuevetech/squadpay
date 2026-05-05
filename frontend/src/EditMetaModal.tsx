import React, { useState, useEffect } from 'react';
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
} from 'react-native';
import { X } from 'lucide-react-native';
import { Button } from './Button';
import { COLORS, FONT, RADIUS, SPACING } from './theme';
import { api, Group } from './api';

type Props = {
  visible: boolean;
  onClose: () => void;
  onSaved: (g: Group) => void;
  group: Group;
  userId: string;
  field: 'title' | 'tax_tip';
};

export function EditMetaModal({ visible, onClose, onSaved, group, userId, field }: Props) {
  const [title, setTitle] = useState(group.title);
  const [tax, setTax] = useState(String(group.tax || ''));
  const [tip, setTip] = useState(String(group.tip || ''));
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (visible) {
      setTitle(group.title);
      setTax(String(group.tax || ''));
      setTip(String(group.tip || ''));
    }
  }, [visible, group]);

  const save = async () => {
    setSaving(true);
    try {
      const payload: any = {};
      if (field === 'title') {
        const t = title.trim();
        if (!t) {
          Alert.alert('Title required', 'Please enter a non-empty bill name.');
          setSaving(false);
          return;
        }
        payload.title = t;
      } else {
        payload.tax = parseFloat(tax) || 0;
        payload.tip = parseFloat(tip) || 0;
      }
      const updated = await api.updateGroupMeta(group.id, userId, payload);
      onSaved(updated);
      onClose();
    } catch (e: any) {
      Alert.alert('Could not save', e?.message || 'Please try again.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal visible={visible} animationType="slide" transparent onRequestClose={onClose}>
      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        style={styles.backdrop}
      >
        <View style={styles.sheet}>
          <View style={styles.handle} />
          <View style={styles.headerRow}>
            <Text style={styles.title}>
              {field === 'title' ? 'Rename bill' : 'Update tax & tip'}
            </Text>
            <TouchableOpacity onPress={onClose} style={styles.closeBtn} testID="edit-meta-close">
              <X size={20} color={COLORS.subtext} />
            </TouchableOpacity>
          </View>
          {field === 'title' ? (
            <>
              <Text style={styles.label}>Bill name</Text>
              <TextInput
                testID="edit-title-input"
                style={styles.input}
                value={title}
                onChangeText={setTitle}
                placeholder="Dinner at Joe's"
                placeholderTextColor={COLORS.disabledText}
                autoFocus
              />
              <Text style={styles.hint}>You can rename until all members finish contributing.</Text>
            </>
          ) : (
            <>
              <View style={styles.row}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.label}>Tax ($)</Text>
                  <TextInput
                    testID="edit-tax-input"
                    style={styles.input}
                    value={tax}
                    onChangeText={setTax}
                    placeholder="0"
                    placeholderTextColor={COLORS.disabledText}
                    keyboardType="decimal-pad"
                  />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.label}>Tip ($)</Text>
                  <TextInput
                    testID="edit-tip-input"
                    style={styles.input}
                    value={tip}
                    onChangeText={setTip}
                    placeholder="0"
                    placeholderTextColor={COLORS.disabledText}
                    keyboardType="decimal-pad"
                  />
                </View>
              </View>
              <Text style={styles.hint}>Total updates immediately after saving.</Text>
            </>
          )}
          <Button
            title={saving ? 'Saving…' : 'Save changes'}
            onPress={save}
            disabled={saving}
            testID="edit-meta-save"
          />
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
  headerRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  title: { fontSize: FONT.sizes.lg, fontWeight: FONT.weights.bold, color: COLORS.text },
  closeBtn: { padding: 4 },
  label: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginBottom: 6, marginTop: SPACING.sm },
  input: {
    height: 48,
    borderRadius: RADIUS.md,
    borderWidth: 1.5,
    borderColor: COLORS.border,
    backgroundColor: COLORS.surface,
    paddingHorizontal: SPACING.md,
    color: COLORS.text,
    fontSize: FONT.sizes.md,
    marginBottom: SPACING.sm,
  },
  hint: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginBottom: SPACING.md },
  row: { flexDirection: 'row', gap: SPACING.md },
});

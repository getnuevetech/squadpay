/**
 * Cross-platform confirmation modal.
 *
 * Why this exists: React Native Web's `Alert.alert` silently collapses
 * multi-button alerts to a single OK button, which means destructive
 * actions like "Remove member?" or "Delete bill?" never fire on web.
 * This component mirrors the iOS-style "destructive action sheet" using a
 * `Modal` so it works identically on iOS, Android, and Web.
 *
 * Usage:
 *
 *   const [open, setOpen] = useState(false);
 *   <ConfirmModal
 *     visible={open}
 *     onClose={() => setOpen(false)}
 *     title="Remove Krish?"
 *     message="They'll be removed from this bill and their item claims released."
 *     confirmLabel="Remove"
 *     destructive
 *     onConfirm={() => doRemove()}
 *   />
 */
import React from 'react';
import { Modal, Pressable, StyleSheet, Text, View } from 'react-native';
import { COLORS, FONT, RADIUS, SPACING } from './theme';

interface ConfirmModalProps {
  visible: boolean;
  title: string;
  message?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  destructive?: boolean;
  onConfirm: () => void;
  onClose: () => void;
  testID?: string;
}

export function ConfirmModal({
  visible,
  title,
  message,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  destructive = false,
  onConfirm,
  onClose,
  testID = 'confirm-modal',
}: ConfirmModalProps) {
  return (
    <Modal
      transparent
      visible={visible}
      animationType="fade"
      onRequestClose={onClose}
    >
      <Pressable
        style={styles.backdrop}
        onPress={onClose}
        testID={`${testID}-backdrop`}
      >
        {/* Inner pressable swallows taps so they don't dismiss the modal. */}
        <Pressable style={styles.card} onPress={() => undefined}>
          <Text style={styles.title} testID={`${testID}-title`}>{title}</Text>
          {message ? <Text style={styles.message}>{message}</Text> : null}
          <View style={styles.actions}>
            <Pressable
              style={[styles.button, styles.cancelBtn]}
              onPress={onClose}
              testID={`${testID}-cancel`}
            >
              <Text style={styles.cancelText}>{cancelLabel}</Text>
            </Pressable>
            <Pressable
              style={[
                styles.button,
                destructive ? styles.destructiveBtn : styles.confirmBtn,
              ]}
              onPress={() => {
                onConfirm();
                onClose();
              }}
              testID={`${testID}-confirm`}
            >
              <Text
                style={destructive ? styles.destructiveText : styles.confirmText}
              >
                {confirmLabel}
              </Text>
            </Pressable>
          </View>
        </Pressable>
      </Pressable>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: 'rgba(15, 9, 36, 0.55)',
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: SPACING.lg,
  },
  card: {
    width: '100%',
    maxWidth: 360,
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.lg,
    padding: SPACING.lg,
    gap: SPACING.md,
    shadowColor: '#000',
    shadowOpacity: 0.25,
    shadowRadius: 20,
    shadowOffset: { width: 0, height: 12 },
    elevation: 12,
  },
  title: {
    fontSize: FONT.sizes.lg,
    fontWeight: FONT.weights.heavy,
    color: COLORS.text,
    letterSpacing: -0.3,
  },
  message: { color: COLORS.subtext, fontSize: FONT.sizes.sm, lineHeight: 20 },
  actions: { flexDirection: 'row', gap: SPACING.sm, marginTop: SPACING.sm },
  button: {
    flex: 1,
    minHeight: 44,
    borderRadius: RADIUS.md,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: SPACING.md,
  },
  cancelBtn: { backgroundColor: COLORS.bg, borderWidth: 1, borderColor: COLORS.border },
  cancelText: { color: COLORS.text, fontWeight: FONT.weights.semibold, fontSize: FONT.sizes.sm },
  confirmBtn: { backgroundColor: COLORS.primary },
  confirmText: { color: '#fff', fontWeight: FONT.weights.bold, fontSize: FONT.sizes.sm },
  destructiveBtn: { backgroundColor: '#DC2626' },
  destructiveText: { color: '#fff', fontWeight: FONT.weights.bold, fontSize: FONT.sizes.sm },
});

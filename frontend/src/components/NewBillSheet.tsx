/**
 * NewBillSheet — small modal action sheet shown when the user taps the
 * BIG "+" on the FeaturedBillCard (or any other "new bill" entry point)
 * while they already have an active bill. Offers a clear choice between
 * starting a brand-new split or joining one with a code/QR.
 */
import React from 'react';
import { Modal, Pressable, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { Plus, QrCode, X } from 'lucide-react-native';
import { COLORS, FONT, RADIUS, SHADOW, SPACING } from '../theme';

type Props = {
  visible: boolean;
  onClose: () => void;
  onStart: () => void;
  onJoin: () => void;
  testID?: string;
};

export function NewBillSheet({ visible, onClose, onStart, onJoin, testID = 'new-bill-sheet' }: Props) {
  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <Pressable style={styles.backdrop} onPress={onClose} testID={`${testID}-backdrop`}>
        <Pressable style={styles.sheet} onPress={(e) => e.stopPropagation()} testID={testID}>
          <View style={styles.header}>
            <Text style={styles.title}>New bill</Text>
            <TouchableOpacity onPress={onClose} hitSlop={10} testID={`${testID}-close`}>
              <X size={20} color={COLORS.text} />
            </TouchableOpacity>
          </View>
          <Text style={styles.subtitle}>What would you like to do?</Text>

          <TouchableOpacity
            style={styles.row}
            onPress={() => {
              onClose();
              onStart();
            }}
            activeOpacity={0.85}
            testID={`${testID}-start`}
          >
            <View style={[styles.icon, { backgroundColor: COLORS.primaryLight }]}>
              <Plus size={20} color={COLORS.primary} />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.rowTitle}>Start a new bill</Text>
              <Text style={styles.rowSub}>Snap a receipt or enter the total to split.</Text>
            </View>
          </TouchableOpacity>

          <TouchableOpacity
            style={styles.row}
            onPress={() => {
              onClose();
              onJoin();
            }}
            activeOpacity={0.85}
            testID={`${testID}-join`}
          >
            <View style={[styles.icon, { backgroundColor: '#E0F2FE' }]}>
              <QrCode size={20} color="#0284C7" />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.rowTitle}>Join a bill</Text>
              <Text style={styles.rowSub}>Use the 8-character code or scan a QR.</Text>
            </View>
          </TouchableOpacity>
        </Pressable>
      </Pressable>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: 'rgba(15,23,42,0.55)',
    justifyContent: 'flex-end',
  },
  sheet: {
    backgroundColor: COLORS.surface,
    borderTopLeftRadius: RADIUS.xl,
    borderTopRightRadius: RADIUS.xl,
    paddingHorizontal: SPACING.lg,
    paddingTop: SPACING.lg,
    paddingBottom: SPACING.xl + SPACING.md,
    gap: SPACING.md,
    ...SHADOW.xl,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  title: {
    fontSize: FONT.sizes.xl,
    fontWeight: FONT.weights.heavy,
    color: COLORS.text,
    letterSpacing: -0.4,
  },
  subtitle: {
    fontSize: FONT.sizes.sm,
    color: COLORS.subtext,
    marginTop: -SPACING.xs,
    marginBottom: SPACING.xs,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 14,
    padding: SPACING.md,
    backgroundColor: COLORS.bg,
    borderRadius: RADIUS.lg,
    borderWidth: 1,
    borderColor: COLORS.border,
  },
  icon: {
    width: 44,
    height: 44,
    borderRadius: 22,
    alignItems: 'center',
    justifyContent: 'center',
  },
  rowTitle: {
    fontSize: FONT.sizes.md,
    fontWeight: FONT.weights.bold,
    color: COLORS.text,
  },
  rowSub: {
    fontSize: FONT.sizes.xs,
    color: COLORS.subtext,
    marginTop: 2,
  },
});

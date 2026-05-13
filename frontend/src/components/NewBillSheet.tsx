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
import { SquadPayMark } from './redesign/SquadPayMark';

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
          {/* Header — replaces the previous "New bill" + helper subtitle with
              the SquadPay brand mark (consistent with the homepage hero), so
              users always recognize where the choice originates. */}
          <View style={styles.header}>
            <SquadPayMark size={36} testID={`${testID}-brand`} />
            <TouchableOpacity onPress={onClose} hitSlop={10} testID={`${testID}-close`}>
              <X size={20} color={COLORS.text} />
            </TouchableOpacity>
          </View>

          <TouchableOpacity
            style={styles.row}
            onPress={() => {
              onClose();
              onStart();
            }}
            activeOpacity={0.85}
            testID={`${testID}-start`}
          >
            <View style={styles.iconOnPurple}>
              <Plus size={20} color="#fff" />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.rowTitle}>Start a Bill</Text>
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
            <View style={styles.iconOnPurple}>
              <QrCode size={20} color="#fff" />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.rowTitle}>Join a Bill</Text>
              <Text style={styles.rowSub}>Use the squad code or scan a QR.</Text>
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
    backgroundColor: COLORS.primary,
    borderRadius: RADIUS.lg,
    ...SHADOW.primary,
  },
  icon: {
    width: 44,
    height: 44,
    borderRadius: 22,
    alignItems: 'center',
    justifyContent: 'center',
  },
  iconOnPurple: {
    width: 44,
    height: 44,
    borderRadius: 22,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: 'rgba(255,255,255,0.22)',
  },
  rowTitle: {
    fontSize: FONT.sizes.md,
    fontWeight: FONT.weights.bold,
    color: '#FFFFFF',
  },
  rowSub: {
    fontSize: FONT.sizes.xs,
    color: 'rgba(255,255,255,0.85)',
    marginTop: 2,
  },
});

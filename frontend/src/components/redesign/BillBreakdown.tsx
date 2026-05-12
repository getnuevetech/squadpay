/**
 * BillBreakdown — collapsible breakdown card showing items / tax / tip /
 * transaction fees / platform fees / admin extra fees / bill total /
 * contributed / repaid / outstanding.
 *
 * Shared between Lead and User dashboards so the math stays self-consistent
 * across the two screens. Driven entirely by the values returned from
 * `useBillMath()`.
 */
import React, { useState } from 'react';
import { StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { ChevronDown } from 'lucide-react-native';
import { COLORS, FONT, RADIUS, SPACING } from '../../theme';
import type { Group } from '../../api';
import type { ExtraFeeAgg } from '../../hooks/useBillMath';

interface BillBreakdownProps {
  group: Group;
  groupItemsTotal: number;
  groupTransactionFees: number;
  groupPlatformFees: number;
  extraFeesAgg: ExtraFeeAgg[];
  grandTotal: number;
  groupContributedTotal: number;
  groupRepaidTotal: number;
  groupOutstandingTotal: number;
  testIDPrefix: string;
}

export function BillBreakdown({
  group,
  groupItemsTotal,
  groupTransactionFees,
  groupPlatformFees,
  extraFeesAgg,
  grandTotal,
  groupContributedTotal,
  groupRepaidTotal,
  groupOutstandingTotal,
  testIDPrefix,
}: BillBreakdownProps) {
  const [open, setOpen] = useState(false);

  return (
    <View style={styles.yourCard}>
      <TouchableOpacity
        onPress={() => setOpen((v) => !v)}
        activeOpacity={0.7}
        style={styles.yourCardHeader}
        testID={`${testIDPrefix}-breakdown-toggle`}
      >
        <Text style={styles.yourLabel}>Bill / Fund Breakdown</Text>
        <View style={[open && { transform: [{ rotate: '180deg' }] }]}>
          <ChevronDown size={18} color={COLORS.subtext} />
        </View>
      </TouchableOpacity>
      {open && (
        <>
          <View style={styles.breakdownRow}>
            <Text style={styles.breakdownKey}>Items subtotal</Text>
            <Text style={styles.breakdownVal}>${groupItemsTotal.toFixed(2)}</Text>
          </View>
          <View style={styles.breakdownRow}>
            <Text style={styles.breakdownKey}>Tax</Text>
            <Text style={styles.breakdownVal}>${Number(group.tax || 0).toFixed(2)}</Text>
          </View>
          <View style={styles.breakdownRow}>
            <Text style={styles.breakdownKey}>Tip</Text>
            <Text style={styles.breakdownVal}>${Number(group.tip || 0).toFixed(2)}</Text>
          </View>
          <View style={styles.breakdownRow}>
            <Text style={styles.breakdownKey}>Transaction fees (3%)</Text>
            <Text style={styles.breakdownVal}>${groupTransactionFees.toFixed(2)}</Text>
          </View>
          <View style={styles.breakdownRow}>
            <Text style={styles.breakdownKey}>Platform fees</Text>
            <Text style={styles.breakdownVal}>${groupPlatformFees.toFixed(2)}</Text>
          </View>
          {extraFeesAgg.map((ef) => (
            <View key={ef.id} style={styles.breakdownRow}>
              <Text style={styles.breakdownKey}>{ef.name}</Text>
              <Text style={styles.breakdownVal}>${ef.amount.toFixed(2)}</Text>
            </View>
          ))}
          <View
            style={[
              styles.breakdownRow,
              { borderTopWidth: 1, borderTopColor: COLORS.border, marginTop: 6, paddingTop: 6 },
            ]}
          >
            <Text style={[styles.breakdownKey, { fontWeight: FONT.weights.bold, color: COLORS.text }]}>
              Bill total
            </Text>
            <Text
              style={[styles.breakdownVal, { color: COLORS.text, fontWeight: FONT.weights.bold }]}
            >
              ${grandTotal.toFixed(2)}
            </Text>
          </View>
          {groupContributedTotal > 0 ? (
            <View style={styles.breakdownRow}>
              <Text style={styles.breakdownKey}>Contributed</Text>
              <Text style={[styles.breakdownVal, { color: COLORS.success }]}>
                −${groupContributedTotal.toFixed(2)}
              </Text>
            </View>
          ) : null}
          {groupRepaidTotal > 0 ? (
            <View style={styles.breakdownRow}>
              <Text style={styles.breakdownKey}>Repaid</Text>
              <Text style={[styles.breakdownVal, { color: COLORS.success }]}>
                −${groupRepaidTotal.toFixed(2)}
              </Text>
            </View>
          ) : null}
          <View
            style={[
              styles.breakdownRow,
              { borderTopWidth: 1, borderTopColor: COLORS.border, marginTop: 6, paddingTop: 6 },
            ]}
          >
            <Text style={[styles.breakdownKey, { fontWeight: FONT.weights.bold, color: COLORS.text }]}>
              Outstanding
            </Text>
            <Text
              style={[
                styles.breakdownVal,
                {
                  fontSize: FONT.sizes.lg,
                  color: COLORS.primary,
                  fontWeight: FONT.weights.heavy,
                },
              ]}
            >
              ${groupOutstandingTotal.toFixed(2)}
            </Text>
          </View>
        </>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  yourCard: {
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.md,
    padding: SPACING.md,
    marginBottom: SPACING.md,
    borderWidth: 1,
    borderColor: COLORS.border,
  },
  yourCardHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  yourLabel: {
    // June 2025 — boldface this label per UX request. Was subtext-color
    // semibold; now uses the main text color with the heaviest weight to
    // make the breakdown section feel like a primary heading.
    color: COLORS.text,
    fontSize: FONT.sizes.sm,
    textTransform: 'uppercase',
    letterSpacing: 1,
    fontWeight: FONT.weights.heavy,
    marginBottom: SPACING.sm,
  },
  breakdownRow: { flexDirection: 'row', justifyContent: 'space-between', paddingVertical: 4 },
  breakdownKey: { color: COLORS.subtext, fontSize: FONT.sizes.sm },
  breakdownVal: { color: COLORS.text, fontSize: FONT.sizes.sm, fontWeight: FONT.weights.semibold },
});

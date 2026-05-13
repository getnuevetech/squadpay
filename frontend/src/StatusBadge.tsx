import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { COLORS, FONT, RADIUS } from './theme';

export type DerivedStatus =
  | 'open'
  | 'contributing'
  | 'contributed'
  | 'lead_paid'
  | 'bill_settled'
  // legacy values kept for back-compat with older API responses
  | 'bill_created'
  | 'settled_with_debt'
  | 'repaying'
  | 'settled';

const STATUS_META: Record<DerivedStatus, { label: string; bg: string; fg: string }> = {
  open: { label: 'Open', bg: COLORS.primaryLight, fg: COLORS.primary },
  contributing: { label: 'Contributing', bg: COLORS.warningLight, fg: COLORS.warning },
  contributed: { label: 'Contributed', bg: '#DBEAFE', fg: '#1D4ED8' },
  lead_paid: { label: 'Lead Paid', bg: '#E0E7FF', fg: '#4338CA' },
  bill_settled: { label: 'Bill Settled', bg: COLORS.successLight, fg: COLORS.success },
  // legacy mappings — map onto closest new state
  bill_created: { label: 'Open', bg: COLORS.primaryLight, fg: COLORS.primary },
  settled_with_debt: { label: 'Contributed', bg: '#DBEAFE', fg: '#1D4ED8' },
  repaying: { label: 'Contributing', bg: COLORS.warningLight, fg: COLORS.warning },
  settled: { label: 'Bill Settled', bg: COLORS.successLight, fg: COLORS.success },
};

export function StatusBadge({
  status,
  size = 'sm',
  testID,
}: {
  status?: DerivedStatus | string | null;
  size?: 'sm' | 'md';
  testID?: string;
}) {
  const meta = STATUS_META[(status as DerivedStatus) || 'contributing'] || STATUS_META.contributing;
  return (
    <View
      style={[
        styles.pill,
        size === 'md' && styles.pillMd,
        { backgroundColor: meta.bg },
      ]}
      testID={testID}
    >
      <View style={[styles.dot, { backgroundColor: meta.fg }]} />
      <Text style={[styles.text, size === 'md' && styles.textMd, { color: meta.fg }]}>{meta.label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  pill: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: RADIUS.pill,
    alignSelf: 'flex-start',
  },
  pillMd: {
    paddingHorizontal: 10,
    paddingVertical: 6,
    gap: 8,
  },
  dot: {
    width: 6,
    height: 6,
    borderRadius: 3,
  },
  text: {
    fontSize: FONT.sizes.xs,
    fontWeight: FONT.weights.semibold,
  },
  textMd: {
    fontSize: FONT.sizes.sm,
  },
});

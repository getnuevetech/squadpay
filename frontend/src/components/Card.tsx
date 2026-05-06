/**
 * Card — single source for elevated surfaces. Accepts an optional `tone`
 * (default | elevated | flat) and an optional `padding` size.
 */
import React from 'react';
import { StyleSheet, View, ViewProps } from 'react-native';
import { COLORS, RADIUS, SHADOW, SPACING } from '../theme';

type Tone = 'default' | 'elevated' | 'flat' | 'inset';
type PadSize = 'none' | 'sm' | 'md' | 'lg';

export function Card({
  tone = 'default',
  padding = 'md',
  style,
  children,
  testID,
  ...rest
}: ViewProps & { tone?: Tone; padding?: PadSize }) {
  const padMap: Record<PadSize, number> = { none: 0, sm: SPACING.sm, md: SPACING.md, lg: SPACING.lg };
  return (
    <View
      testID={testID}
      style={[
        styles.base,
        tone === 'elevated' && [styles.elevated, SHADOW.md],
        tone === 'flat' && styles.flat,
        tone === 'inset' && styles.inset,
        { padding: padMap[padding] },
        style,
      ]}
      {...rest}
    >
      {children}
    </View>
  );
}

const styles = StyleSheet.create({
  base: {
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.lg,
    borderWidth: 1,
    borderColor: COLORS.border,
  },
  elevated: { borderColor: 'transparent' },
  flat: { borderColor: COLORS.border, backgroundColor: COLORS.surface },
  inset: { backgroundColor: COLORS.slate50 },
});

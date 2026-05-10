/**
 * EmptyState — illustrated empty state with title, subtitle, and optional CTA.
 * Centers everything; pass an `Icon` (lucide component) for the visual.
 */
import React from 'react';
import { StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { COLORS, FONT, RADIUS, SPACING } from '../theme';

type Props = {
  Icon?: React.ComponentType<{ color?: string; size?: number; strokeWidth?: number }>;
  icon?: React.ReactNode;
  title: string;
  subtitle?: string;
  cta?: { label: string; onPress: () => void; testID?: string };
  testID?: string;
};

export function EmptyState({ Icon, icon, title, subtitle, cta, testID }: Props) {
  return (
    <View style={styles.wrap} testID={testID}>
      <View style={styles.iconHalo}>
        <View style={styles.iconCircle}>
          {Icon ? (
            <Icon color={COLORS.primary} size={28} strokeWidth={1.8} />
          ) : (
            icon ?? null
          )}
        </View>
      </View>
      <Text style={styles.title}>{title}</Text>
      {subtitle ? <Text style={styles.subtitle}>{subtitle}</Text> : null}
      {cta ? (
        <TouchableOpacity
          onPress={cta.onPress}
          style={styles.cta}
          activeOpacity={0.85}
          testID={cta.testID}
        >
          <Text style={styles.ctaText}>{cta.label}</Text>
        </TouchableOpacity>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    alignItems: 'center',
    paddingVertical: SPACING.xxl,
    paddingHorizontal: SPACING.lg,
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.lg,
    borderWidth: 1,
    borderColor: COLORS.border,
  },
  iconHalo: {
    width: 88,
    height: 88,
    borderRadius: 44,
    backgroundColor: COLORS.primaryLight,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: SPACING.md,
  },
  iconCircle: {
    width: 64,
    height: 64,
    borderRadius: 32,
    backgroundColor: COLORS.primarySoft,
    alignItems: 'center',
    justifyContent: 'center',
  },
  title: {
    fontSize: FONT.sizes.lg,
    fontWeight: FONT.weights.bold,
    color: COLORS.text,
    textAlign: 'center',
  },
  subtitle: {
    marginTop: 6,
    fontSize: FONT.sizes.sm,
    color: COLORS.subtext,
    textAlign: 'center',
    maxWidth: 320,
    lineHeight: 20,
  },
  cta: {
    marginTop: SPACING.lg,
    paddingHorizontal: SPACING.lg,
    paddingVertical: 12,
    borderRadius: RADIUS.pill,
    backgroundColor: COLORS.primary,
  },
  ctaText: {
    color: '#fff',
    fontSize: FONT.sizes.sm,
    fontWeight: FONT.weights.bold,
  },
});

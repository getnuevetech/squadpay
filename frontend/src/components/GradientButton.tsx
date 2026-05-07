// GradientButton — primary CTA with brand violet→indigo gradient.
// Drop-in replacement for primary <Button/> when we want a more vibrant feel.
// Uses expo-linear-gradient under the hood; falls back gracefully on web.
import React from 'react';
import { ActivityIndicator, StyleSheet, Text, View, ViewStyle, StyleProp, TextStyle } from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { COLORS, FONT, RADIUS, SHADOW } from '../theme';
import { PressableScale } from './PressableScale';

interface Props {
  title: string;
  onPress: () => void;
  loading?: boolean;
  disabled?: boolean;
  testID?: string;
  icon?: React.ReactNode;
  style?: StyleProp<ViewStyle>;
  textStyle?: StyleProp<TextStyle>;
  size?: 'md' | 'lg';
}

export function GradientButton({
  title,
  onPress,
  loading,
  disabled,
  testID,
  icon,
  style,
  textStyle,
  size = 'lg',
}: Props) {
  const isDisabled = disabled || loading;
  const verticalPad = size === 'lg' ? 18 : 14;

  return (
    <PressableScale
      testID={testID}
      onPress={onPress}
      disabled={isDisabled}
      scaleTo={0.97}
      style={[styles.wrap, SHADOW.primary, isDisabled && styles.disabled, style]}
    >
      <LinearGradient
        colors={isDisabled ? [COLORS.disabledBg, COLORS.disabledBg] : [COLORS.gradientStart, COLORS.gradientEnd]}
        start={{ x: 0, y: 0 }}
        end={{ x: 1, y: 1 }}
        style={[styles.gradient, { paddingVertical: verticalPad }]}
      >
        {loading ? (
          <ActivityIndicator color="#fff" />
        ) : (
          <View style={styles.row}>
            {icon ? <View style={styles.icon}>{icon}</View> : null}
            <Text style={[styles.text, isDisabled && styles.textDisabled, textStyle]} numberOfLines={1}>
              {title}
            </Text>
          </View>
        )}
      </LinearGradient>
    </PressableScale>
  );
}

const styles = StyleSheet.create({
  wrap: {
    borderRadius: RADIUS.pill,
    overflow: 'hidden',
  },
  gradient: {
    paddingHorizontal: 24,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: RADIUS.pill,
  },
  row: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  icon: { marginRight: 4 },
  text: {
    color: '#FFFFFF',
    fontSize: FONT.sizes.md,
    fontWeight: FONT.weights.bold,
    letterSpacing: 0.2,
  },
  textDisabled: { color: COLORS.disabledText },
  disabled: { opacity: 0.6 },
});

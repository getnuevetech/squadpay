import React from 'react';
import {
  ActivityIndicator,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
  ViewStyle,
} from 'react-native';
import { COLORS, FONT, RADIUS } from './theme';

type Variant = 'primary' | 'secondary' | 'outline' | 'danger' | 'ghost';

type Props = {
  title: string;
  onPress: () => void;
  variant?: Variant;
  loading?: boolean;
  disabled?: boolean;
  style?: ViewStyle;
  testID?: string;
  leftIcon?: React.ReactNode;
};

export function Button({
  title,
  onPress,
  variant = 'primary',
  loading,
  disabled,
  style,
  testID,
  leftIcon,
}: Props) {
  const isDisabled = disabled || loading;
  const s = styles[variant];
  return (
    <TouchableOpacity
      testID={testID}
      onPress={onPress}
      disabled={isDisabled}
      activeOpacity={0.85}
      style={[
        styles.base,
        s.container,
        isDisabled && styles.disabled,
        style,
      ]}
    >
      {loading ? (
        <ActivityIndicator color={s.text.color} />
      ) : (
        <View style={styles.row}>
          {leftIcon ? <View style={{ marginRight: 8 }}>{leftIcon}</View> : null}
          <Text style={[styles.baseText, s.text]}>{title}</Text>
        </View>
      )}
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  base: {
    height: 48,
    borderRadius: RADIUS.md,
    paddingHorizontal: 16,
    alignItems: 'center',
    justifyContent: 'center',
  },
  row: { flexDirection: 'row', alignItems: 'center' },
  baseText: {
    fontSize: FONT.sizes.md,
    fontWeight: FONT.weights.semibold,
  },
  disabled: { opacity: 0.5 },
  primary: {
    container: { backgroundColor: COLORS.primary },
    text: { color: '#fff' },
  } as any,
  secondary: {
    container: { backgroundColor: COLORS.disabledBg },
    text: { color: COLORS.text },
  } as any,
  outline: {
    container: {
      backgroundColor: 'transparent',
      borderWidth: 1.5,
      borderColor: COLORS.border,
    },
    text: { color: COLORS.text },
  } as any,
  danger: {
    container: { backgroundColor: COLORS.danger },
    text: { color: '#fff' },
  } as any,
  ghost: {
    container: { backgroundColor: 'transparent' },
    text: { color: COLORS.primary },
  } as any,
});

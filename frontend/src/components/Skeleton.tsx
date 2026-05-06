/**
 * Skeleton — animated shimmer placeholders for loading states.
 * Use sized presets (rect, line, circle) or pass `width`/`height` directly.
 */
import React, { useEffect, useRef } from 'react';
import { Animated, Easing, StyleSheet, View } from 'react-native';
import { COLORS, RADIUS } from '../theme';

type Props = {
  width?: number | string;
  height?: number;
  radius?: number;
  style?: any;
  testID?: string;
};

export function Skeleton({ width = '100%', height = 16, radius = RADIUS.sm, style, testID }: Props) {
  const opacity = useRef(new Animated.Value(0.6)).current;
  useEffect(() => {
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(opacity, { toValue: 1, duration: 700, easing: Easing.inOut(Easing.ease), useNativeDriver: true }),
        Animated.timing(opacity, { toValue: 0.6, duration: 700, easing: Easing.inOut(Easing.ease), useNativeDriver: true }),
      ]),
    );
    loop.start();
    return () => loop.stop();
  }, [opacity]);
  return (
    <Animated.View
      testID={testID}
      style={[
        { width, height, backgroundColor: COLORS.slate200, borderRadius: radius, opacity },
        style,
      ]}
    />
  );
}

export function SkeletonLine({ width = '70%' }: { width?: number | string }) {
  return <Skeleton width={width as any} height={12} />;
}

export function SkeletonCircle({ size = 40 }: { size?: number }) {
  return <Skeleton width={size} height={size} radius={size / 2} />;
}

export function SkeletonGroupRow({ testID }: { testID?: string }) {
  return (
    <View style={styles.row} testID={testID}>
      <SkeletonCircle size={40} />
      <View style={{ flex: 1, gap: 8 }}>
        <Skeleton width={'60%'} height={14} />
        <Skeleton width={'40%'} height={10} />
      </View>
      <Skeleton width={64} height={22} radius={11} />
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    backgroundColor: COLORS.surface,
    padding: 16,
    borderRadius: RADIUS.md,
    marginBottom: 8,
    borderWidth: 1,
    borderColor: COLORS.border,
  },
});

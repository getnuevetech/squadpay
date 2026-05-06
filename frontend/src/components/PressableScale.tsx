/**
 * PressableScale — tactile press animation wrapper for primary CTAs.
 * Scales down to 0.97 on press-in, springs back on press-out.
 * Use as a drop-in replacement for TouchableOpacity when you want depth.
 */
import React, { useRef } from 'react';
import { Animated, Pressable, PressableProps } from 'react-native';
import { MOTION } from '../theme';

type Props = PressableProps & { scaleTo?: number };

export function PressableScale({ scaleTo = 0.97, children, style, ...rest }: Props) {
  const scale = useRef(new Animated.Value(1)).current;
  const onIn = () => {
    Animated.timing(scale, { toValue: scaleTo, duration: MOTION.fast, useNativeDriver: true }).start();
  };
  const onOut = () => {
    Animated.spring(scale, { toValue: 1, useNativeDriver: true, friction: 7, tension: 140 }).start();
  };
  return (
    <Pressable
      {...rest}
      onPressIn={(e) => { onIn(); rest.onPressIn?.(e); }}
      onPressOut={(e) => { onOut(); rest.onPressOut?.(e); }}
      style={({ pressed }) => [
        typeof style === 'function' ? style({ pressed }) : style,
      ]}
    >
      <Animated.View style={{ transform: [{ scale }] }}>
        {children as any}
      </Animated.View>
    </Pressable>
  );
}

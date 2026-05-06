/**
 * Toast — non-blocking notifications. Replaces low-stakes Alert.alert.
 *
 * Mount <ToastHost /> once near the root of your screen tree, then call
 *   toast.success('Saved')
 *   toast.error('Network failed')
 *   toast.info('Copied to clipboard')
 * from anywhere.
 */
import React, { useEffect, useRef, useState } from 'react';
import { Animated, StyleSheet, Text, View, Easing } from 'react-native';
import { Check, AlertTriangle, Info, X } from 'lucide-react-native';
import { COLORS, FONT, RADIUS, SHADOW, SPACING, MOTION } from '../theme';

type Tone = 'success' | 'error' | 'info';
type Msg = { id: number; text: string; tone: Tone };

const _listeners: Array<(m: Msg) => void> = [];
let _id = 0;

function emit(text: string, tone: Tone) {
  const m: Msg = { id: ++_id, text, tone };
  _listeners.forEach((l) => l(m));
}

export const toast = {
  success: (text: string) => emit(text, 'success'),
  error: (text: string) => emit(text, 'error'),
  info: (text: string) => emit(text, 'info'),
};

function ToneIcon({ tone }: { tone: Tone }) {
  if (tone === 'success') return <Check size={16} color="#fff" />;
  if (tone === 'error') return <X size={16} color="#fff" />;
  return <Info size={16} color="#fff" />;
}

function toneBg(tone: Tone) {
  if (tone === 'success') return '#16A34A';
  if (tone === 'error') return '#DC2626';
  return COLORS.slate800;
}

export function ToastHost() {
  const [queue, setQueue] = useState<Msg[]>([]);
  useEffect(() => {
    const handler = (m: Msg) => {
      setQueue((q) => [...q, m]);
      // Auto-dismiss after 2.6s
      setTimeout(() => setQueue((q) => q.filter((x) => x.id !== m.id)), 2600);
    };
    _listeners.push(handler);
    return () => {
      const i = _listeners.indexOf(handler);
      if (i >= 0) _listeners.splice(i, 1);
    };
  }, []);
  return (
    <View pointerEvents="none" style={styles.host} testID="toast-host">
      {queue.map((m) => (
        <ToastItem key={m.id} msg={m} />
      ))}
    </View>
  );
}

function ToastItem({ msg }: { msg: Msg }) {
  const opacity = useRef(new Animated.Value(0)).current;
  const translateY = useRef(new Animated.Value(20)).current;
  useEffect(() => {
    Animated.parallel([
      Animated.timing(opacity, { toValue: 1, duration: MOTION.base, useNativeDriver: true, easing: Easing.out(Easing.cubic) }),
      Animated.timing(translateY, { toValue: 0, duration: MOTION.base, useNativeDriver: true, easing: Easing.out(Easing.cubic) }),
    ]).start();
  }, [opacity, translateY]);
  return (
    <Animated.View
      style={[styles.toast, { backgroundColor: toneBg(msg.tone), opacity, transform: [{ translateY }] }, SHADOW.lg]}
      testID={`toast-${msg.tone}`}
    >
      <ToneIcon tone={msg.tone} />
      <Text style={styles.text} numberOfLines={2}>{msg.text}</Text>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  host: {
    position: 'absolute',
    bottom: SPACING.xl,
    left: SPACING.md,
    right: SPACING.md,
    alignItems: 'center',
    gap: 8,
    zIndex: 9999,
  },
  toast: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    paddingHorizontal: SPACING.md,
    paddingVertical: 12,
    borderRadius: RADIUS.pill,
    maxWidth: 420,
    minHeight: 40,
  },
  text: { color: '#fff', fontSize: FONT.sizes.sm, fontWeight: FONT.weights.semibold, flexShrink: 1 },
});

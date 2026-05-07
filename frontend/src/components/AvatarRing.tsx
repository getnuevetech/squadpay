// AvatarRing — vibrant friend avatar with a colored ring background.
// Inspired by the "Choose friends to share the bill" treatment in the design refs.
// Rotates through a stable color palette based on a hash of the user id/name,
// so the same person always gets the same color across sessions.
import React from 'react';
import { StyleSheet, Text, View, ViewStyle, StyleProp } from 'react-native';
import { COLORS, FONT } from '../theme';

// Vibrant, youthful color rings (also used as initial-bubble gradients).
// Each entry: [ring color, soft inner background, text color]
const RING_PALETTE: Array<[string, string, string]> = [
  ['#7C3AED', '#EDE9FE', '#5B21B6'], // violet
  ['#22D3EE', '#CFFAFE', '#0E7490'], // cyan
  ['#F59E0B', '#FEF3C7', '#92400E'], // amber
  ['#EC4899', '#FCE7F3', '#9D174D'], // pink
  ['#10B981', '#D1FAE5', '#065F46'], // emerald
  ['#3B82F6', '#DBEAFE', '#1E40AF'], // blue
  ['#F97316', '#FFEDD5', '#9A3412'], // orange
  ['#8B5CF6', '#EDE9FE', '#5B21B6'], // light violet
];

function pickColor(seed: string): [string, string, string] {
  let hash = 0;
  for (let i = 0; i < seed.length; i++) {
    hash = (hash * 31 + seed.charCodeAt(i)) >>> 0;
  }
  return RING_PALETTE[hash % RING_PALETTE.length];
}

interface Props {
  name: string;
  seed?: string;          // optional override for color picking (e.g. user id)
  size?: number;          // outer ring size in px (default 48)
  showLeadCrown?: boolean;
  style?: StyleProp<ViewStyle>;
}

export function AvatarRing({ name, seed, size = 48, showLeadCrown, style }: Props) {
  const [ring, bg, fg] = pickColor(seed || name || '?');
  const innerSize = size - 6;
  const initial = (name || '?').trim().charAt(0).toUpperCase() || '?';
  const fontSize = Math.max(12, Math.round(size * 0.38));

  return (
    <View
      style={[
        styles.outer,
        { width: size, height: size, borderRadius: size / 2, backgroundColor: ring },
        style,
      ]}
    >
      <View
        style={[
          styles.inner,
          {
            width: innerSize,
            height: innerSize,
            borderRadius: innerSize / 2,
            backgroundColor: bg,
          },
        ]}
      >
        <Text style={[styles.initial, { color: fg, fontSize }]}>{initial}</Text>
      </View>
      {showLeadCrown ? (
        <View style={[styles.crown, { width: size * 0.42, height: size * 0.42, borderRadius: size * 0.21 }]}>
          <Text style={{ fontSize: size * 0.22 }}>👑</Text>
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  outer: {
    alignItems: 'center',
    justifyContent: 'center',
    overflow: 'visible',
  },
  inner: {
    alignItems: 'center',
    justifyContent: 'center',
  },
  initial: {
    fontWeight: FONT.weights.bold,
    letterSpacing: 0.3,
  },
  crown: {
    position: 'absolute',
    top: -4,
    right: -4,
    backgroundColor: '#FFFFFF',
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1.5,
    borderColor: COLORS.warning,
  },
});

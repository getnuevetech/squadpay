/**
 * Pure-RN/SVG illustration matching landing hero (Image 1):
 * a rounded-rect phone frame with two avatar bubbles, hashtag chips,
 * 4 colorful overlapping squad dots, and a violet "Split Now" inner CTA.
 * No external assets required — names initials act as avatar fallback.
 */
import { View, Text, StyleSheet } from 'react-native';
import { Zap } from 'lucide-react-native';
import { COLORS, FONT } from '../../theme';

type Props = {
  height?: number;
};

function Avatar({ initials, color, size = 48 }: { initials: string; color: string; size?: number }) {
  return (
    <View
      style={[
        avStyles.avatar,
        { width: size, height: size, borderRadius: size / 2, backgroundColor: color },
      ]}
    >
      <Text style={[avStyles.initials, { fontSize: Math.round(size * 0.36) }]}>{initials}</Text>
    </View>
  );
}

const avStyles = StyleSheet.create({
  avatar: {
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 3,
    borderColor: '#fff',
  },
  initials: { color: '#fff', fontWeight: FONT.weights.bold },
});

export function HeroPhoneFrame({ height = 280 }: Props) {
  return (
    <View style={[styles.wrap, { height }]} testID="hero-phone-frame">
      {/* Soft violet ambient blob behind the frame */}
      <View style={styles.glow} />

      {/* Phone frame card */}
      <View style={styles.frame}>
        {/* Top hashtag chip + avatar (top-left), pulled slightly outside */}
        <View style={[styles.chipFloat, { top: -22, left: -14 }]}>
          <Avatar initials="AS" color="#EF4444" />
          <View style={[styles.chip, styles.chipDark]}>
            <Text style={styles.chipDarkText}># SplitBill</Text>
          </View>
        </View>

        {/* Skeleton lines */}
        <View style={[styles.skel, { width: '70%', marginTop: 36 }]} />
        <View style={[styles.skel, { width: '50%' }]} />

        {/* 4 colorful squad dots */}
        <View style={styles.dotsRow}>
          {[
            { c: '#F59E0B' },
            { c: '#10B981' },
            { c: '#EF4444' },
            { c: COLORS.primary },
          ].map((d, i) => (
            <View
              key={i}
              style={[
                styles.dot,
                { backgroundColor: d.c, marginLeft: i === 0 ? 0 : -10, zIndex: 4 - i },
              ]}
            />
          ))}
        </View>

        <View style={[styles.skel, { width: '60%', marginTop: 14 }]} />
        <View style={[styles.skel, { width: '40%' }]} />

        {/* Bottom "Split Now" pill */}
        <View style={styles.splitBtn}>
          <Zap size={14} color="#fff" fill="#fff" />
          <Text style={styles.splitBtnText}>Split Now</Text>
        </View>

        {/* Bottom-right floating chip + avatar */}
        <View style={[styles.chipFloat, { bottom: 70, right: -22, flexDirection: 'row-reverse' }]}>
          <Avatar initials="JD" color="#7C3AED" />
          <View style={[styles.chip, styles.chipLight, { marginRight: 6 }]}>
            <Text style={styles.chipLightText}># EasyPay</Text>
          </View>
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { width: '100%', alignItems: 'center', justifyContent: 'center', position: 'relative' },
  glow: {
    position: 'absolute',
    width: 240,
    height: 240,
    borderRadius: 120,
    backgroundColor: COLORS.primary,
    opacity: 0.12,
    top: 30,
  },
  frame: {
    width: 220,
    height: 240,
    backgroundColor: '#fff',
    borderRadius: 28,
    borderWidth: 3,
    borderColor: COLORS.primary,
    padding: 18,
    shadowColor: COLORS.primary,
    shadowOpacity: 0.18,
    shadowRadius: 20,
    shadowOffset: { width: 0, height: 12 },
    elevation: 6,
  },
  skel: {
    height: 8,
    backgroundColor: '#EEE9FE',
    borderRadius: 4,
    marginTop: 8,
  },
  dotsRow: { flexDirection: 'row', alignItems: 'center', marginTop: 18, justifyContent: 'center' },
  dot: { width: 36, height: 36, borderRadius: 18, borderWidth: 3, borderColor: '#fff' },
  splitBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    backgroundColor: COLORS.primary,
    paddingVertical: 10,
    paddingHorizontal: 14,
    borderRadius: 12,
    marginTop: 14,
    shadowColor: COLORS.primary,
    shadowOpacity: 0.4,
    shadowRadius: 10,
    shadowOffset: { width: 0, height: 4 },
  },
  splitBtnText: { color: '#fff', fontWeight: FONT.weights.bold, fontSize: 13 },
  chipFloat: { position: 'absolute', flexDirection: 'row', alignItems: 'center', gap: 6, zIndex: 5 },
  chip: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 16,
  },
  chipDark: { backgroundColor: '#1F1240' },
  chipDarkText: { color: '#fff', fontWeight: FONT.weights.bold, fontSize: 12 },
  chipLight: { backgroundColor: '#F1ECFE', borderWidth: 1, borderColor: '#E0D5FB' },
  chipLightText: { color: COLORS.primary, fontWeight: FONT.weights.bold, fontSize: 12 },
});

export default HeroPhoneFrame;

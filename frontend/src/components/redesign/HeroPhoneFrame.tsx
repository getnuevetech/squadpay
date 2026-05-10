/**
 * Pure-RN illustration matching the SquadPay landing hero (reference image):
 * a thick-violet-bordered phone frame with two real photo avatars, hashtag
 * chips (#SplitBill dark, #EasyPay light-violet), 4 colorful overlapping
 * squad dots, and a violet "⚡ Split Now" inner CTA. Uses real Unsplash
 * portraits (sourced via the vision agent) for the avatars.
 */
import { View, Text, StyleSheet, Image } from 'react-native';
import { Zap } from 'lucide-react-native';
import { COLORS, FONT } from '../../theme';

type Props = {
  height?: number;
};

const AVATAR_LEFT = 'https://images.unsplash.com/photo-1594318223885-20dc4b889f9e?crop=entropy&cs=srgb&fm=jpg&w=160&q=80';
const AVATAR_RIGHT_MAN = 'https://images.unsplash.com/photo-1563630423918-b58f07336ac9?crop=entropy&cs=srgb&fm=jpg&w=160&q=80';
const AVATAR_RIGHT_WOMAN = 'https://images.unsplash.com/photo-1713606425111-13c546282729?crop=entropy&cs=srgb&fm=jpg&w=160&q=80';

function PhotoAvatar({ uri, size = 64 }: { uri: string; size?: number }) {
  return (
    <View style={[styles.avatar, { width: size, height: size, borderRadius: size / 2 }]}>
      <Image source={{ uri }} style={{ width: '100%', height: '100%' }} resizeMode="cover" />
    </View>
  );
}

export function HeroPhoneFrame({ height = 320 }: Props) {
  return (
    <View style={[styles.wrap, { height }]} testID="hero-phone-frame">
      {/* Soft violet ambient blob behind the frame */}
      <View style={styles.glowLeft} />
      <View style={styles.glowRight} />

      {/* Decorative sparkle outside frame (right) */}
      <View style={[styles.sparkle, { top: 20, right: 8 }]} />
      <View style={[styles.sparkle, { bottom: 60, left: 6, transform: [{ rotate: '45deg' }] }]} />

      {/* Phone frame card */}
      <View style={styles.frame}>
        {/* Skeleton lines (top) */}
        <View style={[styles.skel, { width: '70%', marginTop: 28 }]} />
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
                { backgroundColor: d.c, marginLeft: i === 0 ? 0 : -14, zIndex: 4 - i },
              ]}
            />
          ))}
        </View>

        {/* Skeleton lines (bottom) */}
        <View style={[styles.skel, { width: '60%', marginTop: 16 }]} />

        {/* Bottom "Split Now" pill */}
        <View style={styles.splitBtn}>
          <Zap size={16} color="#FCD34D" fill="#FCD34D" />
          <Text style={styles.splitBtnText}>Split Now</Text>
        </View>
      </View>

      {/* Top-left photo avatar + dark "# SplitBill" chip */}
      <View style={[styles.float, { top: -8, left: 16, flexDirection: 'row', alignItems: 'center' }]}>
        <PhotoAvatar uri={AVATAR_LEFT} size={64} />
        <View style={[styles.chip, styles.chipDark, { marginLeft: -10 }]}>
          <Text style={styles.chipDarkText}># SplitBill</Text>
        </View>
      </View>

      {/* Bottom-right two photo avatars + light "# EasyPay" chip */}
      <View
        style={[
          styles.float,
          { bottom: 30, right: 16, flexDirection: 'row', alignItems: 'center' },
        ]}
      >
        <View style={[styles.chip, styles.chipLight, { marginRight: -10, zIndex: 1 }]}>
          <Text style={styles.chipLightText}># EasyPay</Text>
        </View>
        <View style={{ flexDirection: 'row', alignItems: 'center' }}>
          <PhotoAvatar uri={AVATAR_RIGHT_MAN} size={56} />
          <View style={{ marginLeft: -16 }}>
            <PhotoAvatar uri={AVATAR_RIGHT_WOMAN} size={56} />
          </View>
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { width: '100%', alignItems: 'center', justifyContent: 'center', position: 'relative' },
  glowLeft: {
    position: 'absolute',
    width: 220,
    height: 220,
    borderRadius: 110,
    backgroundColor: '#E0D5FB',
    opacity: 0.5,
    top: 60,
    left: 30,
  },
  glowRight: {
    position: 'absolute',
    width: 180,
    height: 180,
    borderRadius: 90,
    backgroundColor: '#E0D5FB',
    opacity: 0.4,
    bottom: 30,
    right: 30,
  },
  sparkle: {
    position: 'absolute',
    width: 14,
    height: 14,
    backgroundColor: '#C4B5FD',
    borderRadius: 3,
    transform: [{ rotate: '45deg' }],
    opacity: 0.7,
  },
  frame: {
    width: 240,
    minHeight: 280,
    backgroundColor: '#fff',
    borderRadius: 30,
    borderWidth: 8,
    borderColor: COLORS.primary,
    paddingHorizontal: 22,
    paddingVertical: 24,
    shadowColor: COLORS.primary,
    shadowOpacity: 0.18,
    shadowRadius: 24,
    shadowOffset: { width: 0, height: 14 },
    elevation: 6,
  },
  skel: {
    height: 9,
    backgroundColor: '#EEE9FE',
    borderRadius: 5,
    marginTop: 8,
  },
  dotsRow: { flexDirection: 'row', alignItems: 'center', marginTop: 22, marginBottom: 6 },
  dot: { width: 44, height: 44, borderRadius: 22, borderWidth: 3, borderColor: '#fff' },
  splitBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    backgroundColor: COLORS.primary,
    paddingVertical: 12,
    paddingHorizontal: 16,
    borderRadius: 14,
    marginTop: 18,
    shadowColor: COLORS.primary,
    shadowOpacity: 0.4,
    shadowRadius: 10,
    shadowOffset: { width: 0, height: 4 },
  },
  splitBtnText: { color: '#fff', fontWeight: FONT.weights.bold, fontSize: 14 },
  avatar: {
    overflow: 'hidden',
    borderWidth: 4,
    borderColor: '#fff',
    backgroundColor: '#eee',
    shadowColor: '#1F1240',
    shadowOpacity: 0.15,
    shadowRadius: 8,
    shadowOffset: { width: 0, height: 4 },
    elevation: 3,
  },
  float: { position: 'absolute', zIndex: 5 },
  chip: {
    paddingHorizontal: 12,
    paddingVertical: 7,
    borderRadius: 18,
    minHeight: 32,
    justifyContent: 'center',
  },
  chipDark: { backgroundColor: '#1F1240' },
  chipDarkText: { color: '#fff', fontWeight: FONT.weights.bold, fontSize: 13 },
  chipLight: { backgroundColor: '#fff', borderWidth: 1, borderColor: '#E0D5FB' },
  chipLightText: { color: COLORS.primary, fontWeight: FONT.weights.bold, fontSize: 13 },
});

export default HeroPhoneFrame;

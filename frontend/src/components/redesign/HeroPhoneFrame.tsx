/**
 * SquadPay landing hero illustration — pixel-faithful match to reference:
 *  - Phone frame rotated -10° (tilted left), thick 8px violet border.
 *  - Three large overlapping photo avatars; chips tuck between/beside them.
 *  - Avatars + chips stay upright (only the frame tilts) for legibility.
 *
 * Demographic mapping per user spec: top-left = white girl,
 * bottom-right pair = Hispanic guy (left) + Black girl (right).
 */
import { View, Text, StyleSheet, Image } from 'react-native';
import { Zap } from 'lucide-react-native';
import { COLORS, FONT } from '../../theme';

type Props = {
  height?: number;
};

const AVATAR_LEFT = 'https://images.unsplash.com/photo-1494790108377-be9c29b29330?crop=entropy&cs=srgb&fm=jpg&w=200&q=80';
const AVATAR_RIGHT_MAN = 'https://images.unsplash.com/photo-1539571696357-5a69c17a67c6?crop=entropy&cs=srgb&fm=jpg&w=200&q=80';
const AVATAR_RIGHT_WOMAN = 'https://images.unsplash.com/photo-1531123897727-8f129e1688ce?crop=entropy&cs=srgb&fm=jpg&w=200&q=80';

function PhotoAvatar({ uri, size = 100 }: { uri: string; size?: number }) {
  return (
    <View style={[styles.avatar, { width: size, height: size, borderRadius: size / 2 }]}>
      <Image source={{ uri }} style={{ width: '100%', height: '100%' }} resizeMode="cover" />
    </View>
  );
}

export function HeroPhoneFrame({ height = 380 }: Props) {
  return (
    <View style={[styles.wrap, { height }]} testID="hero-phone-frame">
      {/* Soft violet ambient blob behind the frame */}
      <View style={styles.glowLeft} />
      <View style={styles.glowRight} />

      {/* Decorative violet sparkles around the frame */}
      <View style={[styles.sparkle, { top: 30, right: 12 }]} />
      <View style={[styles.sparkle, { top: 60, right: 0, transform: [{ rotate: '45deg' }] }]} />
      <View style={[styles.sparkleSm, { bottom: 80, left: 10 }]} />
      <View style={[styles.sparkleSm, { bottom: 140, left: 0, transform: [{ rotate: '45deg' }] }]} />

      {/* Phone frame card — tilted -10° (counter-clockwise / "left") */}
      <View style={styles.frameWrap}>
        <View style={styles.frame}>
          {/* Skeleton lines (top) */}
          <View style={[styles.skel, { width: '70%', marginTop: 30 }]} />
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
                  { backgroundColor: d.c, marginLeft: i === 0 ? 0 : -16, zIndex: 4 - i },
                ]}
              />
            ))}
          </View>

          {/* Skeleton line (bottom) */}
          <View style={[styles.skel, { width: '60%', marginTop: 18 }]} />

          {/* Bottom violet "Split Now" pill */}
          <View style={styles.splitBtn}>
            <Zap size={18} color="#FCD34D" fill="#FCD34D" />
            <Text style={styles.splitBtnText}>Split Now</Text>
          </View>
        </View>
      </View>

      {/* ── TOP-LEFT: White girl avatar overlapping frame + dark # SplitBill chip ── */}
      <View style={[styles.floatTopLeft]}>
        <PhotoAvatar uri={AVATAR_LEFT} size={104} />
        <View style={[styles.chipDark, { marginLeft: -28, zIndex: -1 }]}>
          <Text style={styles.chipDarkText}># SplitBill</Text>
        </View>
      </View>

      {/* ── BOTTOM-RIGHT: Hispanic guy + Black girl with # EasyPay chip TUCKED BETWEEN ── */}
      <View style={[styles.floatBottomRight]}>
        <View style={{ flexDirection: 'row', alignItems: 'center' }}>
          <PhotoAvatar uri={AVATAR_RIGHT_MAN} size={92} />
          <View style={[styles.chipLight, { marginLeft: -22, zIndex: -1 }]}>
            <Text style={styles.chipLightText}># EasyPay</Text>
          </View>
          <View style={{ marginLeft: -32, zIndex: 1 }}>
            <PhotoAvatar uri={AVATAR_RIGHT_WOMAN} size={92} />
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
    width: 240,
    height: 240,
    borderRadius: 120,
    backgroundColor: '#E0D5FB',
    opacity: 0.5,
    top: 70,
    left: 30,
  },
  glowRight: {
    position: 'absolute',
    width: 200,
    height: 200,
    borderRadius: 100,
    backgroundColor: '#E0D5FB',
    opacity: 0.45,
    bottom: 30,
    right: 20,
  },
  sparkle: {
    position: 'absolute',
    width: 16,
    height: 16,
    backgroundColor: '#C4B5FD',
    borderRadius: 3,
    transform: [{ rotate: '45deg' }],
    opacity: 0.7,
  },
  sparkleSm: {
    position: 'absolute',
    width: 10,
    height: 10,
    backgroundColor: '#C4B5FD',
    borderRadius: 2,
    transform: [{ rotate: '45deg' }],
    opacity: 0.6,
  },

  // Frame is tilted -10°; floating avatars/chips stay upright on top.
  frameWrap: {
    transform: [{ rotate: '-10deg' }],
  },
  frame: {
    width: 250,
    minHeight: 320,
    backgroundColor: '#fff',
    borderRadius: 32,
    borderWidth: 8,
    borderColor: COLORS.primary,
    paddingHorizontal: 22,
    paddingVertical: 26,
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
  dotsRow: { flexDirection: 'row', alignItems: 'center', marginTop: 26, justifyContent: 'flex-start' },
  dot: { width: 50, height: 50, borderRadius: 25, borderWidth: 4, borderColor: '#fff' },
  splitBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    backgroundColor: COLORS.primary,
    paddingVertical: 14,
    paddingHorizontal: 18,
    borderRadius: 14,
    marginTop: 22,
    shadowColor: COLORS.primary,
    shadowOpacity: 0.4,
    shadowRadius: 10,
    shadowOffset: { width: 0, height: 4 },
  },
  splitBtnText: { color: '#fff', fontWeight: '900', fontSize: 16 },

  // Avatars ── upright (NOT rotated)
  avatar: {
    overflow: 'hidden',
    borderWidth: 4,
    borderColor: '#fff',
    backgroundColor: '#eee',
    shadowColor: '#1F1240',
    shadowOpacity: 0.18,
    shadowRadius: 10,
    shadowOffset: { width: 0, height: 6 },
    elevation: 5,
  },

  // Top-left float: spans the frame's top edge on the LEFT side, half outside.
  floatTopLeft: {
    position: 'absolute',
    top: 24,
    left: 8,
    flexDirection: 'row',
    alignItems: 'center',
    zIndex: 5,
  },
  // Bottom-right float: spans the frame's bottom edge on the RIGHT side.
  floatBottomRight: {
    position: 'absolute',
    bottom: 28,
    right: 0,
    zIndex: 5,
  },

  chipDark: {
    backgroundColor: '#1F1240',
    paddingHorizontal: 18,
    paddingVertical: 10,
    paddingLeft: 36, // extra so face overlaps cleanly
    borderRadius: 22,
    minHeight: 40,
    justifyContent: 'center',
  },
  chipDarkText: { color: '#fff', fontWeight: '900', fontSize: 15 },

  chipLight: {
    backgroundColor: '#fff',
    paddingHorizontal: 22,
    paddingVertical: 10,
    borderRadius: 22,
    minHeight: 40,
    justifyContent: 'center',
    borderWidth: 1.5,
    borderColor: '#E0D5FB',
    shadowColor: '#1F1240',
    shadowOpacity: 0.06,
    shadowRadius: 8,
    shadowOffset: { width: 0, height: 3 },
  },
  chipLightText: { color: COLORS.primary, fontWeight: '900', fontSize: 15 },
});

export default HeroPhoneFrame;

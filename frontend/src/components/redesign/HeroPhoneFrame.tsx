/**
 * SquadPay landing hero illustration — DYNAMIC RANDOM VISUALS (June 2025).
 *
 *   • Phone frame border + Split Now button — random hex from admin pool
 *   • 3 avatar slots (left, right-man, right-woman) — random URL per slot
 *   • 3 hashtag chips (top-left dark, bottom-right light, top-right new)
 *     — random hashtags from admin pool
 *   • Background glow/ambient — picks a complementary shade
 *
 * Falls back to a sensible hardcoded palette if the remote config endpoint
 * (/api/runtime/landing-page) is unreachable.
 *
 * Re-randomizes ONCE per component mount (i.e., once per visit to the
 * landing screen). This gives returning users a fresh look each time
 * without flickering during a session.
 */
import { useEffect, useMemo, useState } from 'react';
import { View, Text, StyleSheet, Image } from 'react-native';
import { Zap } from 'lucide-react-native';
import { FONT } from '../../theme';

type Props = {
  height?: number;
};

// ── Hardcoded fallbacks (also used when admin config is empty) ─────────
const FALLBACK_PHONE_COLORS = ['#7C3AED', '#5B2BC8', '#8B5CF6', '#A78BFA', '#9333EA'];
const FALLBACK_HASHTAGS = ['# SplitBill', '# EasyPay', '# SquadGoals'];
const FALLBACK_AVATARS_LEFT = [
  'https://images.unsplash.com/photo-1494790108377-be9c29b29330?crop=entropy&cs=srgb&fm=jpg&w=200&q=80',
  'https://images.unsplash.com/photo-1438761681033-6461ffad8d80?crop=entropy&cs=srgb&fm=jpg&w=200&q=80',
  'https://images.unsplash.com/photo-1487412720507-e7ab37603c6f?crop=entropy&cs=srgb&fm=jpg&w=200&q=80',
];
const FALLBACK_AVATARS_RIGHT_MAN = [
  'https://images.unsplash.com/photo-1539571696357-5a69c17a67c6?crop=entropy&cs=srgb&fm=jpg&w=200&q=80',
  'https://images.unsplash.com/photo-1500648767791-00dcc994a43e?crop=entropy&cs=srgb&fm=jpg&w=200&q=80',
  'https://images.unsplash.com/photo-1531427186611-ecfd6d936c79?crop=entropy&cs=srgb&fm=jpg&w=200&q=80',
];
const FALLBACK_AVATARS_RIGHT_WOMAN = [
  'https://images.unsplash.com/photo-1531123897727-8f129e1688ce?crop=entropy&cs=srgb&fm=jpg&w=200&q=80',
  'https://images.unsplash.com/photo-1534528741775-53994a69daeb?crop=entropy&cs=srgb&fm=jpg&w=200&q=80',
  'https://images.unsplash.com/photo-1554151228-14d9def656e4?crop=entropy&cs=srgb&fm=jpg&w=200&q=80',
];

/**
 * Pick a random element from `arr` if non-empty, else from `fallback`.
 * NOTE: `fallback` is ALWAYS an array so we still randomize even when the
 * remote config endpoint is unreachable (e.g. on a freshly-deployed
 * frontend whose backend hasn't been redeployed yet — previously we'd
 * return a single fallback value and the visuals never rotated).
 */
function pick<T>(arr: T[] | undefined | null, fallback: T[]): T {
  const src = arr && arr.length > 0 ? arr : fallback;
  return src[Math.floor(Math.random() * src.length)];
}

function pickN<T>(arr: T[] | undefined | null, fallback: T[], n: number): T[] {
  const src = arr && arr.length >= n ? arr : fallback;
  // pick N distinct (or repeat if pool < N)
  const out: T[] = [];
  const usedIdx = new Set<number>();
  for (let i = 0; i < n; i++) {
    if (usedIdx.size >= src.length) usedIdx.clear();
    let idx = Math.floor(Math.random() * src.length);
    while (usedIdx.has(idx)) idx = (idx + 1) % src.length;
    usedIdx.add(idx);
    out.push(src[idx]);
  }
  return out;
}

type RemoteConfig = {
  phone_frame_colors?: string[];
  hashtags?: string[];
  avatars?: { slot_left?: string[]; slot_right_man?: string[]; slot_right_woman?: string[] };
  updated_at?: string | null;
};

function PhotoAvatar({ uri, size = 100 }: { uri: string; size?: number }) {
  return (
    <View style={[styles.avatar, { width: size, height: size, borderRadius: size / 2 }]}>
      <Image source={{ uri }} style={{ width: '100%', height: '100%' }} resizeMode="cover" />
    </View>
  );
}

/**
 * Append a cache-buster (`?v=<updated_at>`) to remote image URLs so the
 * browser re-fetches when the admin replaces an avatar but keeps the
 * same URL slot. The `updated_at` is shared across the response, so all
 * three avatars are invalidated together — that's intentional.
 */
function bust(url: string, version: string | null | undefined): string {
  if (!url || !version) return url;
  try {
    const sep = url.includes('?') ? '&' : '?';
    return `${url}${sep}v=${encodeURIComponent(version)}`;
  } catch {
    return url;
  }
}

export function HeroPhoneFrame({ height = 380 }: Props) {
  const [remote, setRemote] = useState<RemoteConfig | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const base = (process.env.EXPO_PUBLIC_BACKEND_URL || '').replace(/\/$/, '');
        // NOTE: must include /api prefix — every backend route is mounted
        // under /api in server.py. Without it the kubernetes ingress would
        // send this request to the frontend, which serves the SPA shell
        // (HTML), JSON.parse fails silently, and we end up always using
        // the hardcoded FALLBACK_* lists. Bug fixed May 2026.
        const res = await fetch(`${base}/api/runtime/landing-page?t=${Date.now()}`, {
          cache: 'no-store',
          headers: { 'Cache-Control': 'no-cache, no-store, must-revalidate' },
        });
        if (!res.ok) return;
        const ct = res.headers.get('content-type') || '';
        if (!ct.includes('json')) return;       // defensive guard
        const json = await res.json();
        if (!cancelled) setRemote(json);
      } catch {
        // Silent fallback — defaults will be used.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Re-pick on every fresh mount (one-time per landing visit).
  const palette = useMemo(() => {
    const frameColor = pick(remote?.phone_frame_colors, FALLBACK_PHONE_COLORS);
    const [tag1, tag2, tag3] = pickN(remote?.hashtags, FALLBACK_HASHTAGS, 3);
    const ver = remote?.updated_at || '';
    const av = {
      left: bust(pick(remote?.avatars?.slot_left, FALLBACK_AVATARS_LEFT), ver),
      rightMan: bust(pick(remote?.avatars?.slot_right_man, FALLBACK_AVATARS_RIGHT_MAN), ver),
      rightWoman: bust(pick(remote?.avatars?.slot_right_woman, FALLBACK_AVATARS_RIGHT_WOMAN), ver),
    };
    return { frameColor, tag1, tag2, tag3, av };
  }, [remote]);

  return (
    <View style={[styles.wrap, { height }]} testID="hero-phone-frame">
      {/* Soft violet ambient blob behind the frame */}
      <View style={styles.glowLeft} />
      <View style={styles.glowRight} />

      {/* Decorative violet sparkles around the frame */}
      <View style={[styles.sparkle, { top: 30, right: 12, backgroundColor: palette.frameColor + '60' }]} />
      <View style={[styles.sparkle, { top: 60, right: 0, transform: [{ rotate: '45deg' }], backgroundColor: palette.frameColor + '60' }]} />
      <View style={[styles.sparkleSm, { bottom: 80, left: 10, backgroundColor: palette.frameColor + '60' }]} />
      <View style={[styles.sparkleSm, { bottom: 140, left: 0, transform: [{ rotate: '45deg' }], backgroundColor: palette.frameColor + '60' }]} />

      {/* Phone frame card — tilted -10° (counter-clockwise / "left") */}
      <View style={styles.frameWrap}>
        <View style={[styles.frame, { borderColor: palette.frameColor, shadowColor: palette.frameColor }]}>
          {/* Skeleton lines (top) */}
          <View style={[styles.skel, { width: '70%', marginTop: 30 }]} />
          <View style={[styles.skel, { width: '50%' }]} />

          {/* 4 colorful squad dots */}
          <View style={styles.dotsRow}>
            {[
              { c: '#F59E0B' },
              { c: '#10B981' },
              { c: '#EF4444' },
              { c: palette.frameColor },
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
          <View style={[styles.splitBtn, { backgroundColor: palette.frameColor, shadowColor: palette.frameColor }]}>
            <Zap size={18} color="#FCD34D" fill="#FCD34D" />
            <Text style={styles.splitBtnText}>Split Now</Text>
          </View>
        </View>
      </View>

      {/* ── TOP-LEFT: avatar overlapping frame + dark hashtag chip ── */}
      <View style={[styles.floatTopLeft]}>
        <PhotoAvatar uri={palette.av.left} size={104} />
        <View style={[styles.chipDark, { marginLeft: -28, zIndex: -1 }]}>
          <Text style={styles.chipDarkText}>{palette.tag1}</Text>
        </View>
      </View>

      {/* ── TOP-RIGHT: new 3rd hashtag chip (light, accented with frame color) ── */}
      <View style={[styles.floatTopRight]}>
        <View style={[styles.chipAccent, { borderColor: palette.frameColor + '55' }]}>
          <Text style={[styles.chipAccentText, { color: palette.frameColor }]}>
            {palette.tag3}
          </Text>
        </View>
      </View>

      {/* ── BOTTOM-RIGHT: 2 avatars + light hashtag chip TUCKED BETWEEN ── */}
      <View style={[styles.floatBottomRight]}>
        <View style={{ flexDirection: 'row', alignItems: 'center' }}>
          <PhotoAvatar uri={palette.av.rightMan} size={92} />
          <View style={[styles.chipLight, { marginLeft: -22, zIndex: -1 }]}>
            <Text style={[styles.chipLightText, { color: palette.frameColor }]}>
              {palette.tag2}
            </Text>
          </View>
          <View style={{ marginLeft: -32, zIndex: 1 }}>
            <PhotoAvatar uri={palette.av.rightWoman} size={92} />
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
    borderRadius: 3,
    transform: [{ rotate: '45deg' }],
    opacity: 0.7,
  },
  sparkleSm: {
    position: 'absolute',
    width: 10,
    height: 10,
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
    paddingHorizontal: 22,
    paddingVertical: 26,
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
    paddingVertical: 14,
    paddingHorizontal: 18,
    borderRadius: 14,
    marginTop: 22,
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

  // Top-left float
  floatTopLeft: {
    position: 'absolute',
    top: 24,
    left: 8,
    flexDirection: 'row',
    alignItems: 'center',
    zIndex: 5,
  },
  // Bottom-right float
  floatBottomRight: {
    position: 'absolute',
    bottom: 28,
    right: 0,
    zIndex: 5,
  },
  // NEW: top-right floating accent hashtag chip
  floatTopRight: {
    position: 'absolute',
    top: 8,
    right: 12,
    zIndex: 5,
    transform: [{ rotate: '8deg' }],
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
  chipLightText: { fontWeight: '900', fontSize: 15 },

  // NEW: tilted accent chip for 3rd hashtag
  chipAccent: {
    backgroundColor: '#fff',
    paddingHorizontal: 14,
    paddingVertical: 6,
    borderRadius: 14,
    borderWidth: 1.5,
    shadowColor: '#1F1240',
    shadowOpacity: 0.08,
    shadowRadius: 6,
    shadowOffset: { width: 0, height: 2 },
    elevation: 3,
  },
  chipAccentText: { fontWeight: '900', fontSize: 12 },
});

export default HeroPhoneFrame;

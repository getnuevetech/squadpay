// Design system tokens — Phase H1 (UI polish, June 2025)
//
// Extends the original COLORS/SPACING/RADIUS/FONT triplet with:
//   • A full neutral scale (slate 50–900) for finer hierarchy
//   • SHADOW tokens (sm/md/lg/xl) — single source for elevation
//   • Spacing 2xl/3xl for spacious hero sections
//   • Semantic aliases (surfaceElevated, textMuted, etc.)
//
// All existing keys are preserved for backwards-compat.
import { Platform } from 'react-native';

export const COLORS = {
  primary: '#4F46E5',
  primaryDark: '#4338CA',
  primaryLight: '#EEF2FF',
  primarySoft: '#E0E7FF',     // slightly darker than primaryLight, used for hovers
  success: '#16A34A',
  successLight: '#DCFCE7',
  warning: '#F59E0B',
  warningLight: '#FEF3C7',
  danger: '#DC2626',
  dangerLight: '#FEE2E2',
  bg: '#F9FAFB',
  surface: '#FFFFFF',
  surfaceElevated: '#FFFFFF', // alias — used with SHADOW.md to convey depth
  text: '#111827',
  textMuted: '#4B5563',
  subtext: '#6B7280',
  border: '#E5E7EB',
  borderStrong: '#D1D5DB',
  disabledBg: '#F3F4F6',
  disabledText: '#9CA3AF',
  black: '#000000',
  // Slate scale (Tailwind-aligned) — use these for nuanced surface/text hierarchy
  slate50: '#F8FAFC',
  slate100: '#F1F5F9',
  slate200: '#E2E8F0',
  slate300: '#CBD5E1',
  slate400: '#94A3B8',
  slate500: '#64748B',
  slate600: '#475569',
  slate700: '#334155',
  slate800: '#1E293B',
  slate900: '#0F172A',
};

export const SPACING = {
  xs: 4,
  sm: 8,
  md: 16,
  lg: 24,
  xl: 32,
  xxl: 40,
  xxxl: 56,    // new — for hero sections
};

export const RADIUS = {
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
  xxl: 32,     // new — for very tactile hero cards
  pill: 999,
};

export const FONT = {
  sizes: {
    xs: 12,
    sm: 14,
    md: 16,
    lg: 18,
    xl: 22,
    xxl: 28,
    huge: 40,
    display: 56,   // new — for big-number hero amounts
  },
  weights: {
    regular: '400' as const,
    medium: '500' as const,
    semibold: '600' as const,
    bold: '700' as const,
    heavy: '800' as const,
  },
};

// Shadow tokens — single source of truth for elevation across the app.
// Values tuned for iOS / Android / Web parity. On web we add a boxShadow string
// alias to avoid the "shadow* style props are deprecated" warning.
const _shadow = (offsetY: number, radius: number, opacity: number, elevation: number) => {
  const base = {
    shadowColor: '#0F172A',
    shadowOffset: { width: 0, height: offsetY },
    shadowOpacity: opacity,
    shadowRadius: radius,
    elevation,
  };
  if (Platform.OS === 'web') {
    return {
      ...base,
      // RN-Web 0.20+ prefers boxShadow; keeps both keys for back-compat.
      boxShadow: `0 ${offsetY}px ${radius}px rgba(15, 23, 42, ${opacity})`,
    } as any;
  }
  return base;
};

export const SHADOW = {
  none: { elevation: 0 },
  sm: _shadow(1, 3, 0.06, 1),
  md: _shadow(4, 12, 0.10, 4),
  lg: _shadow(8, 24, 0.14, 10),
  xl: _shadow(16, 40, 0.18, 16),
  primary: {   // tinted shadow — used by the primary "Start a Bill" CTA
    shadowColor: COLORS.primary,
    shadowOffset: { width: 0, height: 6 },
    shadowOpacity: 0.28,
    shadowRadius: 14,
    elevation: 8,
    ...(Platform.OS === 'web'
      ? { boxShadow: `0 6px 14px rgba(79, 70, 229, 0.28)` } as any
      : {}),
  },
};

// Animation durations — keep micro-interactions short so they feel instant.
export const MOTION = {
  fast: 120,
  base: 200,
  slow: 320,
};

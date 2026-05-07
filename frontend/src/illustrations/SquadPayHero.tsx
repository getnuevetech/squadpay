// Hero illustration for the SquadPay welcome screen.
// Hand-crafted SVG — youthful, vibrant, on-brand (violet + cyan accent).
// Theme: friends splitting a bill on a phone, with floating receipt + sparkles.
import * as React from 'react';
import { View } from 'react-native';
import Svg, { Defs, LinearGradient, Stop, Rect, Circle, Path, G, Ellipse } from 'react-native-svg';

interface Props {
  size?: number; // square width = height
}

// All numeric values are in a 320x320 viewBox so the illustration scales crisply.
export function SquadPayHero({ size = 280 }: Props) {
  return (
    <View style={{ width: size, height: size, alignItems: 'center', justifyContent: 'center' }}>
      <Svg width={size} height={size} viewBox="0 0 320 320">
        <Defs>
          {/* Brand gradient — violet to indigo, matches CTA gradient */}
          <LinearGradient id="brand" x1="0" y1="0" x2="1" y2="1">
            <Stop offset="0" stopColor="#7C3AED" />
            <Stop offset="1" stopColor="#4F46E5" />
          </LinearGradient>
          {/* Soft violet halo */}
          <LinearGradient id="halo" x1="0" y1="0" x2="0" y2="1">
            <Stop offset="0" stopColor="#EDE9FE" stopOpacity="1" />
            <Stop offset="1" stopColor="#F5F3FF" stopOpacity="0" />
          </LinearGradient>
          {/* Cyan accent bubble */}
          <LinearGradient id="cyan" x1="0" y1="0" x2="1" y2="1">
            <Stop offset="0" stopColor="#22D3EE" />
            <Stop offset="1" stopColor="#06B6D4" />
          </LinearGradient>
          {/* Phone screen gradient */}
          <LinearGradient id="screen" x1="0" y1="0" x2="0" y2="1">
            <Stop offset="0" stopColor="#7C3AED" />
            <Stop offset="1" stopColor="#4F46E5" />
          </LinearGradient>
        </Defs>

        {/* Background halo blob */}
        <Ellipse cx="160" cy="170" rx="155" ry="135" fill="url(#halo)" />

        {/* Decorative dots */}
        <Circle cx="38" cy="68" r="3.5" fill="#22D3EE" opacity="0.55" />
        <Circle cx="280" cy="92" r="4" fill="#7C3AED" opacity="0.45" />
        <Circle cx="56" cy="240" r="3" fill="#7C3AED" opacity="0.4" />
        <Circle cx="282" cy="222" r="3.5" fill="#22D3EE" opacity="0.55" />

        {/* Floating receipt — back-left */}
        <G transform="translate(34 92) rotate(-12)">
          <Rect x="0" y="0" width="78" height="100" rx="8" fill="#FFFFFF" stroke="#E2E8F0" strokeWidth="1.5" />
          {/* Receipt header bar */}
          <Rect x="10" y="12" width="42" height="6" rx="3" fill="#7C3AED" />
          <Rect x="10" y="24" width="58" height="4" rx="2" fill="#E2E8F0" />
          {/* Line items */}
          <Rect x="10" y="36" width="48" height="3" rx="1.5" fill="#CBD5E1" />
          <Rect x="60" y="36" width="10" height="3" rx="1.5" fill="#CBD5E1" />
          <Rect x="10" y="46" width="42" height="3" rx="1.5" fill="#CBD5E1" />
          <Rect x="60" y="46" width="10" height="3" rx="1.5" fill="#CBD5E1" />
          <Rect x="10" y="56" width="36" height="3" rx="1.5" fill="#CBD5E1" />
          <Rect x="60" y="56" width="10" height="3" rx="1.5" fill="#CBD5E1" />
          {/* Total */}
          <Rect x="10" y="74" width="60" height="14" rx="4" fill="#EDE9FE" />
          <Rect x="14" y="79" width="20" height="4" rx="2" fill="#7C3AED" />
          <Rect x="50" y="79" width="16" height="4" rx="2" fill="#7C3AED" />
        </G>

        {/* Center phone */}
        <G transform="translate(102 60)">
          {/* Phone body */}
          <Rect x="0" y="0" width="116" height="208" rx="22" fill="#0F172A" />
          {/* Screen */}
          <Rect x="6" y="8" width="104" height="192" rx="16" fill="url(#screen)" />
          {/* Notch */}
          <Rect x="46" y="12" width="24" height="5" rx="2.5" fill="#0F172A" opacity="0.4" />

          {/* Screen content — Bill Balance card */}
          <Rect x="14" y="30" width="88" height="14" rx="3" fill="rgba(255,255,255,0.15)" />
          <Rect x="14" y="50" width="60" height="20" rx="3" fill="rgba(255,255,255,0.95)" />
          {/* Members row (3 avatars in different rings) */}
          <Circle cx="26" cy="100" r="13" fill="#FCD34D" />
          <Circle cx="26" cy="100" r="9" fill="#FFFFFF" />
          <Circle cx="58" cy="100" r="13" fill="#22D3EE" />
          <Circle cx="58" cy="100" r="9" fill="#FFFFFF" />
          <Circle cx="90" cy="100" r="13" fill="#F472B6" />
          <Circle cx="90" cy="100" r="9" fill="#FFFFFF" />

          {/* Progress bar */}
          <Rect x="14" y="130" width="88" height="6" rx="3" fill="rgba(255,255,255,0.2)" />
          <Rect x="14" y="130" width="60" height="6" rx="3" fill="#22D3EE" />

          {/* CTA pill */}
          <Rect x="14" y="160" width="88" height="26" rx="13" fill="#FFFFFF" />
          <Rect x="36" y="170" width="44" height="6" rx="3" fill="#7C3AED" />
        </G>

        {/* Cyan coin — front-right */}
        <G transform="translate(220 178) rotate(15)">
          <Circle cx="0" cy="0" r="38" fill="url(#cyan)" />
          <Circle cx="0" cy="0" r="30" fill="#FFFFFF" opacity="0.18" />
          <Path
            d="M -8 -6 L 8 -6 M -8 6 L 8 6 M 0 -12 L 0 12"
            stroke="#FFFFFF"
            strokeWidth="4"
            strokeLinecap="round"
          />
        </G>

        {/* Sparkles */}
        <G fill="#7C3AED" opacity="0.85">
          <Path d="M 252 56 l 2 5 l 5 2 l -5 2 l -2 5 l -2 -5 l -5 -2 l 5 -2 z" />
        </G>
        <G fill="#22D3EE" opacity="0.9">
          <Path d="M 50 198 l 1.5 4 l 4 1.5 l -4 1.5 l -1.5 4 l -1.5 -4 l -4 -1.5 l 4 -1.5 z" />
        </G>
        <G fill="#F472B6" opacity="0.85">
          <Path d="M 258 248 l 1.4 3.5 l 3.5 1.4 l -3.5 1.4 l -1.4 3.5 l -1.4 -3.5 l -3.5 -1.4 l 3.5 -1.4 z" />
        </G>
      </Svg>
    </View>
  );
}

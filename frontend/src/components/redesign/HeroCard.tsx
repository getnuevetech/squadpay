/**
 * HeroCard — purple-gradient bill summary at the top of both Lead and User
 * dashboards. Previously inlined and duplicated; now shared so both screens
 * stay visually identical by construction.
 *
 * Props:
 *   • group        — the enriched Group object (with members + funding)
 *   • subLabel     — "Lead Dashboard" | "User Dashboard"
 *   • myShare      — viewer's personal share (formatted on screen as $X.XX)
 *   • grandTotal   — bill total (items + tax + tip + all fees)
 *   • collectedAmount  — what's been contributed so far
 *   • displayedPct — % progress (capped at 99 while outstanding > 0)
 *   • remaining    — grand_total − contributed
 *   • testIDPrefix — testing handle prefix ("dashboard" | "summary")
 */
import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import type { Group } from '../../api';
import { COLORS, FONT } from '../../theme';
import { StatusBadge } from '../../StatusBadge';
import { AvatarRing } from '../AvatarRing';

interface HeroCardProps {
  group: Group;
  subLabel: string;
  myShare: number;
  grandTotal: number;
  collectedAmount: number;
  displayedPct: number;
  remaining: number;
  testIDPrefix: string;
}

export function HeroCard({
  group,
  subLabel,
  myShare,
  grandTotal,
  collectedAmount,
  displayedPct,
  remaining,
  testIDPrefix,
}: HeroCardProps) {
  return (
    <LinearGradient
      colors={['#3F1F8C', '#5B2BC8', '#7C3AED']}
      start={{ x: 0, y: 0 }}
      end={{ x: 1, y: 1 }}
      style={styles.heroV2}
      testID={`${testIDPrefix}-your-card`}
    >
      <View style={styles.heroV2Top}>
        <View style={{ flex: 1 }}>
          <Text
            style={styles.heroV2GroupTitle}
            numberOfLines={2}
            testID={`${testIDPrefix}-group-title`}
          >
            {(group as any).title || (group as any).name || 'Bill'}
          </Text>
          <Text style={styles.heroV2SubLabel}>{subLabel}</Text>
        </View>
        <StatusBadge
          status={(group as any).derived_status}
          size="sm"
          testID={`${testIDPrefix}-status-badge`}
        />
      </View>

      <View style={styles.heroV2AmountCol}>
        <Text style={styles.heroV2Label}>Your Share</Text>
        <Text style={styles.heroV2Amount} testID={`${testIDPrefix}-your-amount`}>
          ${myShare.toFixed(2)}
        </Text>
        <Text style={styles.heroV2Total} testID={`${testIDPrefix}-bill-total`}>
          of ${grandTotal.toFixed(2)} bill total
        </Text>
      </View>

      <View style={styles.heroV2Avatars}>
        {group.members.slice(0, 4).map((m: any, i: number) => (
          <View
            key={m.user_id}
            style={[styles.heroV2Avatar, { marginLeft: i === 0 ? 0 : -10, zIndex: 10 - i }]}
          >
            <AvatarRing
              name={m.name || '?'}
              seed={m.user_id}
              size={32}
              showLeadCrown={m.user_id === group.lead_id}
            />
          </View>
        ))}
        {group.members.length > 4 ? (
          <View style={[styles.heroV2Avatar, styles.heroV2AvatarMore, { marginLeft: -10 }]}>
            <Text style={styles.heroV2AvatarMoreText}>+{group.members.length - 4}</Text>
          </View>
        ) : null}
      </View>

      <View style={styles.heroV2Meta}>
        <Text style={styles.heroV2MetaPrimary}>
          ${collectedAmount.toFixed(2)} of ${grandTotal.toFixed(2)} collected
        </Text>
        <Text style={styles.heroV2MetaSecondary}>{Math.round(displayedPct)}%</Text>
      </View>
      <View style={styles.heroV2Track}>
        <View style={[styles.heroV2Fill, { width: `${Math.min(100, displayedPct)}%` }]} />
      </View>
      <View style={styles.heroV2RemainingRow}>
        <Text style={styles.heroV2RemainingLabel}>Remaining</Text>
        <Text style={styles.heroV2RemainingValue}>${remaining.toFixed(2)}</Text>
      </View>
    </LinearGradient>
  );
}

const styles = StyleSheet.create({
  heroV2: {
    borderRadius: 24,
    paddingHorizontal: 18,
    paddingTop: 16,
    paddingBottom: 18,
    marginBottom: 16,
    shadowColor: '#3F1F8C',
    shadowOpacity: 0.32,
    shadowRadius: 24,
    shadowOffset: { width: 0, height: 16 },
    elevation: 10,
  },
  heroV2Top: { flexDirection: 'row', alignItems: 'center', gap: 10, marginBottom: 10 },
  heroV2GroupTitle: {
    color: '#FFFFFF',
    fontWeight: FONT.weights.heavy,
    fontSize: 18,
    letterSpacing: -0.3,
    lineHeight: 22,
  },
  heroV2SubLabel: {
    color: '#D7C7FB',
    fontSize: 11,
    fontWeight: FONT.weights.semibold,
    letterSpacing: 1,
    textTransform: 'uppercase',
    marginTop: 4,
  },
  heroV2AmountCol: { marginTop: 8, alignItems: 'flex-end' },
  heroV2Label: {
    color: '#fff',
    fontSize: 13,
    fontWeight: FONT.weights.semibold,
    letterSpacing: 0.5,
    textTransform: 'uppercase',
    paddingBottom: 4,
  },
  heroV2Amount: {
    color: '#fff',
    fontSize: 44,
    fontWeight: FONT.weights.heavy,
    letterSpacing: -1,
    lineHeight: 48,
  },
  heroV2Total: { color: '#D7C7FB', fontSize: 12, marginTop: 4 },
  heroV2Avatars: { flexDirection: 'row', alignItems: 'center', marginTop: 14 },
  heroV2Avatar: { borderWidth: 2, borderColor: '#fff', borderRadius: 999 },
  heroV2AvatarMore: {
    minWidth: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: 'rgba(255,255,255,0.18)',
    paddingHorizontal: 8,
    alignItems: 'center',
    justifyContent: 'center',
  },
  heroV2AvatarMoreText: { color: '#fff', fontSize: 11, fontWeight: FONT.weights.bold },
  heroV2Meta: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginTop: 14,
  },
  heroV2MetaPrimary: { color: '#fff', fontWeight: FONT.weights.semibold, fontSize: 12 },
  heroV2MetaSecondary: { color: '#D7C7FB', fontSize: 12 },
  heroV2Track: {
    height: 6,
    borderRadius: 999,
    backgroundColor: 'rgba(255,255,255,0.18)',
    marginTop: 8,
    overflow: 'hidden',
  },
  heroV2Fill: { height: '100%', backgroundColor: '#fff', borderRadius: 999 },
  heroV2RemainingRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginTop: 10,
    paddingTop: 10,
    borderTopWidth: 1,
    borderTopColor: 'rgba(255,255,255,0.18)',
  },
  heroV2RemainingLabel: {
    color: '#D7C7FB',
    fontSize: 12,
    fontWeight: FONT.weights.semibold,
    textTransform: 'uppercase',
    letterSpacing: 0.6,
  },
  heroV2RemainingValue: { color: '#fff', fontSize: 18, fontWeight: FONT.weights.heavy },
});

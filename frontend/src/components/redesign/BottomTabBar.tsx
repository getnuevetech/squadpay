/**
 * Floating bottom tab bar — 5 items with a raised center + button.
 *
 * IA (June 2026 — founder mandate, supersedes the previous Squad slot):
 *   Home / Activity / + / Support / Settings
 *
 * Why "Support" replaced "Squad" in the tab bar:
 *   - Squad screen (`/squad`) is now reached via the Settings menu row
 *     ("Friends & Squad") since it's a contacts directory rather than a
 *     primary navigation destination.
 *   - One-tap "Support" is a high-trust signal for a financial app; cutting
 *     the path to customer service reduces complaints + escalations.
 *
 * Implementation note: this is a *visual* tab bar rendered on the home (and
 * other top-level) screens — not an expo-router Tabs() container, so it does
 * NOT touch the existing routing tree (rollback-safe). Each tab simply
 * router.push()'s the target route.
 */
import { useState } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, Platform } from 'react-native';
import { useRouter, usePathname } from 'expo-router';
import { Home, List, Plus, Headset, Settings as SettingsIcon } from 'lucide-react-native';
import { COLORS, FONT } from '../../theme';
import { NewBillSheet } from '../NewBillSheet';

export type TabKey = 'home' | 'activity' | 'create' | 'support' | 'settings';

type Tab = {
  key: TabKey;
  label: string;
  href: string;
  icon: React.ComponentType<{ size: number; color: string; strokeWidth?: number }>;
};

const TABS: Tab[] = [
  { key: 'home', label: 'Home', href: '/', icon: Home },
  { key: 'activity', label: 'Activity', href: '/activity', icon: List },
  { key: 'create', label: '', href: '/create', icon: Plus },
  { key: 'support', label: 'Support', href: '/contact', icon: HeartHandshake },
  { key: 'settings', label: 'Settings', href: '/settings', icon: SettingsIcon },
];

type Props = {
  active?: TabKey;
  testID?: string;
  /**
   * Optional override for the raised center "+" button. When provided,
   * the host screen can intercept the tap (e.g. to open a "Start a new
   * bill / Join a bill" action sheet) instead of routing straight to
   * /create. When omitted, the default `/create` push behavior is kept.
   */
  onCenterPress?: () => void;
};

export function BottomTabBar({ active, testID = 'bottom-tab-bar', onCenterPress }: Props) {
  const router = useRouter();
  const pathname = usePathname();
  // Sheet visibility — the BIG "+" opens a "Start / Join a bill" action
  // sheet by default. Hosts can pass `onCenterPress` to override entirely.
  const [sheetOpen, setSheetOpen] = useState(false);

  const computedActive: TabKey = active || (
    pathname?.startsWith('/activity') ? 'activity' :
    pathname?.startsWith('/contact') ? 'support' :
    pathname?.startsWith('/settings') ? 'settings' :
    pathname?.startsWith('/create') ? 'create' :
    'home'
  );

  return (
    <View style={styles.wrap} testID={testID}>
      <View style={styles.bar}>
        {TABS.map((t) => {
          const isActive = computedActive === t.key;
          const isCenter = t.key === 'create';
          const Icon = t.icon;
          if (isCenter) {
            return (
              <TouchableOpacity
                key={t.key}
                style={styles.centerWrap}
                onPress={() => {
                  if (onCenterPress) onCenterPress();
                  else setSheetOpen(true);
                }}
                activeOpacity={0.85}
                testID={`tab-${t.key}`}
              >
                <View style={styles.centerBtn}>
                  <Icon size={26} color="#fff" strokeWidth={2.6} />
                </View>
              </TouchableOpacity>
            );
          }
          return (
            <TouchableOpacity
              key={t.key}
              style={styles.item}
              onPress={() => router.push(t.href as any)}
              activeOpacity={0.7}
              testID={`tab-${t.key}`}
            >
              <Icon
                size={22}
                color={isActive ? COLORS.primary : COLORS.subtext}
                strokeWidth={isActive ? 2.4 : 2}
              />
              <Text style={[styles.label, isActive && styles.labelActive]} numberOfLines={1}>
                {t.label}
              </Text>
            </TouchableOpacity>
          );
        })}
      </View>
      <NewBillSheet
        visible={sheetOpen}
        onClose={() => setSheetOpen(false)}
        onStart={() => router.push('/create')}
        onJoin={() => router.push('/join/code')}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    position: 'absolute',
    left: 0,
    right: 0,
    bottom: 0,
    paddingHorizontal: 12,
    paddingBottom: Platform.OS === 'ios' ? 18 : 12,
    paddingTop: 6,
    backgroundColor: 'transparent',
  },
  bar: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#fff',
    borderRadius: 28,
    paddingHorizontal: 6,
    paddingVertical: 8,
    shadowColor: '#1F1240',
    shadowOpacity: 0.12,
    shadowRadius: 18,
    shadowOffset: { width: 0, height: 8 },
    elevation: 10,
    borderWidth: 1,
    borderColor: '#F1ECFE',
  },
  item: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 2, paddingVertical: 4 },
  label: { fontSize: 10, color: COLORS.subtext, fontWeight: FONT.weights.medium },
  labelActive: { color: COLORS.primary, fontWeight: FONT.weights.bold },
  centerWrap: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  centerBtn: {
    width: 56,
    height: 56,
    borderRadius: 28,
    backgroundColor: COLORS.primary,
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: -22,
    shadowColor: COLORS.primary,
    shadowOpacity: 0.4,
    shadowRadius: 14,
    shadowOffset: { width: 0, height: 8 },
    elevation: 10,
    borderWidth: 4,
    borderColor: '#fff',
  },
});

export default BottomTabBar;

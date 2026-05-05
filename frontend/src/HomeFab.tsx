import React from 'react';
import { TouchableOpacity, StyleSheet, Platform } from 'react-native';
import { useRouter, usePathname } from 'expo-router';
import { Home } from 'lucide-react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { COLORS, RADIUS } from './theme';

/**
 * Always-visible "go home" pill, fixed in the top-left.
 * Hides itself on the home route to avoid redundancy.
 */
export function HomeFab() {
  const router = useRouter();
  const pathname = usePathname();
  const insets = useSafeAreaInsets();

  // Hide on home, auth, or unrouted screens
  if (!pathname || pathname === '/' || pathname === '/index' || pathname.startsWith('/auth')) {
    return null;
  }

  return (
    <TouchableOpacity
      testID="home-fab"
      onPress={() => router.replace('/')}
      activeOpacity={0.85}
      style={[styles.fab, { top: insets.top + 8 }]}
      hitSlop={8}
    >
      <Home size={18} color="#fff" />
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  fab: {
    position: 'absolute',
    left: 12,
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: COLORS.primary,
    alignItems: 'center',
    justifyContent: 'center',
    zIndex: 1000,
    ...Platform.select({
      ios: {
        shadowColor: '#000',
        shadowOpacity: 0.18,
        shadowRadius: 6,
        shadowOffset: { width: 0, height: 2 },
      },
      android: {
        elevation: 4,
      },
    }),
  },
});

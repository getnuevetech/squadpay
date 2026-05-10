/**
 * "● Live Squad Session" pill (Image 2). Used in the home hero panel when at
 * least one group is currently active.
 */
import { View, Text, StyleSheet } from 'react-native';
import { FONT } from '../../theme';

type Props = {
  label?: string;
  onDark?: boolean;
  testID?: string;
};

export function LiveSessionPill({ label = 'Live Squad Session', onDark = true, testID }: Props) {
  return (
    <View
      testID={testID}
      style={[
        styles.pill,
        onDark ? styles.pillOnDark : styles.pillOnLight,
      ]}
    >
      <View style={styles.dot} />
      <Text style={[styles.text, { color: onDark ? '#E9DCFE' : '#5B2BC8' }]}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  pill: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 999,
    alignSelf: 'flex-start',
    borderWidth: 1,
  },
  pillOnDark: {
    backgroundColor: 'rgba(255,255,255,0.12)',
    borderColor: 'rgba(255,255,255,0.18)',
  },
  pillOnLight: {
    backgroundColor: '#F1ECFE',
    borderColor: '#E0D5FB',
  },
  dot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: '#22C55E',
    shadowColor: '#22C55E',
    shadowOpacity: 0.6,
    shadowRadius: 6,
  },
  text: { fontWeight: FONT.weights.bold, fontSize: 12, letterSpacing: 0.2 },
});

export default LiveSessionPill;

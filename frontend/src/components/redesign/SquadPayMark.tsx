/**
 * SquadPay brand mark — purple rounded-square with a centered sparkle, optionally
 * paired with the wordmark. Used in landing hero, home header, and tab bar center.
 */
import { View, Text, StyleSheet } from 'react-native';
import Svg, { Path } from 'react-native-svg';
import { COLORS, FONT } from '../../theme';

type Props = {
  size?: number;
  showWordmark?: boolean;
  variant?: 'light' | 'onDark';
  testID?: string;
};

export function SquadPayMark({ size = 36, showWordmark = true, variant = 'light', testID }: Props) {
  const wordColor = variant === 'onDark' ? '#fff' : COLORS.primary;
  return (
    <View style={styles.row} testID={testID}>
      <View
        style={[
          styles.tile,
          { width: size, height: size, borderRadius: Math.round(size * 0.28) },
        ]}
      >
        <Svg width={Math.round(size * 0.55)} height={Math.round(size * 0.55)} viewBox="0 0 24 24" fill="none">
          {/* 4-point sparkle */}
          <Path
            d="M12 2 L13.6 9.2 L21 11 L13.6 12.8 L12 22 L10.4 12.8 L3 11 L10.4 9.2 Z"
            fill="#fff"
          />
        </Svg>
      </View>
      {showWordmark ? (
        <Text style={[styles.wordmark, { color: wordColor, fontSize: Math.round(size * 0.78) }]}>
          SquadPay
        </Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  tile: {
    backgroundColor: COLORS.primary,
    alignItems: 'center',
    justifyContent: 'center',
    shadowColor: COLORS.primary,
    shadowOpacity: 0.3,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 6 },
    elevation: 4,
  },
  wordmark: {
    fontWeight: FONT.weights.bold,
    letterSpacing: -0.5,
  },
});

export default SquadPayMark;

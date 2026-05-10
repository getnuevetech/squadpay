/**
 * SquadPay brand mark — purple rounded-square with a centered 4-point sparkle,
 * optionally paired with the wordmark. Used in landing hero + home header.
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
  const tileSize = size;
  const wordSize = Math.round(size * 0.7);
  const sparkleSize = Math.round(tileSize * 0.62);
  return (
    <View style={styles.row} testID={testID}>
      <View
        style={[
          styles.tile,
          { width: tileSize, height: tileSize, borderRadius: Math.round(tileSize * 0.28) },
        ]}
      >
        {/* Crisp 4-point sparkle (concave diamond) — matches reference. */}
        <Svg width={sparkleSize} height={sparkleSize} viewBox="0 0 100 100">
          <Path
            d="M50 6 C52 36 64 48 94 50 C64 52 52 64 50 94 C48 64 36 52 6 50 C36 48 48 36 50 6 Z"
            fill="#ffffff"
          />
        </Svg>
      </View>
      {showWordmark ? (
        <Text style={[styles.wordmark, { color: wordColor, fontSize: wordSize }]}>
          SquadPay
        </Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center', gap: 12 },
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
    letterSpacing: -0.8,
  },
});

export default SquadPayMark;

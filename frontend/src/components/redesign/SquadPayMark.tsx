/**
 * SquadPay brand mark — uses the real SquadPay logo (group silhouettes + $),
 * optionally paired with the wordmark. Used in landing hero + home header.
 */
import { View, Text, Image, StyleSheet } from 'react-native';
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
  return (
    <View style={styles.row} testID={testID}>
      <View
        style={[
          styles.tile,
          { width: tileSize, height: tileSize, borderRadius: Math.round(tileSize * 0.28) },
        ]}
      >
        <Image
          // Real SquadPay logo (icon-only mark, transparent bg). Sized
          // inside the purple tile so it matches the iOS/Android app icon.
          source={require('../../../assets/images/squadpay-mark.png')}
          style={{
            width: Math.round(tileSize * 0.82),
            height: Math.round(tileSize * 0.82),
            resizeMode: 'contain',
          }}
        />
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
    // Logo is purple — must sit on a light surface to be visible. Using a
    // white tile with a soft purple ring keeps brand presence without
    // burying the logo in the same colour.
    backgroundColor: '#FFFFFF',
    borderWidth: 1,
    borderColor: COLORS.primarySoft || 'rgba(124, 58, 237, 0.18)',
    alignItems: 'center',
    justifyContent: 'center',
    shadowColor: COLORS.primary,
    shadowOpacity: 0.12,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 6 },
    elevation: 2,
  },
  wordmark: {
    fontWeight: '900',
    letterSpacing: -1,
  },
});

export default SquadPayMark;

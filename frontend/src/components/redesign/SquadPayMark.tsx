/**
 * SquadPay brand mark — uses the real SquadPay logo (group silhouettes + $),
 * optionally paired with the wordmark. Used in landing hero + home header.
 *
 * Source preference:
 *   1. Admin-uploaded override from /api/runtime/logo/brand_mark (if any)
 *   2. Bundled `assets/images/squadpay-mark.png` fallback
 *
 * The override fetch is fire-and-forget — if the backend is unreachable we
 * keep using the bundled asset so the UI never breaks.
 */
import React, { useEffect, useState } from 'react';
import { View, Text, Image, StyleSheet } from 'react-native';
import { COLORS, FONT } from '../../theme';

type Props = {
  size?: number;
  showWordmark?: boolean;
  variant?: 'light' | 'onDark';
  testID?: string;
};

const FALLBACK = require('../../../assets/images/squadpay-mark.png');
const BACKEND_URL = process.env.EXPO_PUBLIC_BACKEND_URL || '';

// Module-level memo so every <SquadPayMark/> instance gets the same URL
// without each one re-fetching on mount.
let _cachedRemoteUri: string | null | undefined = undefined;
async function resolveRemoteMarkUri(): Promise<string | null> {
  if (_cachedRemoteUri !== undefined) return _cachedRemoteUri;
  if (!BACKEND_URL) {
    _cachedRemoteUri = null;
    return null;
  }
  try {
    // The endpoint 302s to the bundled asset when there is no override.
    // We treat any 200 (direct PNG response) as "admin uploaded a custom",
    // and a non-OK / redirect to the static asset as "use the bundled one".
    const url = `${BACKEND_URL}/api/runtime/logo/brand_mark?v=${Date.now()}`;
    const res = await fetch(url, { method: 'GET', redirect: 'manual' as any });
    if (res.status === 200 && (res.headers.get('content-type') || '').startsWith('image/')) {
      _cachedRemoteUri = url;
    } else {
      _cachedRemoteUri = null;
    }
  } catch {
    _cachedRemoteUri = null;
  }
  return _cachedRemoteUri;
}

export function SquadPayMark({ size = 36, showWordmark = true, variant = 'light', testID }: Props) {
  const wordColor = variant === 'onDark' ? '#fff' : COLORS.primary;
  const tileSize = size;
  const wordSize = Math.round(size * 0.7);
  const [remoteUri, setRemoteUri] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    resolveRemoteMarkUri().then((u) => { if (!cancelled) setRemoteUri(u); });
    return () => { cancelled = true; };
  }, []);
  const source = remoteUri ? { uri: remoteUri } : FALLBACK;

  return (
    <View style={styles.row} testID={testID}>
      <View
        style={[
          styles.tile,
          { width: tileSize, height: tileSize, borderRadius: Math.round(tileSize * 0.28) },
        ]}
      >
        <Image
          source={source}
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

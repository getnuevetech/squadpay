/**
 * useSettlementMode \u2014 hook that reads admin-configured settlement rail(s).
 *
 * Returns:
 *   "virtual_card"  \u2014 only the Squad Card flow is enabled. Hide any
 *                     "withdraw to my card" CTAs.
 *   "lead_card"     \u2014 only the lead-card-payout flow is enabled. Hide the
 *                     Squad Card surface entirely; Lead receives the squad
 *                     money via instant payout to their saved card.
 *   "lead_choice"   \u2014 BOTH flows are enabled. Show both options to Lead
 *                     (Lead-side picker UI is future work; current behaviour
 *                     keeps Squad Card visible).
 *
 * Public endpoint, no auth required. Cached for 60s in module-local memory
 * so we don't re-fetch on every screen mount.
 */
import { useEffect, useState } from 'react';
import Constants from 'expo-constants';

export type SettlementMode = 'virtual_card' | 'lead_card' | 'lead_choice';

let _cache: { mode: SettlementMode; ts: number } | null = null;
const TTL_MS = 60_000;

function backendUrl(): string {
  // EXPO_PUBLIC_BACKEND_URL is set by the build environment; in dev it's the
  // same origin so we can fall back to '' (relative).
  return (
    (process.env.EXPO_PUBLIC_BACKEND_URL as string | undefined) ||
    (Constants?.expoConfig?.extra?.backendUrl as string | undefined) ||
    ''
  );
}

export async function fetchSettlementMode(): Promise<SettlementMode> {
  if (_cache && Date.now() - _cache.ts < TTL_MS) return _cache.mode;
  try {
    const base = backendUrl();
    const r = await fetch(`${base}/api/runtime/settlement-mode`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const j = await r.json();
    const m = (j?.mode || 'virtual_card') as SettlementMode;
    _cache = { mode: m, ts: Date.now() };
    return m;
  } catch {
    // Fail-safe: assume virtual_card so existing flows keep working.
    return 'virtual_card';
  }
}

export function useSettlementMode(): {
  mode: SettlementMode;
  loading: boolean;
  refresh: () => Promise<void>;
} {
  const [mode, setMode] = useState<SettlementMode>(_cache?.mode || 'virtual_card');
  const [loading, setLoading] = useState(!_cache);

  const refresh = async () => {
    setLoading(true);
    try {
      const m = await fetchSettlementMode();
      setMode(m);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    // Only fire a network call if cache is stale.
    if (!_cache || Date.now() - _cache.ts > TTL_MS) {
      refresh();
    } else {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return { mode, loading, refresh };
}

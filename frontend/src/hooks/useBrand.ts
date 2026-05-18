/**
 * useBrand — fetches admin-configured brand strings from the public
 * /api/runtime/brand endpoint (support_email, default_tip_suggestions,
 * currency) and caches them in-memory for the rest of the session.
 *
 * Customer-facing screens should NEVER hardcode the support email,
 * tip-suggestion percentages, or currency code. Use this hook so that
 * admin edits via /admin/platform-fees → App Config → Brand surface
 * everywhere immediately.
 *
 * Usage:
 *   const brand = useBrand();
 *   <Text>{brand.support_email}</Text>
 *   {brand.default_tip_suggestions.map(p => <Chip key={p} label={`${p}%`} />)}
 *
 * Non-blocking: returns sensible defaults until the network resolves so
 * screens never flash blank strings.
 */
import { useEffect, useState } from 'react';

export type BrandConfig = {
  support_email: string;
  default_tip_suggestions: number[];
  currency: string;
};

const DEFAULTS: BrandConfig = {
  support_email: 'support@getsquadpay.com',
  default_tip_suggestions: [15, 18, 20],
  currency: 'USD',
};

// Module-level cache shared across every mount/screen that uses the hook.
let _cached: BrandConfig | null = null;
let _inflight: Promise<BrandConfig> | null = null;

const BACKEND_URL = process.env.EXPO_PUBLIC_BACKEND_URL || '';

async function _fetchBrand(): Promise<BrandConfig> {
  if (_cached) return _cached;
  if (_inflight) return _inflight;
  _inflight = (async () => {
    try {
      // Cache-bust so admin edits show up on next mount without restart;
      // also defeats edge CDN caching for this endpoint.
      const url = `${BACKEND_URL}/api/runtime/brand?v=${Date.now()}`;
      const res = await fetch(url, { cache: 'no-store' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = (await res.json()) as Partial<BrandConfig>;
      const next: BrandConfig = {
        support_email: json.support_email || DEFAULTS.support_email,
        default_tip_suggestions:
          Array.isArray(json.default_tip_suggestions) && json.default_tip_suggestions.length > 0
            ? json.default_tip_suggestions.map(Number).filter((n) => Number.isFinite(n))
            : DEFAULTS.default_tip_suggestions,
        currency: json.currency || DEFAULTS.currency,
      };
      _cached = next;
      return next;
    } catch {
      // Network failure → return defaults; don't poison cache so we retry next mount.
      return DEFAULTS;
    } finally {
      _inflight = null;
    }
  })();
  return _inflight;
}

/** Force a re-fetch on next access (e.g., after admin edits brand config). */
export function invalidateBrandCache() {
  _cached = null;
  _inflight = null;
}

/**
 * Read the admin-configured brand strings. Returns DEFAULTS / cached value
 * immediately to avoid UI flicker, then refetches in the background on
 * every mount — so admin edits on one device/tab propagate to customer
 * sessions without requiring a hard reload.
 */
export function useBrand(): BrandConfig {
  const [brand, setBrand] = useState<BrandConfig>(_cached || DEFAULTS);
  useEffect(() => {
    let alive = true;
    _cached = null; // refetch every mount; see comment in useFeeLabels.ts
    _fetchBrand().then((next) => {
      if (alive) setBrand(next);
    });
    return () => {
      alive = false;
    };
  }, []);
  return brand;
}

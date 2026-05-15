/**
 * useFeeLabels — fetches admin-configured fee label strings from the public
 * /api/runtime/fee-labels endpoint and caches them in-memory for the rest of
 * the session.
 *
 * Customer-facing screens (BillBreakdown, summary, pay flow) should NEVER
 * hardcode "Platform Fee" / "Transaction Fee" / "Insurance" or the names of
 * the two configurable extra-fee slots. Use this hook instead so admin
 * label edits show up immediately in the app.
 *
 * Usage:
 *   const labels = useFeeLabels();
 *   <Text>{labels.platform_fee_label}</Text>
 *   <Text>{labels.extra_fees.find(e => e.id === 'extra_1')?.name}</Text>
 *
 * The hook is non-blocking — it returns sensible defaults until the network
 * response lands, so screens never flash empty strings.
 */
import { useEffect, useState } from 'react';

export type FeeLabels = {
  transaction_fee_label: string;
  platform_fee_label: string;
  insurance_label: string;
  extra_fees: Array<{ id: string; name: string }>;
};

const DEFAULTS: FeeLabels = {
  transaction_fee_label: 'Transaction Fee',
  platform_fee_label: 'Platform Fee',
  insurance_label: 'Insurance',
  extra_fees: [
    { id: 'extra_1', name: 'Extra Fee 1' },
    { id: 'extra_2', name: 'Extra Fee 2' },
  ],
};

// Module-level cache — shared across every mount of every screen that uses
// the hook. Avoids re-fetching the same labels for every BillBreakdown render.
let _cached: FeeLabels | null = null;
let _inflight: Promise<FeeLabels> | null = null;

const BACKEND_URL = process.env.EXPO_PUBLIC_BACKEND_URL || '';

async function _fetchLabels(): Promise<FeeLabels> {
  if (_cached) return _cached;
  if (_inflight) return _inflight;
  _inflight = (async () => {
    try {
      // Cache-bust so admin edits show up on the very next mount without
      // needing a full app reload (and to bypass any aggressive edge cache).
      const url = `${BACKEND_URL}/api/runtime/fee-labels?v=${Date.now()}`;
      const res = await fetch(url, { cache: 'no-store' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = (await res.json()) as Partial<FeeLabels>;
      const next: FeeLabels = {
        transaction_fee_label: json.transaction_fee_label || DEFAULTS.transaction_fee_label,
        platform_fee_label: json.platform_fee_label || DEFAULTS.platform_fee_label,
        insurance_label: json.insurance_label || DEFAULTS.insurance_label,
        extra_fees:
          Array.isArray(json.extra_fees) && json.extra_fees.length > 0
            ? json.extra_fees.map((e) => ({ id: String(e.id), name: String(e.name) }))
            : DEFAULTS.extra_fees,
      };
      _cached = next;
      return next;
    } catch {
      // Network failure → return defaults. Don't poison the cache so the
      // next mount will retry.
      return DEFAULTS;
    } finally {
      _inflight = null;
    }
  })();
  return _inflight;
}

/** Force a re-fetch on next access (e.g., after admin edits the labels). */
export function invalidateFeeLabelsCache() {
  _cached = null;
  _inflight = null;
}

/**
 * Read the admin-configured fee labels. Returns DEFAULTS immediately and
 * upgrades to the server values once they arrive.
 */
export function useFeeLabels(): FeeLabels {
  const [labels, setLabels] = useState<FeeLabels>(_cached || DEFAULTS);
  useEffect(() => {
    let alive = true;
    _fetchLabels().then((next) => {
      if (alive) setLabels(next);
    });
    return () => {
      alive = false;
    };
  }, []);
  return labels;
}

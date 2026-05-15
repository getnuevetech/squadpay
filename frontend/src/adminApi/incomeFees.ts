/**
 * adminApi/incomeFees.ts — Platform-revenue / fees ledger admin.
 *
 * Owns the Income & Fees export buttons (CSV / PDF) and the response shape
 * consumed by the master `adminApi.getIncomeFees()` method (which still
 * lives in `_legacy.ts` and imports the types from here).
 */
import { BACKEND_URL, _downloadFile } from './_core';

export type IncomeFeesGroup = {
  id: string;
  title: string;
  status: string;
  created_at: string | null;
  settled_at: string | null;
  lead_id: string;
  members_count: number;
  gross_contributed: number;
  // Phase: per-group tabular ledger — surface tax/tips/item count
  tax: number;
  tips: number;
  total_items: number;
  fees: {
    transaction_fees: number;
    platform_fees: number;
    /** June 2025 — Layered Insurance fee aggregated per group. */
    insurance?: number;
    extra_1: number;
    extra_2: number;
    extra_other: number;
    total_retained: number;
  };
  contributions: Array<{
    user_id: string;
    user_name: string;
    amount: number;
    stripe_pi: string | null;
    ts: string | null;
    transaction_fee: number;
    platform_fee: number;
    extra_1: number;
    extra_2: number;
    fee_slice_total: number;
  }>;
  virtual_card_last4: string | null;
};

export type IncomeFeesResponse = {
  totals: {
    transaction_fees: number;
    platform_fees: number;
    /** June 2025 — Layered Insurance fee total. */
    insurance?: number;
    extra_1: number;
    extra_2: number;
    extra_other: number;
    total_retained: number;
    groups_counted: number;
    contributions_counted: number;
    gross_contributed: number;
  };
  window_totals: { week: number; month: number };
  groups: IncomeFeesGroup[];
};

export const incomeFeesApi = {
  downloadCsv: async (params: { status?: string; since?: string; until?: string }) => {
    const q = new URLSearchParams();
    if (params.status) q.set('status', params.status);
    if (params.since) q.set('since', params.since);
    if (params.until) q.set('until', params.until);
    const url = `${BACKEND_URL}/api/admin/income-fees/export.csv${q.toString() ? `?${q.toString()}` : ''}`;
    return _downloadFile(url, 'text/csv', 'income_fees.csv');
  },
  downloadPdf: async (params: { status?: string; since?: string; until?: string }) => {
    const q = new URLSearchParams();
    if (params.status) q.set('status', params.status);
    if (params.since) q.set('since', params.since);
    if (params.until) q.set('until', params.until);
    const url = `${BACKEND_URL}/api/admin/income-fees/export.pdf${q.toString() ? `?${q.toString()}` : ''}`;
    return _downloadFile(url, 'application/pdf', 'income_fees.pdf');
  },
};

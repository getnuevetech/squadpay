/**
 * adminApi/reconciliation.ts — PSP reconciliation admin
 * (settings, list/read rows, manual trigger, master-account ledger).
 */
import { request } from './_core';

export type ReconciliationSettings = {
  credit_contributors_enabled: boolean;
  auto_disable_card: boolean;
  master_account_id?: string;
  updated_at?: string | null;
  updated_by?: string | null;
};

export type ReconciliationRow = {
  id: string;
  group_id: string;
  group_title: string;
  lead_id?: string | null;
  lead_name?: string | null;
  lead_phone?: string | null;
  card_id: string;
  source: 'auto' | 'manual';
  amount_collected: number;
  amount_spent: number;
  leftover: number;
  action: 'credit_contributors' | 'moved_to_master' | 'no_leftover' | null;
  master_account_entry_id?: string | null;
  master_balance_after?: number;
  contributor_credits?: Array<{ user_id: string; name?: string | null; amount: number; credit_id: string }>;
  merchant_summary?: { name?: string | null; category?: string | null; city?: string | null };
  transactions_count: number;
  status: 'pending' | 'finalized';
  created_at: string;
  created_by?: string;
};

export type MasterAccountEntry = {
  id: string;
  master_account_id: string;
  type: 'leftover_in' | 'manual_adjust';
  group_id: string;
  group_title: string;
  lead_id?: string | null;
  lead_name?: string | null;
  card_id: string;
  amount: number;
  balance_after: number;
  reconciliation_id?: string | null;
  note?: string;
  created_at: string;
  created_by?: string;
};

export const reconciliationApi = {
  // ────── Drift Detection (Real-Time Ledger Reconciliation, Phase 1) ──────
  // Detects DB denormalization rot + settlement imbalances. Pure observation.
  driftList: (params?: { resolved?: boolean; kind?: string; limit?: number; skip?: number }) => {
    const q = new URLSearchParams();
    if (params?.resolved !== undefined) q.set('resolved', String(params.resolved));
    if (params?.kind) q.set('kind', params.kind);
    if (params?.limit) q.set('limit', String(params.limit));
    if (params?.skip) q.set('skip', String(params.skip));
    const qs = q.toString();
    return request<{
      items: Array<{
        id: string;
        group_id: string;
        group_title: string;
        group_status: string;
        kind: 'db_internal' | 'settlement_imbalance' | string;
        expected: number;
        observed: number;
        delta: number;
        detected_at: string;
        resolved: boolean;
        resolved_at?: string;
        resolved_by?: string;
        resolution_note?: string;
        notes?: string;
      }>;
      total: number;
      skip: number;
      limit: number;
    }>(`/reconciliation/drift${qs ? `?${qs}` : ''}`);
  },
  driftRuns: () =>
    request<{
      items: Array<{
        id: string;
        ran_at: string;
        elapsed_ms: number;
        kinds_scanned: string[];
        drifts_found: number;
        rows_inserted: number;
        rows_refreshed: number;
      }>;
    }>('/reconciliation/drift/runs'),
  driftScanNow: (kinds?: string[]) => {
    const q = kinds && kinds.length ? `?kinds=${encodeURIComponent(kinds.join(','))}` : '';
    return request<{
      ran_at: string;
      elapsed_ms: number;
      kinds_scanned: string[];
      drifts_found: number;
      rows_inserted: number;
      rows_refreshed: number;
    }>(`/reconciliation/drift/scan${q}`, { method: 'POST' });
  },
  driftResolve: (drift_id: string, note?: string) => {
    const q = note ? `?note=${encodeURIComponent(note)}` : '';
    return request<{ ok: boolean; id: string; resolved: boolean }>(
      `/reconciliation/drift/${drift_id}/resolve${q}`,
      { method: 'POST' },
    );
  },
  // ────── Existing reconciliation routes ──────
  getSettings: () => request<ReconciliationSettings>(`/reconciliation-settings`),
  setSettings: (body: { credit_contributors_enabled?: boolean; auto_disable_card?: boolean }) =>
    request<ReconciliationSettings>(`/reconciliation-settings`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  list: (params?: { q?: string; action?: string; limit?: number; skip?: number }) => {
    const q = new URLSearchParams();
    if (params?.q) q.set('q', params.q);
    if (params?.action) q.set('action', params.action);
    if (params?.limit) q.set('limit', String(params.limit));
    if (params?.skip) q.set('skip', String(params.skip));
    const qs = q.toString();
    return request<{ items: ReconciliationRow[]; total: number; skip: number; limit: number }>(
      `/reconciliations${qs ? `?${qs}` : ''}`,
    );
  },
  get: (rec_id: string) => request<ReconciliationRow>(`/reconciliations/${rec_id}`),
  manual: (group_id: string) => request<ReconciliationRow>(`/groups/${group_id}/reconcile`, { method: 'POST' }),
  getMasterAccount: (params?: { limit?: number; skip?: number }) => {
    const q = new URLSearchParams();
    if (params?.limit) q.set('limit', String(params.limit));
    if (params?.skip) q.set('skip', String(params.skip));
    const qs = q.toString();
    return request<{ items: MasterAccountEntry[]; total: number; balance: number; skip: number; limit: number }>(
      `/master-account${qs ? `?${qs}` : ''}`,
    );
  },
};

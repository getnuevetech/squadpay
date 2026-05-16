/**
 * adminApi/brandingLogos.ts — Admin client for the per-slot logo overrides
 * (backed by /api/admin/logos and /api/runtime/logo/{slot}).
 *
 * Each slot has a fixed required dimension + background expectation; the
 * backend auto-resizes any upload to the right canvas so the admin doesn't
 * have to crop perfectly in advance.
 */
import { request } from './_core';

export type LogoSlot = {
  slot: string;
  label: string;
  where: string;
  width: number;
  height: number;
  background: 'transparent' | 'white' | 'any';
  requires_native_build: boolean;
  has_override: boolean;
  uploaded_at?: string | null;
  uploaded_by?: string | null;
  current_url: string;        // public /api/runtime/logo/{slot}?v=…
};

export type LogoListResp = { slots: LogoSlot[] };

export const brandingLogosApi = {
  list: () => request<LogoListResp>('/logos'),

  upload: (slot: string, dataB64: string) =>
    request<{ ok: boolean; slot: string; rendered_size: [number, number]; bytes: number; current_url: string }>(
      `/logos/${slot}`,
      { method: 'POST', body: JSON.stringify({ data_b64: dataB64 }) },
    ),

  reset: (slot: string) =>
    request<{ ok: boolean; slot: string; deleted: number }>(
      `/logos/${slot}`,
      { method: 'DELETE' },
    ),
};

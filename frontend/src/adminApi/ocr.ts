/**
 * adminApi/ocr.ts — Receipt-scanning OCR provider config admin.
 *
 * Owns: GET/PUT /api/admin/ocr-config + associated types.
 */
import { _aRequest } from './_core';

export type OcrProviderEntry = { provider: string; model: string };
export type OcrAttempt = {
  provider: string;
  model: string;
  ok: boolean;
  error?: string;
  latency_ms?: number;
};
export type OcrConfig = {
  providers: OcrProviderEntry[];
  recent_attempts: Array<{
    id: string;
    at: string;
    chain: OcrProviderEntry[];
    attempts: OcrAttempt[];
    succeeded: boolean;
    provider_used?: string | null;
  }>;
  updated_at?: string | null;
};

export const ocrApi = {
  get: () => _aRequest<OcrConfig>('/admin/ocr-config'),
  set: (providers: OcrProviderEntry[]) =>
    _aRequest<{ ok: boolean; providers: OcrProviderEntry[] }>('/admin/ocr-config', {
      method: 'PUT',
      body: JSON.stringify({ providers }),
    }),
};

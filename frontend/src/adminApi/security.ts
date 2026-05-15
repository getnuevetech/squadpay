/**
 * adminApi/security.ts — KMS status, reload, and rotation.
 */
import { request } from './_core';

export type KmsStatus = {
  key_source: 'kms_master' | 'secrets_key' | 'jwt_derived';
  secure: boolean;
  primary_fingerprint: string | null;
  legacy_fingerprints: string[];
  warning: string | null;
  encrypted_field_count?: number | null;
};

export type KmsRotateResult = {
  rotated: number;
  skipped: number;
  failed: number;
  elapsed_ms: number;
  primary_fingerprint: string;
  key_source: string;
  per_collection?: Record<string, { rotated: number; skipped: number; failed: number }>;
};

export const kmsApi = {
  getStatus: () => request<KmsStatus>(`/security/kms-status`),
  reload: () => request<KmsStatus>(`/security/kms-reload`, { method: 'POST' }),
  rotate: () => request<KmsRotateResult>(`/security/kms-rotate`, { method: 'POST' }),
};

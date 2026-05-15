/**
 * adminApi/appConfig.ts — Unified runtime config (core fees, wallet, limits,
 * OTP, OCR, brand, ops) + admin-configurable extra platform fees.
 */
import { request } from './_core';

export type AdminPlatformFee = {
  id: string;
  name: string;
  type: 'percent' | 'flat';
  value: number;
  enabled: boolean;
  /** June 2025 — Optional per-extra max-$ cap. 0 means no cap. */
  cap?: number;
};

export type AppConfig = {
  core_fees: {
    transaction_fee_pct: number;
    // June 2025 — Platform fee migrated to {type, value}. Both legacy
    // `platform_fee_flat` and the new `platform_fee_type`/`platform_fee_value`
    // are present for backwards-compat; the new fields are the source of
    // truth.
    platform_fee_flat: number;
    platform_fee_type?: 'fixed' | 'percent';
    platform_fee_value?: number;
    // June 2025 — Insurance: always %, layered between Extras and Tx Fee.
    insurance_pct?: number;
    insurance_label?: string;
    // June 2025 — Per-fee enable/disable toggles + max-$ caps.
    transaction_fee_enabled?: boolean;
    platform_fee_enabled?: boolean;
    insurance_enabled?: boolean;
    transaction_fee_cap?: number;
    platform_fee_cap?: number;
    insurance_cap?: number;
    transaction_fee_label: string;
    platform_fee_label: string;
  };
  extra_fees: AdminPlatformFee[];
  wallet: { enabled: boolean; apple_enabled: boolean; google_enabled: boolean };
  limits: {
    min_members_per_bill: number;
    min_bill_amount: number;
    max_bill_amount: number;
    max_items_per_bill: number;
  };
  otp: { code_length: number; expiry_seconds: number; max_attempts_per_hour: number };
  card: { spend_cap_buffer_pct: number; auto_disable_hours: number };
  reminders: { cadence_hours: number; bill_expiry_hours: number };
  ocr: { provider: 'openai' | 'anthropic' | 'gemini'; model: string };
  brand: {
    sms_sender_id: string;
    support_email: string;
    default_tip_suggestions: number[];
    currency: 'USD';
  };
  ops: { maintenance_mode: boolean; maintenance_message: string };
};

export const appConfigApi = {
  get: () => request<AppConfig>('/app-config'),
  update: (cfg: AppConfig) =>
    request<AppConfig>('/app-config', { method: 'PUT', body: JSON.stringify(cfg) }),
  // Platform fees (admin-configurable extra fees — separate endpoint).
  getPlatformFees: () => request<{ fees: AdminPlatformFee[] }>('/platform-fees'),
  updatePlatformFees: (fees: AdminPlatformFee[]) =>
    request<{ fees: AdminPlatformFee[] }>('/platform-fees', {
      method: 'PUT',
      body: JSON.stringify({ fees }),
    }),
};

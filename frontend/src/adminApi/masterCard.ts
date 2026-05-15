/**
 * adminApi/masterCard.ts — Platform-wide master virtual card admin
 * (one stripe-issued card; not per-group cards).
 */
import { request } from './_core';

export type MasterCard = {
  stripe_card_id: string | null;
  last4: string | null;
  status: string;
  issued_at: string | null;
  note?: string;
};

export const masterCardApi = {
  get: () => request<{ card: MasterCard | null }>('/master-card'),
  issue: () =>
    request<{ ok: boolean; card: MasterCard; created: boolean }>('/master-card/issue', {
      method: 'POST',
    }),
};

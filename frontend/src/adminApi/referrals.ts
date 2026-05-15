/**
 * adminApi/referrals.ts — Referral program admin.
 */
import { request } from './_core';

export type ReferralSettings = {
  enabled: boolean;
  referrer_credit: number;
  referee_credit: number;
  updated_at?: string;
};

export type ReferralStats = {
  total_referred: number;
  verified_referred: number;
  conversion_rate: number;
  pending_credits: number;
};

export type ReferrerRow = {
  user_id: string;
  name?: string | null;
  phone?: string | null;
  referral_code?: string | null;
  is_blocked: boolean;
  total_referrals: number;
  verified_referrals: number;
};

export type ReferrerDetail = {
  id: string;
  name?: string | null;
  phone?: string | null;
  referral_code?: string | null;
  is_blocked: boolean;
  referred_by: { id: string; name?: string; referral_code?: string } | null;
  referees: Array<{
    id: string;
    name?: string | null;
    phone?: string | null;
    verified: boolean;
    is_blocked?: boolean;
    created_at: string;
    groups_joined?: number;
  }>;
  pending_credits: number;
};

export const referralsApi = {
  getSettings: () => request<ReferralSettings>('/referrals/settings'),
  setSettings: (s: ReferralSettings) =>
    request<ReferralSettings>('/referrals/settings', { method: 'POST', body: JSON.stringify(s) }),
  list: (params?: { q?: string; limit?: number; skip?: number }) => {
    const q = new URLSearchParams();
    if (params?.q) q.set('q', params.q);
    if (params?.limit) q.set('limit', String(params.limit));
    if (params?.skip) q.set('skip', String(params.skip));
    const qs = q.toString();
    return request<{ items: ReferrerRow[]; total: number; stats: ReferralStats; skip: number; limit: number }>(
      `/referrals${qs ? `?${qs}` : ''}`,
    );
  },
  getDetail: (user_id: string) => request<ReferrerDetail>(`/referrals/${user_id}`),
};

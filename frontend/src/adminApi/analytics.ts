/**
 * adminApi/analytics.ts — Range-windowed analytics rollups.
 */
import { request } from './_core';

export type AnalyticsPayload = {
  range_days: number;
  start_date: string;
  end_date: string;
  groups_per_day: { date: string; count: number }[];
  gmv_per_day: { date: string; amount: number }[];
  aov_per_day: { date: string; value: number }[];
  signups_per_day: { date: string; count: number; verified_count: number }[];
  contributions_per_day: { date: string; amount: number; count: number }[];
  top_referrers: { user_id: string; name: string; referral_code: string | null; signups: number; verified_signups: number }[];
  card_metrics: { total_issued: number; active: number; inactive: number; total_spent: number };
  master_account: { balance: number; entries: number };
  funnel: { signups: number; verified: number; joined_group: number; contributed: number; settled_groups: number };
  totals: {
    users: number;
    verified_users: number;
    groups: number;
    groups_in_range: number;
    contributions: number;
    gmv: number;
    gmv_in_range: number;
    gross_processed_in_range: number;
    signups_in_range: number;
    verified_in_range: number;
  };
};

export const analyticsApi = {
  get: (range: '7d' | '30d' | '90d' = '30d') =>
    request<AnalyticsPayload>(`/analytics?range=${range}`),
};

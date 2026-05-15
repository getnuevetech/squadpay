/**
 * adminApi/users.ts — User management + per-user actions.
 *
 * Houses: list/get/block users, push OTP, view/grant/revoke credits,
 * lead auto-discount management.
 */
import { request } from './_core';
import type { AdminUserRow, AdminUserDetail, UserCreditWallet, CreditRow, LeadAutoDiscount } from './_legacy';

export const usersApi = {
  list: (params?: { q?: string; verified?: boolean; blocked?: boolean; limit?: number; skip?: number }) => {
    const q = new URLSearchParams();
    if (params?.q) q.set('q', params.q);
    if (params?.verified !== undefined) q.set('verified', String(params.verified));
    if (params?.blocked !== undefined) q.set('blocked', String(params.blocked));
    if (params?.limit) q.set('limit', String(params.limit));
    if (params?.skip) q.set('skip', String(params.skip));
    const qs = q.toString();
    return request<{ items: AdminUserRow[]; total: number; skip: number; limit: number }>(`/users${qs ? `?${qs}` : ''}`);
  },
  get: (id: string) => request<AdminUserDetail>(`/users/${id}`),
  block: (id: string, is_blocked: boolean, reason?: string) =>
    request<AdminUserRow>(`/users/${id}/block`, { method: 'POST', body: JSON.stringify({ is_blocked, reason }) }),
  pushOtp: (id: string, opts?: { phone?: string }) =>
    request<{ ok: boolean; mocked: boolean; live: boolean; message: string; info?: string }>(
      `/users/${id}/send-otp`,
      { method: 'POST', body: JSON.stringify(opts || {}) },
    ),
  getCredits: (id: string) => request<UserCreditWallet>(`/users/${id}/credits`),
  grantCredit: (id: string, amount: number, note?: string) =>
    request<CreditRow>(`/users/${id}/credits/grant`, { method: 'POST', body: JSON.stringify({ amount, note }) }),
  revokeCredit: (user_id: string, credit_id: string) =>
    request<CreditRow>(`/users/${user_id}/credits/${credit_id}/revoke`, { method: 'POST' }),
  setLeadDiscount: (id: string, body: { type?: 'flat' | 'percent'; value?: number; note?: string; enabled: boolean }) =>
    request<{ lead_auto_discount: LeadAutoDiscount | null }>(`/users/${id}/lead-discount`, { method: 'POST', body: JSON.stringify(body) }),
};

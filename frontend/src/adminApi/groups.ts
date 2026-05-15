/**
 * adminApi/groups.ts — Squad management (admin view).
 *
 * Houses list/get/block/reassign-lead + per-group discount + card-disable.
 */
import { request } from './_core';
import type { AdminGroupRow, AdminGroupDetail, GroupDiscount } from './_legacy';

export const groupsApi = {
  list: (params?: { q?: string; status?: string; blocked?: boolean; lead_id?: string; limit?: number; skip?: number }) => {
    const q = new URLSearchParams();
    if (params?.q) q.set('q', params.q);
    if (params?.status) q.set('status', params.status);
    if (params?.blocked !== undefined) q.set('blocked', String(params.blocked));
    if (params?.lead_id) q.set('lead_id', params.lead_id);
    if (params?.limit) q.set('limit', String(params.limit));
    if (params?.skip) q.set('skip', String(params.skip));
    const qs = q.toString();
    return request<{ items: AdminGroupRow[]; total: number; skip: number; limit: number }>(`/groups${qs ? `?${qs}` : ''}`);
  },
  get: (id: string) => request<AdminGroupDetail>(`/groups/${id}`),
  block: (id: string, is_blocked: boolean, reason?: string) =>
    request<AdminGroupRow>(`/groups/${id}/block`, { method: 'POST', body: JSON.stringify({ is_blocked, reason }) }),
  reassignLead: (id: string, new_lead_user_id: string) =>
    request<{ ok: boolean; lead_id: string; no_change?: boolean }>(
      `/groups/${id}/reassign-lead`,
      { method: 'POST', body: JSON.stringify({ new_lead_user_id }) },
    ),
  setDiscount: (id: string, discount: { type: 'flat' | 'percent'; value: number; note?: string }) =>
    request<{ discount: GroupDiscount; total_amount: number; original_total_amount: number }>(
      `/groups/${id}/discount`,
      { method: 'POST', body: JSON.stringify(discount) },
    ),
  clearDiscount: (id: string) =>
    request<{ discount: null; total_amount: number }>(`/groups/${id}/discount`, { method: 'DELETE' }),
  disableCard: (groupId: string) =>
    request<{ ok: boolean; virtual_card: any }>(`/groups/${groupId}/disable-card`, { method: 'POST' }),
};

/**
 * adminApi/admins.ts — Admin-user CRUD + role + password-reset actions.
 */
import { request } from './_core';
import type { AdminProfile, AdminRole } from './_legacy';

export const adminsApi = {
  list: () => request<AdminProfile[]>('/admins'),
  create: (body: { email: string; password: string; name: string; role: AdminRole }) =>
    request<AdminProfile>('/admins', { method: 'POST', body: JSON.stringify(body) }),
  toggle: (id: string, is_active: boolean) =>
    request<AdminProfile>(`/admins/${id}/active`, { method: 'PATCH', body: JSON.stringify({ is_active }) }),
  pushPasswordReset: (
    id: string,
    opts?: { alternate_email?: string; return_link?: boolean },
  ) =>
    request<{
      ok: boolean;
      delivered_to: string;
      email_status: 'sent' | 'skipped' | 'failed';
      email_error?: string;
      expires_in_minutes: number;
      reset_url?: string;
      link_note?: string;
    }>(`/admins/${id}/send-password-reset`, {
      method: 'POST',
      body: JSON.stringify(opts || {}),
    }),
  changeRole: (id: string, role: AdminRole) =>
    request<{ ok: boolean; admin_id?: string; role: AdminRole; previous_role?: AdminRole; unchanged?: boolean }>(
      `/admins/${id}/role`,
      { method: 'PATCH', body: JSON.stringify({ role }) },
    ),
};

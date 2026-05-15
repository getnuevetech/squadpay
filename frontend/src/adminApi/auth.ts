/**
 * adminApi/auth.ts — Admin auth + session + global lookups.
 *
 * Houses authentication, profile lookup, metrics, and the global search bar.
 * Consumed by login screen, dashboard header, and the global search palette.
 */
import { request, setSession, clearSession } from './_core';
import type { AdminProfile, AdminMetrics } from './_legacy';

export const authApi = {
  login: async (email: string, password: string) => {
    const res = await request<{ token: string; admin: AdminProfile }>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    });
    await setSession(res.token, res.admin);
    return res;
  },
  me: () => request<AdminProfile>('/auth/me'),
  changePassword: (current_password: string, new_password: string) =>
    request<{ ok: boolean }>('/auth/change-password', {
      method: 'POST',
      body: JSON.stringify({ current_password, new_password }),
    }),
  logout: async () => {
    try { await request('/auth/logout', { method: 'POST' }); } catch {}
    await clearSession();
  },
  metrics: () => request<AdminMetrics>('/metrics'),
  search: (q: string) =>
    request<{
      items: Array<{
        category: 'users' | 'squads' | 'admins' | 'audit' | 'tickets';
        label: string;
        sub: string;
        href: string;
        id: string;
      }>;
    }>(`/search?q=${encodeURIComponent(q)}`),
};

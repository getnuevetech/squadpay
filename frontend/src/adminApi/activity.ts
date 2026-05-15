/**
 * adminApi/activity.ts — Admin activity stream (recent actions audit).
 *
 * Records and retrieves per-admin activity rows. Recording is best-effort
 * (never throws) so callers can fire-and-forget after every action without
 * breaking the UI on transient failures.
 */
import { _aRequest } from './_core';

export type AdminActivityRow = {
  id: string;
  at: string;
  admin_email: string;
  admin_id?: string;
  action: string;
  target_type?: string;
  target_id?: string;
  payload?: any;
  ip?: string;
  user_agent?: string;
};

export const adminActivityApi = {
  record: (
    action: string,
    payload?: Record<string, any>,
    targetType?: string,
    targetId?: string,
  ) =>
    _aRequest<{ ok: boolean; id: string }>('/admin/activity', {
      method: 'POST',
      body: JSON.stringify({
        action,
        target_type: targetType,
        target_id: targetId,
        payload: payload || {},
      }),
    }).catch(() => ({ ok: false, id: '' })), // best-effort: never break the UI
  forAdmin: (adminIdOrEmail: string, params?: { limit?: number; skip?: number }) => {
    const q = new URLSearchParams();
    if (params?.limit) q.set('limit', String(params.limit));
    if (params?.skip) q.set('skip', String(params.skip));
    const qs = q.toString();
    return _aRequest<{ items: AdminActivityRow[]; total: number; skip: number; limit: number }>(
      `/admin/admins/${encodeURIComponent(adminIdOrEmail)}/activity${qs ? `?${qs}` : ''}`,
    );
  },
};

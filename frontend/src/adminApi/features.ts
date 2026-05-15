/**
 * adminApi/features.ts — Global feature flags (credits, invite-friends, etc.).
 */
import { request } from './_core';

export const featuresApi = {
  get: () =>
    request<{ credits_enabled: boolean; invite_friends_enabled: boolean; updated_at?: string; updated_by?: string }>(
      `/features`,
    ),
  set: (body: { credits_enabled?: boolean; invite_friends_enabled?: boolean }) =>
    request<any>(`/features`, { method: 'POST', body: JSON.stringify(body) }),
};

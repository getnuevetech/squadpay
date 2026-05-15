/**
 * adminApi/creditRules.ts — Credit Rules engine admin (criteria → reward).
 */
import { request } from './_core';

export const creditRulesApi = {
  list: () =>
    request<{
      items: Array<{
        id: string;
        name: string;
        active: boolean;
        message: string;
        criteria: any;
        reward: { type: string; value: number; cap: number | null };
        expiry_days: number | null;
        stackable_with: string[];
        created_at: string;
        match_count: number;
        total_paid_out: number;
      }>;
      total: number;
    }>('/credit-rules'),
  create: (body: any) =>
    request<any>('/credit-rules', { method: 'POST', body: JSON.stringify(body) }),
  patch: (id: string, body: any) =>
    request<any>(`/credit-rules/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  delete: (id: string) =>
    request<any>(`/credit-rules/${id}`, { method: 'DELETE' }),
};

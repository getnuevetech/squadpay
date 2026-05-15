/**
 * adminApi/gateways.ts — Payment gateway catalog + credential storage + activation.
 */
import { request } from './_core';

export const gatewaysApi = {
  catalog: () =>
    request<{
      charge_providers: any[];
      payout_providers: any[];
      active: { charge: string | null; payout: string | null };
    }>('/gateways/catalog'),
  state: () =>
    request<{
      items: any[];
      active: { charge: string | null; payout: string | null };
    }>('/gateways'),
  saveCredentials: (
    group: 'charge' | 'payout',
    slug: string,
    credentials: Record<string, string>,
    settings?: Record<string, any>,
  ) =>
    request<any>(`/gateways/${group}/${encodeURIComponent(slug)}`, {
      method: 'PUT',
      body: JSON.stringify({ credentials, ...(settings ? { settings } : {}) }),
    }),
  activate: (group: 'charge' | 'payout', provider_slug: string) =>
    request<{ ok: boolean; group: string; active: string }>(
      `/gateways/${group}/activate`,
      { method: 'POST', body: JSON.stringify({ provider_slug }) },
    ),
};

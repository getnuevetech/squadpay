/**
 * adminApi/settlement.ts — Settlement-delay admin (the configurable grace
 * window between Contributed → Lead Paid).
 */
import { _aRequest } from './_core';

export type SettlementDelay = { minutes: number };

export const settlementDelayApi = {
  get: () => _aRequest<SettlementDelay>('/admin/settlement-delay'),
  set: (minutes: number) =>
    _aRequest<{ ok: boolean; minutes: number }>('/admin/settlement-delay', {
      method: 'PUT',
      body: JSON.stringify({ minutes }),
    }),
};

/**
 * adminApi/kyc.ts — KYC incentives admin (member + lead onboarding rewards).
 */
import { _aRequest } from './_core';

export type KycIncentiveConfig = {
  role: 'lead' | 'member';
  enabled: boolean;
  reward_mode: 'credit_off_next_bill' | 'waive_platform_fees_next_bill';
  credit_amount: number;
  messages: string[];
};

export const kycIncentiveApi = {
  getLead: () => _aRequest<KycIncentiveConfig>('/admin/kyc-incentive'),
  setLead: (cfg: Omit<KycIncentiveConfig, 'role'>) =>
    _aRequest<{ ok: boolean } & KycIncentiveConfig>('/admin/kyc-incentive', {
      method: 'PUT',
      body: JSON.stringify(cfg),
    }),
  getMember: () => _aRequest<KycIncentiveConfig>('/admin/kyc-incentive-member'),
  setMember: (cfg: Omit<KycIncentiveConfig, 'role'>) =>
    _aRequest<{ ok: boolean } & KycIncentiveConfig>('/admin/kyc-incentive-member', {
      method: 'PUT',
      body: JSON.stringify(cfg),
    }),
};

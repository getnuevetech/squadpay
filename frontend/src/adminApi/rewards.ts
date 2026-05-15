/**
 * adminApi/rewards.ts — SquadPay credits wallet types + group/lead discount types.
 *
 * The actual API methods live in:
 *   - `./users.ts`  (getCredits / grantCredit / revokeCredit / setLeadDiscount)
 *   - `./groups.ts` (setDiscount / clearDiscount)
 *
 * This module owns the type definitions so admin screens can import them
 * with a domain-scoped path (or via the barrel as before).
 */

export type GroupDiscount = {
  type: 'flat' | 'percent';
  value: number;
  amount: number;
  note?: string | null;
  source?: string | null;
  applied_at?: string;
  applied_by?: string;
};

export type LeadAutoDiscount = {
  type: 'flat' | 'percent';
  value: number;
  note?: string | null;
  set_at?: string;
  set_by?: string;
};

export type CreditRow = {
  id: string;
  user_id: string;
  amount: number;
  consumed_amount: number;
  kind: string;
  status: 'active' | 'consumed' | 'revoked' | 'pending';
  note?: string | null;
  created_at: string;
  source_user_id?: string | null;
  granted_by?: string;
  revoked_at?: string;
  revoked_by?: string;
  last_consumed_at?: string;
};

export type UserCreditWallet = {
  user_id: string;
  name?: string;
  balance: number;
  items: CreditRow[];
  lead_auto_discount?: LeadAutoDiscount | null;
};

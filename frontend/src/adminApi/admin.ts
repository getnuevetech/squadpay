/**
 * adminApi/admin.ts — Admin role/profile/metrics/audit type definitions.
 *
 * Method implementations live in `./auth.ts`, `./audit.ts`, `./admins.ts`,
 * `./users.ts`, and `./groups.ts`. This module owns the shared type
 * vocabulary used across all admin clients.
 */

// Role slug — was a tight Literal ('super_admin' | 'manager' | 'support').
// As of RBAC v2 (June 2025) custom roles can be defined in Access Role
// Management, so the type is now a free-form string. The 3 system slugs are
// still always present.
export type AdminRole = string;

export type AdminProfile = {
  id: string;
  email: string;
  name: string;
  role: AdminRole;
  is_active: boolean;
  last_login_at: string | null;
  created_at: string;
  // P2 — soft nudge for super-admins still on the env-default password.
  must_change_default_password?: boolean;
};

export type AdminMetrics = {
  groups_total: number;
  groups_active: number;
  groups_paid: number;
  groups_settled: number;
  users_total: number;
  admins_total: number;
  total_billed: number;
  total_contributed: number;
};

export type AuditEntry = {
  id: string;
  admin_id: string;
  admin_email: string;
  action: string;
  target_type: string | null;
  target_id: string | null;
  payload: Record<string, any>;
  ip: string | null;
  destructive: boolean;
  at: string;
};

// ---- User row/detail types (used by both users.ts and groups.ts) ----
export type AdminUserRow = {
  id: string;
  name: string;
  phone: string | null;
  verified: boolean;
  is_blocked: boolean;
  blocked_reason?: string | null;
  blocked_at?: string | null;
  created_at: string;
  groups_led: number;
  groups_joined: number;
  total_billed_as_lead: number;
  total_contributed?: number;
  terms_accepted_at?: string | null;
};

export type AdminUserDetail = AdminUserRow & {
  led_groups: AdminGroupRow[];
  joined_groups: AdminGroupRow[];
  total_contributed: number;
};

export type AdminGroupRow = {
  id: string;
  code: string;
  title: string;
  lead_id: string;
  lead_name?: string | null;
  lead_phone?: string | null;
  status: string;
  is_blocked: boolean;
  blocked_reason?: string | null;
  blocked_at?: string | null;
  total_amount: number;
  tax: number;
  tip: number;
  members_count: number;
  items_count: number;
  contributions_total: number;
  created_at: string;
};

import type { GroupDiscount } from './rewards';
export type AdminGroupDetail = AdminGroupRow & {
  items: { id: string; name: string; price: number; quantity: number }[];
  assignments: { id?: string; user_id: string; item_id: string; quantity: number }[];
  members: { user_id: string; role: string; joined_at: string; name?: string; phone?: string | null; verified: boolean; is_blocked: boolean }[];
  contributions: { id: string; user_id: string; amount: number; at: string; cash_paid?: number; credit_applied?: number }[];
  repayments: { user_id: string; amount: number; at: string }[];
  split_mode?: string;
  funding_mode?: string | null;
  lead_paid_at?: string | null;
  discount?: GroupDiscount | null;
  original_total_amount?: number;
};

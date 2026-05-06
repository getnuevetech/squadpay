/**
 * Admin API client (Phase A).
 * Token persisted in AsyncStorage so the dashboard survives reloads.
 */
import AsyncStorage from '@react-native-async-storage/async-storage';

const BACKEND_URL = process.env.EXPO_PUBLIC_BACKEND_URL || '';
const API = `${BACKEND_URL}/api/admin`;
const TOKEN_KEY = 'gp.admin.token';
const PROFILE_KEY = 'gp.admin.profile';

export type AdminRole = 'super_admin' | 'manager' | 'support';

export type AdminProfile = {
  id: string;
  email: string;
  name: string;
  role: AdminRole;
  is_active: boolean;
  last_login_at: string | null;
  created_at: string;
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

let _cachedToken: string | null = null;

export async function getToken(): Promise<string | null> {
  if (_cachedToken) return _cachedToken;
  _cachedToken = await AsyncStorage.getItem(TOKEN_KEY);
  return _cachedToken;
}

async function setSession(token: string, profile: AdminProfile) {
  _cachedToken = token;
  await AsyncStorage.setItem(TOKEN_KEY, token);
  await AsyncStorage.setItem(PROFILE_KEY, JSON.stringify(profile));
}

export async function getProfile(): Promise<AdminProfile | null> {
  const raw = await AsyncStorage.getItem(PROFILE_KEY);
  return raw ? JSON.parse(raw) : null;
}

export async function clearSession() {
  _cachedToken = null;
  await AsyncStorage.multiRemove([TOKEN_KEY, PROFILE_KEY]);
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = await getToken();
  const headers: any = { 'Content-Type': 'application/json', ...(init.headers || {}) };
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(`${API}${path}`, { ...init, headers });
  const text = await res.text();
  let body: any = null;
  try { body = text ? JSON.parse(text) : null; } catch { body = text; }
  if (!res.ok) {
    // Auto-handle expired/missing admin token: clear session + redirect to login.
    if (res.status === 401) {
      try { await clearSession(); } catch {}
      try {
        // Best-effort web-only redirect; native redirects via the layout's auth check.
        if (typeof window !== 'undefined' && (window as any).location) {
          const onLogin = (window as any).location.pathname?.startsWith('/admin/login');
          if (!onLogin) (window as any).location.replace('/admin/login');
        }
      } catch {}
    }
    const msg = (body && (body.detail?.[0]?.msg || body.detail || body.message)) || `HTTP ${res.status}`;
    throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
  }
  return body as T;
}

export const adminApi = {
  login: async (email: string, password: string) => {
    const res = await request<{ token: string; admin: AdminProfile }>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    });
    await setSession(res.token, res.admin);
    return res;
  },
  me: () => request<AdminProfile>('/auth/me'),
  logout: async () => {
    try { await request('/auth/logout', { method: 'POST' }); } catch {}
    await clearSession();
  },
  metrics: () => request<AdminMetrics>('/metrics'),
  auditLog: (params?: { limit?: number; skip?: number; action?: string; admin_email?: string }) => {
    const q = new URLSearchParams();
    if (params?.limit) q.set('limit', String(params.limit));
    if (params?.skip) q.set('skip', String(params.skip));
    if (params?.action) q.set('action', params.action);
    if (params?.admin_email) q.set('admin_email', params.admin_email);
    const qs = q.toString();
    return request<{ items: AuditEntry[]; skip: number; limit: number }>(`/audit-log${qs ? `?${qs}` : ''}`);
  },
  listAdmins: () => request<AdminProfile[]>('/admins'),
  createAdmin: (body: { email: string; password: string; name: string; role: AdminRole }) =>
    request<AdminProfile>('/admins', { method: 'POST', body: JSON.stringify(body) }),
  toggleAdmin: (id: string, is_active: boolean) =>
    request<AdminProfile>(`/admins/${id}/active`, { method: 'PATCH', body: JSON.stringify({ is_active }) }),

  // ---- Phase B: Users ----
  listUsers: (params?: { q?: string; verified?: boolean; blocked?: boolean; limit?: number; skip?: number }) => {
    const q = new URLSearchParams();
    if (params?.q) q.set('q', params.q);
    if (params?.verified !== undefined) q.set('verified', String(params.verified));
    if (params?.blocked !== undefined) q.set('blocked', String(params.blocked));
    if (params?.limit) q.set('limit', String(params.limit));
    if (params?.skip) q.set('skip', String(params.skip));
    const qs = q.toString();
    return request<{ items: AdminUserRow[]; total: number; skip: number; limit: number }>(`/users${qs ? `?${qs}` : ''}`);
  },
  getUser: (id: string) => request<AdminUserDetail>(`/users/${id}`),
  blockUser: (id: string, is_blocked: boolean, reason?: string) =>
    request<AdminUserRow>(`/users/${id}/block`, { method: 'POST', body: JSON.stringify({ is_blocked, reason }) }),

  // ---- Phase B: Groups ----
  listGroups: (params?: { q?: string; status?: string; blocked?: boolean; lead_id?: string; limit?: number; skip?: number }) => {
    const q = new URLSearchParams();
    if (params?.q) q.set('q', params.q);
    if (params?.status) q.set('status', params.status);
    if (params?.blocked !== undefined) q.set('blocked', String(params.blocked));
    if (params?.lead_id) q.set('lead_id', params.lead_id);
    if (params?.limit) q.set('limit', String(params.limit));
    if (params?.skip) q.set('skip', String(params.skip));
    const qs = q.toString();
    return request<{ items: AdminGroupRow[]; total: number; skip: number; limit: number }>(`/groups${qs ? `?${qs}` : ''}`);
  },
  getGroup: (id: string) => request<AdminGroupDetail>(`/groups/${id}`),
  blockGroup: (id: string, is_blocked: boolean, reason?: string) =>
    request<AdminGroupRow>(`/groups/${id}/block`, { method: 'POST', body: JSON.stringify({ is_blocked, reason }) }),

  // ---- Phase C2: Credits & Discounts ----
  getUserCredits: (id: string) => request<UserCreditWallet>(`/users/${id}/credits`),
  grantUserCredit: (id: string, amount: number, note?: string) =>
    request<CreditRow>(`/users/${id}/credits/grant`, { method: 'POST', body: JSON.stringify({ amount, note }) }),
  revokeUserCredit: (user_id: string, credit_id: string) =>
    request<CreditRow>(`/users/${user_id}/credits/${credit_id}/revoke`, { method: 'POST' }),
  setGroupDiscount: (id: string, discount: { type: 'flat' | 'percent'; value: number; note?: string }) =>
    request<{ discount: GroupDiscount; total_amount: number; original_total_amount: number }>(
      `/groups/${id}/discount`,
      { method: 'POST', body: JSON.stringify(discount) },
    ),
  clearGroupDiscount: (id: string) =>
    request<{ discount: null; total_amount: number }>(`/groups/${id}/discount`, { method: 'DELETE' }),
  setLeadDiscount: (id: string, body: { type?: 'flat' | 'percent'; value?: number; note?: string; enabled: boolean }) =>
    request<{ lead_auto_discount: LeadAutoDiscount | null }>(`/users/${id}/lead-discount`, { method: 'POST', body: JSON.stringify(body) }),

  // ---- Phase D: Integrations ----
  getIntegrations: () => request<IntegrationsView>('/integrations'),
  setStripe: (s: StripeIn) => request<IntegrationsView>('/integrations/stripe', { method: 'POST', body: JSON.stringify(s) }),
  setTwilio: (s: TwilioIn) => request<IntegrationsView>('/integrations/twilio', { method: 'POST', body: JSON.stringify(s) }),

  // ---- Phase F2.2: SignalWire (Twilio alternative) ----
  setSignalWire: (s: SignalWireIn) =>
    request<IntegrationsView>('/integrations/signalwire', { method: 'POST', body: JSON.stringify(s) }),
  testSignalWire: (to_number: string, body?: string) =>
    request<{ sent_real: boolean; info: string }>(`/integrations/signalwire/test`, { method: 'POST', body: JSON.stringify({ to_number, body }) }),
  setSmsRouting: (r: { primary: 'twilio' | 'signalwire'; fallback?: 'twilio' | 'signalwire' | null }) =>
    request<IntegrationsView>('/integrations/sms-routing', { method: 'POST', body: JSON.stringify(r) }),
  testTwilio: (to_number: string, body?: string) =>
    request<{ sent_real: boolean; info: string }>(`/integrations/twilio/test`, { method: 'POST', body: JSON.stringify({ to_number, body }) }),
  setReminders: (r: RemindersIn) => request<IntegrationsView>('/integrations/reminders', { method: 'POST', body: JSON.stringify(r) }),
  runRemindersNow: () => request<{ enabled: boolean; scanned: number; sent_real: number; logged: number; skipped: number; schedule_hours?: number[] }>(`/integrations/reminders/run-now`, { method: 'POST' }),

  // ---- Phase F1: Issuing ----
  getIssuingSettings: () =>
    request<{ enabled: boolean; cardholder_id: string | null; cardholder_name: string; card_disable_mode: 'auto' | 'manual'; require_otp_for_card_reveal?: boolean; reveal_ttl_seconds?: number; require_lead_kyc?: boolean; updated_at?: string }>(`/integrations/issuing`),
  setIssuingSettings: (body: { enabled?: boolean; cardholder_name?: string; card_disable_mode?: 'auto' | 'manual'; require_otp_for_card_reveal?: boolean; reveal_ttl_seconds?: number; require_lead_kyc?: boolean; webhook_secret?: string }) =>
    request<any>(`/integrations/issuing`, { method: 'POST', body: JSON.stringify(body) }),
  disableGroupCard: (groupId: string) =>
    request<{ ok: boolean; virtual_card: any }>(`/groups/${groupId}/disable-card`, { method: 'POST' }),

  // ---- Phase G1: Reconciliation ----
  getReconciliationSettings: () =>
    request<ReconciliationSettings>(`/reconciliation-settings`),
  setReconciliationSettings: (body: { credit_contributors_enabled?: boolean; auto_disable_card?: boolean }) =>
    request<ReconciliationSettings>(`/reconciliation-settings`, { method: 'POST', body: JSON.stringify(body) }),
  listReconciliations: (params?: { q?: string; action?: string; limit?: number; skip?: number }) => {
    const q = new URLSearchParams();
    if (params?.q) q.set('q', params.q);
    if (params?.action) q.set('action', params.action);
    if (params?.limit) q.set('limit', String(params.limit));
    if (params?.skip) q.set('skip', String(params.skip));
    const qs = q.toString();
    return request<{ items: ReconciliationRow[]; total: number; skip: number; limit: number }>(
      `/reconciliations${qs ? `?${qs}` : ''}`,
    );
  },
  getReconciliation: (rec_id: string) => request<ReconciliationRow>(`/reconciliations/${rec_id}`),
  manualReconcile: (group_id: string) =>
    request<ReconciliationRow>(`/groups/${group_id}/reconcile`, { method: 'POST' }),
  getMasterAccount: (params?: { limit?: number; skip?: number }) => {
    const q = new URLSearchParams();
    if (params?.limit) q.set('limit', String(params.limit));
    if (params?.skip) q.set('skip', String(params.skip));
    const qs = q.toString();
    return request<{ items: MasterAccountEntry[]; total: number; balance: number; skip: number; limit: number }>(
      `/master-account${qs ? `?${qs}` : ''}`,
    );
  },

  // ---- Phase G2: Security / KMS ----
  getKmsStatus: () => request<KmsStatus>(`/security/kms-status`),
  reloadKms: () => request<KmsStatus>(`/security/kms-reload`, { method: 'POST' }),
  rotateKms: () => request<KmsRotateResult>(`/security/kms-rotate`, { method: 'POST' }),

  // ---- Feature toggles ----
  getFeatures: () =>
    request<{ credits_enabled: boolean; invite_friends_enabled: boolean; updated_at?: string; updated_by?: string }>(`/features`),
  setFeatures: (body: { credits_enabled?: boolean; invite_friends_enabled?: boolean }) =>
    request<any>(`/features`, { method: 'POST', body: JSON.stringify(body) }),

  // ---- Phase C1: Referrals ----
  getReferralSettings: () => request<ReferralSettings>('/referrals/settings'),
  setReferralSettings: (s: ReferralSettings) =>
    request<ReferralSettings>('/referrals/settings', { method: 'POST', body: JSON.stringify(s) }),
  listReferrers: (params?: { q?: string; limit?: number; skip?: number }) => {
    const q = new URLSearchParams();
    if (params?.q) q.set('q', params.q);
    if (params?.limit) q.set('limit', String(params.limit));
    if (params?.skip) q.set('skip', String(params.skip));
    const qs = q.toString();
    return request<{ items: ReferrerRow[]; total: number; stats: ReferralStats; skip: number; limit: number }>(`/referrals${qs ? `?${qs}` : ''}`);
  },
  getReferrerDetail: (user_id: string) => request<ReferrerDetail>(`/referrals/${user_id}`),
};

export type ReferralSettings = {
  enabled: boolean;
  referrer_credit: number;
  referee_credit: number;
  updated_at?: string;
};

export type ReferralStats = {
  total_referred: number;
  verified_referred: number;
  conversion_rate: number;
  pending_credits: number;
};

export type ReferrerRow = {
  user_id: string;
  name?: string | null;
  phone?: string | null;
  referral_code?: string | null;
  is_blocked: boolean;
  total_referrals: number;
  verified_referrals: number;
};

export type ReferrerDetail = {
  id: string;
  name?: string | null;
  phone?: string | null;
  referral_code?: string | null;
  is_blocked: boolean;
  referred_by: { id: string; name?: string; referral_code?: string } | null;
  referees: Array<{
    id: string;
    name?: string | null;
    phone?: string | null;
    verified: boolean;
    is_blocked?: boolean;
    created_at: string;
    groups_joined?: number;
  }>;
  pending_credits: number;
};

// ---- Phase B types ----
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
};

export type AdminUserDetail = AdminUserRow & {
  led_groups: AdminGroupRow[];
  joined_groups: AdminGroupRow[];
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

export type IntegrationsView = {
  stripe: {
    enabled: boolean;
    mode: 'test' | 'live';
    publishable_key: string;
    secret_key_masked: string;
    secret_key_set: boolean;
    webhook_secret_set: boolean;
    webhook_secret_masked: string;
    updated_at?: string | null;
    updated_by?: string | null;
  };
  twilio: {
    enabled: boolean;
    account_sid_masked: string;
    account_sid_set: boolean;
    auth_token_set: boolean;
    auth_token_masked: string;
    from_number: string;
    updated_at?: string | null;
    updated_by?: string | null;
  };
  reminders: {
    enabled: boolean;
    schedule_hours: number[];
    max_reminders_per_user: number;
    send_via_sms: boolean;
    updated_at?: string | null;
    updated_by?: string | null;
  };
  signalwire?: {
    enabled: boolean;
    project_id_masked: string;
    project_id_set: boolean;
    api_token_set: boolean;
    api_token_masked: string;
    space_url: string;
    from_number: string;
    updated_at?: string | null;
    updated_by?: string | null;
  };
  sms_routing?: {
    primary: 'twilio' | 'signalwire';
    fallback: 'twilio' | 'signalwire' | null;
    updated_at?: string | null;
    updated_by?: string | null;
  };
};

export type StripeIn = {
  enabled: boolean;
  mode: 'test' | 'live';
  publishable_key?: string;
  secret_key?: string;
  webhook_secret?: string;
};

export type TwilioIn = {
  enabled: boolean;
  account_sid?: string;
  auth_token?: string;
  from_number?: string;
};

export type SignalWireIn = {
  enabled: boolean;
  project_id?: string;
  api_token?: string;
  space_url?: string;
  from_number?: string;
};

export type RemindersIn = {
  enabled: boolean;
  schedule_hours: number[];
  max_reminders_per_user: number;
  send_via_sms: boolean;
};

// ---- Phase G1: Reconciliation ----

// ---- Phase G2: Security / KMS ----

export type KmsStatus = {
  key_source: 'kms_master' | 'secrets_key' | 'jwt_derived';
  secure: boolean;
  primary_fingerprint: string | null;
  legacy_fingerprints: string[];
  warning: string | null;
  encrypted_field_count?: number | null;
};

export type KmsRotateResult = {
  rotated: number;
  skipped: number;
  failed: number;
  elapsed_ms: number;
  primary_fingerprint: string;
  key_source: string;
};

export type ReconciliationSettings = {
  credit_contributors_enabled: boolean;
  auto_disable_card: boolean;
  master_account_id?: string;
  updated_at?: string | null;
  updated_by?: string | null;
};

export type ReconciliationRow = {
  id: string;
  group_id: string;
  group_title: string;
  lead_id?: string | null;
  lead_name?: string | null;
  lead_phone?: string | null;
  card_id: string;
  source: 'auto' | 'manual';
  amount_collected: number;
  amount_spent: number;
  leftover: number;
  action: 'credit_contributors' | 'moved_to_master' | 'no_leftover' | null;
  master_account_entry_id?: string | null;
  master_balance_after?: number;
  contributor_credits?: Array<{ user_id: string; name?: string | null; amount: number; credit_id: string }>;
  merchant_summary?: { name?: string | null; category?: string | null; city?: string | null };
  transactions_count: number;
  status: 'pending' | 'finalized';
  created_at: string;
  created_by?: string;
};

export type MasterAccountEntry = {
  id: string;
  master_account_id: string;
  type: 'leftover_in' | 'manual_adjust';
  group_id: string;
  group_title: string;
  lead_id?: string | null;
  lead_name?: string | null;
  card_id: string;
  amount: number;
  balance_after: number;
  reconciliation_id?: string | null;
  note?: string;
  created_at: string;
  created_by?: string;
};

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
    // BUT skip the redirect on the login page itself — otherwise the page reload
    // wipes the inline error message before the user can see it.
    if (res.status === 401) {
      try {
        const onLogin =
          typeof window !== 'undefined' &&
          (window as any).location?.pathname?.startsWith('/admin/login');
        if (!onLogin) {
          await clearSession();
          if (typeof window !== 'undefined' && (window as any).location) {
            (window as any).location.replace('/admin/login');
          }
        }
      } catch {}
    }
    const detail = body?.detail;
    // Surface the structured object (with code / attempts_left / retry_after_seconds)
    // when the backend returns one, so the caller can branch on it.
    if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
      const err = new Error(detail.message || `HTTP ${res.status}`) as Error & { code?: string; data?: any };
      err.code = detail.code;
      err.data = detail;
      (err as any).status = res.status;
      throw err;
    }
    const msg = (body && (body.detail?.[0]?.msg || body.detail || body.message)) || `HTTP ${res.status}`;
    const err = new Error(typeof msg === 'string' ? msg : JSON.stringify(msg)) as Error & { status?: number };
    err.status = res.status;
    throw err;
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
  // June 2025 — Notification Center
  broadcastNotification: (body: {
    message: string;
    image_url?: string | null;
    link_url?: string | null;
    audience: { type: 'all' | 'leads' | 'members' | 'groups'; group_ids?: string[] };
    channels: { in_app: boolean; sms: boolean };
  }) =>
    request<{
      id: string;
      recipient_count: number;
      in_app_delivered: number;
      sms_sent: number;
      sms_failed: number;
    }>('/notifications/broadcast', { method: 'POST', body: JSON.stringify(body) }),
  listBroadcasts: () =>
    request<{
      items: Array<{
        id: string;
        message: string;
        image_url: string | null;
        link_url: string | null;
        audience: { type: string; group_ids?: string[] };
        channels: { in_app: boolean; sms: boolean };
        sent_at: string;
        recipient_count: number;
        sms_sent: number;
        sms_failed: number;
      }>;
    }>('/notifications/broadcasts'),
  createAdmin: (body: { email: string; password: string; name: string; role: AdminRole }) =>
    request<AdminProfile>('/admins', { method: 'POST', body: JSON.stringify(body) }),
  toggleAdmin: (id: string, is_active: boolean) =>
    request<AdminProfile>(`/admins/${id}/active`, { method: 'PATCH', body: JSON.stringify({ is_active }) }),
  // ---- Admin actions: push reset / change role / push OTP ----
  pushAdminPasswordReset: (
    id: string,
    opts?: { alternate_email?: string; return_link?: boolean },
  ) =>
    request<{
      ok: boolean;
      delivered_to: string;
      email_status: 'sent' | 'skipped' | 'failed';
      email_error?: string;
      expires_in_minutes: number;
      reset_url?: string;
      link_note?: string;
    }>(`/admins/${id}/send-password-reset`, {
      method: 'POST',
      body: JSON.stringify(opts || {}),
    }),
  changeAdminRole: (id: string, role: AdminRole) =>
    request<{ ok: boolean; admin_id?: string; role: AdminRole; previous_role?: AdminRole; unchanged?: boolean }>(
      `/admins/${id}/role`,
      { method: 'PATCH', body: JSON.stringify({ role }) },
    ),
  pushUserOtp: (id: string, opts?: { phone?: string }) =>
    request<{ ok: boolean; mocked: boolean; live: boolean; message: string; info?: string }>(
      `/users/${id}/send-otp`,
      { method: 'POST', body: JSON.stringify(opts || {}) },
    ),

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
  // Super-admin only: transfer leadership of a group to one of its existing members.
  reassignGroupLead: (id: string, new_lead_user_id: string) =>
    request<{ ok: boolean; lead_id: string; no_change?: boolean }>(
      `/groups/${id}/reassign-lead`,
      { method: 'POST', body: JSON.stringify({ new_lead_user_id }) },
    ),

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
  // Phase H6 — global mock/live toggle
  setSmsMode: (mode: 'mock' | 'live') =>
    request<IntegrationsView>('/integrations/sms-mode', { method: 'POST', body: JSON.stringify({ mode }) }),
  testTwilio: (to_number: string, body?: string) =>
    request<{ sent_real: boolean; info: string }>(`/integrations/twilio/test`, { method: 'POST', body: JSON.stringify({ to_number, body }) }),
  setReminders: (r: RemindersIn) => request<IntegrationsView>('/integrations/reminders', { method: 'POST', body: JSON.stringify(r) }),
  runRemindersNow: () => request<{ enabled: boolean; scanned: number; sent_real: number; logged: number; skipped: number; schedule_hours?: number[] }>(`/integrations/reminders/run-now`, { method: 'POST' }),

  // ---- Phase F1: Issuing ----
  getIssuingSettings: () =>
    request<{ enabled: boolean; cardholder_id: string | null; cardholder_name: string; card_disable_mode: 'auto' | 'manual'; require_otp_for_card_reveal?: boolean; reveal_ttl_seconds?: number; require_lead_kyc?: boolean; apple_pay_enrolled?: boolean; google_pay_enrolled?: boolean; updated_at?: string }>(`/integrations/issuing`),
  setIssuingSettings: (body: { enabled?: boolean; cardholder_name?: string; card_disable_mode?: 'auto' | 'manual'; require_otp_for_card_reveal?: boolean; reveal_ttl_seconds?: number; require_lead_kyc?: boolean; apple_pay_enrolled?: boolean; google_pay_enrolled?: boolean; webhook_secret?: string }) =>
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

  // ---- Phase G5: Analytics ----
  getAnalytics: (range: '7d' | '30d' | '90d' = '30d') =>
    request<AnalyticsPayload>(`/analytics?range=${range}`),

  // ---- Legal pages (Support / Privacy / Terms) ----
  listLegalPages: () =>
    request<{ pages: LegalPage[] }>(`/legal/pages`),
  updateLegalPage: (slug: 'support' | 'privacy' | 'terms', body: { title: string; content_html: string }) =>
    request<LegalPage & { ok: boolean }>(`/legal/pages/${slug}`, {
      method: 'PUT',
      body: JSON.stringify(body),
    }),
  uploadLegalMedia: async (file: { uri?: string; blob?: Blob; name: string; mime: string }) => {
    // Multipart upload — must NOT set Content-Type manually (browser/RN sets boundary).
    const token = await getToken();
    const fd = new FormData();
    if (file.blob) {
      fd.append('file', file.blob, file.name);
    } else if (file.uri) {
      // React Native form-data: pass {uri, name, type}
      // @ts-ignore — RN-only shape
      fd.append('file', { uri: file.uri, name: file.name, type: file.mime });
    }
    const res = await fetch(`${API}/legal/upload`, {
      method: 'POST',
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body: fd as any,
    });
    const text = await res.text();
    let body: any = null;
    try { body = text ? JSON.parse(text) : null; } catch { body = text; }
    if (!res.ok) {
      const msg = body?.detail || body?.message || `HTTP ${res.status}`;
      throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
    }
    return body as { id: string; url: string; size: number; mime_type: string };
  },

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

  // -------- Platform fees (admin-configurable extra fees) --------
  getPlatformFees: () => request<{ fees: AdminPlatformFee[] }>('/platform-fees'),
  updatePlatformFees: (fees: AdminPlatformFee[]) =>
    request<{ fees: AdminPlatformFee[] }>('/platform-fees', {
      method: 'PUT',
      body: JSON.stringify({ fees }),
    }),

  // -------- Unified App Config (core fees, wallet, limits, otp, etc.) --------
  // Source of truth for ALL admin-tunable runtime settings. See
  // /app/backend/routes/admin_app_config.py for the section schemas.
  getAppConfig: () => request<AppConfig>('/app-config'),
  updateAppConfig: (cfg: AppConfig) =>
    request<AppConfig>('/app-config', { method: 'PUT', body: JSON.stringify(cfg) }),

  // -------- Income & Fees ledger (Batch B) --------
  getIncomeFees: () => request<IncomeFeesResponse>('/income-fees'),

  // -------- Master Virtual Card (Batch C — new; existing /master-account ledger lives at adminApi.getMasterAccount above) --------
  getMasterCard: () => request<{ card: MasterCard | null }>('/master-card'),
  issueMasterCard: () =>
    request<{ ok: boolean; card: MasterCard; created: boolean }>('/master-card/issue', {
      method: 'POST',
    }),
};

export type IncomeFeesGroup = {
  id: string;
  title: string;
  status: string;
  created_at: string | null;
  settled_at: string | null;
  lead_id: string;
  members_count: number;
  gross_contributed: number;
  fees: {
    transaction_fees: number;
    platform_fees: number;
    extra_1: number;
    extra_2: number;
    extra_other: number;
    total_retained: number;
  };
  contributions: Array<{
    user_id: string;
    user_name: string;
    amount: number;
    stripe_pi: string | null;
    ts: string | null;
    transaction_fee: number;
    platform_fee: number;
    extra_1: number;
    extra_2: number;
    fee_slice_total: number;
  }>;
  virtual_card_last4: string | null;
};

export type IncomeFeesResponse = {
  totals: {
    transaction_fees: number;
    platform_fees: number;
    extra_1: number;
    extra_2: number;
    extra_other: number;
    total_retained: number;
    groups_counted: number;
    contributions_counted: number;
    gross_contributed: number;
  };
  window_totals: { week: number; month: number };
  groups: IncomeFeesGroup[];
};

export type MasterCard = {
  stripe_card_id: string | null;
  last4: string | null;
  status: string;
  issued_at: string | null;
  note?: string;
};

export type AppConfig = {
  core_fees: {
    transaction_fee_pct: number;
    platform_fee_flat: number;
    // Admin-editable display labels (Item 2 of May 2026 batch).
    transaction_fee_label: string;
    platform_fee_label: string;
  };
  extra_fees: AdminPlatformFee[];
  wallet: { enabled: boolean; apple_enabled: boolean; google_enabled: boolean };
  limits: {
    min_members_per_bill: number;
    min_bill_amount: number;
    max_bill_amount: number;
    max_items_per_bill: number;
  };
  otp: { code_length: number; expiry_seconds: number; max_attempts_per_hour: number };
  card: { spend_cap_buffer_pct: number; auto_disable_hours: number };
  reminders: { cadence_hours: number; bill_expiry_hours: number };
  ocr: { provider: 'openai' | 'anthropic' | 'gemini'; model: string };
  brand: {
    sms_sender_id: string;
    support_email: string;
    default_tip_suggestions: number[];
    currency: 'USD';
  };
  ops: { maintenance_mode: boolean; maintenance_message: string };
};

export type AdminPlatformFee = {
  id: string;
  name: string;
  type: 'percent' | 'flat';
  value: number;
  enabled: boolean;
};

export type LegalPage = {
  slug: 'support' | 'privacy' | 'terms';
  title: string;
  content_html: string;
  updated_at: string | null;
  updated_by?: string;
  is_default?: boolean;
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
  // ISO timestamp the user agreed to T&C; null/undefined if pre-T&C account.
  terms_accepted_at?: string | null;
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
    mode?: 'mock' | 'live';
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

// ---- Phase G5: Analytics ----

export type AnalyticsPayload = {
  range_days: number;
  start_date: string;
  end_date: string;
  groups_per_day: { date: string; count: number }[];
  gmv_per_day: { date: string; amount: number }[];
  aov_per_day: { date: string; value: number }[];
  signups_per_day: { date: string; count: number; verified_count: number }[];
  contributions_per_day: { date: string; amount: number; count: number }[];
  top_referrers: { user_id: string; name: string; referral_code: string | null; signups: number; verified_signups: number }[];
  card_metrics: { total_issued: number; active: number; inactive: number; total_spent: number };
  master_account: { balance: number; entries: number };
  funnel: { signups: number; verified: number; joined_group: number; contributed: number; settled_groups: number };
  totals: {
    users: number;
    verified_users: number;
    groups: number;
    groups_in_range: number;
    contributions: number;
    gmv: number;
    gmv_in_range: number;
    gross_processed_in_range: number;
    signups_in_range: number;
    verified_in_range: number;
  };
};

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

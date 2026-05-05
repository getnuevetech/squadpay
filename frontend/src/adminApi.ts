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
  contributions: { id: string; user_id: string; amount: number; at: string }[];
  repayments: { user_id: string; amount: number; at: string }[];
  split_mode?: string;
  funding_mode?: string | null;
  lead_paid_at?: string | null;
};

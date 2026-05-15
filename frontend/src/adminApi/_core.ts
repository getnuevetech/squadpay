/**
 * adminApi/_core.ts — Shared infrastructure for the admin API layer.
 *
 * Centralised so domain modules (ocr, cms, incomeFees, notifications, etc.)
 * don't each re-implement auth-header plumbing, token caching, JSON parsing,
 * 401 redirect handling, or file-download helpers.
 *
 * Public exports:
 *   - BACKEND_URL, API constants
 *   - getToken / setSession / getProfile / clearSession
 *   - request<T>()      — authenticated /api/admin/* JSON helper
 *   - _aRequest<T>()    — flexible /api/* helper (used by domain APIs)
 *   - _downloadFile()   — authenticated file-blob download (CSV/PDF/etc.)
 *
 * NOTE: setSession accepts an unknown `profile` to keep this module type-free
 * of admin-domain types (avoids circular imports back to `./_legacy`).
 */
import AsyncStorage from '@react-native-async-storage/async-storage';

export const BACKEND_URL = process.env.EXPO_PUBLIC_BACKEND_URL || '';
export const API = `${BACKEND_URL}/api/admin`;
const TOKEN_KEY = 'gp.admin.token';
const PROFILE_KEY = 'gp.admin.profile';

let _cachedToken: string | null = null;

export async function getToken(): Promise<string | null> {
  if (_cachedToken) return _cachedToken;
  _cachedToken = await AsyncStorage.getItem(TOKEN_KEY);
  return _cachedToken;
}

export async function setSession(token: string, profile: unknown): Promise<void> {
  _cachedToken = token;
  await AsyncStorage.setItem(TOKEN_KEY, token);
  await AsyncStorage.setItem(PROFILE_KEY, JSON.stringify(profile));
}

export async function getProfile<T = unknown>(): Promise<T | null> {
  const raw = await AsyncStorage.getItem(PROFILE_KEY);
  return raw ? (JSON.parse(raw) as T) : null;
}

export async function clearSession(): Promise<void> {
  _cachedToken = null;
  await AsyncStorage.multiRemove([TOKEN_KEY, PROFILE_KEY]);
}

/**
 * Authenticated request against `/api/admin/<path>`.
 *
 * Auto-clears session and redirects to /admin/login on 401 (except when the
 * caller is already on /admin/login — preserves inline error messages on the
 * login form).
 */
export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = await getToken();
  const headers: any = { 'Content-Type': 'application/json', ...(init.headers || {}) };
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(`${API}${path}`, { ...init, headers });
  const text = await res.text();
  let body: any = null;
  try { body = text ? JSON.parse(text) : null; } catch { body = text; }
  if (!res.ok) {
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

/**
 * Flexible authenticated request. Unlike `request()` it accepts ANY
 * `/api/...` path (not just `/api/admin/*`) and supports a `skipAuth` option.
 *
 * Used by domain-scoped APIs (ocrApi, cmsApi, ticketsApi, etc.) that often
 * span both /admin/* and public /api/* endpoints.
 */
export async function _aRequest<T>(path: string, init?: RequestInit & { skipAuth?: boolean }): Promise<T> {
  const token = await getToken();
  const isAbsolute = path.startsWith('http');
  const isAdmin = path.startsWith('/admin');
  const url = isAbsolute ? path : `${BACKEND_URL}/api${isAdmin ? '' : ''}${path}`;
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (token && !init?.skipAuth) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(url, { ...init, headers: { ...headers, ...(init?.headers as any) } });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(text || `HTTP ${res.status}`);
  }
  const ct = res.headers.get('content-type') || '';
  if (ct.includes('json')) return res.json();
  return (await res.text()) as any;
}

/**
 * Authenticated file download helper. Fetches a blob and triggers an anchor
 * download on web. Returns `{ filename, size }` for native callers to wire
 * into share sheets.
 */
export async function _downloadFile(
  url: string,
  mime: string,
  fallbackName: string,
): Promise<{ filename: string; size: number }> {
  const token = await getToken();
  const res = await fetch(url, {
    method: 'GET',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(text || `HTTP ${res.status}`);
  }
  const blob = mime === 'application/pdf' ? await res.blob() : new Blob([await res.text()], { type: mime });
  const cd = res.headers.get('content-disposition') || '';
  const m = /filename="?([^"]+)"?/.exec(cd);
  const filename = m?.[1] || fallbackName;
  if (typeof window !== 'undefined' && typeof document !== 'undefined') {
    const href = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = href;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(href);
  }
  return { filename, size: blob.size };
}

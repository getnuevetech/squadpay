/**
 * adminApi/legal.ts — Static legal pages (support/privacy/terms) admin
 * + media upload helper.
 */
import { API, request, getToken } from './_core';

export type LegalPage = {
  slug: 'support' | 'privacy' | 'terms';
  title: string;
  /** Authoritative source format — markdown. May be empty for very old rows. */
  content_md?: string;
  /** Derived from content_md server-side; what the public reader uses. */
  content_html: string;
  updated_at: string | null;
  updated_by?: string;
  is_default?: boolean;
};

export const legalApi = {
  list: () => request<{ pages: LegalPage[] }>(`/legal/pages`),
  /**
   * Save a page. New callers should pass `content_md` (markdown). The
   * legacy `content_html` shape is still accepted server-side for
   * back-compat but the editor (May 2026 rebuild) only sends markdown.
   */
  update: (
    slug: 'support' | 'privacy' | 'terms',
    body: { title: string; content_md?: string; content_html?: string },
  ) =>
    request<LegalPage & { ok: boolean }>(`/legal/pages/${slug}`, {
      method: 'PUT',
      body: JSON.stringify(body),
    }),
  uploadMedia: async (file: { uri?: string; blob?: Blob; name: string; mime: string }) => {
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
};

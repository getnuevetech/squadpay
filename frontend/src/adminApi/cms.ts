/**
 * adminApi/cms.ts — Static CMS pages (terms, privacy, help center)
 * admin client + public read endpoints.
 */
import { _aRequest, BACKEND_URL } from './_core';

export type CmsPage = {
  id: string;
  slug: string;
  title: string;
  body: string;
  body_format: 'markdown' | 'plain';
  published: boolean;
  visibility: 'web' | 'mobile' | 'both';
  meta_description?: string | null;
  created_at: string;
  updated_at: string;
  created_by?: string | null;
};

export const cmsApi = {
  list: () => _aRequest<{ items: CmsPage[]; total: number }>('/admin/cms/pages'),
  get: (id: string) => _aRequest<CmsPage>(`/admin/cms/pages/${id}`),
  create: (body: Partial<CmsPage>) =>
    _aRequest<CmsPage>('/admin/cms/pages', { method: 'POST', body: JSON.stringify(body) }),
  update: (id: string, body: Partial<CmsPage>) =>
    _aRequest<CmsPage>(`/admin/cms/pages/${id}`, { method: 'PUT', body: JSON.stringify(body) }),
  remove: (id: string) =>
    _aRequest<{ ok: boolean }>(`/admin/cms/pages/${id}`, { method: 'DELETE' }),
};

/**
 * Public CMS fetch (no admin token required). Used by the public web route.
 */
export const publicCmsApi = {
  list: async () => {
    const res = await fetch(`${BACKEND_URL}/api/cms/pages`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return (await res.json()) as { items: CmsPage[] };
  },
  get: async (slug: string) => {
    const res = await fetch(`${BACKEND_URL}/api/cms/pages/${encodeURIComponent(slug)}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return (await res.json()) as CmsPage;
  },
};

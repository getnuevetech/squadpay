/**
 * adminApi/audit.ts — Admin audit log (read + CSV export).
 */
import { API, request, getToken } from './_core';
import type { AuditEntry } from './_legacy';

type AuditQuery = {
  limit?: number;
  skip?: number;
  action?: string;
  admin_email?: string;
  target_type?: string;
  target_id?: string;
  destructive?: boolean;
  date_from?: string;
  date_to?: string;
};

function _buildAuditQs(params?: AuditQuery): string {
  const q = new URLSearchParams();
  if (params?.limit) q.set('limit', String(params.limit));
  if (params?.skip !== undefined) q.set('skip', String(params.skip));
  if (params?.action) q.set('action', params.action);
  if (params?.admin_email) q.set('admin_email', params.admin_email);
  if (params?.target_type) q.set('target_type', params.target_type);
  if (params?.target_id) q.set('target_id', params.target_id);
  if (params?.destructive !== undefined) q.set('destructive', String(params.destructive));
  if (params?.date_from) q.set('date_from', params.date_from);
  if (params?.date_to) q.set('date_to', params.date_to);
  return q.toString();
}

export const auditApi = {
  list: (params?: AuditQuery) => {
    const qs = _buildAuditQs(params);
    return request<{ items: AuditEntry[]; total: number; skip: number; limit: number }>(
      `/audit-log${qs ? `?${qs}` : ''}`,
    );
  },
  exportUrl: async (params?: Omit<AuditQuery, 'limit' | 'skip'>) => {
    const qs = _buildAuditQs(params as AuditQuery);
    return `/audit-log/export${qs ? `?${qs}` : ''}`;
  },
  downloadCsv: async (params?: Omit<AuditQuery, 'limit' | 'skip'>) => {
    const qs = _buildAuditQs(params as AuditQuery);
    const url = `${API}/audit-log/export${qs ? `?${qs}` : ''}`;
    const token = await getToken();
    const res = await fetch(url, {
      method: 'GET',
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok) {
      const text = await res.text().catch(() => '');
      throw new Error(text || `HTTP ${res.status}`);
    }
    const text = await res.text();
    const filename = `audit_log_${new Date().toISOString().replace(/[:.]/g, '-')}.csv`;
    if (typeof window !== 'undefined' && typeof document !== 'undefined') {
      const blob = new Blob([text], { type: 'text/csv' });
      const href = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = href;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(href);
    }
    return { filename, size: text.length };
  },
};

/**
 * adminApi/contactMessages.ts — Contact-us inbox admin
 * (assignment, status, internal notes).
 */
import { request } from './_core';

export const contactMessagesApi = {
  list: (page: number = 1, page_size: number = 25, opts: { status?: string; subject?: string; q?: string } = {}) => {
    const qs = new URLSearchParams({ page: String(page), page_size: String(page_size) });
    if (opts.status) qs.set('status', opts.status);
    if (opts.subject) qs.set('subject', opts.subject);
    if (opts.q) qs.set('q', opts.q);
    return request<any>(`/contact-messages?${qs.toString()}`);
  },
  get: (id: string) => request<any>(`/contact-messages/${id}`),
  patch: (id: string, body: { status?: string; assignee_email?: string }) =>
    request<any>(`/contact-messages/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  addNote: (id: string, note: string) =>
    request<any>(`/contact-messages/${id}/notes`, { method: 'POST', body: JSON.stringify({ note }) }),
};

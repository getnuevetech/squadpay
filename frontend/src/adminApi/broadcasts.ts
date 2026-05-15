/**
 * adminApi/broadcasts.ts — Notification Center + Bulk SMS broadcaster.
 */
import { request } from './_core';

export const broadcastsApi = {
  notify: (body: {
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
  list: (page: number = 1, page_size: number = 20) =>
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
      page: number;
      page_size: number;
      total: number;
      has_more: boolean;
    }>(`/notifications/broadcasts?page=${page}&page_size=${page_size}`),
  sendBulkSms: (body: {
    message: string;
    audience: 'all_users' | 'leads' | 'members' | 'groups' | 'numbers';
    group_ids?: string[];
    phone_numbers?: string[];
  }) =>
    request<{
      id: string;
      recipient_count: number;
      sms_sent: number;
      sms_failed: number;
    }>('/bulk-sms/send', { method: 'POST', body: JSON.stringify(body) }),
  listBulkSms: (page: number = 1, page_size: number = 20) =>
    request<{
      items: Array<{
        id: string;
        message: string;
        audience: string;
        group_ids: string[] | null;
        recipient_count: number;
        sms_sent: number;
        sms_failed: number;
        sent_at: string;
      }>;
      page: number;
      page_size: number;
      total: number;
      has_more: boolean;
    }>(`/bulk-sms/history?page=${page}&page_size=${page_size}`),
};

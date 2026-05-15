/**
 * adminApi/notifications.ts — Notification matrix admin
 * (Event × Channel push/SMS config).
 */
import { _aRequest } from './_core';

export type NotifChannel = 'off' | 'sms' | 'push' | 'both';
export type NotifEventConfig = { channel: NotifChannel; description: string };
export type NotificationConfig = {
  events: Record<string, NotifEventConfig>;
  push_enabled: boolean;
  push_status?: 'coming_soon' | 'live';
  updated_at?: string;
  updated_by?: string;
};

export const notificationConfigApi = {
  get: () => _aRequest<NotificationConfig>('/admin/notification-config'),
  set: (events: Record<string, NotifChannel>, push_enabled: boolean) =>
    _aRequest<NotificationConfig & { ok: boolean }>('/admin/notification-config', {
      method: 'PUT',
      body: JSON.stringify({ events, push_enabled }),
    }),
};

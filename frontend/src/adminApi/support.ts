/**
 * adminApi/support.ts — Support ticket admin (replies, escalations).
 */
import { _aRequest } from './_core';

export type TicketReply = {
  id: string;
  ticket_id: string;
  direction: 'outgoing' | 'incoming';
  from_email?: string;
  message: string;
  created_at: string;
  email_dispatch?: { sent: boolean; error?: string | null };
};

export const ticketsApi = {
  reply: (ticketId: string, message: string, alsoSendEmail = true) =>
    _aRequest<any>(`/admin/contact-messages/${ticketId}/reply`, {
      method: 'POST',
      body: JSON.stringify({ message, also_send_email: alsoSendEmail }),
    }),
  forUser: (userId: string) =>
    _aRequest<{ items: any[]; total: number }>(`/admin/users/${userId}/tickets`),
};

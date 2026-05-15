/**
 * adminApi/integrations.ts — Third-party integrations admin
 * (Stripe, Twilio, SignalWire, Reminders, Issuing) + shared types.
 */
import { request } from './_core';

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

export const integrationsApi = {
  get: () => request<IntegrationsView>('/integrations'),
  setStripe: (s: StripeIn) =>
    request<IntegrationsView>('/integrations/stripe', { method: 'POST', body: JSON.stringify(s) }),
  setTwilio: (s: TwilioIn) =>
    request<IntegrationsView>('/integrations/twilio', { method: 'POST', body: JSON.stringify(s) }),
  setSignalWire: (s: SignalWireIn) =>
    request<IntegrationsView>('/integrations/signalwire', { method: 'POST', body: JSON.stringify(s) }),
  testSignalWire: (to_number: string, body?: string) =>
    request<{ sent_real: boolean; info: string }>(`/integrations/signalwire/test`, {
      method: 'POST',
      body: JSON.stringify({ to_number, body }),
    }),
  setSmsRouting: (r: { primary: 'twilio' | 'signalwire'; fallback?: 'twilio' | 'signalwire' | null }) =>
    request<IntegrationsView>('/integrations/sms-routing', { method: 'POST', body: JSON.stringify(r) }),
  setSmsMode: (mode: 'mock' | 'live') =>
    request<IntegrationsView>('/integrations/sms-mode', { method: 'POST', body: JSON.stringify({ mode }) }),
  testTwilio: (to_number: string, body?: string) =>
    request<{ sent_real: boolean; info: string }>(`/integrations/twilio/test`, {
      method: 'POST',
      body: JSON.stringify({ to_number, body }),
    }),
  setReminders: (r: RemindersIn) =>
    request<IntegrationsView>('/integrations/reminders', { method: 'POST', body: JSON.stringify(r) }),
  runRemindersNow: () =>
    request<{ enabled: boolean; scanned: number; sent_real: number; logged: number; skipped: number; schedule_hours?: number[] }>(
      `/integrations/reminders/run-now`,
      { method: 'POST' },
    ),
  // Issuing (virtual cards) admin settings.
  getIssuing: () =>
    request<{
      enabled: boolean;
      cardholder_id: string | null;
      cardholder_name: string;
      card_disable_mode: 'auto' | 'manual';
      require_otp_for_card_reveal?: boolean;
      reveal_ttl_seconds?: number;
      require_lead_kyc?: boolean;
      apple_pay_enrolled?: boolean;
      google_pay_enrolled?: boolean;
      updated_at?: string;
    }>(`/integrations/issuing`),
  setIssuing: (body: {
    enabled?: boolean;
    cardholder_name?: string;
    card_disable_mode?: 'auto' | 'manual';
    require_otp_for_card_reveal?: boolean;
    reveal_ttl_seconds?: number;
    require_lead_kyc?: boolean;
    apple_pay_enrolled?: boolean;
    google_pay_enrolled?: boolean;
    webhook_secret?: string;
  }) => request<any>(`/integrations/issuing`, { method: 'POST', body: JSON.stringify(body) }),
};

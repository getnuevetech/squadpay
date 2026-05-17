/**
 * adminApi/paymentGateways.ts — Virtual card issuer adapter management.
 *
 * Surfaces the multi-provider issuer architecture (Stripe / Lithic / Highnote
 * / Unit) so admins can:
 *   • See which provider is currently issuing virtual cards (mutex — only one
 *     at a time)
 *   • Toggle enable/disable per provider
 *   • Activate a different provider (zero-downtime swap)
 *   • Save credentials per provider
 *   • Probe provider health (live ping)
 *
 * Backed by /api/admin/payment-gateways (see
 * /app/backend/routes/admin_payment_gateways.py).
 */
import { request } from './_core';

export type IssuerHealth = {
  ok: boolean;
  message: string;
  latency_ms: number;
  env: string;
};

export type IssuerCapabilities = {
  apple_wallet: boolean;
  google_wallet: boolean;
  single_use: boolean;
  multi_use: boolean;
};

export type IssuerProvider = {
  slug: string;                 // "stripe" | "lithic" | "highnote" | "unit"
  display_name: string;
  active: boolean;              // true for exactly one entry
  enabled: boolean;             // admin toggle
  configured: boolean;          // credentials present
  capabilities: IssuerCapabilities;
  health: IssuerHealth;
  env_keys: string[];           // .env keys this provider needs
  updated_by?: string | null;
  updated_at?: string | null;
};

export type IssuerListResp = {
  active_issuer: string;
  active_changed_by?: string | null;
  active_changed_at?: string | null;
  providers: IssuerProvider[];
};

export const paymentGatewaysApi = {
  list: () => request<IssuerListResp>('GET', '/payment-gateways'),

  activate: (slug: string) =>
    request<{ ok: boolean; active_issuer: string }>(
      'POST',
      '/payment-gateways/activate',
      { slug },
    ),

  toggle: (slug: string, enabled: boolean) =>
    request<{ ok: boolean }>('POST', '/payment-gateways/toggle', { slug, enabled }),

  configure: (slug: string, credentials: Record<string, string>) =>
    request<{ ok: boolean; health: IssuerHealth }>(
      'POST',
      '/payment-gateways/configure',
      { slug, credentials },
    ),

  health: (slug: string) =>
    request<IssuerHealth>('GET', `/payment-gateways/${slug}/health`),
};

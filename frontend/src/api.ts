const BACKEND_URL = process.env.EXPO_PUBLIC_BACKEND_URL;

if (!BACKEND_URL) {
  console.warn('EXPO_PUBLIC_BACKEND_URL is not set');
}

const BASE = `${BACKEND_URL}/api`;

async function request<T>(path: string, opts: RequestInit = {}): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...opts,
    headers: {
      'Content-Type': 'application/json',
      ...(opts.headers || {}),
    },
  });
  const text = await res.text();
  let data: any;
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { raw: text };
  }
  if (!res.ok) {
    const msg = data?.detail || data?.message || `Request failed (${res.status})`;
    throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
  }
  return data as T;
}

export type User = {
  id: string;
  name: string;
  phone: string | null;
  verified: boolean;
  created_at: string;
  referral_code?: string | null;
  referred_by_user_id?: string | null;
};

export type ReferralSummary = {
  user_id: string;
  referral_code: string | null;
  referred_by: { id: string; name?: string; code?: string } | null;
  referees_count: number;
  verified_referees_count: number;
  referees: Array<{ id: string; name?: string; phone?: string | null; verified: boolean; created_at: string }>;
  settings: { enabled: boolean; referrer_credit: number; referee_credit: number };
  pending_credits: number;
};

export type Item = {
  id: string;
  name: string;
  price: number;
  quantity: number;
};

export type Member = {
  user_id: string;
  role: 'lead' | 'member';
  joined_at: string;
  name?: string;
  phone?: string | null;
  verified?: boolean;
};

export type Assignment = {
  user_id: string;
  item_id: string;
  quantity: number;
};

export type PerUser = {
  user_id: string;
  food: number;
  tax_tip: number;
  merchant_share: number;
  transaction_fee: number;
  platform_fee: number;
  total: number;
  contributed: number;
  repaid: number;
  shortfall_owed: number;
  outstanding: number;
  /** Phase H7 — amount the member has overpaid (e.g. lead paid full bill, then
   *  group expanded and equal-split halved their share). 0 if not overpaid. */
  overpaid?: number;
};

export type Repayment = {
  id: string;
  user_id: string;
  amount: number;
  at: string;
};

export type Contribution = {
  id: string;
  user_id: string;
  amount: number;
  at: string;
};

export type ShortfallObligation = {
  id: string;
  user_id: string;
  amount: number;
  kind: 'shortfall_member' | 'shortfall_split';
  covers?: string[];
  at: string;
};

export type Notification = {
  id: string;
  user_id: string;
  kind: string;
  amount?: number;
  message: string;
  at: string;
  delivered_via?: string;
};

export type Funding = {
  total_contributed: number;
  total_repaid: number;
  lead_shortfall: number;
  remaining_to_collect: number;
};

export type VirtualCard = {
  id: string;
  number: string;
  last4: string;
  exp_month: number;
  exp_year: number;
  cvv: string;
  balance: number;
  currency: string;
  issued_at: string;
};

export type Group = {
  id: string;
  code: string;
  lead_id: string;
  title: string;
  total_amount: number;
  tax: number;
  tip: number;
  split_mode: 'fast' | 'smart' | 'itemized';
  status: 'open' | 'paid' | 'closed';
  derived_status: 'contributing' | 'contributed' | 'repaying' | 'settled';
  funding_mode: 'group' | 'lead' | 'shortfall' | null;
  items: Item[];
  assignments: Assignment[];
  members: Member[];
  contributions: Contribution[];
  repayments: Repayment[];
  shortfall_obligations?: ShortfallObligation[];
  notifications?: Notification[];
  shortfall_settlement?: {
    mode: 'lead' | 'member' | 'split_equal';
    is_loan: boolean;
    amount: number;
    funder_id?: string;
    beneficiaries: string[];
    at: string;
  };
  lead_paid_at: string | null;
  lead_shortfall?: number;
  virtual_card?: VirtualCard;
  // C2 fields
  discount?: {
    type: 'flat' | 'percent';
    value: number;
    amount: number;
    note?: string | null;
    source?: string | null;
    applied_by?: string;
  } | null;
  original_total_amount?: number;
  created_at: string;
  // enriched
  subtotal: number;
  total: number;
  per_user: PerUser[];
  unclaimed: { item_id: string; name: string; remaining: number; price: number }[];
  fully_claimed: boolean;
  funding: Funding;
};

export const api = {
  register: (name: string, referral_code?: string) =>
    request<User>('/auth/register', {
      method: 'POST',
      body: JSON.stringify({ name, ...(referral_code ? { referral_code } : {}) }),
    }),
  lookupReferral: (code: string) =>
    request<{ valid: boolean; referrer_name: string; referrer_code: string; settings: { enabled: boolean; referee_credit: number } }>(
      `/referrals/lookup/${encodeURIComponent(code)}`,
    ),
  getReferralSummary: (user_id: string) => request<ReferralSummary>(`/users/${user_id}/referrals`),
  sendOtp: (user_id: string, phone: string) =>
    request<{ ok: boolean; message: string; mocked?: boolean; live?: boolean; info?: string }>('/auth/send-otp', {
      method: 'POST',
      body: JSON.stringify({ user_id, phone }),
    }),
  // Phase H2 — pre-flight check used by the auth flow before verify-otp.
  // Returns { exists: boolean, name?: string, blocked?: boolean }.
  lookupPhone: (phone: string, exclude_user_id?: string) => {
    const q = new URLSearchParams({ phone });
    if (exclude_user_id) q.set('exclude_user_id', exclude_user_id);
    return request<{ exists: boolean; name?: string; blocked?: boolean }>(
      `/auth/lookup-phone?${q.toString()}`,
    );
  },
  verifyOtp: (user_id: string, phone: string, code: string, confirm_existing: boolean = false) =>
    request<User & { session_id?: string }>('/auth/verify-otp', {
      method: 'POST',
      body: JSON.stringify({ user_id, phone, code, confirm_existing }),
    }),
  checkSession: (user_id: string, session_id: string) =>
    request<{ valid: boolean; reason?: string }>('/auth/check-session', {
      method: 'POST',
      body: JSON.stringify({ user_id, session_id }),
    }),
  logout: (user_id: string, session_id?: string) =>
    request<{ ok: boolean; cleared: boolean }>('/auth/logout', {
      method: 'POST',
      body: JSON.stringify({ user_id, ...(session_id ? { session_id } : {}) }),
    }),
  getUser: (user_id: string) => request<User>(`/users/${user_id}`),
  acceptTerms: (user_id: string) =>
    request<{ ok: boolean; terms_accepted_at: string }>(
      `/users/${encodeURIComponent(user_id)}/accept-terms`,
      { method: 'POST' },
    ),
  getLegalPage: (slug: 'support' | 'privacy' | 'terms') =>
    request<{
      slug: string;
      title: string;
      content_html: string;
      updated_at: string | null;
      is_default?: boolean;
    }>(`/legal/pages/${slug}`),
  getUserCredits: (user_id: string) =>
    request<{ user_id: string; balance: number; items: Array<{ id: string; amount: number; consumed_amount: number; remaining: number; kind: string; status: string; note: string | null; created_at: string; last_consumed_at: string | null }>; lead_auto_discount: any }>(
      `/users/${user_id}/credits`,
    ),
  // Phase H7 — refund a member's overpayment when the group expanded
  // (e.g. lead paid full bill, then equal-split halved their share).
  refundOverpayment: (group_id: string, user_id: string, amount?: number) =>
    request<{
      ok: boolean;
      refunded: number;
      breakdown: Array<{ contribution_id: string; via: 'stripe' | 'wallet_credit' | 'stripe_failed'; amount: number; stripe_refund_id?: string; credit_id?: string }>;
      remaining_overpaid: number;
      group: Group;
      info: string;
    }>(`/groups/${group_id}/refund-overpayment`, {
      method: 'POST',
      body: JSON.stringify({ user_id, amount }),
    }),
  getUserGroups: (user_id: string) =>
    request<
      {
        id: string;
        title: string;
        total: number;
        status: string;
        derived_status?: string;
        lead_id: string;
        created_at: string;
        member_count: number;
        members_preview?: { user_id: string; name: string }[];
        // Phase J2 — this user's slice of each group.
        user_share?: number;
        user_contributed?: number;
        user_outstanding?: number;
      }[]
    >(`/users/${user_id}/groups`),
  createGroup: (payload: {
    lead_id: string;
    title: string;
    total_amount: number;
    split_mode: string;
    tax?: number;
    tip?: number;
    items?: { name: string; price: number; quantity: number }[];
  }) =>
    request<Group>('/groups', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  getGroup: (id: string) => request<Group>(`/groups/${id}`),
  getGroupByCode: (code: string) => request<Group>(`/groups/by-code/${code}`),
  joinGroup: (id: string, user_id: string, joined_via?: 'code' | 'qr' | 'link' | 'invite' | 'manual') =>
    request<Group>(`/groups/${id}/join`, {
      method: 'POST',
      // joined_via is logged backend-side per Item 6 of the May 2026 batch.
      body: JSON.stringify({ user_id, joined_via }),
    }),
  removeMember: (id: string, user_id: string, target_id: string) =>
    request<Group>(`/groups/${id}/remove-member`, {
      method: 'POST',
      body: JSON.stringify({ user_id, target_id }),
    }),
  updateItems: (id: string, items: { name: string; price: number; quantity: number }[]) =>
    request<Group>(`/groups/${id}/items`, {
      method: 'PUT',
      body: JSON.stringify({ items }),
    }),
  appendItems: (id: string, user_id: string, items: { name: string; price: number; quantity: number }[]) =>
    request<Group>(`/groups/${id}/items/append`, {
      method: 'POST',
      body: JSON.stringify({ user_id, items }),
    }),
  // Lead switches a bill's split mode mid-flight. Backend rejects this once
  // any contribution has been made (see /groups/{id}/split-mode).
  setSplitMode: (id: string, user_id: string, split_mode: 'fast' | 'itemized') =>
    request<Group>(`/groups/${id}/split-mode`, {
      method: 'POST',
      body: JSON.stringify({ user_id, split_mode }),
    }),
  updateGroupMeta: (
    id: string,
    user_id: string,
    payload: { title?: string; tax?: number; tip?: number },
  ) =>
    request<Group>(`/groups/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({ user_id, ...payload }),
    }),
  deleteItem: (id: string, item_id: string, user_id: string) =>
    request<Group>(`/groups/${id}/items/${item_id}?user_id=${encodeURIComponent(user_id)}`, {
      method: 'DELETE',
    }),
  patchItemQty: (id: string, item_id: string, user_id: string, quantity_delta: number) =>
    request<Group>(`/groups/${id}/items/${item_id}`, {
      method: 'PATCH',
      body: JSON.stringify({ user_id, quantity_delta }),
    }),
  assign: (id: string, user_id: string, item_id: string, quantity: number) =>
    request<Group>(`/groups/${id}/assign`, {
      method: 'POST',
      body: JSON.stringify({ user_id, item_id, quantity }),
    }),
  payGroup: (
    id: string,
    user_id: string,
    opts?: {
      shortfall_mode?: 'lead' | 'member' | 'split_equal';
      is_loan?: boolean;
      funder_member_id?: string;
    },
  ) =>
    request<Group>(`/groups/${id}/pay`, {
      method: 'POST',
      body: JSON.stringify({ user_id, ...(opts || {}) }),
    }),
  contribute: (
    id: string,
    user_id: string,
    amount?: number,
    notify_on_settled?: boolean,
    origin_url?: string,
    app_return_url?: string,
  ) =>
    request<
      | { checkout_required: false; credit_only: true; amount: number; credit_applied: number; group: Group }
      | { checkout_required: true; url: string; session_id: string; amount: number; cash_owed: number; credit_planned: number }
    >(`/groups/${id}/contribute`, {
      method: 'POST',
      body: JSON.stringify({ user_id, amount, notify_on_settled, origin_url, app_return_url }),
    }),
  getContributeStatus: (sessionId: string) =>
    request<{ session_id: string; status: string; payment_status: string; amount_total: number | null; currency: string | null; applied: boolean; group_id: string }>(
      `/contribute/status/${encodeURIComponent(sessionId)}`,
    ),

  // ---- Feature toggles (public — admin-controlled on/off flags) ----
  getAppFeatures: () =>
    request<{ credits_enabled: boolean; invite_friends_enabled: boolean }>(
      `/app-features`,
    ),

  // ---- Phase F2: Card reveal ----
  sendSensitiveOtp: (user_id: string) =>
    request<{ ok: boolean; mocked: boolean; message: string }>(`/auth/sensitive/send-otp`, {
      method: 'POST',
      body: JSON.stringify({ user_id }),
    }),
  verifySensitiveOtp: (user_id: string, code: string, purpose: string = 'card_reveal') =>
    request<{ reveal_token: string; expires_in: number }>(`/auth/sensitive/verify-otp`, {
      method: 'POST',
      body: JSON.stringify({ user_id, code, purpose }),
    }),
  getCardEphemeralKey: (groupId: string, body: { user_id: string; reveal_token: string; nonce: string; stripe_version: string }) =>
    request<{ ephemeral_key_secret: string; card_id: string; nonce: string; stripe_publishable_key: string; ttl_seconds: number }>(
      `/groups/${groupId}/card/ephemeral-key`,
      { method: 'POST', body: JSON.stringify(body) },
    ),
  repay: (id: string, user_id: string, amount: number) =>
    request<Group>(`/groups/${id}/repay`, {
      method: 'POST',
      body: JSON.stringify({ user_id, amount }),
    }),

  // Phase E: Stripe Checkout
  createCheckoutSession: (groupId: string, originUrl: string, appReturnUrl?: string) =>
    request<{ url: string; session_id: string; amount: number }>(
      `/groups/${groupId}/checkout-session`,
      { method: 'POST', body: JSON.stringify({ origin_url: originUrl, app_return_url: appReturnUrl }) },
    ),
  getCheckoutStatus: (sessionId: string) =>
    request<{ session_id: string; status: string; payment_status: string; amount_total: number; currency: string; applied: boolean; group_id: string }>(
      `/checkout/status/${encodeURIComponent(sessionId)}`,
    ),
  // ---- Admin password reset (public — by-email) ----
  adminForgotPassword: (email: string) =>
    request<{ ok: boolean }>(`/admin/auth/forgot-password`, {
      method: 'POST',
      body: JSON.stringify({ email }),
    }),
  adminValidateResetToken: (token: string) =>
    request<{ valid: boolean; reason?: string }>(
      `/admin/auth/reset-password/validate?token=${encodeURIComponent(token)}`,
    ),
  adminResetPassword: (token: string, new_password: string) =>
    request<{ ok: boolean }>(`/admin/auth/reset-password`, {
      method: 'POST',
      body: JSON.stringify({ token, new_password }),
    }),

  scanReceipt: (image_base64: string) =>
    request<{
      items: { name: string; price: number; quantity: number }[];
      tax: number;
      tip: number;
      total: number;
    }>('/receipt/scan', {
      method: 'POST',
      body: JSON.stringify({ image_base64 }),
    }),
};

export { BACKEND_URL };

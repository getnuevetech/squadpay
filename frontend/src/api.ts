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
    request<{ ok: boolean; message: string }>('/auth/send-otp', {
      method: 'POST',
      body: JSON.stringify({ user_id, phone }),
    }),
  verifyOtp: (user_id: string, phone: string, code: string) =>
    request<User>('/auth/verify-otp', {
      method: 'POST',
      body: JSON.stringify({ user_id, phone, code }),
    }),
  getUser: (user_id: string) => request<User>(`/users/${user_id}`),
  getUserGroups: (user_id: string) =>
    request<
      {
        id: string;
        title: string;
        total: number;
        status: string;
        lead_id: string;
        created_at: string;
        member_count: number;
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
  joinGroup: (id: string, user_id: string) =>
    request<Group>(`/groups/${id}/join`, {
      method: 'POST',
      body: JSON.stringify({ user_id }),
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
  ) =>
    request<Group>(`/groups/${id}/contribute`, {
      method: 'POST',
      body: JSON.stringify({ user_id, amount, notify_on_settled }),
    }),
  repay: (id: string, user_id: string, amount: number) =>
    request<Group>(`/groups/${id}/repay`, {
      method: 'POST',
      body: JSON.stringify({ user_id, amount }),
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

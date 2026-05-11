/**
 * useBillMath — single source of truth for the dashboard math.
 *
 * Historically duplicated in `dashboard.tsx` and `summary.tsx`. Now both
 * screens import this hook so the math is computed once and impossible
 * to drift between Lead and User dashboards.
 *
 * All amounts are USD floats. `grandTotal` is intentionally computed from
 * the same numbers we render in the breakdown — never from the backend's
 * legacy `group.total` (which historically excluded the SquadPay fees).
 */
import { useMemo } from 'react';
import type { Group } from '../api';

export type ExtraFeeAgg = { id: string; name: string; amount: number };

export interface BillMath {
  // Per-user (current viewer)
  myPer: any | undefined;
  myShare: number;
  myContributed: number;
  myRepaid: number;
  myOutstanding: number;

  // Group-level totals
  groupItemsTotal: number;
  groupTransactionFees: number;
  groupPlatformFees: number;
  extraFeesAgg: ExtraFeeAgg[];
  groupExtraFeesTotal: number;
  groupContributedTotal: number;
  groupRepaidTotal: number;
  grandTotal: number;
  groupOutstandingTotal: number;

  // Derived
  collectedPct: number;
  displayedPct: number;
  remaining: number;

  // Member guard
  memberCount: number;
  needsMoreMembers: boolean;
}

export function useBillMath(group: Group | null, userId: string | null): BillMath {
  return useMemo<BillMath>(() => {
    if (!group) {
      return {
        myPer: undefined,
        myShare: 0,
        myContributed: 0,
        myRepaid: 0,
        myOutstanding: 0,
        groupItemsTotal: 0,
        groupTransactionFees: 0,
        groupPlatformFees: 0,
        extraFeesAgg: [],
        groupExtraFeesTotal: 0,
        groupContributedTotal: 0,
        groupRepaidTotal: 0,
        grandTotal: 0,
        groupOutstandingTotal: 0,
        collectedPct: 0,
        displayedPct: 0,
        remaining: 0,
        memberCount: 0,
        needsMoreMembers: true,
      };
    }

    const myPer = userId ? group.per_user.find((p: any) => p.user_id === userId) : undefined;

    const groupItemsTotal = (group.items || []).reduce(
      (s: number, it: any) => s + Number(it.price || 0) * Number(it.quantity || 1),
      0,
    );
    const groupTransactionFees = (group.per_user || []).reduce(
      (s: number, p: any) => s + Number(p.transaction_fee || 0),
      0,
    );
    const groupPlatformFees = (group.per_user || []).reduce(
      (s: number, p: any) => s + Number(p.platform_fee || 0),
      0,
    );
    const groupContributedTotal = group.funding?.total_contributed || 0;
    const groupRepaidTotal = group.funding?.total_repaid || 0;

    // Aggregate admin-configurable extra fees across members. Each fee may
    // appear on every member's per_user entry — we sum by fee id.
    const extraFeesAgg: ExtraFeeAgg[] = [];
    for (const p of (group.per_user || []) as any[]) {
      for (const ef of (p.extra_fees || []) as any[]) {
        const found = extraFeesAgg.find((x) => x.id === ef.id);
        if (found) found.amount += Number(ef.amount || 0);
        else extraFeesAgg.push({ id: ef.id, name: ef.name || 'Extra fee', amount: Number(ef.amount || 0) });
      }
    }
    const groupExtraFeesTotal = extraFeesAgg.reduce((s, f) => s + f.amount, 0);

    const grandTotal =
      groupItemsTotal +
      Number(group.tax || 0) +
      Number(group.tip || 0) +
      groupTransactionFees +
      groupPlatformFees +
      groupExtraFeesTotal;

    const groupOutstandingTotal = Math.max(0, grandTotal - groupContributedTotal);
    const collectedPct = grandTotal > 0 ? Math.min(100, (groupContributedTotal / grandTotal) * 100) : 0;
    const totalOutstandingPerUser = (group.per_user || []).reduce(
      (s: number, p: any) => s + Number(p.outstanding || 0),
      0,
    );
    // Cap at 99% while anyone still owes — bill is only "100% collected" once every share lands.
    const displayedPct = totalOutstandingPerUser > 0.01 ? Math.min(99, collectedPct) : collectedPct;
    const remaining = Math.max(0, grandTotal - groupContributedTotal);

    const memberCount = (group.members || []).length;
    const needsMoreMembers = memberCount < 2;

    return {
      myPer,
      myShare: myPer?.total || 0,
      myContributed: myPer?.contributed || 0,
      myRepaid: myPer?.repaid || 0,
      myOutstanding: myPer?.outstanding || 0,
      groupItemsTotal,
      groupTransactionFees,
      groupPlatformFees,
      extraFeesAgg,
      groupExtraFeesTotal,
      groupContributedTotal,
      groupRepaidTotal,
      grandTotal,
      groupOutstandingTotal,
      collectedPct,
      displayedPct,
      remaining,
      memberCount,
      needsMoreMembers,
    };
  }, [group, userId]);
}

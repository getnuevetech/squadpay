/**
 * adminApi/incomeFees.ts — Platform-revenue / fees ledger admin.
 *
 * The Income & Fees screen consumes this to render the global revenue
 * dashboard (transaction fees, platform fees, insurance, extras).
 *
 * Today: thin re-export from `_legacy.ts`. Future: source code will be
 * progressively moved here.
 */
export { incomeFeesApi } from './_legacy';
export type {
  IncomeFeesGroup,
  IncomeFeesResponse,
} from './_legacy';

/**
 * adminApi/admin.ts — Core admin domain.
 *
 * Houses the master `adminApi` client (auth, profile, metrics, audit,
 * user/group lists, capability flags, etc.) plus its shared types.
 *
 * Today: thin re-export shim from `_legacy.ts`. Future: source code will
 * be progressively moved into this file as part of the refactor.
 */
export {
  adminApi,
} from './_legacy';
export type {
  AdminRole,
  AdminProfile,
  AdminMetrics,
  AuditEntry,
  AdminUserRow,
  AdminUserDetail,
  AdminGroupRow,
  AdminGroupDetail,
} from './_legacy';

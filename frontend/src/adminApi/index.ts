/**
 * adminApi/index.ts — Public barrel for the admin API layer.
 *
 * Phase C (June 2025) refactor COMPLETE: the original ~1,400 line
 * `src/adminApi.ts` has been fully decomposed. Every API method now lives
 * in its own domain module. The legacy `adminApi` object (and historical
 * type exports) live in `_legacy.ts` as a backwards-compat shim that simply
 * composes the domain modules.
 *
 *   // ✅ Both import styles work today:
 *   import { adminApi, AdminProfile } from '../../src/adminApi';            // legacy
 *   import { usersApi, integrationsApi } from '../../src/adminApi';         // recommended
 *   import { usersApi } from '../../src/adminApi/users';                    // domain-scoped
 *
 * Migration history:
 *   • Phase A — Folder scaffolding + barrel.
 *   • Phase B — Moved 10 self-contained standalone APIs (ocrApi, cmsApi,
 *               ticketsApi, etc.) out of `_legacy.ts`.
 *   • Phase C — Decomposed the master adminApi (~50 methods) into domain
 *               modules. `_legacy.ts` is now ~230 LOC (down from 1,400+).
 *   • Phase D — Future: when consumers migrate to domain-scoped clients
 *               (`usersApi.list()` instead of `adminApi.listUsers()`), the
 *               `_legacy.ts` composition shim can be deleted entirely.
 */

// Master backwards-compat shim (composes domain APIs into legacy `adminApi`):
export * from './_legacy';

// Phase B — Standalone domain APIs (source-of-truth):
export * from './ocr';
export * from './support';
export * from './cms';
export * from './activity';
export * from './edits';
export * from './settlement';
export * from './notifications';
export * from './landingPage';
export * from './kyc';
export * from './incomeFees';

// Phase C — Domain APIs decomposed from the old master `adminApi` object:
export * from './auth';
export * from './audit';
export * from './admins';
export * from './broadcasts';
export * from './creditRules';
export * from './access';
export * from './gateways';
export * from './contactMessages';
export * from './users';
export * from './groups';
export * from './integrations';
export * from './reconciliation';
export * from './security';
export * from './analytics';
export * from './legal';
export * from './features';
export * from './referrals';
export * from './appConfig';
export * from './masterCard';
export * from './rewards';
export * from './admin';

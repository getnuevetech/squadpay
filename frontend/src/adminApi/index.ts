/**
 * adminApi/index.ts — Backwards-compat re-export shim.
 *
 * June 2025 refactor (Phase 2): the original `/app/frontend/src/adminApi.ts`
 * (~1,400 LOC) was renamed to `./_legacy.ts`. Self-contained domain APIs
 * (ocrApi, cmsApi, ticketsApi, etc.) have been migrated OUT of `_legacy.ts`
 * into focused domain modules. This barrel re-exports EVERYTHING so existing
 * import paths continue to work unchanged:
 *
 *   // ✅ Old import — still works, resolves to this barrel:
 *   import { adminApi, ocrApi, AdminProfile } from '../../src/adminApi';
 *
 *   // ✅ New import — domain-scoped (recommended for new code):
 *   import { ocrApi } from '../../src/adminApi/ocr';
 *
 * MIGRATION PROGRESS:
 *   1. ✅ DONE — Moved original file into this folder + barrel shim.
 *   2. ✅ DONE — Created domain-scoped modules (ocr, cms, support, etc.).
 *   3. ✅ DONE (Phase 2) — Migrated the 10 self-contained standalone APIs
 *         out of `_legacy.ts` into their domain modules with full source
 *         code (not just re-exports). Shared infrastructure (auth headers,
 *         token caching, file download helper) extracted to `./_core.ts`.
 *   4. 🔜 FUTURE — Decompose the master `adminApi` object (~50 methods) into
 *         per-domain clients (usersApi, groupsApi, integrationsApi, etc.).
 *         Will require touching every admin screen import — defer until the
 *         object grows again or domain boundaries firm up.
 *   5. 🔜 FUTURE — When `_legacy.ts` is empty, delete it.
 *
 * Why this structure:
 *   - Zero behaviour change today — every previous import path still works.
 *   - Domain modules already source-of-truth for their APIs (no re-export
 *     indirection through `_legacy.ts`).
 *   - Future moves are isolated to one domain at a time (low blast radius).
 *   - Consumers get clean, focused import paths immediately for new code.
 */

// Master adminApi client + its method-signature types (still in _legacy.ts):
export * from './_legacy';

// Migrated standalone domain APIs (source-of-truth in their own modules):
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

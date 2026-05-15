/**
 * adminApi/index.ts — Backwards-compat re-export shim.
 *
 * June 2025 refactor: the original `/app/frontend/src/adminApi.ts`
 * (~1,400 LOC) was renamed to `./_legacy.ts` to keep blame history
 * intact. This barrel file re-exports EVERYTHING so existing import
 * paths continue to work unchanged:
 *
 *   // ✅ Old import — still works, resolves to this barrel:
 *   import { adminApi } from '../../src/adminApi';
 *
 *   // ✅ New import — domain-scoped (recommended for new code):
 *   import { incomeFeesApi } from '../../src/adminApi/incomeFees';
 *
 * MIGRATION PLAN (incremental, low-risk):
 *   1. (DONE) Move the legacy file into this folder + add re-export shim.
 *   2. (DONE) Create domain-scoped re-export modules that pull specific
 *             exports from `_legacy.ts` (users, groups, payments, etc.).
 *   3. (FUTURE) Progressively MOVE source code from `_legacy.ts` into the
 *             domain modules; the barrel keeps all paths working.
 *   4. (FUTURE) When `_legacy.ts` is empty, delete it.
 *
 * Why this structure:
 *   - Zero behaviour change today.
 *   - Future moves are isolated to one domain at a time (low blast radius).
 *   - Consumers get clean, focused import paths immediately for new code.
 */
export * from './_legacy';

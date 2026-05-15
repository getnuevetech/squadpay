/**
 * adminApi/edits.ts — Misc admin one-shot edits (super_admin only).
 *
 * Currently the slim PUT /admins/:id endpoint used by the Edit Admin modal.
 */
import { _aRequest } from './_core';

export const adminEditApi = {
  update: (
    adminId: string,
    patch: { name?: string; role?: string; is_active?: boolean; notes?: string },
  ) =>
    _aRequest<any>(`/admin/admins/${adminId}`, {
      method: 'PUT',
      body: JSON.stringify(patch),
    }),
};

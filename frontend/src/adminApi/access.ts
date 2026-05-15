/**
 * adminApi/access.ts — Module registry, role CRUD, capability toggles (RBAC v2).
 */
import { request } from './_core';

export const accessApi = {
  myModules: () =>
    request<{
      role: string;
      role_name?: string;
      is_super_admin: boolean;
      group_order: string[];
      modules: Array<{
        key: string;
        label: string;
        group: string;
        path: string;
        sensitive: boolean;
      }>;
    }>('/me/modules'),
  registry: () =>
    request<{
      group_order: string[];
      modules: Array<{
        key: string; label: string; group: string; path: string;
        sensitive: boolean;
      }>;
    }>('/access/registry'),
  listRoles: () =>
    request<{
      count: number;
      items: Array<{
        id: string;
        slug: string;
        name: string;
        description: string | null;
        modules: string[];
        is_system: boolean;
        assigned_admin_count: number;
        created_at: string;
        updated_at: string;
      }>;
    }>('/access/roles'),
  rolesLookup: () =>
    request<{
      items: Array<{ id: string; slug: string; name: string; description: string | null; is_system: boolean }>;
    }>('/access/roles/lookup'),
  createRole: (body: { name: string; description?: string; modules: string[] }) =>
    request<{
      id: string; slug: string; name: string; description: string | null;
      modules: string[]; is_system: boolean; assigned_admin_count: number;
    }>('/access/roles', { method: 'POST', body: JSON.stringify(body) }),
  updateRole: (role_id: string, body: { name?: string; description?: string; modules?: string[] }) =>
    request<{
      id: string; slug: string; name: string; description: string | null;
      modules: string[]; is_system: boolean; assigned_admin_count: number;
    }>(`/access/roles/${encodeURIComponent(role_id)}`, {
      method: 'PUT', body: JSON.stringify(body),
    }),
  deleteRole: (role_id: string) =>
    request<{ ok: boolean; deleted: string }>(`/access/roles/${encodeURIComponent(role_id)}`, {
      method: 'DELETE',
    }),
  listCapabilities: () =>
    request<{
      group_order: string[];
      items: Array<{
        key: string;
        label: string;
        description: string;
        group: string;
        enabled: boolean;
        sensitive: boolean;
        updated_at: string;
      }>;
    }>('/capabilities'),
  setCapability: (key: string, enabled: boolean) =>
    request<{
      key: string; label: string; description: string; group: string;
      enabled: boolean; sensitive: boolean; updated_at: string;
    }>(`/capabilities/${encodeURIComponent(key)}`, {
      method: 'PUT',
      body: JSON.stringify({ enabled }),
    }),
};

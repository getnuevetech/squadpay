/**
 * Customer-service-friendly ID labels.
 *
 * Internal IDs look like `u_c9439b4255` / `g_c02c29ec10`. Support agents
 * find them awkward to read aloud over the phone, so we surface them with
 * uppercase, hyphenated chunks and a clear UID/SID prefix wherever they
 * are shown to users.
 *
 *   u_c9439b4255  →  UID  C9439-B4255
 *   g_c02c29ec10  →  SID  C02C2-9EC10
 *
 * The underlying ID is NEVER mutated — these helpers are pure
 * display formatters.
 */

/** Format a user-facing UID (User ID) label from an internal user id. */
export function formatUid(internalId?: string | null): string {
  return formatLabel(internalId, 'UID', /^u_/i);
}

/** Format a user-facing SID (Squad / Group ID) label. */
export function formatSid(internalId?: string | null): string {
  return formatLabel(internalId, 'SID', /^g_/i);
}

/** Just the body part (without the label prefix) — useful for copy-buttons. */
export function formatUidBody(internalId?: string | null): string {
  return formatBody(internalId, /^u_/i);
}
export function formatSidBody(internalId?: string | null): string {
  return formatBody(internalId, /^g_/i);
}

function formatLabel(id: string | null | undefined, prefix: string, strip: RegExp): string {
  if (!id) return `${prefix} —`;
  return `${prefix} ${formatBody(id, strip)}`;
}

function formatBody(id: string | null | undefined, strip: RegExp): string {
  if (!id) return '—';
  const stripped = String(id).replace(strip, '').toUpperCase();
  // Chunk into 5-char groups so the eye can scan it. e.g. C9439-B4255.
  return stripped.match(/.{1,5}/g)?.join('-') || stripped;
}
